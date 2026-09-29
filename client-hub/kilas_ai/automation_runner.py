"""One bounded Kilas AI Automation pass; suitable for a one-minute Render Cron."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from . import automation_store as store, providers, tools, usage


class RunError(RuntimeError):
    pass


def _plain_ai(prompt):
    pieces = []
    provider = model = None
    recorded = {"input_tokens": 0, "output_tokens": 0}
    for event in providers.stream("FAST", [{"role": "user", "content": prompt[:4000]}]):
        if event["type"] == "provider":
            provider, model = event["provider"], event["model"]
        elif event["type"] == "delta":
            pieces.append(event["text"])
            if sum(len(part) for part in pieces) > 12000:
                raise RunError("result_too_long")
        elif event["type"] == "usage":
            recorded.update({key: max(0, int(event.get(key) or 0)) for key in recorded if key in event})
    answer = "".join(pieces).strip()
    if not answer:
        raise RunError("empty_result")
    return answer[:12000], provider, model, recorded


def _watch_value(text):
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise RunError("watch_value_missing")
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        raise RunError("watch_value_missing") from None
    summary = str(data.get("summary") or "").strip()[:2000]
    value = data.get("value")
    if not summary or value is None:
        raise RunError("watch_value_missing")
    return value, summary


def _settle(user_id, reservations, *, results):
    for key, operations in reservations:
        result = results.get(key) or {}
        usage.finish(user_id, key, operations, success=bool(result),
                     provider=result.get("provider"), model=result.get("model"), usage=result.get("usage"))


def execute(run_id):
    item = store.run_for_worker(run_id)
    if not item or item["status"] != "RUNNING":
        return False
    if item["automation_status"] != "ACTIVE" or item["deleted_at"] is not None:
        store.finish_run(run_id, status="FAILED", error="paused_before_execution")
        return False
    kind, user_id = item["automation_type"], item["user_id"]
    instruction = item["instruction"][:1200]
    if kind == "REMINDER":
        store.finish_run(run_id, status="SUCCEEDED", text="Pengingat: " + instruction)
        return True
    plan = usage.effective_plan(user_id)["plan"]
    reservations, results = [], {}
    try:
        tools_needed = (("WEB", "CHAT") if kind == "WATCH" else
                        ("WEB",) if kind == "SEARCH" else ("CHAT",))
        for index, tool in enumerate(tools_needed):
            key = f"automation-{run_id}-attempt-{item['attempt_count']}-{index}"
            reserved_plan, operations = usage.reserve(user_id, None, key, "FAST", tool)
            if reserved_plan is None:
                raise RunError("duplicate_reservation")
            reservations.append((key, operations))
        if kind == "AI_TASK":
            prompt = ("Kerjakan tugas terjadwal berikut secara ringkas dalam bahasa pengguna. "
                      "Jangan mengarang fakta baru atau mengaku membaca chat yang tidak disertakan. "
                      "Tanggal UTC: " + datetime.now(timezone.utc).strftime("%Y-%m-%d") +
                      "\n\nInstruksi: " + instruction)
            text, provider, model, recorded = _plain_ai(prompt)
            results[reservations[0][0]] = {"provider": provider, "model": model, "usage": recorded}
            _settle(user_id, reservations, results=results)
            store.finish_run(run_id, status="SUCCEEDED", text=text,
                             usage_metadata={"operation": "CHAT"})
            return True
        searched = tools.web_search([{"role": "user", "content": instruction}], mode="FAST",
                                    plan=plan, max_calls=1)
        results[reservations[0][0]] = {"provider": "openai", "model": searched.get("model"),
                                       "usage": searched.get("usage") or {}}
        if not searched.get("citations"):
            raise RunError("sources_missing")
        citations = [{"title": str(source.get("title") or "Sumber")[:120],
                      "url": str(source.get("url") or "")[:1000]} for source in searched["citations"][:5]
                     if str(source.get("url") or "").startswith("https://")]
        if not citations:
            raise RunError("sources_missing")
        if kind == "SEARCH":
            _settle(user_id, reservations, results=results)
            store.finish_run(run_id, status="SUCCEEDED", text=searched["text"][:12000],
                             metadata={"citations": citations}, usage_metadata={"operation": "WEB_SEARCH"})
            return True
        condition = json.loads(item["condition_json"] or "{}")
        prompt = ("Extract the currently observed value relevant to this watch instruction from the "
                  "cited search answer below. Reply ONLY JSON with keys value and summary. "
                  "For a numeric threshold, value must be the observed number, never the threshold. "
                  "If no verified observed value exists, use null. For a change watch, value is a stable "
                  "short label for the observed finding. Do not invent facts.\nInstruction: " + instruction +
                  "\nCondition: " + json.dumps(condition) + "\nCited answer:\n" + searched["text"][:5000])
        analysis, provider, model, recorded = _plain_ai(prompt)
        results[reservations[1][0]] = {"provider": provider, "model": model, "usage": recorded}
        observed, summary = _watch_value(analysis)
        if condition.get("operator") in ("lt", "gt"):
            try:
                numeric = float(str(observed).replace(".", "").replace(",", ".")) if isinstance(observed, str) else float(observed)
            except (ValueError, TypeError):
                raise RunError("watch_value_invalid") from None
            if not 0 <= numeric < 1e15:
                raise RunError("watch_value_invalid")
            matched = numeric < condition["threshold"] if condition["operator"] == "lt" else numeric > condition["threshold"]
            fingerprint = hashlib.sha256(str(numeric).encode()).hexdigest()
        else:
            matched = True
            fingerprint = hashlib.sha256(str(observed).strip().lower().encode()).hexdigest()
        previous = json.loads(item["watch_state_json"] or "{}")
        notify = matched and (not previous.get("matched") or previous.get("fingerprint") != fingerprint)
        store.update_watch_state(item["automation_id"], user_id,
                                 {"matched": matched, "fingerprint": fingerprint,
                                  "checked_at": datetime.now(timezone.utc).isoformat()})
        _settle(user_id, reservations, results=results)
        store.finish_run(run_id, status="SUCCEEDED", text=summary if notify else None,
                         metadata={"citations": citations} if notify else {},
                         usage_metadata={"operation": "WATCH", "matched": matched})
        return True
    except usage.UsageLimit:
        _settle(user_id, reservations, results=results)
        store.finish_run(run_id, status="SKIPPED_QUOTA", error="underlying_quota")
    except (providers.ProviderError, tools.ToolUnavailable, RunError, ValueError, KeyError):
        _settle(user_id, reservations, results=results)
        store.finish_run(run_id, status="FAILED", error="temporary", retry=True)
    return False


def run_once(limit=10):
    if os.environ.get("KILAS_AI_AUTOMATION_RUNNER_ENABLED", "").strip().lower() != "true":
        return {"claimed": 0, "completed": 0, "disabled": True}
    store.recover_stale()
    ids = store.claim_due(limit=min(20, max(1, int(limit))))
    complete = sum(bool(execute(run_id)) for run_id in ids)
    return {"claimed": len(ids), "completed": complete, "disabled": False}


if __name__ == "__main__":
    outcome = run_once()
    print("Kilas AI Automation runner: claimed=" + str(outcome["claimed"]) +
          " completed=" + str(outcome["completed"]) +
          (" disabled" if outcome["disabled"] else ""))
