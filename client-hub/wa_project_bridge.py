"""AI-as-sales/project-coordinator logic — Business Hub V2, Phase F (Section 16/17/24-26).

SCOPE HONESTY: this module implements the pure decision/parsing logic the master spec describes
(classify an owner message, parse a natural-language price offer, render a professional
customer-facing message, and describe how customer/WhatsApp price questions should be answered).
It is fully built and unit-tested here, exactly like every other "future bot integration" piece in
this codebase (tenant_config_service.py's contract functions, wa_takeover_service.py). It is NOT
wired into the live production WhatsApp bot (../app.py) in this phase — see
BOT_INTEGRATION_GUIDE.md's Patch 5/6 for the deliberate, unapplied integration plan, and the
Phase A-onward pattern of never touching the live bot's message-handling loop without a dedicated,
separately-reviewed patch. The bot's OWN existing owner-NLU/action-routing logic (already
production-tested, see test_owner_nlu.py etc. in the parent app) is untouched and keeps working
exactly as it does today.

Functions here are deliberately pure (no I/O, no DB writes) so they're trivial to unit test and
trivial to eventually call from the bot's webhook handler without any circular dependency.
"""
import re

# ---------------------------------------------------------------------------
# Owner message classification (Section 16: query vs internal note vs send-action)
# ---------------------------------------------------------------------------

_QUERY_PATTERNS = [
    r"\b(gimana|bagaimana)\b.*\?", r"\bberapa\b", r"\bsiapa\b", r"\bstatus\b",
    r"\budah masuk belum\b", r"\bsudah masuk belum\b", r"minta berapa",
]

# Task 4 (Pro tenant owner assistant deepening cycle) — this list intentionally does NOT depend on
# one magic verb. It started as a short set ('bilang', 'kirim', 'kasih tau', 'sampaikan',
# 'beritahu', 'info ke') and is extended here with the natural variants an Indonesian small-
# business owner actually types for "reply to/relay to/follow up with a customer": bales/balas,
# jawab, bilangin, terusin, follow up/follow-up, tanyain, ingetin, and "reminder-in" (customer). A
# few examples this now recognizes as OWNER_ACTION that it did not before:
#   "Bales Budi bilang stoknya ada."      -> bales
#   "Follow up yang kemarin."             -> follow up
#   "Tanyain jadi booking atau enggak."   -> tanyain
#   "Terusin ke customer tadi."           -> terusin
#   "Ingetin dia besok jam 3."            -> ingetin
# Multi-word phrases work the same way single words already did — a plain substring/word-boundary
# check — so no separate matching logic is needed for them.
_SEND_ACTION_VERBS = [
    "bilang", "bilangin", "kirim", "kasih tau", "kabarin", "sampaikan", "beritahu", "info ke",
    "bales", "balas", "jawab", "terusin", "follow up", "follow-up", "tanyain", "ingetin",
    "reminder-in", "reminderin",
]


def classify_owner_message(text):
    """Returns one of OWNER_QUERY | OWNER_INTERNAL_NOTE | OWNER_ACTION.

    OWNER_ACTION requires an explicit send-verb (see _SEND_ACTION_VERBS — 'bilang', 'kirim',
    'bales', 'follow up', 'tanyain', 'ingetin', ...) — this is deliberately conservative
    (Section 16: 'Only explicit sending intent should send to customer'), just no longer limited
    to one narrow verb list. Anything that looks like a question is OWNER_QUERY. Everything else
    (owner thinking out loud / 'curhat') is OWNER_INTERNAL_NOTE and NEVER triggers an outbound
    message.
    """
    lowered = (text or "").strip().lower()
    if not lowered:
        return "OWNER_INTERNAL_NOTE"

    for verb in _SEND_ACTION_VERBS:
        # Word-boundary match, not a bare substring check — with more (and shorter) verbs in the
        # list now ('jawab', 'kirim', 'bales', ...), a plain "verb in lowered" would also fire
        # inside unrelated words that happen to contain them (e.g. "jawab" inside "terjawab"/
        # "dijawab", "kirim" inside "pengiriman"), which a bare substring check for the original
        # short list mostly avoided by luck rather than by design.
        if re.search(rf"\b{re.escape(verb)}\b", lowered):
            return "OWNER_ACTION"

    if "?" in lowered:
        return "OWNER_QUERY"
    for pattern in _QUERY_PATTERNS:
        if re.search(pattern, lowered):
            return "OWNER_QUERY"

    return "OWNER_INTERNAL_NOTE"


# ---------------------------------------------------------------------------
# Natural-language price-offer parsing (Section 16/17)
# e.g. "bilang ke customer 3 juta bisa 3 video. kalau 5 video 4,2 juta. shooting satu hari."
# ---------------------------------------------------------------------------

_NUMBER_WORD_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(juta|jt|rb|ribu|k)\b", re.IGNORECASE
)


def _parse_rupiah_amount(fragment):
    """Parses Indonesian shorthand currency ('3 juta', '4,2 juta', '500rb', '500ribu') into whole
    rupiah. Returns None if nothing recognizable is found — callers must never guess a default."""
    match = _NUMBER_WORD_RE.search(fragment)
    if not match:
        return None
    number_str, unit = match.group(1), match.group(2).lower()
    number_str = number_str.replace(",", ".")
    try:
        number = float(number_str)
    except ValueError:
        return None
    if unit in ("juta", "jt"):
        return int(number * 1_000_000)
    if unit in ("rb", "ribu", "k"):
        return int(number * 1_000)
    return None


def _parse_quantity(fragment):
    match = re.search(r"(\d+)\s*(video|foto|konten|content|pieces?)\b", fragment, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def parse_owner_offers(owner_text):
    """Splits owner text into clauses and extracts (quantity, price) pairs where BOTH are present
    in the same clause. Clauses with only a price and no quantity are returned with quantity=None
    (e.g. a flat project price) — never inferred.

    Clause breaks are '.', ';', newlines, or a comma NOT used as an Indonesian decimal separator
    (the comma in "4,2 juta" is kept together; the comma in "3 video, kalau 5 video" is a break) —
    otherwise a multi-offer message like the spec's own example ("3 juta bisa 3 video, kalau 5
    video 4,2 juta") would collapse into a single clause and lose the second offer.

    Returns a list of dicts: [{"quantity": 3, "price": 3000000}, ...], in the order mentioned.
    Also returns any extra notes clauses (no price found) as `notes` in the returned tuple, e.g.
    "shooting satu hari" — these are passed through verbatim into the customer-facing message
    (Section 17 example explicitly includes "produksi dalam 1 hari shooting").
    """
    clauses = re.split(r"[.;\n]|,(?!\s*\d)", owner_text or "")
    offers, notes = [], []
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        price = _parse_rupiah_amount(clause)
        quantity = _parse_quantity(clause)
        if price is not None:
            offers.append({"quantity": quantity, "price": price, "raw": clause})
        elif clause:
            notes.append(clause)
    return offers, notes


def build_customer_facing_offer_message(offers, notes=None):
    """Renders a professional, customer-safe Indonesian message from parsed offers — NEVER
    includes the owner's raw wording, any internal marker, or debug text (Section 16's explicit
    prohibition list: ACTION/STATE/DEBUG/JSON/PESAN_UNTUK_CUSTOMER/internal notes)."""
    if not offers:
        return None

    lines = []
    for offer in offers:
        price_fmt = f"Rp{offer['price']:,}".replace(",", ".")
        if offer["quantity"]:
            unit_label = "video" if "video" in (offer.get("raw") or "").lower() else "konten"
            lines.append(f"Untuk kebutuhan {offer['quantity']} {unit_label}, penawarannya {price_fmt}.")
        else:
            lines.append(f"Penawaran untuk project ini: {price_fmt}.")

    message = " ".join(lines)
    if notes:
        message += " " + " ".join(f"{n}." if not n.endswith(".") else n for n in notes)
    message += " Kalau oke, penawaran ini akan kami siapkan sebagai quotation resmi di Kilas Works Business Hub — kakak tinggal approve di sana untuk lanjut ke pembayaran."
    return message.strip()


# ---------------------------------------------------------------------------
# Customer-facing price disclosure rules (Section 24-26)
# ---------------------------------------------------------------------------

def customer_price_response(catalog_item):
    """Given a service_catalog row, returns what the bot should say about price — used as a pure
    decision function so the (not-yet-wired) bot integration has one obviously-correct place to
    call. Fixed-price items get the real figure; custom-quote items NEVER get an invented number."""
    if catalog_item is None:
        return None
    if catalog_item["pricing_mode"] == "CUSTOM_QUOTE":
        return (
            f"{catalog_item['name']} sifatnya custom quote — harga tergantung kebutuhan campaign/project. "
            "Kirim detail kebutuhannya ya, nanti tim kami buatkan penawaran lewat Kilas Works Business Hub."
        )
    price_fmt = f"Rp{catalog_item['price_amount']:,}".replace(",", ".")
    unit = catalog_item.get("price_unit") or ""
    return f"{catalog_item['name']}: {price_fmt} {unit}".strip()


# ---------------------------------------------------------------------------
# Tenant-persistence cycle — owner natural-language RECORD COMMANDS (Section: appointment/payment
# confirm/reject). These are deliberately a THIRD, more specific category on top of
# classify_owner_message's OWNER_QUERY/OWNER_ACTION/OWNER_INTERNAL_NOTE — an instruction like
# "Confirm booking Budi." or "Tolak pembayaran Budi, nominalnya kurang." must actually mutate a
# persisted appointment/payment-review row (see ../app.py's webhook handler), not just be relayed
# as a customer-facing message (OWNER_ACTION) or answered conversationally by the AI (OWNER_QUERY/
# OWNER_INTERNAL_NOTE). The caller (../app.py) checks classify_owner_record_command() FIRST, before
# falling through to classify_owner_message() for everything else — same "pure decision function,
# no I/O" philosophy as the rest of this module, so the actual DB read/write/notify/audit-log
# side-effects all live in ../app.py, never here.
# ---------------------------------------------------------------------------

_RECORD_CONFIRM_VERBS = ["confirm", "konfirmasi", "konfirm", "terima", "approve", "acc"]
_RECORD_REJECT_VERBS = ["tolak", "reject", "gagalkan"]
_APPOINTMENT_KEYWORDS = ["booking", "appointment", "jadwal", "janjian"]
_PAYMENT_KEYWORDS = ["pembayaran", "bayar", "transfer", "payment"]
# Generic filler words stripped out when trying to isolate a customer NAME from an owner's command
# text — never treated as a name candidate themselves.
_RECORD_COMMAND_STOPWORDS = set(
    w.lower() for w in (
        _RECORD_CONFIRM_VERBS + _RECORD_REJECT_VERBS + _APPOINTMENT_KEYWORDS + _PAYMENT_KEYWORDS
        + ["yang", "si", "punya", "punyanya", "untuk", "dong", "ya", "jam", "nya"]
    )
)


def classify_owner_record_command(text):
    """Returns one of CONFIRM_APPOINTMENT | REJECT_APPOINTMENT | CONFIRM_PAYMENT | REJECT_PAYMENT,
    or None when the text isn't a clear, unambiguous record command (e.g. no confirm/reject verb
    at all, or it mentions BOTH appointment and payment keywords with no way to tell which record
    type is meant — callers must fall back to the normal owner-assistant/relay path in that case,
    never guess a record type)."""
    lowered = (text or "").strip().lower()
    if not lowered:
        return None

    action = None
    for verb in _RECORD_CONFIRM_VERBS:
        if re.search(rf"\b{re.escape(verb)}\b", lowered):
            action = "CONFIRM"
            break
    if action is None:
        for verb in _RECORD_REJECT_VERBS:
            if re.search(rf"\b{re.escape(verb)}\b", lowered):
                action = "REJECT"
                break
    if action is None:
        return None

    is_payment = any(re.search(rf"\b{re.escape(kw)}\b", lowered) for kw in _PAYMENT_KEYWORDS)
    # A bare "jam <n>" time reference (e.g. "yang jam 4") is also treated as an appointment signal
    # — an owner confirming/rejecting a specific TIME slot is talking about a booking, even without
    # the word "booking"/"appointment" itself (see the master spec's own example: "Tolak yang jam
    # 4, bilang penuh.").
    is_appointment = (
        any(re.search(rf"\b{re.escape(kw)}\b", lowered) for kw in _APPOINTMENT_KEYWORDS)
        or bool(re.search(r"\bjam\s*\d{1,2}\b", lowered))
    )

    if is_payment and is_appointment:
        return None  # genuinely ambiguous which record type — never guess
    if is_payment:
        return f"{action}_PAYMENT"
    if is_appointment:
        return f"{action}_APPOINTMENT"
    return None


def extract_owner_command_reason(text):
    """The part of an owner's record-command text after a comma (e.g. 'bilang penuh' / 'nominalnya
    kurang'), with a leading filler word ('bilang'/'karena'/'alasan'/'bilangin') stripped, since
    that's how these commands are naturally phrased ('Tolak ..., bilang penuh.'). Returns None if
    there's no comma at all — never invents a reason."""
    if not text or "," not in text:
        return None
    tail = text.split(",", 1)[1].strip()
    lowered_tail = tail.lower()
    for prefix in ("bilang ", "bilangin ", "karena ", "alasan "):
        if lowered_tail.startswith(prefix):
            tail = tail[len(prefix):].strip()
            break
    tail = tail.rstrip(". ").strip()
    return tail or None


def extract_owner_command_target_name(text):
    """Best-effort customer-name fragment out of an owner's record-command text, e.g. 'Budi' out
    of 'Confirm booking Budi.' or 'Tolak pembayaran Budi, nominalnya kurang.' — only looks at the
    part BEFORE any comma (the reason clause is not a name source). Returns None when nothing
    name-like is left after stripping verbs/keywords/filler (e.g. 'Tolak yang jam 4' has no name at
    all — callers should fall back to time-based resolution, see resolve_appointment_target)."""
    if not text:
        return None
    head = text.split(",", 1)[0]
    tokens = re.findall(r"[A-Za-z]+", head)
    kept = [t for t in tokens if t.lower() not in _RECORD_COMMAND_STOPWORDS]
    name = " ".join(kept).strip()
    return name or None


def resolve_appointment_target(appointments, raw_text):
    """appointments: list of dicts (tenant_appointments rows, ALREADY scoped to one tenant by the
    caller) with at least 'customer_name' and 'request_text'. Returns (matched_row_or_None,
    ambiguous_matches_or_None) — ambiguous_matches is a non-empty list when 2+ DIFFERENT
    appointments could plausibly be meant (never guessed, per the master spec's explicit
    'ask a clarifying question' requirement)."""
    name = extract_owner_command_target_name(raw_text)
    if name:
        matches = [a for a in appointments if a.get("customer_name") and name.lower() in a["customer_name"].lower()]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, matches

    time_match = re.search(r"\bjam\s*(\d{1,2})\b", (raw_text or "").lower())
    if time_match:
        hour = int(time_match.group(1))
        # Owner text is almost always spoken 12-hour ("jam 4" meaning 4 sore/16:00), while a
        # customer's stored request_text may have been captured in 24-hour form ("jam 16:00") — so
        # a bare hour also matches its +12 afternoon/evening equivalent, never just an exact string
        # match that would silently miss the single most common real-world case.
        candidate_hours = {hour} if hour >= 12 else {hour, hour + 12}

        def _row_hour(appt):
            match = re.search(r"\bjam\s*(\d{1,2})", (appt.get("request_text") or "").lower())
            return int(match.group(1)) if match else None

        time_matches = [a for a in appointments if _row_hour(a) in candidate_hours]
        if len(time_matches) == 1:
            return time_matches[0], None
        if len(time_matches) > 1:
            return None, time_matches

    if len(appointments) == 1:
        return appointments[0], None
    return None, None


def resolve_payment_review_target(reviews, raw_text):
    """Same shape as resolve_appointment_target, for tenant_payment_reviews rows — resolved by
    customer name only (the master spec's own examples never reference a payment by time)."""
    name = extract_owner_command_target_name(raw_text)
    if name:
        matches = [r for r in reviews if r.get("customer_name") and name.lower() in r["customer_name"].lower()]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, matches

    if len(reviews) == 1:
        return reviews[0], None
    return None, None


def customer_payment_response(pricing_mode):
    """Section 25: WhatsApp explains payment happens in the app; never invents a payment amount
    or sends unofficial instructions."""
    if pricing_mode == "CUSTOM_QUOTE":
        return (
            "Untuk layanan custom, pembayaran baru bisa dilakukan setelah penawaran (quotation) "
            "disetujui di Kilas Works Business Hub. Setelah approve, halaman checkout dan instruksi "
            "pembayaran resmi akan muncul di sana."
        )
    return (
        "Checkout dan pembayaran resmi dilakukan lewat Kilas Works Business Hub "
        "(app.kilasworks.id) — link checkout-nya bisa langsung dibuka dari akunmu."
    )
