"""Central UI display-label / humanization helpers — Client Hub UI cleanup.

Backend field names, enum/status codes, and raw audit event/detail strings are NEVER changed in
the database — this module only maps them to human-readable Indonesian copy for PRESENTATION.
Templates should call these (registered as Jinja filters in app.py) instead of rendering a raw
`.status`/`.package`/field name directly, and instead of hardcoding a translation inline wherever
one happens to be needed — one place to add/fix a label, not N scattered copies that can drift out
of sync with each other.

Nothing here ever deletes, alters, or hides underlying data — an unmapped code still displays
(title-cased, underscores replaced with spaces) rather than disappearing, so a status this module
doesn't yet know about is still visible and diagnosable, just not perfectly phrased.
"""
import re
from datetime import datetime, timezone, timedelta

FIELD_LABELS = {
    "business_name": "Nama bisnis",
    "owner_name": "Nama owner",
    "category": "Kategori bisnis",
    "primary_language": "Bahasa utama",
    "additional_languages": "Bahasa tambahan",
    "customer_salutation": "Sapaan untuk pelanggan",
    "core_product_or_service": "Produk / layanan utama",
    "operating_hours": "Jam operasional",
    "closed_days": "Hari libur",
    "holiday_info": "Hari libur",
    "online_or_offline": "Jenis layanan",
    "tone": "Gaya bahasa AI",
    "business_phone": "Nomor WhatsApp bisnis",
    "address": "Alamat",
    "short_description": "Deskripsi singkat",
    "country": "Negara",
    "timezone": "Zona waktu",
    "appointment_enabled": "Booking appointment",
    "appointment_rules_raw": "Aturan booking appointment",
    "payment_bank_name": "Nama bank",
    "payment_account_number": "Nomor rekening",
    "payment_account_holder": "Nama pemilik rekening",
    "payment_account_name": "Nama pemilik rekening",
    "payment_instructions": "Instruksi pembayaran",
}

PACKAGE_LABELS = {
    "NONE": "Belum pakai AI Admin",
    "AI_ADMIN_BASIC": "AI Admin Basic",
    "AI_ADMIN_PRO": "AI Admin Pro",
}

BUSINESS_STATUS_LABELS = {
    "DRAFT": "Draft",
    "ONBOARDING": "Sedang setup",
    "READY_FOR_REVIEW": "Siap ditinjau",
    "NEEDS_REVISION": "Perlu revisi",
    "APPROVED": "Disetujui",
    "ACTIVE": "Aktif",
    "SUSPENDED": "Ditangguhkan",
    "CANCELLED": "Dibatalkan",
}

PROJECT_STATUS_LABELS = {
    "WAITING_FOR_QUOTE": "Menunggu penawaran",
    "APPROVED": "Disetujui",
    "PAYMENT_PENDING": "Menunggu pembayaran",
    "PAID": "Sudah dibayar",
    "IN_PROGRESS": "Sedang dikerjakan",
    "COMPLETED": "Selesai",
    "CANCELLED": "Dibatalkan",
    "REJECTED": "Ditolak",
}

PAYMENT_STATUS_LABELS = {
    "PAYMENT_PENDING": "Menunggu pembayaran",
    "PAYMENT_NOT_STARTED": "Belum mulai bayar",
    "PENDING_VERIFICATION": "Menunggu verifikasi",
    "UNDER_REVIEW": "Sedang diperiksa",
    "AUTO_CHECK_PASSED": "Cek otomatis lolos",
    "AMOUNT_MISMATCH": "Nominal tidak sesuai",
    "DATA_MISMATCH": "Data tidak sesuai",
    "UNREADABLE": "Tidak terbaca",
    "POSSIBLE_DUPLICATE": "Kemungkinan duplikat",
    "NEEDS_MANUAL_REVIEW": "Perlu review manual",
    "VERIFIED": "Terverifikasi",
    "REJECTED": "Ditolak",
}

# Full-sentence customer-facing messages (Section 12 of the payment-verification-strengthening
# request) — deliberately SEPARATE from PAYMENT_STATUS_LABELS above, which stays short (used
# inline in admin tables/pills where a full sentence would break the layout). These are for the
# CUSTOMER'S OWN invoice page, where a complete, natural sentence is what was explicitly asked
# for, not a short label.
PAYMENT_CUSTOMER_MESSAGE_LABELS = {
    "PAYMENT_PENDING": "Menunggu pembayaran. Silakan transfer sesuai nominal tagihan.",
    "UNDER_REVIEW": "Bukti pembayaran sudah diterima dan sedang dikonfirmasi.",
    "AUTO_CHECK_PASSED": "Bukti pembayaran sudah diterima dan sedang dikonfirmasi.",
    "AMOUNT_MISMATCH": "Nominal pada bukti belum sesuai dengan tagihan.",
    "DATA_MISMATCH": "Data pada bukti belum sesuai dengan tagihan.",
    "UNREADABLE": "Bukti pembayaran kurang jelas. Silakan upload ulang.",
    "POSSIBLE_DUPLICATE": "Pembayaran sedang diperiksa oleh tim.",
    "NEEDS_MANUAL_REVIEW": "Pembayaran sedang diperiksa oleh tim.",
    "VERIFIED": "Pembayaran berhasil diverifikasi.",
    "REJECTED": "Bukti pembayaran belum bisa diverifikasi. Silakan hubungi tim atau upload ulang.",
}

QUOTATION_STATUS_LABELS = {
    "DRAFT": "Draft",
    "SENT": "Terkirim",
    "VIEWED": "Sudah dilihat",
    "APPROVED": "Disetujui",
    "REJECTED": "Ditolak",
    "EXPIRED": "Kedaluwarsa",
}

INVOICE_STATUS_LABELS = {
    "ISSUED": "Diterbitkan",
    "PAID": "Sudah dibayar",
    "CANCELLED": "Dibatalkan",
}

SUBSCRIPTION_STATUS_LABELS = {
    "ACTIVE": "Aktif",
    "GRACE": "Masa tenggang",
    "SUSPENDED": "Ditangguhkan",
    "CANCELLED": "Dibatalkan",
}

TALENT_REQUEST_STATUS_LABELS = {
    "PENDING": "Menunggu respons",
    "CONFIRMED": "Dikonfirmasi",
    "DECLINED": "Ditolak",
}

AI_SETUP_STATUS_LABELS = {
    "PENDING": "Menunggu diproses",
    "RUNNING": "Sedang diproses",
    "DONE": "Selesai",
    "STALE": "Perlu diproses ulang (data bisnis baru diubah)",
    "FAILED": "Belum berhasil — data kamu tetap aman",
}

TONE_LABELS = {
    "friendly": "Ramah & santai",
    "formal": "Formal",
    "casual-professional": "Santai tapi profesional",
}

_STATUS_TABLES = {
    "business": BUSINESS_STATUS_LABELS,
    "project": PROJECT_STATUS_LABELS,
    "payment": PAYMENT_STATUS_LABELS,
    "quotation": QUOTATION_STATUS_LABELS,
    "invoice": INVOICE_STATUS_LABELS,
    "subscription": SUBSCRIPTION_STATUS_LABELS,
    "talent_request": TALENT_REQUEST_STATUS_LABELS,
    "ai_setup": AI_SETUP_STATUS_LABELS,
}

AUDIT_ACTION_LABELS = {
    "PROJECT_CREATED": "Pesanan dibuat",
    "PROJECT_STATUS_CHANGED": "Status pesanan diperbarui",
    "business_upgraded_to_ai_admin": "Paket AI Admin diaktifkan",
    "submitted_for_review": "Bisnis dikirim untuk ditinjau",
    "PAYMENT_PROOF_UPLOADED": "Bukti pembayaran diunggah",
    "CS_MANUAL_REPLY_SENT": "Balasan manual dikirim",
    "CS_TEMPLATE_REPLY_SENT": "Template pesan dikirim",
    "PLATFORM_CS_MANUAL_REPLY_SENT": "Balasan manual dikirim",
    "PLATFORM_CS_TEMPLATE_REPLY_SENT": "Template pesan dikirim",
    "HUMAN_TAKEOVER_STARTED": "Chat diambil alih manusia",
    "HUMAN_TAKEOVER_ENDED": "Chat dikembalikan ke AI",
    "QUOTATION_SENT": "Penawaran dikirim",
    "QUOTATION_APPROVED": "Penawaran disetujui",
    "QUOTATION_REJECTED": "Penawaran ditolak",
}


def humanize_field(field_name):
    """A raw backend field name -> its Indonesian display label. Unknown fields fall back to the
    field name itself (never hidden), so an unmapped field is still visible for diagnosis."""
    return FIELD_LABELS.get(field_name, field_name)


def humanize_missing_fields(fields):
    return [humanize_field(f) for f in (fields or [])]


def missing_fields_sentence(fields):
    """Natural full-sentence Indonesian for a missing-required-fields warning, replacing a bare
    comma-separated list of raw/label field names. E.g. ["Bahasa utama", "Sapaan untuk pelanggan"]
    -> "Lengkapi Bahasa utama dan Sapaan untuk pelanggan agar AI Admin dapat berkomunikasi sesuai
    gaya bisnis ini." Falls back gracefully for 1 or 3+ items."""
    labels = humanize_missing_fields(fields)
    if not labels:
        return ""
    if len(labels) == 1:
        joined = labels[0]
    else:
        joined = ", ".join(labels[:-1]) + f" dan {labels[-1]}"
    return f"Lengkapi {joined} agar AI Admin dapat berkomunikasi sesuai gaya bisnis ini."


def humanize_package(code):
    if not code:
        return "Belum diisi"
    return PACKAGE_LABELS.get(code, code.replace("_", " ").title())


def humanize_status(code, kind="business"):
    """`kind` picks which status vocabulary to use (business/project/payment/quotation/invoice/
    subscription/talent_request) — the SAME code string can mean different things in different
    tables (e.g. "APPROVED" on a business vs. a quotation), so the caller must say which one this
    is. Unknown kind or unknown code both fall back to a readable title-cased version rather than
    hiding the value."""
    if not code:
        return "Belum diisi"
    table = _STATUS_TABLES.get(kind, {})
    return table.get(code, code.replace("_", " ").title())


def display_or_missing(value):
    """None, empty string, or whitespace-only -> "Belum diisi". Anything else is returned as-is
    (never modifies real content, only substitutes the "nothing here" case)."""
    if value is None:
        return "Belum diisi"
    if isinstance(value, str) and not value.strip():
        return "Belum diisi"
    return value


_DETAIL_PATTERNS = [
    (re.compile(r'^fixed-price:\s*(.+?)\s*\(project_id=\d+\)$'), lambda m: f"Pesanan {m.group(1)} dibuat"),
    (re.compile(r'^checkout:\s*(\S+)$'), lambda m: f"Invoice {m.group(1)} dibuat"),
    (re.compile(r'^package=NONE$'), lambda m: "Belum memiliki paket AI Admin"),
    (re.compile(r'^package=(\S+)$'), lambda m: f"Paket: {humanize_package(m.group(1))}"),
    (re.compile(r'^customer=(\S+)$'), lambda m: f"Customer: {m.group(1)}"),
    (re.compile(r'^config_version=(\d+)$'), lambda m: f"Konfigurasi tenant diperbarui (versi {m.group(1)})"),
]


def humanize_audit_action(action):
    """A raw audit_log.action value -> a human-readable Indonesian description. The RAW value in
    the database is never touched — this only affects what's rendered. Unknown actions fall back
    to a readable version (underscores replaced with spaces, capitalized) rather than being
    hidden, so a not-yet-mapped event type is still visible/traceable on the dashboard."""
    if not action:
        return "-"
    if action in AUDIT_ACTION_LABELS:
        return AUDIT_ACTION_LABELS[action]
    return action.replace("_", " ").strip().capitalize()


def humanize_audit_detail(detail):
    """A raw audit_log.detail string -> human-readable Indonesian, when it matches one of a small
    set of known structured formats (e.g. "fixed-price: AI Admin Pro (project_id=1)" ->
    "Pesanan AI Admin Pro dibuat"). The RAW value in the database is never touched. A detail string
    that doesn't match any known pattern is returned exactly as stored — never hidden or
    truncated, since it may still carry technically-useful information for an admin even
    unformatted."""
    if not detail:
        return "-"
    text = detail.strip()
    for pattern, fn in _DETAIL_PATTERNS:
        m = pattern.match(text)
        if m:
            return fn(m)
    return detail


def humanize_tone(code):
    if not code:
        return "Belum diisi"
    return TONE_LABELS.get(code, code.replace("-", " ").title())


def humanize_payment_message(code):
    """Full-sentence customer-facing message for a (possibly derived, see payment_service.
    derive_review_status()) payment status code — see PAYMENT_CUSTOMER_MESSAGE_LABELS above.
    Unknown code falls back to the short PAYMENT_STATUS_LABELS entry (still readable, never
    hidden) rather than a blank message."""
    if not code:
        return "Belum diisi"
    return PAYMENT_CUSTOMER_MESSAGE_LABELS.get(code, humanize_status(code, "payment"))


def humanize_timestamp(value):
    """Raw UTC timestamp (e.g. "2026-09-03 02:51:58.217447+00:00", or a naive SQLite string with
    no offset at all, or a datetime object) -> Indonesia-friendly WIB display (e.g.
    "3 Sep 2026, 09:51 WIB"). Real timezone conversion (UTC -> UTC+7), never a string-replace
    trick — a naive/offset-less timestamp is explicitly assumed to already be UTC (matching how
    every timestamp in this codebase is actually stored, both SQLite's `datetime('now')` and
    PostgreSQL's `now()`), so it is converted the same way a tz-aware one is. Unparseable/empty
    input returns "Belum diisi" (display_or_missing's own convention) rather than raising."""
    if value is None:
        return "Belum diisi"
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return "Belum diisi"
        # Normalize a SQL-style "YYYY-MM-DD HH:MM:SS[.ffffff][+00:00]" into something
        # datetime.fromisoformat() accepts (it wants a "T" separator, or Python 3.11+ which
        # accepts a space too — stay compatible either way by inserting "T" explicitly).
        normalized = text.replace(" ", "T", 1) if " " in text and "T" not in text else text
        normalized = normalized.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return text  # unrecognized format — show as-is rather than hide real information
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    wib = dt.astimezone(timezone(timedelta(hours=7)))
    months = ("Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des")
    return f"{wib.day} {months[wib.month - 1]} {wib.year}, {wib.strftime('%H:%M')} WIB"


def looks_technical(detail):
    """Section S: hide technical details (config_version=N, internal enum names, etc.) from the
    default audit log view, available behind "Lihat detail" instead. Used to decide whether the
    RAW detail string should also be shown (collapsed) alongside the humanized one — a detail that
    humanize_audit_detail() already fully replaced (e.g. matched one of _DETAIL_PATTERNS) has
    nothing further to hide; this specifically catches whatever's LEFT OVER after that pass:
    raw key=value pairs, SCREAMING_SNAKE_CASE tokens, or a detail with no matched pattern at all
    that still isn't plain human sentence."""
    if not detail:
        return False
    text = detail.strip()
    if re.search(r'[a-zA-Z_]+=\S', text):  # key=value pattern (config_version=2, project_id=1, ...)
        return True
    if re.fullmatch(r'[A-Z0-9_]+', text):  # bare SCREAMING_SNAKE_CASE token
        return True
    return False


def register_jinja_filters(app):
    """Wires every helper above into Jinja as a template filter, so templates use e.g.
    `{{ business.package|humanize_package }}` instead of a raw `{{ business.package }}`, and
    `{{ a.action|humanize_audit_action }}` instead of `{{ a.action }}`."""
    app.jinja_env.filters["humanize_field"] = humanize_field
    app.jinja_env.filters["humanize_package"] = humanize_package
    app.jinja_env.filters["humanize_status"] = humanize_status
    app.jinja_env.filters["humanize_tone"] = humanize_tone
    app.jinja_env.filters["humanize_payment_message"] = humanize_payment_message
    app.jinja_env.filters["humanize_timestamp"] = humanize_timestamp
    app.jinja_env.filters["looks_technical"] = looks_technical
    app.jinja_env.filters["display_or_missing"] = display_or_missing
    app.jinja_env.filters["humanize_audit_action"] = humanize_audit_action
    app.jinja_env.filters["humanize_audit_detail"] = humanize_audit_detail
