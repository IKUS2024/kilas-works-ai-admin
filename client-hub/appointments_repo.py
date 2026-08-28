"""Persistence for a Pro tenant's own appointment/booking requests (migration 0013).

Replaces ../app.py's previous in-process `tenant_meeting_requests` dict as the SOURCE OF TRUTH —
that dict is process memory only, so a server restart used to silently forget every open booking.
Every function here is scoped by business_id (the tenant) + customer_phone; there is no function
that reads across tenants (that's a Kilas Admin dashboard concern, not this bot-facing module).

STATUS VALUES — deliberately just the ones the actual bot flow uses, nothing speculative:
  REQUESTED             - customer asked for a day/time, not yet confirmed by the owner.
  CONFIRMED             - the tenant owner explicitly confirmed this booking.
  RESCHEDULE_REQUESTED  - customer (or owner) asked to move an existing booking to a new time.
  CANCELLED             - customer or owner cancelled/declined it.
  COMPLETED             - the appointment happened (not written by any flow yet this cycle, but
                          kept available for a future manual/cron mark-as-done step).
"""
import db

STATUSES = ("REQUESTED", "CONFIRMED", "RESCHEDULE_REQUESTED", "CANCELLED", "COMPLETED")

# "Still needs someone's attention / still live" — used for owner-facing listings/queries and for
# resolving which record a "confirm"/"reject" command should act on. CANCELLED/COMPLETED are
# terminal and excluded.
OPEN_STATUSES = ("REQUESTED", "CONFIRMED", "RESCHEDULE_REQUESTED")


def create_appointment(business_id, customer_phone, customer_name, request_text, status="REQUESTED"):
    """Inserts a new appointment row for this tenant+customer. Always inserts (never updates in
    place) — a customer's booking history for a tenant is a sequence of rows, same shape as
    Kilas Works' own `appointments` table already uses for ITS OWN meeting flow."""
    return db.insert_returning_id(
        "INSERT INTO tenant_appointments (business_id, customer_phone, customer_name, request_text, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (business_id, customer_phone, customer_name, request_text, status),
    )


def get_latest_for_customer(business_id, customer_phone, statuses=None):
    """Most recent appointment row for this tenant+customer, optionally restricted to a set of
    statuses (e.g. OPEN_STATUSES, to find 'the booking a reschedule/cancel should act on'). Returns
    None if there is none — callers must treat that as 'no appointment on file', never an error."""
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        row = db.query_one(
            f"SELECT * FROM tenant_appointments WHERE business_id = ? AND customer_phone = ? "
            f"AND status IN ({placeholders}) ORDER BY id DESC LIMIT 1",
            (business_id, customer_phone, *statuses),
        )
    else:
        row = db.query_one(
            "SELECT * FROM tenant_appointments WHERE business_id = ? AND customer_phone = ? "
            "ORDER BY id DESC LIMIT 1",
            (business_id, customer_phone),
        )
    return dict(row) if row is not None else None


def update_status(appointment_id, status, notes=None):
    """Updates status (and optionally notes) on an existing row, scoped by its own id (the caller
    is expected to have already resolved the id via a business_id-scoped lookup — see
    get_latest_for_customer/list_for_business/find_by_customer_name — so this never needs to
    re-check business_id itself)."""
    if status not in STATUSES:
        raise ValueError(f"Unknown tenant_appointments status: {status!r}")
    if notes is not None:
        db.execute(
            "UPDATE tenant_appointments SET status = ?, notes = ?, updated_at = datetime('now') WHERE id = ?",
            (status, notes, appointment_id),
        )
    else:
        db.execute(
            "UPDATE tenant_appointments SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, appointment_id),
        )


def update_request_text(appointment_id, request_text, status=None):
    """Used by the reschedule flow to record the newly-requested day/time on the SAME row (rather
    than creating a second row) while optionally moving its status (e.g. to
    RESCHEDULE_REQUESTED)."""
    if status is not None:
        update_status(appointment_id, status)
    db.execute(
        "UPDATE tenant_appointments SET request_text = ?, updated_at = datetime('now') WHERE id = ?",
        (request_text, appointment_id),
    )


def list_for_business(business_id, statuses=None, limit=50):
    """This tenant's own appointments only, newest first — used for the owner assistant's query
    context and for resolving which appointment a natural-language owner command
    ('Confirm booking Budi.') refers to."""
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        rows = db.query_all(
            f"SELECT * FROM tenant_appointments WHERE business_id = ? AND status IN ({placeholders}) "
            f"ORDER BY id DESC LIMIT ?",
            (business_id, *statuses, limit),
        )
    else:
        rows = db.query_all(
            "SELECT * FROM tenant_appointments WHERE business_id = ? ORDER BY id DESC LIMIT ?",
            (business_id, limit),
        )
    return [dict(r) for r in rows]


def find_by_customer_name(business_id, name_fragment, statuses=OPEN_STATUSES):
    """This tenant's OPEN appointments whose customer_name contains name_fragment
    (case-insensitive) — one row per matching CUSTOMER (their latest open appointment), used to
    resolve an owner command like 'Confirm booking Budi.' Returns a list (0, 1, or several matches
    — several means the caller must ask a clarifying question rather than guess)."""
    if not name_fragment:
        return []
    rows = list_for_business(business_id, statuses=statuses, limit=200)
    fragment = name_fragment.strip().lower()
    seen_customers = set()
    matches = []
    for row in rows:
        name = (row.get("customer_name") or "").strip().lower()
        if name and fragment in name and row["customer_phone"] not in seen_customers:
            seen_customers.add(row["customer_phone"])
            matches.append(row)
    return matches
