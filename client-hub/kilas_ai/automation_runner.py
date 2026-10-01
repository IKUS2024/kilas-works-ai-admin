"""One bounded Kilas AI Automation pass; suitable for a one-minute Render Cron."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from . import automation_store as store, providers, response_style, routing, tools, usage


class RunError(RuntimeError):
    pass


def _plain_ai(prompt, mode="FAST"):
    pieces = []
    length = 0
    provider = model = None
    recorded = {"input_tokens": 0, "output_tokens": 0}
    for event in providers.stream(mode, [{"role": "user", "content": prompt[:4000]}]):
        if event["type"] == "provider":
            provider, model = event["provider"], event["model"]
        elif event["type"] == "delta":
            pieces.append(event["text"])
            length += len(event["text"])
            if length > 12000:
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
    if not summary or "value" not in data:
        raise RunError("watch_value_missing")
    return value, summary


def _numeric_value(value):
    if not isinstance(value, str):
        return float(value)
    clean = re.sub(r"(?i)^rp\s*", "", value.strip()).replace(" ", "")
    if not re.fullmatch(r"\d[\d.,]*", clean):
        raise ValueError("not_numeric")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", clean):
        clean = clean.replace(".", "").replace(",", "")
    elif "." in clean and "," in clean:
        clean = clean.replace(".", "").replace(",", ".") if clean.rfind(",") > clean.rfind(".") else clean.replace(",", "")
    elif "," in clean:
        clean = clean.replace(",", ".") if len(clean.rsplit(",", 1)[-1]) <= 2 else clean.replace(",", "")
    elif "." in clean and len(clean.rsplit(".", 1)[-1]) > 2:
        clean = clean.replace(".", "")
    return float(clean)


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
    from . import connector_flow, connectors
    if json.loads(item["condition_json"] or "{}").get("connector_read") is True:
        try:
            text = connector_flow.scheduled_read(user_id, instruction, item["timezone"], run_id=run_id)
            store.finish_run(run_id, status="SUCCEEDED", text=text[:12000],
                             usage_metadata={"operation": "CONNECTOR_PREPARE" if connector_flow.DRAFT_WORDS.search(instruction)
                                             else "CONNECTOR_READ"})
            return True
        except (connectors.ConnectorError, connector_flow.connector_planner.InterpretationError):
            store.finish_run(run_id, status="FAILED", error="connector_unavailable")
            return False
    plan = usage.effective_plan(user_id)["plan"]
    reservations, results = [], {}
    try:
        task_mode = routing.mode_for(instruction) if kind == "AI_TASK" else "FAST"
        tools_needed = (("WEB", "CHAT") if kind in ("WATCH", "SEARCH") else ("CHAT",))
        for index, tool in enumerate(tools_needed):
            key = f"automation-{run_id}-attempt-{item['attempt_count']}-{index}"
            reserve_mode = (task_mode if kind == "AI_TASK" else
                            "SMART" if kind == "SEARCH" and tool == "CHAT" else "FAST")
            reserved_plan, operations = usage.reserve(user_id, None, key, reserve_mode, tool)
            if reserved_plan is None:
                raise RunError("duplicate_reservation")
            reservations.append((key, operations))
        if kind == "AI_TASK":
            prompt = response_style.automation_task_prompt(
                instruction, datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )
            text, provider, model, recorded = _plain_ai(prompt, task_mode)
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
            final = tools.finalize_scheduled_search(instruction, searched["text"], citations)
            results[reservations[1][0]] = {"provider": "openai", "model": final["model"],
                                           "usage": final.get("usage") or {}}
            _settle(user_id, reservations, results=results)
            store.finish_run(run_id, status="SUCCEEDED", text=final["text"],
                             metadata={"citations": citations},
                             usage_metadata={"operation": "WEB_SEARCH", "final_model": final["model"]})
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
        previous = json.loads(item["watch_state_json"] or "{}")
        if observed is None:
            _settle(user_id, reservations, results=results)
            store.finish_run(run_id, status="SUCCEEDED", usage_metadata={"operation": "WATCH", "matched": False},
                             watch_state={**previous, "checked_at": datetime.now(timezone.utc).isoformat()})
            return True
        if condition.get("operator") in ("lt", "gt"):
            try:
                numeric = _numeric_value(observed)
            except (ValueError, TypeError):
                raise RunError("watch_value_invalid") from None
            if not 0 <= numeric < 1e15:
                raise RunError("watch_value_invalid")
            matched = numeric < condition["threshold"] if condition["operator"] == "lt" else numeric > condition["threshold"]
            fingerprint = hashlib.sha256(str(numeric).encode()).hexdigest()
        else:
            matched = True
            fingerprint = hashlib.sha256(str(observed).strip().lower().encode()).hexdigest()
        notify = matched and (not previous.get("matched") or previous.get("fingerprint") != fingerprint)
        watch_state = {"matched": matched, "fingerprint": fingerprint,
                       "checked_at": datetime.now(timezone.utc).isoformat()}
        _settle(user_id, reservations, results=results)
        store.finish_run(run_id, status="SUCCEEDED", text=summary if notify else None,
                         metadata={"citations": citations} if notify else {},
                         usage_metadata={"operation": "WATCH", "matched": matched}, watch_state=watch_state)
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
