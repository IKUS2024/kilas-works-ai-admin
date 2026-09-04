"""Owner WhatsApp notifications — Business Hub V2, Final Ecosystem Sync (Section 10/11/12).

WHY THIS SHAPE (documented per the master spec's explicit request):

Client Hub and the production WhatsApp bot (../app.py) are two separate Flask processes — Client
Hub has no direct handle on app.py's `send_whatsapp_message()` / WhatsApp Cloud API credentials,
and app.py is not supposed to import Client Hub's route layer either. Rather than merge the two
processes (explicitly out of scope — "DO NOT redesign the whole system"), this module follows the
same shape the codebase already uses for the Client-Hub-bridge in app.py, just mirrored the other
direction:

  1. Client Hub writes a durable, idempotent "pending notification" row to `owner_notifications`
     (this module) at the exact moment an important event happens (quotation approved, payment
     proof uploaded, custom project / talent request submitted, AI onboarding ready for review,
     WhatsApp-connection-ready). No network call happens here — writing to Client Hub's own
     database can never fail because WhatsApp/Meta is down.
  2. app.py polls for PENDING rows via a small cron-secured endpoint (`/cron/owner-notifications`,
     added alongside the existing `/cron/followups` pattern) and does the actual WhatsApp send with
     its own `send_whatsapp_message()` / OWNER_WHATSAPP_NUMBER — the one place in the whole system
     that is allowed to talk to the WhatsApp Cloud API. It marks each row SENT or FAILED.
     FAILED rows are retried on the next poll; SENT rows are never touched again.

IDEMPOTENCY: `notify_owner_once()` is the only way to create a row. `event_key` is UNIQUE at the
DB level (migration 0010) — a caller may invoke this function any number of times for the same
logical event (webhook retry, duplicate form submit, restart re-processing a queue) and only the
first call ever creates a row. Even if the unique constraint's IntegrityError races with another
thread, both threads end up with exactly one PENDING row.

This module deliberately does no delivery itself — it has no WhatsApp credentials to do so, and
should never be given any (keeps the "callers unrelated to WhatsApp never touch that surface"
boundary intact).
"""
import db

EVENT_TYPES = (
    "AI_ONBOARDING_READY_FOR_REVIEW",
    "CUSTOM_PROJECT_SUBMITTED",
    "TALENT_REQUEST_SUBMITTED",
    "QUOTATION_APPROVED",
    "PAYMENT_PROOF_UPLOADED",
    "WHATSAPP_CONNECTION_READY",
    "HUMAN_ATTENTION_REQUIRED",
)


def notify_owner_once(event_key, event_type, entity_id, business_id, message):
    """Check-then-insert: if a row with this event_key already exists (this event was already
    queued/sent before), do nothing and return False. Otherwise insert a new PENDING row and
    return True. Never raises — a notification-plumbing bug must never break the caller's real
    business-logic transaction (quotation approval, payment upload, etc.).

    Absolute Final Production Patch: right after a fresh row is created, this ALSO makes one
    immediate delivery attempt (see owner_notification_delivery.py) instead of waiting for the
    next /cron/owner-notifications poll. That attempt is wrapped so any failure (network error,
    bot unreachable, secret misconfigured) just leaves the row PENDING/FAILED for the retry sweep
    — it can never turn a successfully-queued notification into a lost one, and it can never raise
    into the caller."""
    try:
        existing = db.query_one("SELECT id FROM owner_notifications WHERE event_key = ?", (event_key,))
        if existing is not None:
            return False
        notification_id = db.insert_returning_id(
            "INSERT INTO owner_notifications (event_key, event_type, entity_id, business_id, "
            "message, delivery_status) VALUES (?, ?, ?, ?, ?, 'PENDING')",
            (event_key, event_type, entity_id, business_id, message),
        )
    except Exception:
        # Includes a UNIQUE-constraint race on event_key (two concurrent callers for the same
        # event) — that is the expected "someone else already queued this" outcome, not an error.
        return False

    try:
        _attempt_immediate_delivery(notification_id, event_type, message, entity_id, business_id)
    except Exception:
        # Immediate delivery is best-effort. Any failure here (including this module's own import
        # failing) leaves the row PENDING — the row was already committed above, so the event is
        # never lost, just not sent instantly. The fallback /cron/owner-notifications sweep will
        # pick it up.
        pass
    return True


def _attempt_immediate_delivery(notification_id, event_type, message, entity_id, business_id):
    import owner_notification_delivery
    ok, detail = owner_notification_delivery.deliver_owner_notification(
        event_type, message, entity_id=entity_id, business_id=business_id,
    )
    if ok:
        mark_sent(notification_id)
    else:
        mark_failed(notification_id)
        print(f"Owner notification #{notification_id} ({event_type}): immediate delivery gagal ({detail}), "
              f"disimpan PENDING/FAILED untuk retry sweep.")


def list_pending():
    return db.query_all(
        "SELECT * FROM owner_notifications WHERE delivery_status IN ('PENDING', 'FAILED') "
        "ORDER BY created_at ASC"
    )


def mark_sent(notification_id):
    """Marks a row SENT (terminal — the retry sweep's `list_pending()` never selects SENT rows
    again, so this is also what guarantees a row is delivered at most once). Also records this as
    a delivery attempt, whether the send happened via the immediate-delivery path or the
    /cron/owner-notifications fallback sweep."""
    if db.BACKEND == "sqlite":
        db.execute(
            "UPDATE owner_notifications SET delivery_status = 'SENT', sent_at = ?, "
            "delivery_attempts = delivery_attempts + 1, last_attempted_at = ? WHERE id = ?",
            (_now_sqlite(), _now_sqlite(), notification_id),
        )
    else:
        db.execute(
            "UPDATE owner_notifications SET delivery_status = 'SENT', sent_at = now(), "
            "delivery_attempts = delivery_attempts + 1, last_attempted_at = now() WHERE id = ?",
            (notification_id,),
        )


def mark_failed(notification_id):
    """Marks a row FAILED (== FAILED_RETRYABLE in the master spec's vocabulary — this codebase
    keeps the original PENDING/SENT/FAILED status names from migration 0010 rather than renaming
    them, since `list_pending()` already retries both PENDING and FAILED rows and only ever
    excludes SENT ones)."""
    if db.BACKEND == "sqlite":
        db.execute(
            "UPDATE owner_notifications SET delivery_status = 'FAILED', "
            "delivery_attempts = delivery_attempts + 1, last_attempted_at = ? WHERE id = ?",
            (_now_sqlite(), notification_id),
        )
    else:
        db.execute(
            "UPDATE owner_notifications SET delivery_status = 'FAILED', "
            "delivery_attempts = delivery_attempts + 1, last_attempted_at = now() WHERE id = ?",
            (notification_id,),
        )


def _now_sqlite():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(sep=" ", timespec="seconds")


# ---------------------------------------------------------------------------
# Event builders — one per trigger point (Section 11). Each builds a stable event_key (so the
# same underlying event never double-fires) and a professional, concise Indonesian message with a
# deep link into the admin app. None of these ever invent a price or expose raw DB internals.
# ---------------------------------------------------------------------------

_ADMIN_BASE = "https://app.kilasworks.id/admin"


def notify_ai_onboarding_ready(business_id, business_name):
    message = (
        f"\U0001F514 Onboarding AI Admin dari \"{business_name}\" sudah lengkap dan siap direview.\n"
        f"Review di: {_ADMIN_BASE}/business/{business_id}"
    )
    return notify_owner_once(
        f"ai_onboarding_ready:{business_id}", "AI_ONBOARDING_READY_FOR_REVIEW",
        business_id, business_id, message,
    )


def notify_custom_project_submitted(project_id, business_id, project_type, title):
    message = (
        f"\U0001F4DD Permintaan custom project baru ({project_type.title()}): \"{title}\".\n"
        f"Lihat & buat penawaran: {_ADMIN_BASE}/projects/{project_id}"
    )
    return notify_owner_once(
        f"custom_project_submitted:{project_id}", "CUSTOM_PROJECT_SUBMITTED",
        project_id, business_id, message,
    )


def notify_talent_request_submitted(request_id, project_id, business_id, talent_name):
    message = (
        f"\U0001F3AC Ada permintaan Talent Management baru untuk {talent_name}.\n"
        f"Lihat & buat penawaran: {_ADMIN_BASE}/projects/{project_id}"
    )
    return notify_owner_once(
        f"talent_request_submitted:{request_id}", "TALENT_REQUEST_SUBMITTED",
        project_id, business_id, message,
    )


def notify_quotation_approved(quotation_id, project_id, business_id, quotation_number, final_price):
    price_fmt = f"Rp{final_price:,}".replace(",", ".") if final_price else "-"
    message = (
        f"✅ Quotation {quotation_number} ({price_fmt}) sudah di-approve customer.\n"
        f"Lihat project: {_ADMIN_BASE}/projects/{project_id}"
    )
    return notify_owner_once(
        f"quotation_approved:{quotation_id}", "QUOTATION_APPROVED",
        project_id, business_id, message,
    )


def notify_payment_proof_uploaded(payment_id, invoice_id, business_id, business_name, amount):
    """Section 10(E): VERY IMPORTANT / highest priority notification.

    business_name may be None for a business-less payment (purchase-flow correction — general
    fixed-price services work end-to-end without ever requiring a business). The message falls
    back to identifying the invoice by number instead of inventing/faking a business name — never
    silently drops the "who is this from" context the admin needs, just derives it from what
    genuinely exists (the invoice) instead of what doesn't (a business)."""
    amount_fmt = f"Rp{amount:,}".replace(",", ".") if amount else "-"
    source_label = f'"{business_name}"' if business_name else f"invoice #{invoice_id}"
    message = (
        f"\U0001F4B0 Bukti pembayaran baru masuk dari {source_label} untuk invoice #{invoice_id} "
        f"— {amount_fmt}. Cek & verifikasi: {_ADMIN_BASE}/payments/{payment_id}"
    )
    return notify_owner_once(
        f"payment_proof_uploaded:{payment_id}", "PAYMENT_PROOF_UPLOADED",
        payment_id, business_id, message,
    )


def notify_whatsapp_connection_ready(business_id, business_name):
    message = (
        f"\U0001F4F1 \"{business_name}\" sudah paid & approved untuk AI Admin — siap dihubungkan "
        f"ke WhatsApp.\nBuka: {_ADMIN_BASE}/business/{business_id}"
    )
    return notify_owner_once(
        f"whatsapp_connection_ready:{business_id}", "WHATSAPP_CONNECTION_READY",
        business_id, business_id, message,
    )


def notify_human_attention_required(business_id, reason, ref_id=None):
    message = f"⚠️ Perlu perhatian manual: {reason}"
    key = f"human_attention:{business_id}:{ref_id or reason}"
    return notify_owner_once(key, "HUMAN_ATTENTION_REQUIRED", ref_id, business_id, message)
