"""Bounded, metered Agent intent proposal. Model output never performs a side effect."""
import json
import os
import re
import secrets

import requests

from . import response_style, routing, usage


class PlanUnavailable(RuntimeError):
    pass


CONNECTIONS = (
    (re.compile(r"\b(?:gmail|e-?mail|inbox email)\b", re.I), "Gmail"),
    (re.compile(r"\b(?:google calendar|kalender google|calendar|kalender)\b", re.I), "Google Calendar"),
    (re.compile(r"\b(?:google drive|drive)\b", re.I), "Google Drive"),
    (re.compile(r"\b(?:whatsapp|wa)\b", re.I), "WhatsApp"),
    (re.compile(r"\b(?:kilas finance|finance|laporan keuangan|rekening|invoice|transaksi|saldo)\b", re.I), "Kilas Finance"),
)


def required_connection(text):
    for pattern, name in CONNECTIONS:
        if pattern.search(text or ""):
            return name
    return None


SCHEMA = {"type": "object", "properties": {
    "action": {"type": "string", "enum": ["CREATE", "EDIT", "PAUSE", "RESUME", "HELP", "CLARIFY"]},
    "task_id": {"type": "integer"},
    "schedule_text": {"type": "string"},
    "reply": {"type": "string"},
}, "required": ["action", "task_id", "schedule_text", "reply"], "additionalProperties": False}


def _mode(text):
    if re.search(r"\b(?:multi.?step|beberapa (?:langkah|sumber)|gabungkan|combine|strategi|analisis|risiko)\b", text, re.I):
        return "SMART"
    return routing.mode_for(text)


def _output_text(data):
    for item in data.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    return str(part.get("text") or "")
    raise PlanUnavailable("empty_agent_plan")


def propose(user_id, text, history, tasks, default_timezone="Asia/Jakarta"):
    """Propose one bounded intent; caller validates ownership, schedule and permissions."""
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise PlanUnavailable("agent_planner_unavailable")
    key = "agent-plan-" + secrets.token_hex(16)
    intent_mode = _mode(text)
    # Agent planning is a high-value control surface: use the stronger reasoning budget even
    # for short conversational follow-ups so intent, context, and schedule edits stay coherent.
    mode = "SMART"
    try:
        _, operations = usage.reserve(user_id, None, key, mode, "CHAT")
    except usage.UsageLimit as error:
        raise PlanUnavailable(str(error)) from None
    if not operations:
        raise PlanUnavailable("duplicate_agent_plan")
    model = os.environ.get(
        "KILAS_AI_AGENT_MODEL",
        os.environ.get("KILAS_AI_AGENT_SMART_MODEL", "gpt-6.1-sol"),
    )
    if model not in ("gpt-6-luna", "gpt-6.1-sol"):
        usage.finish(user_id, key, operations, success=False)
        raise PlanUnavailable("invalid_agent_model")
    system = (
        "You are the Kilas AI Agent task planner. " + response_style.BASE_STYLE + " "
        "Return JSON only. Propose exactly one action. Never claim a connector or task ran. "
        "A task changes only after a separate user confirmation. Do not invent a time, date, connection, "
        "task ID, or capability. The account already has a saved timezone: " + default_timezone + ". "
        "Use that timezone whenever the user does not explicitly name another timezone; do not ask them to choose "
        "WIB/WITA/WIT merely because a timezone was omitted. Treat WIB as Asia/Jakarta, WITA as Asia/Makassar, "
        "and WIT as Asia/Jayapura. Use CLARIFY only when information that materially blocks scheduling is truly missing. "
        "If task + date/time are already clear, return CREATE immediately; do not ask 'do you want me to create it?' "
        "because the separate preview/activation UI is the confirmation step. Preserve the prior task details when a "
        "short follow-up supplies only one missing detail such as 'WIB', 'jam 5', or 'besok'. "
        "Use HELP for general guidance. For CREATE/EDIT, schedule_text must contain the complete task "
        "and explicit schedule that the existing parser can verify. For EDIT, use an existing task ID. "
        "For PAUSE/RESUME use an existing task ID. Two runs per day in one task, automatic resume dates, "
        "email sending, and external writes are not available; explain limits honestly. "
        "Never expose JSON, models, tokens or provider details to the user."
    )
    previous = [{"role": row["role"], "content": str(row["content"])[:1000]}
                for row in history[-8:]]
    task_context = [{"id": int(row["id"]), "title": str(row["title"])[:90],
                     "instruction": str(row["instruction"])[:350], "status": row["status"]}
                    for row in tasks[:30]]
    prompt = ("Account timezone: " + default_timezone + "\nExisting tasks: " +
              json.dumps(task_context, ensure_ascii=False) + "\nCurrent message: " + text)
    success = False
    used = {}
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": "Bearer " + os.environ.get("OPENAI_API_KEY", ""),
                     "Content-Type": "application/json"},
            json={"model": model, "instructions": system, "input": previous + [{"role": "user", "content": prompt}],
                  "text": {"format": {"type": "json_schema", "name": "kilas_agent_intent",
                                      "strict": True, "schema": SCHEMA}},
                  "reasoning": {"effort": "medium" if intent_mode == "SMART" else "none"},
                  "max_output_tokens": 600, "store": False},
            timeout=(10, 45))
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "completed":
            raise PlanUnavailable("incomplete_agent_plan")
        used = data.get("usage") or {}
        plan = json.loads(_output_text(data))
        if (plan.get("action") not in SCHEMA["properties"]["action"]["enum"] or
                not isinstance(plan.get("task_id"), int) or
                not isinstance(plan.get("schedule_text"), str) or
                not isinstance(plan.get("reply"), str)):
            raise PlanUnavailable("invalid_agent_plan")
        success = True
        return plan
    except (requests.RequestException, ValueError, TypeError, KeyError) as error:
        raise PlanUnavailable("agent_planner_unavailable") from error
    finally:
        usage.finish(user_id, key, operations, success=success, provider="openai" if success else None,
                     model=model if success else None, usage=used)