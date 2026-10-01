"""Metered model interpretation for connected tools; output is always re-authorized."""
import json
import os
import secrets

import requests

from . import agent_planner, connectors, response_style, usage


class InterpretationError(ValueError):
    pass


SCHEMA = {"type": "object", "properties": {
    "intent": {"type": "string", "enum": ["READ", "PREPARE", "ACTION", "CLARIFY", "NONE"]},
    "tool": {"type": "string", "enum": ["none", *connectors.TOOLS.keys()]},
    "business_id": {"type": "integer"},
    "arguments_json": {"type": "string"},
    "reply": {"type": "string"},
}, "required": ["intent", "tool", "business_id", "arguments_json", "reply"], "additionalProperties": False}


def propose(user_id, text, history, available, businesses, timezone_name, *, scheduled=False):
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise InterpretationError("planner_unavailable")
    key = "connector-plan-" + secrets.token_hex(16)
    try:
        _, operations = usage.reserve(user_id, None, key, "SMART", "CHAT")
    except usage.UsageLimit as error:
        raise InterpretationError(str(error)) from None
    if not operations:
        raise InterpretationError("duplicate_plan")
    model = os.environ.get("KILAS_AI_AGENT_MODEL", "gpt-6.1-sol")
    if model not in ("gpt-6-luna", "gpt-6.1-sol"):
        usage.finish(user_id, key, operations, success=False)
        raise InterpretationError("invalid_agent_model")
    from zoneinfo import ZoneInfo
    from datetime import datetime
    local_now = datetime.now(ZoneInfo(timezone_name)).isoformat()
    system = (
        "You interpret one Kilas AI Agent connector intent. " + response_style.BASE_STYLE + " "
        "Answer JSON only. Never claim a tool ran. Tools are available only when listed. "
        "READ retrieves data, PREPARE writes no external message, ACTION requires an exact preview "
        "and separate user approval before any external effect. Never invent an account, business, "
        "recipient, conversation, event ID, amount or fact. Use CLARIFY only for a genuinely missing "
        "target or permission. Preserve the user's language, earlier context, and short follow-ups. " +
        ("For this already-confirmed scheduled run, choose only a READ tool; no external action or draft creation. "
         if scheduled else "For schedule requests choose NONE: the existing task planner owns canonical schedules. ") +
        "arguments_json must be a JSON object with only the fields the selected tool needs. "
        "For email: query, to, subject, body, thread_id, reply_to. For Calendar: start/end ISO "
        "timestamps with timezone and summary. For WhatsApp: query, conversation_id, text. "
        "For Finance reads: branch_id, start_date, end_date, as_of, limit; for writes: "
        "branch_id, direction, amount_minor, account_id, category_id, occurred_on. "
        "For Drive/Contacts: query or file_id. Empty unknown values instead of inventing. "
        "User account timezone is " + timezone_name + "; current local timestamp is " + local_now + ". "
        "Do not ask timezone if already known."
    )
    context = {"available_tools": available, "businesses": businesses,
               "timezone": timezone_name, "current_message": text}
    previous = [{"role": row["role"], "content": str(row["content"])[:800]} for row in history[-8:]]
    success = False
    metering = {}
    try:
        response = requests.post("https://api.openai.com/v1/responses",
            headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"], "Content-Type": "application/json"},
            json={"model": model, "instructions": system,
                  "input": previous + [{"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
                  "text": {"format": {"type": "json_schema", "name": "kilas_connector_intent",
                                      "strict": True, "schema": SCHEMA}},
                  "reasoning": {"effort": "medium"}, "max_output_tokens": 900, "store": False},
            timeout=(10, 45))
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "completed":
            raise InterpretationError("planner_incomplete")
        metering = data.get("usage") or {}
        plan = json.loads(agent_planner._output_text(data))
        if plan.get("tool") not in SCHEMA["properties"]["tool"]["enum"] or plan.get("intent") not in SCHEMA["properties"]["intent"]["enum"]:
            raise InterpretationError("planner_invalid")
        args = json.loads(plan["arguments_json"])
        if not isinstance(args, dict) or len(json.dumps(args)) > 10000 or not isinstance(plan.get("business_id"), int):
            raise InterpretationError("planner_invalid")
        plan["arguments"] = args
        success = True
        return plan
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise InterpretationError("planner_unavailable") from None
    finally:
        usage.finish(user_id, key, operations, success=success,
                     provider="openai" if success else None, model=model if success else None, usage=metering)
