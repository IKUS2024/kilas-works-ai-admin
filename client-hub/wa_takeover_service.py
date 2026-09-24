"""Human takeover — Business Hub V2, Phase H (Section 21).

Scope discipline (from the master spec itself): "If full WhatsApp Business App coexistence is not
currently enabled/eligible, do not fake it. Provide the supported dashboard/manual human takeover
architecture first." This module IS that architecture — a per (tenant, customer_phone) mode flag,
tenant-safe (never affects another tenant's conversations) and per-customer-safe (never affects
another customer of the SAME tenant). It is fully built and tested here.

WHAT IS NOT DONE YET, AND WHY: the production WhatsApp bot (../app.py) does not yet check this
table before auto-replying — wiring that in is Patch 4 in BOT_INTEGRATION_GUIDE.md, deliberately
left unapplied for the same reason every other bot-integration patch in this codebase has been left
unapplied so far: it is a change to the LIVE, working WhatsApp engine, and every cycle in this
engagement has treated "do not modify production bot behavior" as an absolute constraint unless a
specific patch has been explicitly reviewed and approved. This module's own logic is complete and
tested; only the one-line check inside app.py's message handler remains, by design, for a
deliberate future step.
"""
import db
import repo

MODES = ("AI_ACTIVE", "HUMAN_TAKEOVER")


def get_state(business_id, customer_phone):
    row = db.query_one(
        "SELECT * FROM wa_conversation_state WHERE business_id = ? AND customer_phone = ?",
        (business_id, customer_phone),
    )
    return row["mode"] if row else "AI_ACTIVE"  # default: AI active until a human explicitly takes over


def is_human_takeover_active(business_id, customer_phone):
    return get_state(business_id, customer_phone) == "HUMAN_TAKEOVER"


def start_human_takeover(business_id, customer_phone, actor_user_id):
    _upsert(business_id, customer_phone, "HUMAN_TAKEOVER", actor_user_id)
    repo.write_audit(actor_user_id, business_id, "HUMAN_TAKEOVER_STARTED", f"customer={customer_phone}")


def return_to_ai(business_id, customer_phone, actor_user_id):
    _upsert(business_id, customer_phone, "AI_ACTIVE", actor_user_id)
    repo.write_audit(actor_user_id, business_id, "HUMAN_TAKEOVER_ENDED", f"customer={customer_phone}")


def _upsert(business_id, customer_phone, mode, actor_user_id):
    from kilas_core import whatsapp_access
    if whatsapp_access.selected(business_id):
        from public_chat import store
        from kilas_core.adapters import whatsapp
        with store.transaction() as tx:
            link=tx.one('SELECT conversation_id FROM kw_core_wa_conversations WHERE business_id=? AND customer_phone=?',(business_id,customer_phone))
        if link:
            whatsapp.mode(business_id,link['conversation_id'],mode,actor_user_id)
            return
    existing = db.query_one(
        "SELECT id FROM wa_conversation_state WHERE business_id = ? AND customer_phone = ?",
        (business_id, customer_phone),
    )
    if existing is None:
        db.execute(
            "INSERT INTO wa_conversation_state (business_id, customer_phone, mode, updated_by_user_id) "
            "VALUES (?, ?, ?, ?)",
            (business_id, customer_phone, mode, actor_user_id),
        )
    else:
        db.execute(
            "UPDATE wa_conversation_state SET mode = ?, updated_by_user_id = ?, updated_at = datetime('now') "
            "WHERE id = ?"
            if db.BACKEND == "sqlite" else
            "UPDATE wa_conversation_state SET mode = ?, updated_by_user_id = ?, updated_at = now() "
            "WHERE id = ?",
            (mode, actor_user_id, existing["id"]),
        )


def list_takeover_conversations_for_business(business_id):
    return db.query_all(
        "SELECT * FROM wa_conversation_state WHERE business_id = ? ORDER BY updated_at DESC",
        (business_id,),
    )


def set_state_in_transaction(tx, business_id, customer_phone, mode, actor_user_id):
    """Core adapter uses the same takeover state inside its conversation-fenced transaction."""
    if mode not in MODES:
        raise ValueError('invalid_mode')
    tx.execute('INSERT INTO wa_conversation_state(business_id,customer_phone,mode,updated_by_user_id) '
               'VALUES (?,?,?,?) ON CONFLICT(business_id,customer_phone) DO UPDATE SET '
               'mode=excluded.mode,updated_by_user_id=excluded.updated_by_user_id',
               (business_id,customer_phone,mode,actor_user_id))
