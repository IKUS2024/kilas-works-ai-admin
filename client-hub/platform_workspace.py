"""Hidden Kilas Works platform workspace backed by the existing Core Customers/Jobs engine.

The platform WhatsApp Inbox is global/operator-owned rather than tenant-owned. To reuse the same
CRM/Jobs contracts without mixing it into a real client tenant, this module owns one hidden
business row referenced by platform_workspace_scope. It has no membership and is filtered out of
normal client/account listings. Admin-only routes resolve this scope explicitly.

No messages are copied. Contacts are mirrored as Core customer identities while Customer Insight
reads the authoritative platform WhatsApp message table directly.
"""
from datetime import datetime, timezone
import time

import db
import platform_inbox_service
from kilas_core import customers

_SLUG = "__kilas_platform_workspace__"
_NAME = "Kilas Works Workspace"


def _epoch(value):
    if value is None:
        return int(time.time())
    if isinstance(value, (int, float)):
        return max(1, int(value))
    if hasattr(value, "timestamp"):
        try:
            return max(1, int(value.timestamp()))
        except Exception:
            return int(time.time())
    text = str(value).strip()
    if not text:
        return int(time.time())
    try:
        return max(1, int(float(text)))
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(1, int(parsed.timestamp()))
    except (TypeError, ValueError):
        return int(time.time())


def is_scope_business(business_id):
    try:
        row = db.query_one(
            "SELECT business_id FROM platform_workspace_scope WHERE singleton=1"
        )
        return bool(row and int(row["business_id"]) == int(business_id))
    except Exception:
        return False


def business(create=False):
    try:
        row = db.query_one(
            "SELECT b.* FROM platform_workspace_scope s "
            "JOIN businesses b ON b.id=s.business_id WHERE s.singleton=1"
        )
    except Exception:
        row = None
    if row or not create:
        return row
    return ensure_business()


def ensure_business():
    """Idempotently create/resolve the hidden platform workspace business."""
    with customers.transaction() as tx:
        current = tx.one(
            "SELECT b.* FROM platform_workspace_scope s "
            "JOIN businesses b ON b.id=s.business_id WHERE s.singleton=1"
        )
        if current:
            return current

        tx.execute(
            "INSERT INTO businesses(tenant_slug,business_name,package,status,whatsapp_connected) "
            "VALUES (?,?,?,'ACTIVE',?) ON CONFLICT(tenant_slug) DO NOTHING",
            (_SLUG, _NAME, "AI_ADMIN", True),
        )
        internal = tx.one("SELECT * FROM businesses WHERE tenant_slug=?", (_SLUG,))
        if not internal:
            raise RuntimeError("platform_workspace_unavailable")
        tx.execute(
            "INSERT INTO platform_workspace_scope(singleton,business_id) VALUES (1,?) "
            "ON CONFLICT(singleton) DO NOTHING",
            (internal["id"],),
        )
        scoped = tx.one(
            "SELECT b.* FROM platform_workspace_scope s "
            "JOIN businesses b ON b.id=s.business_id WHERE s.singleton=1"
        )
        if not scoped or scoped["id"] != internal["id"]:
            raise RuntimeError("platform_workspace_conflict")
        tx.execute(
            "INSERT INTO business_profiles(business_id,category,short_description,country,timezone,"
            "primary_language,tone,customer_salutation) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(business_id) DO NOTHING",
            (internal["id"], "software agency", "Kilas Works internal platform operations",
             "Indonesia", "Asia/Jakarta", "id", "friendly", "Kak"),
        )
        return scoped


def sync_contacts(limit_messages=5000):
    """Mirror authoritative platform Inbox identities into Core CRM as Leads.

    Existing owner-edited names/stages are preserved. Only the verified WhatsApp identity,
    optional saved platform contact name, and last-activity timestamp are refreshed.
    """
    scope = ensure_business()
    bid = scope["id"]
    rows = platform_inbox_service.list_conversations(limit_messages=limit_messages)
    synced = 0
    for item in rows:
        phone = platform_inbox_service.normalize_customer_phone(item.get("customer_phone"))
        if not phone:
            continue
        display_name = item.get("customer_name") or phone
        activity = _epoch(item.get("last_message_at"))
        try:
            customer = customers.ensure_whatsapp_lead(
                bid, phone, display_name=display_name, now=activity
            )
            if not customer:
                continue
            with customers.transaction() as tx:
                latest = tx.one(
                    "SELECT display_name,phone,last_activity_at FROM kw_core_customers "
                    "WHERE business_id=? AND id=?",
                    (bid, customer["id"]),
                )
                if not latest:
                    continue
                name = latest["display_name"]
                # A platform-saved contact name may replace the original phone placeholder,
                # but never an owner-edited CRM name.
                if item.get("customer_name") and (not name or name == phone):
                    name = str(item["customer_name"]).strip()[:160] or phone
                tx.execute(
                    "UPDATE kw_core_customers SET display_name=?,phone=?,"
                    "last_activity_at=CASE WHEN last_activity_at<? THEN ? ELSE last_activity_at END,"
                    "updated_at=CASE WHEN updated_at<? THEN ? ELSE updated_at END "
                    "WHERE business_id=? AND id=?",
                    (name, phone, activity, activity, activity, activity, bid, customer["id"]),
                )
            synced += 1
        except Exception:
            continue
    return scope, synced


def customer_for_phone(phone):
    scope = ensure_business()
    normalized = platform_inbox_service.normalize_customer_phone(phone)
    if not normalized:
        return None
    try:
        identity_hash = __import__("hashlib").sha256(normalized.encode()).hexdigest()
        return db.query_one(
            "SELECT c.*,COALESCE(s.stage,'CUSTOMER') AS stage "
            "FROM kw_core_customer_identities i "
            "JOIN kw_core_customers c ON c.business_id=i.business_id AND c.id=i.customer_id "
            "LEFT JOIN kw_core_customer_stages s ON s.business_id=c.business_id AND s.customer_id=c.id "
            "WHERE i.business_id=? AND i.identity_type='WHATSAPP_PHONE' AND i.identity_hash=?",
            (scope["id"], identity_hash),
        )
    except Exception:
        return None
