"""Authenticated simulator adapter using existing, isolated simulation persistence.

The caller MUST authorize business membership and retrieve the business-specific simulator
token from the signed owner session. Never resolve these from payload or a platform fallback.
The repository and legacy reply provider are trusted, injected server dependencies.
"""
from datetime import datetime, timezone

from ..contracts import ContractError, HistoryMessage, InboundMessage
from .. import service

FAILURE_REPLY = "(Simulasi gagal memproses pesan ini — coba lagi. Detail teknis dicatat untuk Kilas Works.)"


def simulate_message(*, business, session_token, actor_id, payload, repository, reply_provider):
    """Return the existing UI (JSON body, HTTP status) contract. No live writes/delivery.

    Legacy requests have no event ID: every submitted message consumes an attempt, including
    identical text. Reject supplied IDs rather than pretending retries are durably deduplicated.
    Quota/history/onboarding semantics remain owned by the existing repository methods.
    """
    if (not isinstance(business, dict) or type(business.get("id")) is not int
            or business["id"] <= 0 or type(actor_id) is not int or actor_id <= 0):
        return {"error": "unauthorized_business"}, 404
    if not isinstance(session_token, str) or not session_token.strip():
        return {"error": "no_session"}, 400
    if not isinstance(payload, dict):
        return {"error": "invalid_message"}, 400
    if any(payload.get(key) for key in ("media", "media_references", "attachments")):
        return {"error": "unsupported_media"}, 400
    if payload.get("external_message_id") is not None:
        return {"error": "unsupported_external_message_id"}, 400
    text = payload.get("message", "")
    try:
        message = InboundMessage(
            business_id=business["id"], channel="simulator",
            conversation_id=f"simulator:{business['id']}:{session_token}", actor_type="owner",
            text=text.strip() if isinstance(text, str) else text,
            timestamp=datetime.now(timezone.utc),
        )
    except ContractError as error:
        return {"error": str(error)}, 400

    business_id = message.business_id
    ai_settings = repository.get_ai_settings(business_id)
    config = ai_settings.get("normalized_config") if ai_settings else None
    rows = repository.get_simulation_history(business_id, session_token, limit=10)
    history = tuple(HistoryMessage(row["role"], row["content"]) for row in rows)
    if not repository.reserve_simulation_user_message(business_id, session_token, message.text):
        return {"reply": "Batas Test AI hari ini sudah tercapai. Coba lagi besok ya.",
                "error": "daily_simulation_quota", "message_id": None}, 429

    def provide(envelope, scoped_history):
        return reply_provider(business, config,
                              [{"role": row.role, "content": row.content} for row in scoped_history],
                              envelope.text)

    result = service.process_message(message, history=history, reply_provider=provide)
    reply = result.reply
    if result.error:
        reply = FAILURE_REPLY
        repository.write_audit(actor_id, business_id, "simulation_error", result.error)
    repository.save_simulation_message(business_id, session_token, "assistant", reply)
    repository.mark_onboarding_step_done(business_id, "simulated_done")
    latest = repository.get_simulation_history(business_id, session_token, limit=1)
    return {"reply": reply, "message_id": latest[0]["id"] if latest else None}, 200
