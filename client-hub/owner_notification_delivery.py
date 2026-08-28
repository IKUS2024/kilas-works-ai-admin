"""Absolute Final Production Patch — immediate delivery of owner_notifications rows.

Client Hub and the production WhatsApp bot (../app.py) are two separately-deployed Flask
processes on Render (this repo bundles both for local dev — see BOT_INTEGRATION_GUIDE.md — but a
real production deploy is not guaranteed to run them in the same OS process). Only the bot process
holds WhatsApp Cloud API credentials, so Client Hub can never send the WhatsApp message itself; it
asks the bot to do it, over a small internal HTTP endpoint (`POST /internal/owner-notify` in
../app.py), authenticated with a shared secret.

This module is intentionally the ONLY place in Client Hub that makes that call. It is used by
owner_notifications.notify_owner_once() right after a new row is inserted, so delivery is attempted
immediately rather than waiting for the next /cron/owner-notifications sweep. It is also safe to
call again later (the cron sweep re-imports this same function) for any row still PENDING/FAILED.

FAILURE HANDLING: a network error, timeout, non-200 response, or the bot being completely
unreachable must NEVER raise up into the caller's request (quotation approval, payment upload,
etc.) — this function always returns (ok: bool, detail: str) and swallows every exception itself.
On any failure the caller leaves the row PENDING/FAILED for the retry sweep to pick up later.

CONFIGURATION: reads KILAS_BOT_INTERNAL_URL and INTERNAL_SERVICE_SECRET from the environment.
Neither is hardcoded. If either is unset/empty, this module fails closed — it reports failure and
logs (internally only, never crashing, never looping) rather than silently pretending to succeed.
"""
import os
import requests

KILAS_BOT_INTERNAL_URL = (os.environ.get("KILAS_BOT_INTERNAL_URL") or "").strip()
INTERNAL_SERVICE_SECRET = (os.environ.get("INTERNAL_SERVICE_SECRET") or "").strip()

_TIMEOUT_SECONDS = 5


def deliver_owner_notification(event_type, message, entity_id=None, business_id=None):
    """Attempts one immediate delivery of an owner notification via the bot's internal endpoint.
    Returns (ok: bool, detail: str). Never raises.

    `event_type` must be one of owner_notifications.EVENT_TYPES (the bot's endpoint independently
    validates this too — belt and suspenders). No destination phone number is ever sent in the
    payload: the bot always sends to its own configured trusted owner number."""
    if not KILAS_BOT_INTERNAL_URL:
        return False, "KILAS_BOT_INTERNAL_URL belum di-set — delivery langsung dilewati, nunggu retry sweep."
    if not INTERNAL_SERVICE_SECRET:
        return False, "INTERNAL_SERVICE_SECRET belum di-set — delivery langsung dilewati, nunggu retry sweep."

    try:
        resp = requests.post(
            KILAS_BOT_INTERNAL_URL,
            json={
                "notification_type": event_type,
                "message": message,
                "entity_id": entity_id,
                "business_id": business_id,
            },
            headers={"X-Internal-Service-Secret": INTERNAL_SERVICE_SECRET},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as e:
        # Network error / timeout / connection refused / DNS failure — the bot process may simply
        # be down or unreachable right now. Never raise; the row stays PENDING for the cron sweep.
        return False, f"internal_delivery_network_error: {type(e).__name__}"

    if resp.status_code != 200:
        return False, f"internal_delivery_http_{resp.status_code}"

    try:
        body = resp.json()
    except ValueError:
        return False, "internal_delivery_bad_response_body"

    if body.get("status") == "ok":
        return True, "delivered"
    return False, f"internal_delivery_rejected: {body.get('message', '(no detail)')}"
