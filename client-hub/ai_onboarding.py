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

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLIENT_HUB_MODEL = os.environ.get("CLIENT_HUB_MODEL", "claude-sonnet-4-6")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

REQUIRED_CONFIG_KEYS = (
    "business_name", "category", "description", "languages", "tone", "owner",
    "business_hours", "services", "faqs", "policies", "appointment_rules",
    "payment_rules", "features_enabled",
)

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
    if not ANTHROPIC_API_KEY:
        return None, "ANTHROPIC_API_KEY_NOT_CONFIGURED"
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
        return data["content"][0]["text"], None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


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


def normalize_business_data(business, profile, raw_services, raw_faqs, extracted_file_texts):
    """Returns (config_dict_or_None, error_str_or_None). Never raises — callers persist
    ai_status=FAILED + last_error on failure and keep the raw data untouched, so onboarding can
    be retried without the client re-entering anything (section 24)."""
    input_text = build_normalization_input_text(business, profile, raw_services, raw_faqs, extracted_file_texts)
    raw_text, err = _call_claude(
        NORMALIZATION_SYSTEM_PROMPT,
        [{"role": "user", "content": input_text}],
    )
    if err:
        return None, err

    try:
        config = _extract_json_object(raw_text)
    except Exception as e:
        return None, f"RESPONSE_PARSE_ERROR: {e}"

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
    reply_text, err = _call_claude(system_prompt, messages, max_tokens=500)
    if err:
        return None, err
    return reply_text, None
