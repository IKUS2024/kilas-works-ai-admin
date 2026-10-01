"""Execute one explicitly approved, exact-payload external action."""
from . import connectors, google_tools, internal_tools


def execute(user_id, approval_id):
    proposal = connectors.claim_action(user_id, approval_id)
    tool, body = proposal["tool"], proposal["payload"]
    try:
        if tool == "gmail.send":
            result = (google_tools.gmail_send_draft(user_id, body["draft_id"], body)
                      if body.get("draft_id") else
                      google_tools.gmail_send(user_id, body["to"], body["subject"], body["body"],
                                              body.get("thread_id"), body.get("reply_to")))
        elif tool == "calendar.create":
            result = google_tools.calendar_create(user_id, body)
        elif tool == "calendar.update":
            result = google_tools.calendar_update(user_id, proposal["target"], body)
        elif tool == "calendar.delete":
            result = google_tools.calendar_delete(user_id, proposal["target"])
        elif tool == "whatsapp.send":
            result = internal_tools.whatsapp_send(user_id, proposal["business_id"],
                proposal["target"], body["text"], approval_id)
        elif tool == "finance.create_transaction":
            result = {"id": internal_tools.finance_create_transaction(
                user_id, proposal["business_id"], body, approval_id)}
        else:
            raise connectors.ConnectorError("unknown_tool")
    except connectors.ConnectorError as error:
        # If transport was attempted, the provider may have accepted the request. Claim is
        # terminal: the owner must inspect provider state before making a fresh proposal.
        code = str(error)[:80]
        definite = code in ("invalid_target", "invalid_message", "invalid_event", "invalid_recipient",
                            "invalid_header", "branch_required", "not_connected", "permission_missing",
                            "provider_rejected", "rate_limited", "approval_payload_changed")
        connectors.finish_action(user_id, approval_id, "FAILED" if definite else "UNKNOWN", error_code=code)
        raise
    except Exception:
        connectors.finish_action(user_id, approval_id, "UNKNOWN", error_code="provider_outcome_uncertain")
        raise connectors.ConnectorError("provider_outcome_uncertain") from None
    result_id = str(result.get("id") or "")
    if not result_id:
        connectors.finish_action(user_id, approval_id, "UNKNOWN", error_code="provider_result_missing")
        raise connectors.ConnectorError("provider_outcome_uncertain")
    connectors.finish_action(user_id, approval_id, "SUCCEEDED", provider_result_id=result_id)
    return result
