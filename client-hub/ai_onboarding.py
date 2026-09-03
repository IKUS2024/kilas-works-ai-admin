"""Claude API integration for the onboarding app. Two responsibilities:

1. normalize_business_data(...) — the APPLICATION calls Claude automatically once a client
   submits onboarding data (section 8/24 of the request). The Kilas Works admin never has to
   paste anything into Claude by hand. Output is validated JSON; the AI is explicitly instructed
   never to invent missing facts (price, address, hours, policies, availability) and to flag them
   instead — this app additionally re-validates the shape of what comes back before writing it to
   the database (section 25: AI returns validated structured data only, it never touches SQL).

2. simulate_customer_reply(...) — powers the "Test AI Admin" sandbox (section 15). Uses the
   tenant's DRAFT config only, entirely isolated from production (no WhatsApp send, no real
   appointment/payment writes — those functions are never imported here).

Both reuse the exact same Anthropic Messages API call shape already used in production by
../app.py (raw `requests.post` to https://api.anthropic.com/v1/messages with x-api-key +
anthropic-version headers) — same auth, same account, no new SDK dependency, no behavior
surprises. Model id comes from an env var with a current, non-deprecated default (matching what
was just re-audited as clean in the main bot's Final Launch QA cycle).
"""
import json
import os
import re

import requests

import feature_flags

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLIENT_HUB_MODEL = os.environ.get("CLIENT_HUB_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

REQUIRED_CONFIG_KEYS = (
    "business_name", "category", "description", "languages", "tone", "owner",
    "business_hours", "services", "faqs", "policies", "appointment_rules",
    "payment_rules", "features_enabled",
)

# Production bug fix (AI_RESPONSE_SHAPE_INVALID: missing keys ['features_enabled']): note that
# "features_enabled" is REQUIRED above but deliberately does NOT appear anywhere in
# NORMALIZATION_SYSTEM_PROMPT's JSON schema below — the model was never asked to produce it, so it
# reliably omitted it, and every AI setup run failed shape validation. That was the root cause.
#
# The fix is not to ask the model for it: feature entitlement (owner_commands, voice_note,
# appointment, payment_conversation, etc.) is a backend-enforced fact of the tenant's PACKAGE (see
# feature_flags.py / repo.get_tenant_features), never something an LLM should infer or invent from
# free-form business description text — inventing it here would risk granting a feature the
# tenant's actual package doesn't include. normalize_business_data() now always injects a
# well-formed "features_enabled" into the parsed config itself (see _normalize_features_enabled()
# below) before the required-keys check runs, so this key is guaranteed present and well-formed
# regardless of whether — or how — the model's raw JSON mentions it.

NORMALIZATION_SYSTEM_PROMPT = """Kamu adalah asisten internal Kilas Works yang membantu merapikan data onboarding client menjadi konfigurasi AI Admin yang terstruktur.

ATURAN MUTLAK:
1. JANGAN PERNAH mengarang data yang tidak ada di input. Kalau sebuah informasi (harga, alamat, jam operasional, kebijakan, aturan pembayaran, ketersediaan appointment) tidak disebutkan jelas di data client, kosongkan field itu (null) dan sebutkan nama fieldnya di "missing_fields".
2. Kalau ada input harga yang AMBIGU (misalnya rentang tanpa satuan jelas, atau tidak yakin), tetap isi field-nya dengan tebakan terbaik TAPI set needs_review=true untuk item itu, JANGAN diam-diam menganggapnya pasti benar.
3. Balas HANYA dengan satu objek JSON valid, tanpa teks lain, tanpa markdown code fence, tanpa penjelasan sebelum/sesudah JSON.
4. Struktur JSON WAJIB persis seperti ini (isi null/array kosong kalau tidak ada datanya):

{
  "business_name": string,
  "category": string,
  "description": string (ringkasan bisnis yang rapi, dari deskripsi mentah client),
  "languages": {"primary": "id"|"en", "additional": [string]},
  "tone": string,
  "owner": {"name": string|null, "salutation_for_customers": string},
  "business_hours": {"raw_summary": string|null, "structured": object|null},
  "services": [
    {"raw_input": string, "service_name": string|null, "description": string|null,
     "price_from": number|null, "price_to": number|null, "currency": string, "needs_review": boolean}
  ],
  "faqs": [
    {"raw_input": string, "question": string|null, "answer": string|null,
     "category": "general"|"policy"|"shipping"|"booking", "needs_review": boolean}
  ],
  "policies": [string],
  "appointment_rules": string|null,
  "payment_rules": string|null,
  "missing_fields": [string]
}

Balasan kamu adalah data yang akan disimpan oleh sistem apa adanya — jangan sertakan apapun selain objek JSON di atas."""

# Production reliability fix, ROUND 2 (real customer incident, confirmed recurring): a PRIOR fix
# already raised this from 1500 -> 4096 tokens, citing this exact same failure signature
# (RESPONSE_PARSE_ERROR around ~4,100 characters). The SAME symptom recurred for a business with a
# genuinely large services list (e.g. many endorsement/package tiers) — proving 4096 is STILL too
# low for a real, legitimate customer, not a one-off fluke. Raised again to a more generous bound.
# Considered switching this call to Claude's native tool-use (forced JSON via a `tools` schema +
# `tool_choice`) as the "strongest structured-output mechanism" available from the current
# provider/client — deliberately DEFERRED, not because it isn't a good idea, but because the
# confirmed root cause (token budget) is fully addressed by the fix below and by
# _scaled_max_tokens() below, and a tool-use conversion is a larger structural change (different
# response shape, different repair-attempt semantics) that deserves its own focused follow-up
# rather than being bundled into an urgent customer-reliability fix.
NORMALIZATION_MAX_TOKENS = int(os.environ.get("CLIENT_HUB_NORMALIZATION_MAX_TOKENS", "8192"))

# Hard ceiling for the dynamic scaling below — bounded, not "absurdly high" (Section B of the
# request): comfortably covers even an unusually large services/FAQ list while staying well short
# of the model's full output ceiling.
NORMALIZATION_MAX_TOKENS_CEILING = int(os.environ.get("CLIENT_HUB_NORMALIZATION_MAX_TOKENS_CEILING", "16000"))


def _scaled_max_tokens(input_text):
    """Safe bounded strategy for large business data (Section B of the request): a business with
    an unusually long services/FAQ list needs more OUTPUT tokens to represent in the normalized
    JSON schema than a small one does — a single flat token budget either wastes tokens on every
    small business or truncates every large one. This scales the request's max_tokens with the
    INPUT size (longer raw input -> proportionally more room for structured output), never
    dropping below NORMALIZATION_MAX_TOKENS and never exceeding NORMALIZATION_MAX_TOKENS_CEILING.
    The exact multiplier (2x input length in characters, converted to a rough token estimate) is a
    deliberately simple, conservative heuristic — output JSON for a services list is usually
    somewhat LARGER than the raw input text describing it (structured fields + punctuation add
    overhead), so 2x input length is a safe, generous-but-bounded estimate, not a tight one."""
    if not input_text:
        return NORMALIZATION_MAX_TOKENS
    estimated_input_tokens = len(input_text) // 3  # rough, conservative chars-per-token estimate
    scaled = max(NORMALIZATION_MAX_TOKENS, estimated_input_tokens * 2)
    return min(scaled, NORMALIZATION_MAX_TOKENS_CEILING)

REPAIR_SYSTEM_PROMPT = """Kamu memperbaiki output JSON yang tidak valid/rusak jadi valid.

Input yang kamu terima ADALAH OUTPUT ASLI (rusak) yang perlu diperbaiki — bukan data client baru.

ATURAN MUTLAK:
1. Perbaiki HANYA masalah FORMAT/STRUKTUR JSON-nya (kutip yang tidak ditutup, koma yang salah tempat,
   kurung yang tidak seimbang, teks terpotong di tengah, dll).
2. JANGAN mengubah, mengarang, atau menghapus informasi bisnis yang SUDAH ADA di output rusak itu — kalau
   sebagian data terpotong di tengah kalimat/angka dan gak bisa dipastikan lanjutannya, potong/tutup
   dengan aman di titik yang masuk akal (misal tutup string, tutup array/objek) daripada menebak isinya.
3. Balas HANYA dengan satu objek JSON valid, tanpa teks lain, tanpa markdown code fence, tanpa penjelasan.
4. Struktur JSON WAJIB tetap mengikuti schema yang sama persis dengan yang diminta di awal (field yang
   sama, tipe yang sama) — kalau ada field yang datanya jadi tidak lengkap gara-gara perbaikan ini, isi
   null / array kosong untuk field itu, JANGAN mengarang isinya."""

SIMULATION_SYSTEM_PROMPT_TEMPLATE = """Kamu adalah SIMULASI AI Admin WhatsApp untuk bisnis "{business_name}" ({category}), dipakai HANYA untuk mode "Test AI" oleh calon client Kilas Works sebelum tenant ini beneran aktif.

Data bisnis (draft, bisa saja belum lengkap):
{config_text}

ATURAN:
- Ini SIMULASI, bukan percakapan customer asli. JANGAN pernah bilang pesan ini "sudah dikirim ke WhatsApp asli" atau semacamnya.
- Jawab pakai bahasa & tone sesuai data di atas ("primary language" = {primary_language}), sapaan customer pakai "{salutation}" kalau bahasanya Indonesia.
- JANGAN PERNAH mengarang harga/jam operasional/kebijakan/alamat yang tidak ada di data di atas — kalau ditanya sesuatu yang datanya belum ada, jawab jujur bahwa informasi itu belum tersedia dan perlu dilengkapi client di tahap onboarding.
- Jawab natural & ringkas seperti admin WhatsApp asli, bukan seperti membaca database.
- Auto-detect bahasa pesan customer dan balas di bahasa yang sama kalau bahasa itu ada di daftar languages di atas; kalau tidak ada di daftar, tetap balas pakai primary language."""


def _extract_json_object(text):
    """Claude is instructed to return raw JSON only, but this defensively also handles a stray
    ```json fence in case the model doesn't follow the instruction exactly."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _call_claude(system_prompt, messages, max_tokens=1500):
    """Returns (text, stop_reason, error_str). stop_reason is Anthropic's own explicit signal for
    WHY generation stopped ("end_turn" = complete, "max_tokens" = genuinely truncated mid-output)
    — this is the strongest, most direct truncation signal the current API/client already
    provides (no new SDK/provider needed), used instead of only inferring truncation indirectly
    from a JSON parse failure. See normalize_business_data() for how this is used to distinguish
    "malformed but complete" (worth a repair attempt) from "cut off mid-string" (also worth a
    repair attempt, but logged/reported distinctly for diagnosis)."""
    if not ANTHROPIC_API_KEY:
        return None, None, "ANTHROPIC_API_KEY_NOT_CONFIGURED"
    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLIENT_HUB_MODEL,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": messages,
            },
            timeout=45,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"], data.get("stop_reason"), None
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"


def build_normalization_input_text(business, profile, raw_services, raw_faqs, extracted_file_texts):
    """Assemble the RAW client input (never AI output) into one text block for Claude to read.
    Keeping this separate from the prompt template makes it easy to unit-test what exactly gets
    sent, and to log/store it for debugging a failed normalization without needing the AI call."""
    lines = [
        f"Nama bisnis: {business['business_name']}",
        f"Kategori: {(profile or {}).get('category') or '(tidak diisi)'}",
        f"Deskripsi singkat dari client: {(profile or {}).get('short_description') or '(tidak diisi)'}",
        f"Negara: {(profile or {}).get('country') or '(tidak diisi)'}",
        f"Alamat: {(profile or {}).get('address') or '(tidak diisi)'}",
        f"Nomor telepon bisnis: {(profile or {}).get('business_phone') or '(tidak diisi)'}",
        f"Nama owner: {(profile or {}).get('owner_name') or '(tidak diisi)'}",
        f"Bahasa utama: {(profile or {}).get('primary_language') or 'id'}",
        f"Bahasa tambahan: {(profile or {}).get('additional_languages') or '[]'}",
        f"Tone yang diinginkan: {(profile or {}).get('tone') or 'friendly'}",
        f"Sapaan ke customer: {(profile or {}).get('customer_salutation') or 'Kak'}",
        f"Jam operasional (mentah dari client): {(profile or {}).get('operating_hours') or '(tidak diisi)'}",
        f"Hari libur/tutup: {(profile or {}).get('closed_days') or '(tidak diisi)'}",
        f"Online/offline: {(profile or {}).get('online_or_offline') or '(tidak diisi)'}",
        f"Aturan appointment (mentah): {(profile or {}).get('appointment_rules_raw') or '(tidak diisi)'}",
        "",
        "Produk/Jasa (mentah, satu per baris, PERSIS seperti diketik client):",
    ]
    for s in raw_services:
        lines.append(f"- {s}")
    if not raw_services:
        lines.append("(client belum mengisi produk/jasa apapun)")

    lines.append("")
    lines.append("FAQ / kebijakan (mentah, satu per baris, PERSIS seperti diketik client):")
    for f in raw_faqs:
        lines.append(f"- {f}")
    if not raw_faqs:
        lines.append("(client belum mengisi FAQ apapun)")

    if extracted_file_texts:
        lines.append("")
        lines.append("Teks yang berhasil diekstrak dari file yang diupload client (PDF/gambar/txt katalog):")
        for name, text in extracted_file_texts:
            snippet = (text or "").strip()
            if not snippet:
                continue
            lines.append(f"--- {name} ---")
            lines.append(snippet[:4000])  # guard against extremely long extracted text

    return "\n".join(lines)


def _normalize_features_enabled(raw_value, tenant_features=None):
    """Guarantees a well-formed features_enabled dict — {feature_key: bool} for every key in
    feature_flags.ALL_FEATURE_KEYS — no matter what (if anything) the model returned for it.
    Never raises; this is pure/deterministic and safe to call unconditionally.

    Precedence, most trustworthy first:
      1. tenant_features (the tenant's REAL, current entitlement — e.g. from
         repo.get_tenant_features(business_id), which is derived from the tenant's package via
         feature_flags.py, not from anything the AI wrote). When the caller supplies this, it is
         used in full and the model's raw_value is ignored entirely — this is what keeps
         appointment/payment_conversation (and every other flag) aligned with the tenant's actual
         configuration, and guarantees no feature is invented that the tenant doesn't have.
      2. raw_value, ONLY if it is a non-empty dict where every present key maps to an actual bool
         (never invented from something else, never coerced from e.g. a string) — used for
         standalone/offline callers that don't have a tenant_features source of truth to hand in.
         Any key from ALL_FEATURE_KEYS the model omitted is filled in as False (never assumed
         True — omission must never grant a feature).
      3. All-False over every known feature key — the only safe default when nothing concrete is
         known about this tenant's real entitlement. Used whenever raw_value is missing entirely,
         not a dict, empty, or contains a non-boolean value for a known key (malformed shape).
    """
    if isinstance(tenant_features, dict) and tenant_features:
        return {k: bool(tenant_features.get(k, False)) for k in feature_flags.ALL_FEATURE_KEYS}

    if isinstance(raw_value, dict) and raw_value:
        well_formed = True
        normalized = {}
        for k in feature_flags.ALL_FEATURE_KEYS:
            if k in raw_value:
                v = raw_value[k]
                if not isinstance(v, bool):
                    well_formed = False
                    break
                normalized[k] = v
            else:
                normalized[k] = False
        if well_formed:
            return normalized

    return {k: False for k in feature_flags.ALL_FEATURE_KEYS}


def _try_parse(raw_text):
    """Returns (config_dict_or_None, error_str_or_None) — a thin wrapper around
    _extract_json_object() that never raises, so callers can try a parse without a try/except at
    every call site."""
    try:
        return _extract_json_object(raw_text), None
    except Exception as e:
        return None, f"RESPONSE_PARSE_ERROR: {e}"


def normalize_business_data(business, profile, raw_services, raw_faqs, extracted_file_texts, tenant_features=None):
    """Returns (config_dict_or_None, error_str_or_None). Never raises — callers persist
    ai_status=FAILED + last_error on failure and keep the raw data untouched, so onboarding can
    be retried without the client re-entering anything (section 24).

    Reliability fix (real production incident — see NORMALIZATION_MAX_TOKENS's own comment): if
    the FIRST attempt's output is malformed (parse failure OR the API's own stop_reason says
    "max_tokens", i.e. genuinely truncated), exactly ONE repair attempt is made — sending the
    malformed output + the same schema to a dedicated repair prompt that fixes ONLY JSON
    formatting, never invents/changes business information. Hard cap: initial attempt + one
    repair, never more — a repair that also fails to parse results in FAILED, not a retry loop.

    tenant_features: optional dict of this business's REAL current feature entitlement (pass
    repo.get_tenant_features(business["id"]) from the caller, which already has DB access — this
    module deliberately never imports repo/db itself, see the module docstring). When supplied, it
    is the sole source of truth for the normalized config's "features_enabled" — see
    _normalize_features_enabled() for exactly why the model's own output is never trusted for
    this specific field.
    """
    input_text = build_normalization_input_text(business, profile, raw_services, raw_faqs, extracted_file_texts)
    scaled_tokens = _scaled_max_tokens(input_text)
    raw_text, stop_reason, err = _call_claude(
        NORMALIZATION_SYSTEM_PROMPT,
        [{"role": "user", "content": input_text}],
        max_tokens=scaled_tokens,
    )
    if err:
        return None, err

    config, parse_err = _try_parse(raw_text)
    attempted_repair = False
    if parse_err or stop_reason == "max_tokens":
        attempted_repair = True
        reason_note = (
            "Output sebelumnya TERPOTONG (kehabisan token) di tengah jalan."
            if stop_reason == "max_tokens"
            else f"Output sebelumnya gagal di-parse sebagai JSON valid: {parse_err}"
        )
        repair_text, _repair_stop_reason, repair_err = _call_claude(
            REPAIR_SYSTEM_PROMPT,
            [{
                "role": "user",
                "content": (
                    f"{reason_note}\n\n"
                    f"SCHEMA yang wajib diikuti:\n{NORMALIZATION_SYSTEM_PROMPT}\n\n"
                    f"OUTPUT RUSAK yang perlu diperbaiki:\n{raw_text or '(kosong)'}"
                ),
            }],
            # Repair fix (same root cause as the initial call above): the repair prompt is
            # instructed to PRESERVE the original business information, so its output needs to be
            # roughly as large as the (still-too-large-for-a-flat-budget) content that caused the
            # first failure — reusing only NORMALIZATION_MAX_TOKENS here would let the repair
            # attempt truncate at the exact same point for the exact same reason. Scale from the
            # length of the malformed output itself (a good proxy for how much content actually
            # needs to be represented), not the original input.
            max_tokens=_scaled_max_tokens(raw_text),
        )
        if repair_err:
            return None, f"REPAIR_CALL_FAILED: {repair_err} (original: {parse_err or 'stop_reason=max_tokens'})"
        config, repair_parse_err = _try_parse(repair_text)
        if repair_parse_err:
            # Repair attempt ALSO failed to produce valid JSON — stop here (max: initial + 1
            # repair, never an unbounded loop). Report the ORIGINAL failure reason as the primary
            # diagnostic, since that's what actually needs fixing (prompt/schema/token budget).
            return None, (
                f"{parse_err or 'RESPONSE_TRUNCATED (stop_reason=max_tokens)'} "
                f"(repair attempt also failed: {repair_parse_err})"
            )

    if not isinstance(config, dict):
        return None, "AI_RESPONSE_SHAPE_INVALID: top-level response must be a JSON object"

    # Production bug fix: normalize features_enabled BEFORE the required-keys check below, so its
    # absence or malformed shape in the model's raw output never fails the whole AI setup — see
    # _normalize_features_enabled() and the comment above REQUIRED_CONFIG_KEYS for the full reasoning.
    config["features_enabled"] = _normalize_features_enabled(config.get("features_enabled"), tenant_features)

    missing_top_level = [k for k in REQUIRED_CONFIG_KEYS if k not in config]
    if missing_top_level:
        return None, f"AI_RESPONSE_SHAPE_INVALID: missing keys {missing_top_level}"

    if not isinstance(config.get("services"), list) or not isinstance(config.get("faqs"), list):
        return None, "AI_RESPONSE_SHAPE_INVALID: services/faqs must be arrays"

    return config, None


def simulate_customer_reply(business, config, history, customer_message):
    """`history` is a list of {"role": "user"|"assistant", "content": str} from
    simulation_messages — entirely separate storage from production `conversations`, and this
    function never calls any WhatsApp-sending or appointment/payment-writing code."""
    config = config or {}
    languages = config.get("languages") or {"primary": "id", "additional": []}
    salutation = (config.get("owner") or {}).get("salutation_for_customers") or "Kak"
    config_text = json.dumps(config, ensure_ascii=False, indent=2) if config else "(belum ada hasil AI setup — masih draft mentah)"

    system_prompt = SIMULATION_SYSTEM_PROMPT_TEMPLATE.format(
        business_name=business["business_name"],
        category=config.get("category") or "(belum diisi)",
        config_text=config_text,
        primary_language=languages.get("primary", "id"),
        salutation=salutation,
    )
    messages = history + [{"role": "user", "content": customer_message}]
    reply_text, _stop_reason, err = _call_claude(system_prompt, messages, max_tokens=500)
    if err:
        return None, err
    return reply_text, None


# ---------------------------------------------------------------------------
# Reusable "Bantu dengan AI" writing helper (UX pass, Sections D-H) — ONE function used by every
# eligible text field (business description, FAQ question/answer, ordering instructions, payment
# explanation, booking/cancellation policy, service notes) instead of one-off code per field.
# ---------------------------------------------------------------------------

# Whitelist of field types this helper may ever touch — enforced HERE (not just in the route),
# so calling this function directly with an unlisted field_type fails loudly rather than silently
# running anyway. Deliberately excludes phone numbers, prices, IDs, bank account numbers, dates,
# credentials, package selectors — anything factual/technical where an AI "rewrite" makes no sense
# and could introduce risk (Section D/E: "Do NOT put it on... phone numbers... prices... bank
# account numbers... credentials... technical fields").
WRITING_HELPER_FIELD_TYPES = {
    "short_description": "Deskripsi singkat bisnis",
    "faq_question": "Pertanyaan FAQ",
    "faq_answer": "Jawaban FAQ",
    "faq_raw": "FAQ & Kebijakan (daftar pertanyaan-jawaban)",
    "appointment_rules_raw": "Aturan booking/appointment",
    "payment_instructions": "Instruksi pembayaran untuk customer",
    "closed_days": "Keterangan hari libur",
}

WRITING_HELPER_ACTIONS = {
    "rapikan": "Rapikan kalimatnya — perbaiki tata bahasa & alur, TANPA mengubah maksud/fakta.",
    "profesional": "Buat lebih profesional — nada lebih formal & terpercaya, TANPA mengubah maksud/fakta.",
    "singkat": "Buat lebih singkat — padatkan jadi lebih ringkas, TANPA menghilangkan fakta penting.",
    "ramah": "Buat lebih ramah — nada lebih hangat & personal, TANPA mengubah maksud/fakta.",
    "perjelas": "Perjelas kalimatnya — hilangkan ambiguitas, TANPA menambah fakta baru yang tidak ada.",
    "draft": "Buat draft teks baru dari nol, HANYA berdasarkan data bisnis yang tersedia di bawah.",
}

WRITING_HELPER_SYSTEM_PROMPT = """Kamu adalah asisten penulisan untuk pemilik bisnis yang sedang mengisi
profil bisnisnya di Client Hub. Tugasmu membantu merapikan/memperbaiki TEKS yang customer tulis sendiri,
BUKAN membuat fakta bisnis baru.

ATURAN MUTLAK (WAJIB DIIKUTI PERSIS):
1. JANGAN PERNAH menambahkan fakta yang TIDAK ADA di teks asli ATAU di data bisnis yang diberikan —
   termasuk harga, ketersediaan, kebijakan refund, aturan booking, jam operasional, timeline
   pengerjaan, cakupan layanan, info rekening, diskon, atau janji apapun.
2. Kalau field-nya KOSONG dan data bisnis yang diberikan TIDAK CUKUP buat bikin draft yang jujur
   (bukan karangan), JANGAN mengarang — balas dengan needs_more_info berisi kalimat singkat yang
   natural minta customer isi sedikit info dulu (jangan template kaku, sesuaikan konteks field-nya).
3. Kalau field-nya KOSONG tapi data bisnis CUKUP, boleh bikin draft HANYA dari fakta yang benar-benar
   ada di data itu.
4. Kalau field-nya SUDAH ADA ISINYA, perbaiki sesuai aksi yang diminta TANPA mengubah maksud/fakta
   aslinya sama sekali — kamu MERAPIKAN, bukan MENULIS ULANG dari sudut pandang berbeda.
5. Balas HANYA dengan satu objek JSON valid, tanpa markdown fence, tanpa teks lain:
{
  "suggestion": string|null (hasil teks yang disarankan, null kalau needs_more_info diisi),
  "needs_more_info": string|null (pesan minta info tambahan, null kalau suggestion diisi)
}
Salah satu dari "suggestion"/"needs_more_info" HARUS diisi, yang lain null — jangan dua-duanya diisi,
jangan dua-duanya null."""


def _build_business_facts_context(business, profile, raw_services, raw_faqs):
    """The ONLY source of truth the writing helper may draw NEW facts from (Section G: "AI may
    draft text ONLY from existing saved business information") — same idea as
    build_normalization_input_text() above, kept as a separate, smaller function since the writing
    helper doesn't need extracted file text and is called far more frequently (once per click, not
    once per onboarding submit)."""
    profile = profile or {}
    lines = [
        f"Nama bisnis: {business['business_name']}",
        f"Kategori: {profile.get('category') or '(tidak diisi)'}",
        f"Jam operasional: {profile.get('operating_hours') or '(tidak diisi)'}",
        f"Jenis layanan: {profile.get('online_or_offline') or '(tidak diisi)'}",
    ]
    if raw_services:
        lines.append("Layanan/produk: " + "; ".join(raw_services))
    if raw_faqs:
        lines.append("FAQ yang sudah ada: " + "; ".join(raw_faqs))
    return "\n".join(lines)


def generate_writing_suggestion(business, profile, raw_services, raw_faqs, field_type, current_text, action):
    """Returns (result_dict_or_None, error_str_or_None) where result_dict is
    {"suggestion": str} or {"needs_more_info": str} — NEVER both, never neither. Never raises;
    callers show a generic "coba lagi" message on error, matching every other AI call in this
    module. field_type/action are validated against the whitelists above — an unlisted value is a
    caller bug (route-level validation should have already rejected it), not something this
    function silently tolerates."""
    if field_type not in WRITING_HELPER_FIELD_TYPES:
        return None, f"UNSUPPORTED_FIELD_TYPE: {field_type}"
    if action not in WRITING_HELPER_ACTIONS:
        return None, f"UNSUPPORTED_ACTION: {action}"

    field_label = WRITING_HELPER_FIELD_TYPES[field_type]
    action_instruction = WRITING_HELPER_ACTIONS[action]
    facts_context = _build_business_facts_context(business, profile, raw_services, raw_faqs)
    current_text = (current_text or "").strip()

    user_content = (
        f"FIELD: {field_label}\n"
        f"AKSI YANG DIMINTA: {action_instruction}\n\n"
        f"DATA BISNIS YANG TERSEDIA (satu-satunya sumber fakta yang boleh kamu pakai):\n{facts_context}\n\n"
        + (f"TEKS SAAT INI (perbaiki ini, jangan tulis ulang dari nol):\n{current_text}"
           if current_text else "TEKS SAAT INI: (kosong — field ini belum diisi customer)")
    )

    raw_text, stop_reason, err = _call_claude(
        WRITING_HELPER_SYSTEM_PROMPT, [{"role": "user", "content": user_content}], max_tokens=800,
    )
    if err:
        return None, err

    try:
        parsed = _extract_json_object(raw_text)
    except (ValueError, TypeError) as e:
        return None, f"RESPONSE_PARSE_ERROR: {e}"

    if not isinstance(parsed, dict):
        return None, "AI_RESPONSE_SHAPE_INVALID"

    suggestion = parsed.get("suggestion")
    needs_more_info = parsed.get("needs_more_info")
    if suggestion:
        return {"suggestion": str(suggestion).strip()}, None
    if needs_more_info:
        return {"needs_more_info": str(needs_more_info).strip()}, None
    return None, "AI_RESPONSE_SHAPE_INVALID: neither suggestion nor needs_more_info was set"


FAQ_SUGGESTION_SYSTEM_PROMPT = """Kamu membantu pemilik bisnis melengkapi FAQ untuk AI Admin mereka.

Analisis data bisnis yang diberikan, lalu sarankan pertanyaan FAQ yang BELUM ada di daftar tapi
kemungkinan besar akan ditanyakan customer (contoh topik umum: cara booking, area/kota yang dilayani,
metode pembayaran, lama waktu konfirmasi, kebijakan pembatalan/reschedule — sesuaikan dengan jenis
bisnisnya, jangan asal tempel semua topik ini kalau gak relevan).

ATURAN MUTLAK:
1. JANGAN sarankan pertanyaan yang JAWABANNYA HARUS DIKARANG — kalau data bisnis yang diberikan tidak
   cukup untuk menjawab pertanyaan itu secara jujur, tetap boleh disarankan sebagai TOPIK, tapi answer
   HARUS null (bukan jawaban karangan).
2. JANGAN duplikasi pertanyaan yang sudah ada di "FAQ yang sudah ada".
3. Maksimal 5 saran per panggilan — kualitas di atas kuantitas.
4. Balas HANYA dengan objek JSON valid, tanpa markdown fence, tanpa teks lain:
{
  "suggestions": [
    {"question": string, "answer": string|null}
  ]
}
answer null berarti "topik ini relevan tapi datanya belum cukup buat dijawab otomatis" — JANGAN
mengarang jawaban hanya supaya field-nya keisi."""


def generate_faq_suggestions(business, profile, raw_services, raw_faqs):
    """Smart FAQ assistant, missing-topics mode (Section H). Returns
    ({"suggestions": [{"question": str, "answer": str|None}, ...]}, None) or (None, error_str).
    An entry with answer=None means the topic is relevant but not supported by saved data yet —
    the caller/template must show "Jawaban belum tersedia — isi informasi terlebih dahulu." for
    those, never silently drop them or fabricate a value."""
    facts_context = _build_business_facts_context(business, profile, raw_services, raw_faqs)
    raw_text, stop_reason, err = _call_claude(
        FAQ_SUGGESTION_SYSTEM_PROMPT,
        [{"role": "user", "content": f"DATA BISNIS:\n{facts_context}"}],
        max_tokens=1000,
    )
    if err:
        return None, err
    try:
        parsed = _extract_json_object(raw_text)
    except (ValueError, TypeError) as e:
        return None, f"RESPONSE_PARSE_ERROR: {e}"
    if not isinstance(parsed, dict) or not isinstance(parsed.get("suggestions"), list):
        return None, "AI_RESPONSE_SHAPE_INVALID"
    cleaned = []
    for item in parsed["suggestions"][:5]:
        if not isinstance(item, dict) or not item.get("question"):
            continue
        cleaned.append({
            "question": str(item["question"]).strip(),
            "answer": (str(item["answer"]).strip() if item.get("answer") else None),
        })
    return {"suggestions": cleaned}, None
