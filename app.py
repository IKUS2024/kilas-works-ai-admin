import os
import sys
import re
import io
import hmac
import json
import time
import base64
import requests
from collections import deque
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

app = Flask(__name__)

# ==== KONFIGURASI (diambil dari environment variables) ====
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "kilasworks123")  # bebas, dipakai buat verifikasi webhook di Meta

# ---------------------------------------------------------------------------
# Business Hub V2 — Client Hub bridge (WhatsApp Patches 1-6, client-hub/BOT_INTEGRATION_GUIDE.md)
# ---------------------------------------------------------------------------
# ADDITIVE ONLY. `ENABLE_MULTI_TENANT` defaults to "false" — every gate below that checks this flag
# stays fully inert by default, so nothing here changes behavior unless a human deliberately turns
# it on in Render. Even with the flag on, `tenant_id` only ever resolves to a REAL, ACTIVE Client Hub
# tenant whose `whatsapp_phone_number_id` matches the incoming webhook's own `phone_number_id` — it
# is None for every message on Kilas Works' own WhatsApp number today (that number has never been
# registered as a Client Hub tenant), so production traffic for the business currently live is
# completely unaffected either way. Every helper below is wrapped so a missing/broken Client Hub
# install (e.g. this file copied somewhere without the client-hub/ folder) degrades to "as if this
# patch set didn't exist" rather than crashing the webhook.
ENABLE_MULTI_TENANT = os.environ.get("ENABLE_MULTI_TENANT", "false").strip().lower() == "true"
_CLIENT_HUB_AVAILABLE = False
try:
    _client_hub_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "client-hub")
    if os.path.isdir(_client_hub_dir) and _client_hub_dir not in sys.path:
        sys.path.insert(0, _client_hub_dir)
    import tenant_config_service as _tcs
    import wa_takeover_service as _wa_takeover
    import platform_inbox_service as _platform_inbox
    import wa_project_bridge as _wa_bridge
    import appointments_repo as _appt_repo
    import payment_reviews_repo as _pay_review_repo
    import repo as _ch_repo
    import tenant_followup_service as _tenant_followup
    _CLIENT_HUB_AVAILABLE = True
except Exception as _client_hub_import_err:
    print(f"Client Hub bridge tidak tersedia ({_client_hub_import_err}) — bot jalan tanpa fitur multi-tenant.")

if _CLIENT_HUB_AVAILABLE and ENABLE_MULTI_TENANT:
    # Multi-tenant runtime safety cycle (Task B) — DATABASE SOURCE OF TRUTH startup check.
    #
    # FACT (verified by reading the actual code, not assumed): the imports right above are plain
    # in-process Python imports — `tenant_config_service`/`wa_takeover_service`/`wa_project_bridge`
    # (and everything they import: repo.py, db.py) run as LOCAL MODULES inside this SAME bot
    # process, not over HTTP to a separately-running Client Hub server. Within THIS process there
    # is exactly one `DATABASE_URL` environment variable, read independently by this file's own
    # get_db_connection() (this bot's own chat-history/leads Postgres) and by client-hub/db.py's
    # get_connection() (Client Hub's tenant/business Postgres) — so within one process they can
    # never disagree, by construction (same os.environ, same key).
    #
    # The REAL risk is operational, not code-level: per
    # LAPORAN-CLIENT-HUB-PRODUCTION-FOUNDATION.md section 12, Client Hub is meant to ALSO be
    # deployed as its own SEPARATE Render web service (its own admin UI, its own env panel) for
    # staff to approve/connect/activate tenants. For this bridge to see the SAME tenant data that
    # separately-deployed admin service manages, THIS bot service's own Render environment must
    # ALSO have its `DATABASE_URL` set, to the EXACT SAME production Postgres connection string as
    # the Client Hub admin service's `DATABASE_URL` — two independently-configured Render env
    # panels that must agree, which nothing enforces automatically. If a human forgets to set
    # `DATABASE_URL` on THIS service, client-hub/db.py silently falls back to a local SQLite file
    # (see its own module docstring) that no admin ever writes to — every tenant lookup then
    # returns "no match" (gracefully — see _resolve_tenant_id's docstring), which reads as "no
    # tenants exist yet" rather than a crash, so this is easy to miss without a check like this
    # one. This log line is the entire check: minimal, non-breaking, startup-only.
    if not os.environ.get("DATABASE_URL", "").strip():
        print(
            "PERINGATAN (Database source of truth): ENABLE_MULTI_TENANT=true tapi DATABASE_URL "
            "belum diset di service bot ini. client-hub/db.py (di-import langsung dalam proses "
            "yang sama) akan fallback ke SQLite lokal, TERPISAH dari database Postgres yang "
            "dipakai Client Hub admin service — setiap tenant lookup akan gagal senyap (dianggap "
            "'tidak ada tenant'), bukan error. Set DATABASE_URL di service bot ini ke connection "
            "string Postgres PRODUKSI yang SAMA PERSIS dengan yang dipakai Client Hub admin "
            "service, baru multi-tenant bridge ini bisa melihat data tenant yang sebenarnya."
        )


def _resolve_tenant_id(phone_number_id):
    """Patch 1 — authoritative tenant resolution, ONLY via the webhook payload's own
    `phone_number_id` (Meta's own channel identifier), NEVER from message text or a business name.
    Returns None on any failure (Client Hub unavailable, no match, DB error) — None means 'treat
    exactly like every request before this patch existed' everywhere else in this file."""
    if not _CLIENT_HUB_AVAILABLE or not phone_number_id:
        return None
    try:
        return _tcs.get_tenant_by_phone_number_id(phone_number_id)
    except Exception as e:
        print(f"Tenant resolution gagal ({e}) — fallback tenant_id=None (perilaku default).")
        return None


def _resolve_tenant_or_unknown(phone_number_id):
    """Task 7 (multi-tenant runtime safety) — tri-state resolution of the webhook's own
    `phone_number_id`, used ONLY by the webhook route (receive_webhook/_webhook_body_impl), never
    by anything that predates this cycle (see _resolve_tenant_id above, kept unchanged for its
    existing callers/tests). Returns (tenant_id, is_unknown):
      - phone_number_id matches Kilas Works' OWN configured WHATSAPP_PHONE_NUMBER_ID -> (None, False)
        — process as Kilas Works, exactly like every request before multi-tenancy existed.
      - phone_number_id matches a real, ACTIVE Client Hub tenant -> (tenant_id, False) — process as
        that tenant.
      - anything else — no match at all, Client Hub unavailable, OR the tenant lookup itself raised
        (e.g. a database error) -> (None, True) — GENUINELY UNKNOWN. The caller must NOT process
        this as Kilas Works (tenant_id=None here is NOT a green light — check is_unknown first),
        must not send any reply, and must only log an internal warning and stop. A lookup failure
        must never silently degrade into 'treat as Kilas Works' — that would make an outage/bug in
        Client Hub's database look identical to legitimate Kilas Works traffic."""
    if not phone_number_id:
        return None, True
    if WHATSAPP_PHONE_NUMBER_ID and phone_number_id == WHATSAPP_PHONE_NUMBER_ID:
        return None, False
    if not _CLIENT_HUB_AVAILABLE:
        # Can't tell whether this is a real tenant without Client Hub — never default to Kilas.
        return None, True
    try:
        found = _tcs.get_tenant_by_phone_number_id(phone_number_id)
    except Exception as e:
        print(
            f"Tenant resolution GAGAL (phone_number_id={phone_number_id!r}): {e} — diperlakukan "
            "sebagai UNKNOWN (BUKAN Kilas Works), tidak diproses, tidak dibalas."
        )
        return None, True
    if found is not None:
        # Fix 4 (audit finding) — resolving as an ACTIVE business is NOT by itself sufficient to
        # grant a paid-AI-Admin tenant a live reply: the AI Admin SUBSCRIPTION must also be in a
        # currently-operating state (ACTIVE or GRACE). Before this fix, only businesses.status was
        # checked here, so a tenant whose subscriptions row is MISSING (e.g. a pre-existing tenant
        # never backfilled after migration 0014 — see that migration's own docstring + the
        # deployment report's backfill procedure) or SUSPENDED/CANCELLED for some reason without
        # businesses.status having (yet) been flipped to SUSPENDED would still receive full paid
        # AI automation — exactly the fail-open gap this fix closes. A business with a non-AI-Admin
        # package ("NONE") never needs a subscription row at all and is unaffected by this check.
        if not _tenant_subscription_permits_ai_runtime_safe(found):
            print(
                f"Tenant resolution: business_id={found} ACTIVE tapi subscription AI Admin-nya "
                "TIDAK dalam status yang boleh jalan (missing/SUSPENDED/CANCELLED) — diperlakukan "
                "sebagai UNKNOWN, tidak diproses, tidak dibalas."
            )
            return None, True
        return found, False
    return None, True


def _get_conversation_mode_safe(tenant_id, customer_phone):
    """Human-takeover safety check for BOTH Kilas Works and client tenants.

    Kilas Works' own WhatsApp now has a persistent platform_wa_conversation_state table so a human
    reply from WhatsApp Business / Admin Inbox can silence AI for that one customer exactly like a
    client tenant. Any state-read failure fails safe to HUMAN_TAKEOVER: delaying one automated
    reply is safer than talking over a human operator.
    """
    if not _CLIENT_HUB_AVAILABLE:
        # Fail closed for BOTH Kilas Works' own number and tenant numbers.
        # If Client Hub cannot be loaded at process boot, takeover state cannot
        # be trusted. Staying silent is safer than risking an AI + human double reply.
        return "HUMAN_TAKEOVER"
    try:
        if tenant_id is None:
            return _platform_inbox.get_state(customer_phone)
        return _tcs.get_conversation_mode(tenant_id, customer_phone)
    except Exception as e:
        scope = "Kilas Works" if tenant_id is None else f"tenant_id={tenant_id}"
        print(f"Cek human takeover {scope} gagal ({e}) — fail-safe HUMAN_TAKEOVER (AI diam sementara).")
        return "HUMAN_TAKEOVER"


# Bug fix: a resolved CLIENT tenant (e.g. a coffee shop) must NEVER fall back to "" here in a way
# that makes build_customer_system_prompt() treat it as "no tenant" (which would use SYSTEM_PROMPT,
# i.e. KILAS WORKS' OWN catalog/pricing). Once a tenant_id has actually resolved, this ALWAYS returns
# a non-empty, tenant-labeled block — using that tenant's own onboarding data when available, or this
# neutral fallback (never Kilas Works' own catalog) when the tenant's profile is incomplete/missing.
_TENANT_INCOMPLETE_PROFILE_BLOCK = (
    "\n\nCATATAN PENTING: profil resmi bisnis ini (nama, layanan, harga, FAQ, jam, alamat) BELUM "
    "lengkap tersedia buat kamu saat ini. JANGAN PERNAH karang info/layanan/harga apapun, dan JANGAN "
    "PERNAH pakai info/layanan/harga dari bisnis lain manapun (TERMASUK Kilas Works) untuk menjawab "
    "customer bisnis ini. Kalau customer nanya produk/harga/jam/FAQ yang belum ada datanya, jawab "
    "jujur & natural kamu perlu cek dulu ke tim, atau tanya balik dengan sopan buat memahami kebutuhan "
    "customer lebih spesifik dulu."
)


def _build_tenant_context_block_safe(tenant_id):
    """Patch 2/6 — additional system-prompt context for a resolved MULTI-TENANT client, injected
    for THIS request only (never written into any global/module-level prompt string). Returns ""
    ONLY when tenant_id is None / Client Hub is unavailable (i.e. genuinely no tenant resolved — the
    caller correctly falls back to Kilas Works' own SYSTEM_PROMPT in that case). Once a tenant_id HAS
    resolved, this ALWAYS returns a non-empty block (that tenant's own data, or a neutral incomplete-
    profile notice) — it must never again fall back to Kilas Works' own catalog/pricing."""
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return ""
    try:
        # Bug fix: this used to call _tcs.get_active_service_catalog(), which returns KILAS WORKS'
        # OWN service_catalog table (catalog_service.list_active_catalog() — see its docstring:
        # "Not tenant-scoped, the catalog is Kilas Works' own service list") — mislabeled here as
        # "KATALOG LAYANAN RESMI BISNIS INI", so every resolved tenant (any client business) was
        # actually being handed KILAS WORKS' OWN products/prices as if it were their own catalog.
        # The tenant's OWN data lives in its provisioned tenant config instead.
        config = _tcs.get_tenant_config(tenant_id)
    except Exception as e:
        print(f"Ambil tenant config gagal ({e}) — fallback ke profil bisnis kosong (BUKAN katalog Kilas Works).")
        return _TENANT_INCOMPLETE_PROFILE_BLOCK
    if not config:
        return _TENANT_INCOMPLETE_PROFILE_BLOCK
    try:
        business_name = config.get("business_name") or "bisnis ini"
        ai_cfg = config.get("ai") or {}
        business_info = config.get("business_info") or {}
        knowledge = config.get("knowledge") or {}

        lines = [f"NAMA BISNIS INI: {business_name}"]
        description = ai_cfg.get("business_description") or ai_cfg.get("system_instructions")
        if description:
            lines.append(f"DESKRIPSI BISNIS: {description}")
        address = business_info.get("address")
        if address:
            lines.append(f"ALAMAT: {address}")
        hours_raw = (business_info.get("business_hours") or {}).get("raw")
        if hours_raw:
            lines.append(f"JAM OPERASIONAL: {hours_raw}")
        closed_days = (business_info.get("business_hours") or {}).get("closed_days")
        if closed_days:
            lines.append(f"HARI LIBUR/TUTUP: {closed_days}")

        services = knowledge.get("services") or []
        service_lines = []
        for s in services:
            name = (s.get("service_name") or s.get("raw_input") or "").strip()
            if not name:
                continue
            price_from, price_to = s.get("price_from"), s.get("price_to")
            if price_from and price_to and price_from != price_to:
                price_text = f"Rp{price_from:,} - Rp{price_to:,}".replace(",", ".")
            elif price_from or price_to:
                price_text = f"Rp{(price_from or price_to):,}".replace(",", ".")
            else:
                price_text = "harga belum ditentukan (JANGAN karang angka, tanya/eskalasi dulu)"
            service_lines.append(f"- {name}: {price_text}")
        if service_lines:
            lines.append("LAYANAN/PRODUK BISNIS INI:")
            lines.extend(service_lines)

        faqs = knowledge.get("faq") or []
        faq_lines = []
        for f in faqs:
            q, a = f.get("question"), f.get("answer")
            if q and a:
                faq_lines.append(f"- Q: {q}\n  A: {a}")
        if faq_lines:
            lines.append("FAQ BISNIS INI:")
            lines.extend(faq_lines)

        if not service_lines and not faq_lines and not description and not address and not hours_raw:
            # Tenant resolved, but onboarding data is essentially empty — never fall back to Kilas
            # Works' own catalog, fall back to the neutral incomplete-profile notice instead.
            return _TENANT_INCOMPLETE_PROFILE_BLOCK

        info_text = "\n".join(lines)

        # Task 3/4 — appointment and tenant-own-payment instructions are ONLY added when THIS
        # tenant's own Pro feature flags (feature_flags.FEATURE_MATRIX) actually allow it; a Basic
        # tenant (or a Pro tenant without payment/appointment configured) gets neither block, so
        # the AI never has the tags/wording to attempt either and falls back to the generic
        # "cek dulu ke tim" behavior already covered by the general instructions below.
        features = {}
        try:
            features = _tcs.get_tenant_features(tenant_id) or {}
        except Exception:
            pass

        appt_settings = _get_tenant_appointment_settings_safe(tenant_id)
        if features.get("appointment") and appt_settings.get("meeting_enabled"):
            appointment_block = build_tenant_appointment_context(appt_settings)
            payment_note = (
                "Pembayaran untuk layanan Kilas Works sendiri (bukan produk/jasa bisnis ini) tetap "
                "HANYA lewat app.kilasworks.id — itu di luar topik ini."
            )
        else:
            appointment_block = ""
            payment_note = (
                "Belum ada layanan booking appointment lewat chat untuk bisnis ini — kalau customer "
                "minta jadwal ketemu, arahkan mereka menghubungi bisnis ini langsung."
            )

        payment_cfg = _get_tenant_payment_config_safe(tenant_id)
        if features.get("payment_conversation") and payment_cfg.get("bank_name") and payment_cfg.get("account_number"):
            payment_block = (
                "\n\nPEMBAYARAN KE BISNIS INI: kalau customer nanya cara bayar/rekening/transfer ke "
                "bisnis ini, respon transisi natural SANGAT SINGKAT lalu sertakan tag PERSIS di akhir "
                "balasan: [GIVE_PAYMENT_INFO] — SISTEM yang otomatis isi rincian rekening resmi "
                "bisnis ini, JANGAN PERNAH kamu ketik nomor rekening sendiri. "
                "Kalau customer bilang sudah transfer atau mengirim gambar yang jelas merupakan bukti "
                "transfer, ucapkan terima kasih dan jelaskan bahwa bukti sedang dicek, JANGAN PERNAH "
                "mengatakan pasti asli/terverifikasi/lunas, lalu sertakan tag [SUDAH_BAYAR]. Kalau dari "
                "gambar nominalnya terbaca jelas, sertakan juga [PAYMENT_PROOF_DETAILS: amount=<angka "
                "rupiah tanpa titik/koma>]. Kalau gambar buram, bukan bukti transfer, atau nominalnya "
                "tidak jelas/mencurigakan, JANGAN sertakan [SUDAH_BAYAR]; minta customer kirim ulang "
                "bukti yang lebih jelas atau bilang akan dicek ke tim."
            )
        else:
            payment_block = (
                "\n\nPEMBAYARAN KE BISNIS INI: belum ada rekening resmi yang bisa kamu sampaikan lewat "
                "chat — kalau customer nanya cara bayar, jawab jujur & natural kamu perlu cek dulu ke "
                "tim/owner, JANGAN PERNAH mengarang nomor rekening apapun."
            )

        return (
            "\n\nINFO & KATALOG RESMI BISNIS INI (SATU-SATUNYA SUMBER INFORMASI UNTUK BISNIS INI — "
            "JANGAN PERNAH KARANG INFO LAIN, DAN JANGAN PERNAH PAKAI INFO/LAYANAN/HARGA DARI BISNIS "
            "LAIN MANAPUN, TERMASUK KILAS WORKS, UNTUK BISNIS INI):\n"
            f"{info_text}\n\n"
            "Kalau customer nanya sesuatu (produk/harga/jam/FAQ) yang belum ada di data di atas, JANGAN "
            "NGARANG jawaban — jawab jujur kamu perlu cek dulu, atau tanya klarifikasi kebutuhan "
            "customer dengan sopan.\n"
            f"{payment_note}"
            f"{appointment_block}"
            f"{payment_block}"
        )
    except Exception as e:
        print(f"Build tenant context gagal ({e}) — fallback ke profil bisnis kosong (BUKAN katalog Kilas Works).")
        return _TENANT_INCOMPLETE_PROFILE_BLOCK


def _get_open_projects_summary_safe(tenant_id):
    """Patch 5 — owner-facing project query support ('project Rina gimana?'). Never raises."""
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return []
    try:
        return _tcs.get_open_projects_summary(tenant_id)
    except Exception as e:
        print(f"Ambil ringkasan project gagal ({e}).")
        return []


def _get_trusted_owner_phone_safe(tenant_id):
    """Patch 5 — this ONE tenant's own trusted owner phone (never Kilas Works' own
    OWNER_WHATSAPP_NUMBER), used to recognize that tenant's owner messages on their own WhatsApp
    channel. Never raises; returns None on any failure so the message just falls through to the
    normal customer path (same as today, before this patch existed)."""
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return None
    try:
        return _tcs.get_trusted_owner_phone(tenant_id)
    except Exception as e:
        print(f"Ambil trusted_owner_phone gagal ({e}).")
        return None


def _get_tenant_features_safe(tenant_id):
    """Patch 3 — backend-enforced feature gate for a resolved tenant. Returns {} on any failure —
    callers must treat a missing/False feature as 'not enabled', never as an error."""
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return {}
    try:
        return _tcs.get_tenant_features(tenant_id)
    except Exception as e:
        print(f"Ambil tenant features gagal ({e}).")
        return {}


# ---------------------------------------------------------------------------
# Gap-fix Area F — tenant-scoped automatic follow-up safe wrappers. Same defensive shape as every
# other Client Hub bridge function above: any failure -> a safe no-op default, NEVER an exception
# that could break the main webhook, and NEVER a signal that could be misread as "go ahead and
# send". See client-hub/tenant_followup_service.py for the actual logic/eligibility rules.
# ---------------------------------------------------------------------------

def _tf_mark_activity_safe(tenant_id, customer_phone):
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return
    try:
        _tenant_followup.mark_customer_activity(tenant_id, customer_phone)
    except Exception as e:
        print(f"tenant_followup.mark_customer_activity gagal (tenant_id={tenant_id}): {e}")


def _tf_mark_resolved_safe(tenant_id, customer_phone, reason=None):
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return
    try:
        _tenant_followup.mark_resolved(tenant_id, customer_phone, reason)
    except Exception as e:
        print(f"tenant_followup.mark_resolved gagal (tenant_id={tenant_id}): {e}")


# Subscription states allowed to actually receive paid AI automation — kept in ONE place, in sync
# with client-hub/tenant_followup_service.py's identical constant (that module can't import this
# one — app.py imports client-hub modules, not the reverse — so the two lists are intentionally
# duplicated in exactly two places rather than one importing the other across that boundary).
_SUBSCRIPTION_STATES_ALLOWED_TO_RUN = ("ACTIVE", "GRACE")


def _tenant_subscription_permits_ai_runtime_safe(tenant_id):
    """Fix 4 (audit finding) — the main tenant AI-runtime gate. A business with a non-AI-Admin
    package ("NONE") has no subscription row by design and is NOT gated by this function (returns
    True) — subscriptions only apply to AI_ADMIN_BASIC/AI_ADMIN_PRO. For an AI Admin package, this
    returns True ONLY if a subscription row exists AND its status is ACTIVE or GRACE — a MISSING
    row, or one that is SUSPENDED/CANCELLED, returns False (fail closed). Any plumbing failure
    (Client Hub unavailable, DB error) also returns False — never treats an error as permission."""
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return True  # Kilas Works' own conversations (tenant_id=None) are never subscription-gated
    try:
        business = _ch_repo.get_business(tenant_id)
        if not business:
            return False
        if business.get("package") not in ("AI_ADMIN_BASIC", "AI_ADMIN_PRO"):
            return True  # no AI Admin package -> no subscription requirement applies
        import subscription_service
        sub = subscription_service.get_subscription(tenant_id)
        if sub is None:
            return False
        return sub["status"] in _SUBSCRIPTION_STATES_ALLOWED_TO_RUN
    except Exception as e:
        print(f"_tenant_subscription_permits_ai_runtime_safe gagal (tenant_id={tenant_id}): {e}")
        return False


def is_kilas_platform_tenant(tenant_id):
    """Multi-tenant runtime safety cycle — the ONE stable identifier used everywhere in this file
    to tell 'Kilas Works' own platform conversation' apart from 'a client tenant's conversation
    with its own customer'. tenant_id is ALWAYS None for Kilas Works' own WhatsApp number (see
    _resolve_tenant_id's docstring — that number has never been registered as a Client Hub
    tenant), and is otherwise a real, ACTIVE Client Hub business_id. This is deliberately NOT a
    string match against a business/display name (a client could legally be named anything,
    including something that happens to contain "Kilas") — it is the exact same tenant_id the
    webhook already resolved from the authoritative phone_number_id, so this helper can never
    disagree with the rest of the routing in this file."""
    return tenant_id is None


def _ck(tenant_id, number):
    """Compound per-(tenant, customer-phone) key for the in-memory conversation state dicts below
    (conversations/customer_names/agreed_facts/customer_language, etc). The SAME phone number can
    legitimately message two different client tenants (or a tenant AND Kilas Works itself) — those
    must be completely separate conversations with zero shared history/facts/state.

    tenant_id=None (Kilas Works' own conversations — see is_kilas_platform_tenant) maps to the
    PLAIN phone number, unchanged — every call site that predates multi-tenancy, and every test
    that never sets ENABLE_MULTI_TENANT, keeps working with byte-for-byte identical dict keys."""
    return number if tenant_id is None else f"T{tenant_id}:{number}"


def _get_tenant_whatsapp_channel_safe(tenant_id):
    """Multi-tenant runtime safety cycle (Task 1/2), credential architecture documented for Task 8
    — this ONE tenant's own WhatsApp Phone-Number-ID + access token, resolved server-side. Never
    raises; returns None (a clear 'not configured' signal) on ANY failure: Client Hub unavailable,
    tenant not found/ACTIVE, no channel recorded yet, OR a distinct per-tenant credentials_reference
    was recorded but its env var isn't actually set on THIS process — every one of those must be
    treated identically by the caller (skip sending, never fall back to Kilas Works' own identity).

    ---------------------------------------------------------------------------------------------
    TASK 8 — CREDENTIAL ARCHITECTURE DESIGN DECISION (read this before changing this function)
    ---------------------------------------------------------------------------------------------
    Business goal: onboarding a new client must not require adding a brand-new Render environment
    variable per tenant — that does not scale past a handful of clients.

    DOCUMENTED ASSUMPTION (NOT independently verified against a real Meta account from inside this
    sandboxed environment — this sandbox cannot make live calls to Meta's Graph API, so this is
    stated as an assumption to carry into the final report, not a verified fact): when several
    WhatsApp Business phone numbers are added under the SAME Meta Business Portfolio / WhatsApp
    Business Account (WABA) — the standard shape for one agency (Kilas Works) managing several
    clients' numbers under its own embedded-signup/portfolio setup — a single system-user access
    token scoped to that WABA can typically send on behalf of ANY phone number registered under it,
    with only the Phone-Number-ID varying per send. This is the common, expected Meta multi-number
    model; a client who instead brings their OWN separate Meta app/WABA would need their own
    distinct token, which is the rarer case this design still supports.

    CONCRETE DESIGN (implemented below): `credentials_reference` in tenant_whatsapp_config is now
    OPTIONAL, a config-time CHOICE per tenant record, not a hard requirement:
      (a) left EMPTY/None -> this tenant shares Kilas Works' own default server-side access value,
          the single `WHATSAPP_ACCESS_TOKEN` env var already configured for the whole service (the
          expected case: same agency-managed WABA/Portfolio, only phone_number_id differs). Onboarding
          a new such client requires ZERO new Render env vars — only a phone_number_id to record.
      (b) set to a SPECIFIC env var name (e.g. "WHATSAPP_TOKEN__TENANT_7") -> that tenant genuinely
          has its own separate Meta app/token, resolved from that named env var instead.
    Either way, the actual access token value is NEVER stored in any database column, NEVER
    displayed in any UI/API/log/report — only an env var NAME is ever persisted (case b), or
    nothing tenant-specific at all is persisted (case a, the shared default is simply read by name
    from this process's own environment, exactly like Kilas Works' own conversations already do)."""
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return None
    try:
        channel = _tcs.get_tenant_whatsapp_channel(tenant_id)
    except Exception as e:
        print(f"Ambil tenant WhatsApp channel gagal (tenant_id={tenant_id}): {e}")
        return None
    if not channel:
        return None
    credentials_reference = channel.get("credentials_reference")
    if credentials_reference:
        # Case (b) above — this tenant genuinely has its own separate Meta app/token.
        access_token = os.environ.get(credentials_reference, "")
        if not access_token:
            # Recorded a pointer, but the actual secret was never provisioned on this process —
            # treat exactly like "not configured" (never fall back to Kilas Works' own token).
            print(f"Tenant {tenant_id} WhatsApp credentials_reference belum diisi di environment — channel belum siap.")
            return None
    else:
        # Case (a) above — no per-tenant reference recorded: this tenant shares Kilas Works' own
        # default access value (same underlying Meta Business Portfolio/WABA, per the documented
        # assumption). Falling back to "" (not configured) rather than crashing if the operator
        # hasn't set WHATSAPP_ACCESS_TOKEN at all — that's a real 'not ready' state, not an error.
        access_token = WHATSAPP_ACCESS_TOKEN
        if not access_token:
            print(f"Tenant {tenant_id} pakai shared default WHATSAPP_ACCESS_TOKEN tapi env var itu kosong — channel belum siap.")
            return None
    return {"phone_number_id": channel["phone_number_id"], "access_token": access_token}


# Thread-local override for the ACTIVE WhatsApp channel used by every send_*/upload_*/
# download_whatsapp_media() call below. Reset explicitly at the top of every webhook request (see
# receive_webhook) — never left over from a previous request on the same worker thread — so a
# resolved client tenant's outgoing traffic uses THAT tenant's own Phone-Number-ID/access token,
# and Kilas Works' own conversations (tenant_id is None) keep using the global
# WHATSAPP_PHONE_NUMBER_ID/WHATSAPP_ACCESS_TOKEN exactly as before this cycle existed.
import threading as _threading
_active_channel_local = _threading.local()


def _set_active_whatsapp_channel(phone_number_id, access_token):
    _active_channel_local.phone_number_id = phone_number_id
    _active_channel_local.access_token = access_token


def _clear_active_whatsapp_channel():
    _active_channel_local.phone_number_id = None
    _active_channel_local.access_token = None


def _active_whatsapp_phone_number_id():
    return getattr(_active_channel_local, "phone_number_id", None) or WHATSAPP_PHONE_NUMBER_ID


def _active_whatsapp_access_token():
    return getattr(_active_channel_local, "access_token", None) or WHATSAPP_ACCESS_TOKEN


def _get_tenant_owner_notify_target_safe(tenant_id):
    """Multi-tenant runtime safety cycle (Task 6) — which owner should receive a day-to-day
    customer-service notification (new customer, escalation, appointment request, etc.) for THIS
    conversation. Kilas Works' own platform owner (OWNER_WHATSAPP_NUMBER) must NEVER receive a
    client tenant's own customer-service events, and a client tenant's own owner must never be
    confused with the Kilas Works platform owner — so this NEVER falls back from one to the other.
    Returns None (meaning: skip sending, do NOT fall back to Kilas Works' own owner) when a
    resolved tenant has no trusted_owner_phone configured yet — a known limitation until Client
    Hub's onboarding UI collects one, not something this bridge should paper over by guessing."""
    if is_kilas_platform_tenant(tenant_id):
        return OWNER_WHATSAPP_NUMBER
    return _get_trusted_owner_phone_safe(tenant_id)


def _get_tenant_appointment_settings_safe(tenant_id):
    """Task 3 — THIS tenant's OWN appointment settings (business hours, the appointment-enabled
    toggle, booking notes/rules). Never raises; returns {} on any failure — callers must treat a
    missing settings block as 'appointments not available', never as an error."""
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return {}
    try:
        return _tcs.get_tenant_appointment_settings(tenant_id) or {}
    except Exception as e:
        print(f"Ambil tenant appointment settings gagal (tenant_id={tenant_id}): {e}")
        return {}


def _get_tenant_payment_config_safe(tenant_id):
    """Task 4 — THIS tenant's OWN bank/payment details (never Kilas Works' own PAYMENT_CONFIG/BCA
    account). Never raises; returns {} on any failure."""
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return {}
    try:
        return _tcs.get_tenant_payment_config(tenant_id) or {}
    except Exception as e:
        print(f"Ambil tenant payment config gagal (tenant_id={tenant_id}): {e}")
        return {}


def build_tenant_payment_info_text(payment_cfg):
    """Task 4 — renders THIS tenant's OWN bank/payment details as plain text, exactly the way
    build_payment_info_text() does for Kilas Works' own PAYMENT_CONFIG, but sourced entirely from
    payment_cfg (that tenant's own configured bank_name/account_number/account_name/instructions —
    see tenant_config_service.get_tenant_payment_config). Returns None if the essential fields
    (bank + account number) aren't actually configured yet — caller must fall back to a natural
    'ask the business directly' message rather than ever inventing/guessing details."""
    bank = (payment_cfg or {}).get("bank_name")
    account_number = (payment_cfg or {}).get("account_number")
    if not bank or not account_number:
        return None
    account_name = (payment_cfg or {}).get("account_name") or ""
    text = f"{bank} {account_number}" + (f" a.n. {account_name}" if account_name else "")
    instructions = (payment_cfg or {}).get("instructions")
    if instructions:
        text += f"\n{instructions}"
    return text


def build_tenant_appointment_context(settings):
    """Task 3 — the customer-facing appointment negotiation instructions for a resolved CLIENT
    tenant, using ONLY that tenant's own business hours/closed days/booking notes (`settings`, from
    _get_tenant_appointment_settings_safe) — NEVER Kilas Works' own office-hours/slot-grid
    (build_appointment_context() above, which stays Kilas-Works-only). Deliberately simpler than
    the Kilas Works flow (no online/offline mode, no owner-offered-slot-grid subflow): the AI just
    captures the customer's preferred day/time within these business hours and hands off to the
    tenant's own owner for confirmation via the SAME MEETING_PREFERENCE/RESCHEDULE_MEETING/
    CANCEL_MEETING tags already defined below (parsed generically, not tied to Kilas Works' own
    negotiation rules)."""
    today = now_wib().date()
    hours = settings.get("business_hours_raw") or "belum ditentukan — tanya customer & catat aja preferensinya"
    closed = settings.get("closed_days")
    rules = settings.get("appointment_rules")
    lines = [
        "\n\n📅 APPOINTMENT / BOOKING BISNIS INI\n",
        f"HARI INI adalah {format_date_id(today)} ({today.strftime('%Y-%m-%d')}), WIB.\n",
        f"JAM OPERASIONAL BISNIS INI: {hours}.\n",
    ]
    if closed:
        lines.append(f"HARI TUTUP/LIBUR: {closed}.\n")
    if rules:
        lines.append(f"CATATAN/ATURAN BOOKING BISNIS INI: {rules}\n")
    lines.append(
        "Kalau customer mau booking/appointment: tanya hari & jam yang diinginkan (dalam jam "
        "operasional di atas kalau ada), respon transisi natural SANGAT SINGKAT (misal 'oke aku "
        "catat dulu ya'), lalu sertakan tag PERSIS di akhir balasan: [MEETING_PREFERENCE: "
        "day=<hari/tanggal persis kata-kata customer>|time=HH:MM] (time= opsional, isi kalau "
        "customer udah sebutin jamnya). JANGAN PERNAH bilang sendiri 'sudah dikonfirmasi/"
        "dijadwalkan' — itu tugas SISTEM setelah bisnis ini benar-benar konfirmasi.\n"
        "RESCHEDULE: kalau customer yang appointment-nya SUDAH ada mau ganti jadwal, tag PERSIS: "
        "[RESCHEDULE_MEETING: date=<hari/tanggal>|time=HH:MM].\n"
        "CANCEL: kalau customer mau batalin appointment-nya, tag PERSIS: [CANCEL_MEETING]."
    )
    return "".join(lines)


# ---------------------------------------------------------------------------
# Tenant-persistence cycle — thin, never-raising wrappers around client-hub/appointments_repo.py
# and client-hub/payment_reviews_repo.py, same "safe wrapper" convention as every other
# _get_tenant_*_safe helper above: a missing/broken Client Hub install degrades to "feature
# unavailable" (empty list / None / False), never a crash of the live webhook.
# ---------------------------------------------------------------------------

def _tenant_appt_create_safe(tenant_id, customer_phone, customer_name, request_text):
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return None
    try:
        return _appt_repo.create_appointment(tenant_id, customer_phone, customer_name, request_text)
    except Exception as e:
        print(f"Simpan tenant appointment gagal (tenant_id={tenant_id}): {e}")
        return None


def _tenant_appt_latest_safe(tenant_id, customer_phone, statuses=None):
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return None
    try:
        return _appt_repo.get_latest_for_customer(tenant_id, customer_phone, statuses=statuses)
    except Exception as e:
        print(f"Ambil tenant appointment gagal (tenant_id={tenant_id}): {e}")
        return None


def _tenant_appt_update_status_safe(appt_id, status, notes=None):
    if not _CLIENT_HUB_AVAILABLE or appt_id is None:
        return False
    try:
        _appt_repo.update_status(appt_id, status, notes=notes)
        return True
    except Exception as e:
        print(f"Update tenant appointment status gagal (id={appt_id}): {e}")
        return False


def _tenant_appt_update_reschedule_safe(appt_id, request_text, status=None):
    if not _CLIENT_HUB_AVAILABLE or appt_id is None:
        return False
    try:
        _appt_repo.update_request_text(appt_id, request_text, status=status)
        return True
    except Exception as e:
        print(f"Update tenant appointment reschedule gagal (id={appt_id}): {e}")
        return False


def _tenant_appt_list_safe(tenant_id, statuses=None, limit=50):
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return []
    try:
        return _appt_repo.list_for_business(tenant_id, statuses=statuses, limit=limit)
    except Exception as e:
        print(f"List tenant appointments gagal (tenant_id={tenant_id}): {e}")
        return []


def _tenant_payment_review_create_safe(tenant_id, customer_phone, customer_name,
                                        amount_claimed=None, amount_detected=None, proof_file_id=None):
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return None
    try:
        return _pay_review_repo.create_review(
            tenant_id, customer_phone, customer_name,
            amount_claimed=amount_claimed, amount_detected=amount_detected, proof_file_id=proof_file_id,
        )
    except Exception as e:
        print(f"Simpan tenant payment review gagal (tenant_id={tenant_id}): {e}")
        return None


def _tenant_payment_proof_store_safe(tenant_id, content_bytes, mime_type):
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return None
    try:
        return _pay_review_repo.store_proof_image(tenant_id, content_bytes, mime_type)
    except Exception as e:
        print(f"Simpan file bukti pembayaran tenant gagal (tenant_id={tenant_id}): {e}")
        return None


def _tenant_payment_review_list_pending_safe(tenant_id, limit=50):
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return []
    try:
        return _pay_review_repo.list_pending_for_business(tenant_id, limit=limit)
    except Exception as e:
        print(f"List tenant payment reviews gagal (tenant_id={tenant_id}): {e}")
        return []


def _tenant_payment_review_update_status_safe(review_id, status, owner_note=None, verified_by=None):
    if not _CLIENT_HUB_AVAILABLE or review_id is None:
        return False
    try:
        _pay_review_repo.update_status(review_id, status, owner_note=owner_note, verified_by=verified_by)
        return True
    except Exception as e:
        print(f"Update tenant payment review status gagal (id={review_id}): {e}")
        return False


def _tenant_payment_review_get_scoped_safe(review_id, tenant_id):
    if not _CLIENT_HUB_AVAILABLE or review_id is None or tenant_id is None:
        return None
    try:
        return _pay_review_repo.get_review_scoped(review_id, tenant_id)
    except Exception as e:
        print(f"Ambil tenant payment review gagal (id={review_id}, tenant_id={tenant_id}): {e}")
        return None


def _write_tenant_audit_safe(tenant_id, action, detail):
    """Reuses Client Hub's EXISTING audit_log mechanism (repo.write_audit) for tenant-owner
    WhatsApp commands that mutate a persisted record (payment confirm/reject, appointment confirm/
    reject) — actor_user_id is None (there is no logged-in Client Hub user behind a WhatsApp
    command; audit_log.actor_user_id is nullable for exactly this case), business_id is the
    resolved tenant, never a different one."""
    if not _CLIENT_HUB_AVAILABLE or tenant_id is None:
        return
    try:
        _ch_repo.write_audit(None, tenant_id, action, detail)
    except Exception as e:
        print(f"Tulis audit log tenant gagal (tenant_id={tenant_id}, action={action}): {e}")


# ---------------------------------------------------------------------------
# Task 1/2 (multi-tenant runtime safety) — the Pro tenant owner assistant. Gives a Pro CLIENT
# tenant's own recognized owner the SAME category of natural, conversational "asisten pribadi"
# experience Kilas Works' own owner already gets via call_claude_owner()/build_owner_system_prompt()
# above — asking about customers, what someone said, instructing a relay to a customer, or just
# thinking out loud — but strictly scoped to THAT tenant's own customers/conversations/appointments,
# using a SEPARATE conversation history/state (tenant_owner_conversations, tenant_meeting_requests)
# so it can never read or touch Kilas Works' own data or another tenant's. Reuses the SAME
# classify_owner_message() (client-hub/wa_project_bridge.py) already used by the thin bridge this
# replaces, and the SAME Anthropic Claude call pattern call_claude_owner() uses — this is an
# EXTENSION of that architecture (making it reachable/correctly-scoped for a tenant owner), not a
# second parallel decision engine.
# ---------------------------------------------------------------------------

tenant_owner_conversations = {}  # key: _ck(tenant_id, owner_phone) -> [{"role":..,"content":..}]


def _tenant_customer_index(tenant_id):
    """This tenant's OWN known customers only — {phone: name}, scanned from the tenant-scoped
    slice of the global `customer_names` cache (keys of the form 'T<tenant_id>:<phone>', written by
    the normal customer webhook path via _ck()). Never includes Kilas Works' own customers or
    another tenant's — those live under a different key prefix (or no prefix at all, for Kilas)."""
    prefix = f"T{tenant_id}:"
    out = {}
    for key, name in customer_names.items():
        if isinstance(key, str) and key.startswith(prefix):
            out[key[len(prefix):]] = name
    return out


def _build_tenant_owner_query_context(tenant_id, owner_phone):
    """Assembles a tenant-scoped 'what's going on' summary for the owner assistant's system prompt
    — recent customers + their last few messages (from this tenant's OWN scoped conversation
    history only), open appointment requests, and open Business Hub projects. Every piece here is
    resolved via tenant_id, never via message content, so it can never mix in another tenant's or
    Kilas Works' own data."""
    lines = []
    known = _tenant_customer_index(tenant_id)
    if known:
        cust_lines = []
        for phone, name in list(known.items())[:25]:
            scoped_key = _ck(tenant_id, phone)
            history = conversations.get(scoped_key) or load_recent_messages_from_db(scoped_key, "customer")
            last_msgs = history[-4:] if history else []
            snippet = " | ".join(
                f"{m.get('role')}: {(m.get('content') if isinstance(m.get('content'), str) else '(media)')[:120]}"
                for m in last_msgs
            ) or "(belum ada histori tersimpan)"
            cust_lines.append(f"- {name or 'Customer'} (wa.me/{phone}): {snippet}")
        lines.append("CUSTOMER BISNIS INI (terbaru):\n" + "\n".join(cust_lines))
    else:
        lines.append("Belum ada customer yang tercatat chat ke bisnis ini.")

    # Tenant-persistence cycle — read from the PERSISTED tenant_appointments table (DB), not the
    # in-process tenant_meeting_requests dict, so this context (and therefore the owner's answer
    # to "Ada booking besok?"/"Siapa booking jam 3?") is correct even after a server restart.
    appt_rows = _tenant_appt_list_safe(tenant_id, statuses=_appt_repo.OPEN_STATUSES if _CLIENT_HUB_AVAILABLE else None, limit=25)
    appt_lines = []
    for row in appt_rows:
        name = row.get("customer_name") or known.get(row["customer_phone"], "Customer")
        when = row.get("request_text") or "-"
        appt_lines.append(f"- {name} (wa.me/{row['customer_phone']}): {when} — status {row.get('status')}")
    if appt_lines:
        lines.append("\nAPPOINTMENT/BOOKING YANG TERCATAT:\n" + "\n".join(appt_lines))

    # Tenant-persistence cycle (Task 2/3) — pending/recent payment-proof reviews for THIS tenant
    # only, so the owner can ask "Ada transfer yang belum gue cek?"/"Yang Budi bayar berapa?"/
    # "Bukti transfer yang tadi gimana?" and get a real, data-backed answer. Never claims
    # authenticity — only reports what was claimed/detected and the current review status.
    pay_rows = _tenant_payment_review_list_pending_safe(tenant_id, limit=25)
    if pay_rows:
        pay_lines = []
        for row in pay_rows:
            name = row.get("customer_name") or known.get(row["customer_phone"], "Customer")
            claimed = f"Rp{row['amount_claimed']:,}".replace(",", ".") if row.get("amount_claimed") else "(nominal belum disebut customer)"
            detected = f"Rp{row['amount_detected']:,}".replace(",", ".") if row.get("amount_detected") else "(nominal di gambar tidak terbaca jelas)"
            pay_lines.append(
                f"- {name} (wa.me/{row['customer_phone']}): klaim {claimed}, kelihatan di gambar {detected} "
                f"— status {row.get('status')} (BELUM DIVERIFIKASI, JANGAN PERNAH bilang ini pasti asli/lunas)."
            )
        lines.append("\nBUKTI TRANSFER YANG BELUM DICEK:\n" + "\n".join(pay_lines))

    projects = _get_open_projects_summary_safe(tenant_id)
    if projects:
        proj_lines = [f"- {p['title']} ({p['project_type']}): {p['status'].replace('_', ' ')}" for p in projects]
        lines.append("\nPROJECT BUSINESS HUB YANG MASIH JALAN:\n" + "\n".join(proj_lines))

    active_target = _tenant_active_customer_context.get((tenant_id, owner_phone))
    if active_target:
        active_name = known.get(active_target, f"wa.me/{active_target}")
        lines.append(f"\nCUSTOMER TERAKHIR YANG CHAT: {active_name} ({active_target}).")

    return "\n".join(lines)


def build_tenant_owner_system_prompt(tenant_id, owner_phone, business_name):
    """Task 1 — system prompt for the Pro tenant owner assistant. Explicitly scoped to THIS
    business only, and explicitly forbidden from ever surfacing raw internal tags/markers/system
    wording to the owner (the owner IS a real person reading real WhatsApp messages, not a debug
    console) or forwarding them into any customer-facing message."""
    return (
        f"Kamu adalah asisten pribadi WhatsApp untuk pemilik bisnis \"{business_name}\" (bukan "
        "Kilas Works — ini bisnis KLIEN Kilas Works yang pakai produk AI Admin). Kamu HANYA boleh "
        "membahas data/customer/appointment/project milik bisnis INI — JANGAN PERNAH menyebut atau "
        "mencampur data bisnis lain manapun, termasuk Kilas Works sendiri.\n\n"
        "Balas natural, santai, seperti asisten pribadi manusia lewat chat WhatsApp — dalam Bahasa "
        "Indonesia kecuali owner jelas menulis dalam bahasa lain. JANGAN PERNAH menampilkan tag/kode "
        "internal apapun (semacam [ACTION], [STATE], JSON mentah, atau istilah debug) ke owner — "
        "kalau ada instruksi sistem, jalankan diam-diam saja, balasannya tetap kalimat natural.\n\n"
        "Owner bisa nanya soal customer yang sedang serius, siapa yang tadi nanya harga, apa yang "
        "terakhir dikatakan seorang customer, ada booking/appointment apa aja, siapa yang belum "
        "di-follow-up, atau sekadar mikir/curhat soal bisnisnya — SELALU balas dengan jawaban nyata "
        "berdasarkan data di bawah, JANGAN PERNAH diam saja / tidak membalas apapun.\n\n"
        "Kalau owner MINTA kamu menyampaikan/membalas sesuatu ke seorang customer (mis. 'bales si "
        "Budi bilang stoknya ada', 'terusin ke customer tadi jam 3 bisa'), SISTEM yang akan benar-"
        "benar mengirim pesan itu ke customer secara terpisah — tugasmu di sini HANYA menjawab "
        "owner secara natural mengonfirmasi apa yang akan disampaikan (mis. 'Oke, aku sampaikan ke "
        "Budi ya'). JANGAN PERNAH menulis pesan seolah-olah kamu sedang berbicara LANGSUNG ke "
        "customer di balasan ini.\n\n"
        f"DATA BISNIS INI SAAT INI:\n{_build_tenant_owner_query_context(tenant_id, owner_phone)}"
    )


def call_tenant_owner_ai(tenant_id, owner_phone, owner_message, business_name,
                          image_b64=None, image_mime=None, is_voice_note=False):
    """Task 1 — the actual Claude call for the Pro tenant owner assistant, same request shape as
    call_claude_owner() above but with its OWN conversation history (tenant_owner_conversations,
    keyed by _ck(tenant_id, owner_phone)) and its OWN tenant-scoped system prompt — never shares
    history/state with Kilas Works' own owner_conversations or another tenant's.

    image_b64/image_mime and is_voice_note (deepening cycle, Task 1/3 parity with Kilas Works' own
    call_claude_owner()) — SAME pattern as that function: a voice note's transcript is fed in as
    plain text (no second AI engine, just tagged "[OWNER VOICE NOTE]" for memory/history so the
    assistant can later answer 'apa kata aku tadi lewat voice note'), and an image forces the
    vision-capable model (MODEL_PRIMARY) since MODEL_FAST/Haiku does not support vision, tagged
    "[OWNER KIRIM GAMBAR]" the same way."""
    scoped_key = _ck(tenant_id, owner_phone)
    history = tenant_owner_conversations.get(scoped_key)
    if history is None:
        history = load_recent_messages_from_db(scoped_key, "owner")

    if image_b64:
        api_content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": image_mime or "image/jpeg", "data": image_b64},
            },
            {"type": "text", "text": owner_message or "(owner kirim gambar tanpa keterangan)"},
        ]
        memory_text = f"[OWNER KIRIM GAMBAR] {owner_message}".strip()
    elif is_voice_note:
        api_content = owner_message
        memory_text = f"[OWNER VOICE NOTE] {owner_message}".strip()
    else:
        api_content = owner_message
        memory_text = owner_message

    history.append({"role": "user", "content": api_content})
    save_message_to_db(scoped_key, "owner", "user", memory_text)

    system_prompt = build_tenant_owner_system_prompt(tenant_id, owner_phone, business_name)
    model_to_use = MODEL_FAST if not image_b64 else MODEL_PRIMARY
    try:
        if image_b64:
            raise RuntimeError("skip-haiku-vision-not-supported")
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={"model": model_to_use, "max_tokens": 300, "system": system_prompt, "messages": history},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        reply_text = data["content"][0]["text"]
        log_ai_usage("tenant_owner", model_to_use, data)
    except Exception as e:
        if not image_b64:
            print(f"Tenant owner AI call gagal (tenant_id={tenant_id}): {e}")
        model_to_use = MODEL_FALLBACK if image_b64 else model_to_use
        try:
            if image_b64:
                resp = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={"model": model_to_use, "max_tokens": 300, "system": system_prompt, "messages": history},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
                reply_text = data["content"][0]["text"]
                log_ai_usage("tenant_owner", model_to_use, data)
            else:
                raise
        except Exception as e2:
            print(f"Tenant owner AI call gagal (tenant_id={tenant_id}): {e2}")
            reply_text = "Aku catat ya — coba tanya lagi sebentar kalau butuh detail lebih lanjut."

    if image_b64:
        history[-1] = {"role": "user", "content": memory_text}

    history.append({"role": "assistant", "content": reply_text})
    tenant_owner_conversations[scoped_key] = history[-20:]
    save_message_to_db(scoped_key, "owner", "assistant", reply_text)
    return strip_tags(reply_text)


def _resolve_tenant_owner_relay_target(tenant_id, owner_phone, raw_text):
    """Task 1 — resolves WHO an owner's relay instruction ('bales si Budi ...', 'terusin ke 6281...
    ...') is talking about, scoped to THIS tenant's own known customers only (see
    _tenant_customer_index) — falls back to the 'last customer who chatted' context
    (_tenant_active_customer_context) when no name/number is explicitly mentioned.

    Returns (customer_phone_or_None, remaining_message_text, ambiguous_matches). The third element
    is None in the normal case; it is a non-empty list of (phone, name) candidates (Task 4) when
    the owner's text genuinely names 2+ DIFFERENT known customers (e.g. both "Budi" and "Sari" are
    mentioned) with no way to tell which one is meant — callers must ask a clarifying question
    rather than silently guessing one of them. A name that is merely a SHORTER form of another
    match (e.g. "Budi" inside "Budi Kurniawan") is not treated as ambiguous — the longest/most
    specific match is picked, same as before this cycle."""
    known = _tenant_customer_index(tenant_id)
    # Direct phone number mention (customer wrote to us using their own WhatsApp number).
    phone_match = re.search(r"\b(\d{8,15})\b", raw_text)
    if phone_match and phone_match.group(1) in known:
        target = phone_match.group(1)
        remainder = (raw_text[:phone_match.start()] + raw_text[phone_match.end():]).strip()
        return target, remainder, None
    # Name mention(s) among this tenant's own known customer names.
    lowered = raw_text.lower()
    matches = [(phone, name) for phone, name in known.items() if name and name.lower() in lowered]
    if matches:
        matches.sort(key=lambda pn: len(pn[1]), reverse=True)
        longest_phone, longest_name = matches[0]
        genuinely_distinct = [pn for pn in matches if pn[1].lower() not in longest_name.lower()]
        if genuinely_distinct:
            return None, raw_text, matches
        return longest_phone, raw_text, None
    active = _tenant_active_customer_context.get((tenant_id, owner_phone))
    if active:
        return active, raw_text, None
    return None, raw_text, None


# ---------------------------------------------------------------------------
# Final Ecosystem Sync — Section 20: canonical runtime price lookup against Client Hub's catalog
# (the single source of truth per Section 1/19), used to keep the WhatsApp bot's answers in sync
# once an admin edits a price in Client Hub, WITHOUT ripping out or duplicating PRICING_CONFIG
# (158+ existing regression tests exercise that dict directly and must keep passing unchanged).
# Same safe-wrapper shape as every other bridge function above: any failure -> None -> caller
# falls back to PRICING_CONFIG exactly as before this patch existed.
# ---------------------------------------------------------------------------
try:
    import catalog_service as _catalog_service
except Exception as _catalog_import_err:
    _catalog_service = None
    print(f"Client Hub catalog_service tidak tersedia ({_catalog_import_err}) — bot pakai PRICING_CONFIG statis.")


def _get_catalog_price_safe(catalog_key):
    """Returns {'price_amount': int, 'price_unit': str, 'name': str} for an ACTIVE catalog_key, or
    None on ANY failure (Client Hub unavailable, key not found, inactive, DB error, CUSTOM_QUOTE
    item with no fixed price). Never raises. Logged internally only — never surfaced to a customer."""
    if _catalog_service is None:
        return None
    try:
        item = _catalog_service.get_catalog_item(catalog_key)
        if not item or not item.get("is_active") or item.get("pricing_mode") == "CUSTOM_QUOTE":
            return None
        if item.get("price_amount") is None:
            return None
        return {"price_amount": item["price_amount"], "price_unit": item.get("price_unit") or "",
                "name": item.get("name") or catalog_key}
    except Exception as e:
        print(f"Ambil live catalog price gagal untuk {catalog_key!r} ({e}) — fallback ke PRICING_CONFIG.")
        return None


# Bug fix: this used to be a deliberately tiny, hand-picked set of ~7 catalog_keys (AI Admin,
# Content, 2 website items) — every other FIXED_PRICE/STARTING_FROM item in the live catalog (Meta
# Ads, bundles, remaining website items, events, etc.) silently never got synced, so the bot kept
# quoting a stale PRICING_CONFIG number for those forever, however long ago an admin changed them
# in Client Hub. Coverage is now generic: every item is discovered by catalog_key from Client Hub's
# own pricing_config.CATALOG_ITEMS (the exact source service_catalog is seeded from, i.e. exactly
# the set of catalog_keys the bot's PRICING_TEXT_BLOCK bakes a number in for), never a fixed list
# maintained by hand here. CUSTOM_QUOTE items (Custom Content/Photo/Video/Talent/Website-App) are
# never included — _get_catalog_price_safe() already refuses to return a price for those.
try:
    import pricing_config as _pricing_config_module
except Exception as _pricing_config_import_err:
    _pricing_config_module = None
    print(f"Client Hub pricing_config tidak tersedia ({_pricing_config_import_err}) — pakai fallback kecil.")

# Last-resort fallback ONLY for the rare case pricing_config.py itself can't be imported (e.g. this
# file copied somewhere without client-hub/) — _get_full_catalog_sync_baseline_safe() below prefers
# the full generic set and only drops to this tiny dict when that genuinely fails.
_CATALOG_SYNC_KEYS_FALLBACK = {
    "ai_admin_basic": ("AI Admin Basic", 499_000),
    "ai_admin_pro": ("AI Admin Pro", 999_000),
    "content_basic": ("Content Basic", 1_500_000),
    "content_growth": ("Content Growth", 2_750_000),
    "content_pro": ("Content Pro", 4_250_000),
    "website_landing_page": ("Landing Page", 799_000),
    "website_company_profile": ("Company Profile Website", 1_500_000),
}


def _get_full_catalog_sync_baseline_safe():
    """Returns {catalog_key: (label, seeded_amount)} for EVERY FIXED_PRICE/STARTING_FROM item
    Client Hub's pricing_config.py defines (i.e. every catalog_key with a concrete number baked
    into the bot's own PRICING_TEXT_BLOCK/PRICING_CONFIG) — never a hand-picked subset. Returns the
    small _CATALOG_SYNC_KEYS_FALLBACK dict instead ONLY when pricing_config.py itself can't be
    imported/read (Client Hub missing, corrupted install, etc.), and never raises."""
    if _pricing_config_module is None:
        return _CATALOG_SYNC_KEYS_FALLBACK
    try:
        return {
            item["key"]: (item["name"], item["price_amount"])
            for item in _pricing_config_module.CATALOG_ITEMS
            if item.get("pricing_mode") in ("FIXED_PRICE", "STARTING_FROM") and item.get("price_amount") is not None
        }
    except Exception as e:
        print(f"Baca pricing_config.CATALOG_ITEMS gagal ({e}) — pakai fallback kecil.")
        return _CATALOG_SYNC_KEYS_FALLBACK


def _build_live_price_sync_note_safe():
    """Gap-fix Area H (extends Section 20's original price-only sync): returns an ADDITIVE
    system-prompt note covering THREE kinds of live Client Hub catalog divergence from the
    hardcoded PRICING_CONFIG/PRICING_TEXT_BLOCK baked into SYSTEM_PROMPT at import time — price
    changes (original Section 20 behavior, unchanged), an item being DEACTIVATED (no longer
    offered), and an item being RENAMED. Returns "" when Client Hub is unavailable OR nothing has
    diverged — every one of the 158+ existing regression tests (none of which touch Client Hub's
    catalog) sees byte-identical prompt behavior to before this patch existed.

    Client Hub currently has NO "add a brand-new catalog item from scratch" admin capability (see
    catalog_service.update_catalog_item's docstring — only editing an already-seeded row's price/
    name/description/active-flag/sort-order/pricing-mode is supported), so "a genuinely new item
    admin invented out of thin air" is not a reachable state to sync here; what IS reachable and
    now covered is an existing seeded item being renamed or turned off.

    Covers EVERY currently active FIXED_PRICE/STARTING_FROM catalog item generically (see
    _get_full_catalog_sync_baseline_safe) — not just a hand-picked handful. A historical/already-
    placed order's own locked-in price is never touched by this (it lives on the order/invoice row,
    not here) — this only affects what the bot SAYS about the CURRENT live catalog going forward."""
    if _catalog_service is None:
        return ""
    try:
        baseline = _get_full_catalog_sync_baseline_safe()
        price_diffs = []
        deactivated = []
        renamed = []
        for catalog_key, (label, hardcoded_amount) in baseline.items():
            try:
                live_item = _catalog_service.get_catalog_item(catalog_key)
            except Exception as e:
                print(f"Ambil live catalog item gagal untuk {catalog_key!r} ({e}).")
                continue
            if not live_item:
                continue  # key not seeded/found live -> nothing to compare, stay silent (fail safe)

            if not live_item.get("is_active"):
                deactivated.append(f"- {label}: SUDAH TIDAK DITAWARKAN LAGI — JANGAN pernah rekomendasikan atau sebut ini sebagai paket yang bisa dipesan sekarang")
                continue  # an inactive item's price/name are irrelevant to a customer

            live = _get_catalog_price_safe(catalog_key)
            if live is not None and live["price_amount"] != hardcoded_amount:
                price_fmt = f"Rp{live['price_amount']:,}".replace(",", ".")
                unit = f" {live['price_unit']}" if live.get("price_unit") else ""
                price_diffs.append(f"- {label}: harga TERBARU adalah {price_fmt}{unit} (BUKAN angka lama manapun)")

            live_name = (live_item.get("name") or "").strip()
            if live_name and live_name != label:
                renamed.append(f"- \"{label}\" sekarang bernama \"{live_name}\" — pakai nama BARU ini kalau menyebutnya")

        if not price_diffs and not deactivated and not renamed:
            return ""
        sections = []
        if price_diffs:
            sections.append("Harga terbaru:\n" + "\n".join(price_diffs))
        if deactivated:
            sections.append("Paket yang SUDAH TIDAK AKTIF (jangan tawarkan):\n" + "\n".join(deactivated))
        if renamed:
            sections.append("Paket yang GANTI NAMA:\n" + "\n".join(renamed))
        diffs_text = "\n\n".join(sections)
        return (
            "\n\nUPDATE TERBARU DARI KILAS WORKS BUSINESS HUB (SUMBER DATA PALING BENAR, "
            "OVERRIDE data manapun di atas untuk item-item ini SAJA — JANGAN tampilkan daftar "
            "lengkap kalau customer cuma nanya satu layanan, cukup jawab yang ditanya):\n"
            f"{diffs_text}"
        )
    except Exception as e:
        print(f"Build live catalog sync note gagal ({e}) — fallback ke PRICING_CONFIG statis tanpa note.")
        return ""


# ---------------------------------------------------------------------------
# Final Ecosystem Sync — Section 13: owner-bot database-query safe wrappers, same defensive
# pattern as _get_open_projects_summary_safe above (never raise, degrade to a harmless empty
# default on any failure). These answer real owner questions ("ada payment yang belum gue
# verifikasi?", "project custom baru siapa aja?", etc.) truthfully from Client Hub's own DB —
# never invented. Only meaningful when ENABLE_MULTI_TENANT's Client Hub install is present; on a
# plain single-tenant deploy (client-hub/ folder absent) these all safely return "no data".
# ---------------------------------------------------------------------------
try:
    import payment_service as _payment_service
    import projects_repo as _projects_repo
    import talent_service as _talent_service
    import repo as _client_hub_repo
except Exception:
    _payment_service = None
    _projects_repo = None
    _talent_service = None
    _client_hub_repo = None


def _business_name_safe(business_id):
    if _client_hub_repo is None or business_id is None:
        return f"business #{business_id}"
    try:
        b = _client_hub_repo.get_business(business_id)
        return b["business_name"] if b else f"business #{business_id}"
    except Exception:
        return f"business #{business_id}"


def _get_pending_payment_verifications_safe():
    """Section 13: 'Ada payment yang belum gue verifikasi/cek?' / 'Siapa yang belum gue verifikasi
    pembayarannya?' — count + short list (WITH the business name, not just raw ids, so the owner's
    natural-language question can actually be answered), or a harmless empty result on failure."""
    if _payment_service is None:
        return {"count": 0, "items": []}
    try:
        rows = _payment_service.list_payments_pending_review()
        items = []
        for r in rows[:10]:
            name = _business_name_safe(r.get("business_id"))
            amount = None
            try:
                invoice = _payment_service.get_invoice(r.get("invoice_id"))
                amount = invoice.get("amount") if invoice else None
            except Exception:
                amount = None
            amount_fmt = f"Rp{amount:,}".replace(",", ".") if amount else "-"
            items.append(f"{name} — invoice #{r.get('invoice_id')} ({amount_fmt}), payment #{r.get('id')}, "
                         f"status {r.get('status')}")
        return {"count": len(rows), "items": items}
    except Exception as e:
        print(f"Ambil pending payment verifications gagal ({e}).")
        return {"count": 0, "items": []}


def _get_new_custom_project_requests_safe():
    """Section 13: 'Ada project custom baru?' — with business name + budget."""
    if _projects_repo is None:
        return {"count": 0, "items": []}
    try:
        rows = [p for p in _projects_repo.list_all_projects() if p.get("status") == "WAITING_FOR_QUOTE"]
        items = []
        for r in rows[:10]:
            name = _business_name_safe(r.get("business_id"))
            budget = r.get("budget_max") or r.get("budget_min")
            budget_fmt = f"Rp{budget:,}".replace(",", ".") if budget else "belum disebutkan"
            items.append(f"{name} — {r.get('title')} ({r.get('project_type')}), budget {budget_fmt}, "
                         f"project #{r.get('id')}")
        return {"count": len(rows), "items": items}
    except Exception as e:
        print(f"Ambil new custom project requests gagal ({e}).")
        return {"count": 0, "items": []}


def _get_new_talent_requests_safe():
    """Section 13: 'Siapa yang request Putri?' / 'Talent request hari ini ada?' — with business
    name + talent name + campaign type."""
    if _talent_service is None:
        return {"count": 0, "items": []}
    try:
        rows = _talent_service.list_all_talent_requests()
        pending = [r for r in rows if r.get("status") == "WAITING_FOR_REVIEW"]
        items = []
        for r in rows[:20]:
            name = _business_name_safe(r.get("business_id"))
            talent = None
            try:
                t = _talent_service.get_talent(r.get("talent_id"))
                talent = t["name"] if t else f"talent #{r.get('talent_id')}"
            except Exception:
                talent = f"talent #{r.get('talent_id')}"
            items.append(f"{name} — minta {talent} untuk {r.get('campaign_type') or 'campaign (belum disebutkan)'}, "
                         f"status {r.get('status')}, dibuat {r.get('created_at')}, request #{r.get('id')}")
        return {"count": len(pending), "items": items}
    except Exception as e:
        print(f"Ambil new talent requests gagal ({e}).")
        return {"count": 0, "items": []}



def _build_live_talent_knowledge_note_safe(for_owner=False):
    """Ground Kilas Works Talent Management from Client Hub's live talents table.

    This fixes the knowledge gap where Talent Management existed end-to-end in Client Hub/catalog,
    but the WhatsApp prompt only knew the older PRICING_CONFIG service list and could incorrectly
    claim that Kilas Works did not offer Talent Management.

    Customer mode exposes public fields only. Owner mode may additionally expose the internal rate
    because the owner is the authorized operator. Never invents a talent or availability.

    Sales Brain V2 (production-safety refinement, kept as the SAME single function/call sites —
    NOT a parallel implementation): the OWNER branch below is byte-for-byte unchanged from the
    already-verified-in-production version. Only the CUSTOMER branch (for_owner=False) is
    refined: it no longer includes the raw availability_status enum in the per-talent line (a
    customer should never see a literal "AVAILABLE"/"BUSY" database code — see SYSTEM_PROMPT's
    SOAL TALENT MANAGEMENT section for the natural-language handling of this), and the trailing
    instruction is stronger about this data being KNOWLEDGE for the model, not text to paste
    verbatim into a reply — gating WHEN to actually name specific talents to a customer is the
    job of SYSTEM_PROMPT's SOAL TALENT MANAGEMENT section, not this data function."""
    if _talent_service is None:
        return (
            "\n\nTALENT MANAGEMENT KILAS WORKS:\n"
            "- Talent Management adalah layanan RESMI dan AKTIF Kilas Works dengan harga Custom Quote.\n"
            "- Jangan pernah bilang Kilas Works tidak punya Talent Management. "
            "Kalau daftar talent live sedang tidak tersedia, bilang daftar talent sedang dicek, jangan mengarang."
        )
    try:
        rows = _talent_service.list_active_talents()
        lines = [
            "\n\nTALENT MANAGEMENT KILAS WORKS — DATA LIVE DARI CLIENT HUB:",
            "- Talent Management adalah layanan RESMI dan AKTIF Kilas Works.",
            "- Pricing: Custom Quote (jangan mengarang harga publik).",
            "- Kalau ditanya apakah fitur/layanan Talent Management ada, jawab YA.",
            "- Daftar talent aktif saat ini:",
        ]
        if not rows:
            lines.append("  * (belum ada talent aktif saat ini)")
        for t in rows[:50]:
            name = t.get("name") or "-"
            handle = t.get("social_handle") or "-"
            followers = t.get("follower_count")
            followers_text = f"{int(followers):,}".replace(",", ".") if followers is not None else "-"
            niche = t.get("niche") or "-"
            if for_owner:
                availability = t.get("availability_status") or "AVAILABLE"
                line = (
                    f"  * {name} | {handle} | followers {followers_text} | "
                    f"niche {niche} | availability {availability}"
                )
                if t.get("internal_rate") is not None:
                    try:
                        rate_text = f"Rp{int(t.get('internal_rate')):,}".replace(",", ".")
                    except Exception:
                        rate_text = str(t.get("internal_rate"))
                    line += f" | internal_rate {rate_text}"
            else:
                # Sales Brain V2: no raw availability_status code, no internal_rate — public
                # fields only (name/handle/followers/niche), and this line is KNOWLEDGE for you
                # to draw on naturally per SOAL TALENT MANAGEMENT, not a template to paste as-is.
                line = f"  * {name} | {handle} | followers {followers_text} | niche {niche}"
            lines.append(line)
        lines.append(
            "- Data di atas adalah source-of-truth saat ini. Kalau admin mengubah talent/status di Client Hub, "
            "gunakan data live ini dan jangan mengandalkan daftar lama/hardcoded."
        )
        if not for_owner:
            lines.append(
                "- Ini KNOWLEDGE buat kamu, BUKAN teks siap-tempel ke customer — lihat SOAL TALENT MANAGEMENT "
                "di atas buat kapan & gimana cara nyebutnya natural. Ke customer, JANGAN PERNAH bocorkan "
                "internal_rate/internal_notes atau kode availability mentah (data itu memang sudah tidak "
                "disertakan di baris di atas untuk mode customer). Kalau customer minta harga talent, "
                "arahkan ke Custom Quote sesuai campaign."
            )
        return "\n".join(lines)
    except Exception as e:
        print(f"Build live talent knowledge gagal ({e}).")
        return (
            "\n\nTALENT MANAGEMENT KILAS WORKS:\n"
            "- Talent Management adalah layanan RESMI dan AKTIF Kilas Works dengan harga Custom Quote.\n"
            "- Jangan pernah bilang layanan ini tidak ada. Kalau detail talent live gagal dibaca, "
            "jawab bahwa daftar/ketersediaan sedang dicek, jangan mengarang."
        )


def _get_recent_quotations_safe():
    """'Quotation Rina berapa?' / 'Kopi ABC udah bayar?' (context for) — recent quotations with
    business name, number, price, status."""
    if _client_hub_repo is None:
        return []
    try:
        import quotation_service as _quotation_service
    except Exception as e:
        print(f"quotation_service tidak tersedia ({e}).")
        return []
    try:
        rows = _quotation_service.list_all_quotations()
        items = []
        for r in rows[:20]:
            name = _business_name_safe(r.get("business_id"))
            price = r.get("final_price")
            price_fmt = f"Rp{price:,}".replace(",", ".") if price else "-"
            items.append(f"{name} — {r.get('quotation_number')}: {price_fmt}, status {r.get('status')}")
        return items
    except Exception as e:
        print(f"Ambil recent quotations gagal ({e}).")
        return []


def _get_ai_admin_pipeline_status_safe():
    """Section 13: 'WhatsApp connection yang masih pending siapa aja?' plus the wider AI Admin
    onboarding pipeline counts (ready for review / waiting WhatsApp connection)."""
    if _client_hub_repo is None:
        return {"ready_for_review": 0, "waiting_whatsapp_connection": 0}
    try:
        businesses = _client_hub_repo.list_all_businesses(status_filter=None)
        ready_for_review = [b for b in businesses if b.get("status") == "READY_FOR_REVIEW"]
        waiting_connection = [
            b for b in businesses
            if b.get("status") == "APPROVED" and not b.get("whatsapp_connected") and b.get("package") != "NONE"
        ]
        return {
            "ready_for_review": len(ready_for_review),
            "waiting_whatsapp_connection": len(waiting_connection),
            "waiting_whatsapp_connection_names": [b.get("business_name") for b in waiting_connection[:10]],
        }
    except Exception as e:
        print(f"Ambil AI admin pipeline status gagal ({e}).")
        return {"ready_for_review": 0, "waiting_whatsapp_connection": 0}


def _build_business_hub_owner_query_context_safe():
    """Absolute Final Production Patch (Section 4): grounds the Kilas-Works-owner AI mode with
    REAL, LIVE Client Hub data so natural questions like 'Ada payment yang belum gue cek?',
    'Siapa yang request Putri?', 'Kopi ABC udah bayar?', 'Client mana yang belum connect
    WhatsApp?' get answered from actual DB state — never invented.

    This is injected the SAME way _build_live_price_sync_note_safe() already is: an additive,
    read-only text block appended to the existing owner system prompt. No second AI engine, no
    parallel routing table — Claude answers directly from this block using the SAME conversational
    flow that already handles every other owner question. Returns "" when Client Hub is
    unavailable (single-tenant deploy) so the owner prompt is byte-identical to before this patch
    on such a deploy."""
    if not _CLIENT_HUB_AVAILABLE:
        return ""
    try:
        payments = _get_pending_payment_verifications_safe()
        projects = _get_new_custom_project_requests_safe()
        talent_reqs = _get_new_talent_requests_safe()
        quotations = _get_recent_quotations_safe()
        pipeline = _get_ai_admin_pipeline_status_safe()
        onboarding_done = _get_onboarding_complete_businesses_safe()

        lines = ["\n\nDATA KILAS WORKS BUSINESS HUB SAAT INI (real-time, JANGAN PERNAH KARANG DATA "
                 "LAIN — kalau owner nanya sesuatu yang gak ada di sini, jawab jujur 'belum ada data "
                 "itu' / 'nggak ketemu', JANGAN menebak. Kalau nama bisnis yang ditanya cocok dengan "
                 "LEBIH DARI SATU entri di bawah, tanya balik satu pertanyaan klarifikasi singkat "
                 "dulu sebelum jawab — jangan asal pilih salah satu):"]

        lines.append(f"- Payment menunggu verifikasi ({payments['count']}):")
        lines += [f"  * {i}" for i in payments["items"]] if payments["items"] else ["  * (tidak ada)"]

        lines.append(f"- Project custom baru menunggu penawaran ({projects['count']}):")
        lines += [f"  * {i}" for i in projects["items"]] if projects["items"] else ["  * (tidak ada)"]

        lines.append(f"- Talent request menunggu review ({talent_reqs['count']}), semua talent request terbaru:")
        lines += [f"  * {i}" for i in talent_reqs["items"]] if talent_reqs["items"] else ["  * (tidak ada)"]

        lines.append("- Quotation terbaru (nomor, harga, status):")
        lines += [f"  * {i}" for i in quotations] if quotations else ["  * (tidak ada)"]

        lines.append(f"- Onboarding AI Admin siap direview: {pipeline.get('ready_for_review', 0)} business")
        wc_names = pipeline.get("waiting_whatsapp_connection_names") or []
        lines.append(f"- Client yang APPROVED tapi BELUM connect WhatsApp ({pipeline.get('waiting_whatsapp_connection', 0)}): "
                     + (", ".join(wc_names) if wc_names else "(tidak ada)"))
        lines.append("- Client yang onboarding-nya SUDAH SELESAI (ACTIVE / sudah connect WhatsApp): "
                     + (", ".join(onboarding_done) if onboarding_done else "(tidak ada)"))

        lines.append(
            "\nPENTING (Section 5 — query vs action): semua di atas HANYA untuk MENJAWAB pertanyaan. "
            "Kalau owner minta AKSI resmi lewat WhatsApp (verifikasi/tolak pembayaran, approve/aktifkan "
            "tenant, kirim quotation, dll), JANGAN coba lakukan aksinya di sini — arahkan owner untuk "
            "buka Kilas Works Business Hub (app.kilasworks.id) buat melakukan aksi itu resmi lewat app."
        )
        return "\n".join(lines)
    except Exception as e:
        print(f"Build business hub owner query context gagal ({e}) — owner prompt fallback tanpa data ini.")
        return ""


def _get_onboarding_complete_businesses_safe():
    """'Siapa yang onboardingnya sudah selesai?' — businesses that are ACTIVE (approved AND
    already WhatsApp-connected)."""
    if _client_hub_repo is None:
        return []
    try:
        businesses = _client_hub_repo.list_all_businesses(status_filter=None)
        done = [b for b in businesses if b.get("status") == "ACTIVE" or b.get("whatsapp_connected")]
        return [b.get("business_name") for b in done[:20]]
    except Exception as e:
        print(f"Ambil onboarding complete list gagal ({e}).")
        return []


# Customer TERAKHIR yang chat ke SETIAP tenant client (bukan Kilas Works sendiri), per (tenant_id,
# trusted_owner_phone) — dipakai Patch 5 sebagai target default kalau owner tenant itu bilang
# "bilang ke customer ...". Sama polanya persis dengan `active_customer_context` yang sudah ada di
# bawah untuk Kilas Works sendiri, cuma discope per tenant biar tidak pernah campur.
_tenant_active_customer_context = {}

# ==== MODEL CLAUDE — SATU TEMPAT SAJA (jangan hardcode model ID di fungsi manapun lagi) ====
# AUDIT Agustus 2026: "claude-3-5-haiku-20241022" (model lama yang sebelumnya dipakai di sini)
# sudah RETIRED oleh Anthropic sejak 19 Feb 2026 — setiap request ke situ SELALU gagal. Selama ini
# bot customer & owner diam-diam SELALU jatuh ke fallback Sonnet (karena percobaan Haiku selalu
# error), demo malah gak punya fallback sama sekali jadi selalu nampilin pesan gangguan teknis.
# MODEL_FAST dipulihkan ke generasi Haiku yang masih aktif, biar desain asli (cepat & hemat untuk
# balasan teks biasa, Sonnet cuma untuk gambar/fallback) beneran jalan lagi seperti niat awal kode.
MODEL_FAST = os.environ.get("MODEL_FAST", "claude-haiku-4-5-20251001")      # default balasan teks (customer & owner)
MODEL_PRIMARY = os.environ.get("MODEL_PRIMARY", "claude-sonnet-4-6")        # wajib dipakai kalau ada gambar (vision)
MODEL_FALLBACK = os.environ.get("MODEL_FALLBACK", "claude-sonnet-4-6")      # dipakai kalau MODEL_FAST error/timeout

# Password buat buka halaman dashboard (/dashboard?key=...). GANTI ini di environment variable
# Render, jangan pakai default di production.
DASHBOARD_KEY = os.environ.get("DASHBOARD_KEY", "kilasworks-dashboard")

# Password buat trigger follow-up otomatis (/cron/followups?key=...). Endpoint ini HARUS dipanggil
# dari luar secara berkala (misal via cron-job.org tiap 1 jam) — Render gak bisa "bangunin dirinya
# sendiri" tiap 12 jam, jadi butuh trigger eksternal. Kalau kosong, fallback ke DASHBOARD_KEY.
CRON_SECRET = os.environ.get("CRON_SECRET", "") or DASHBOARD_KEY

# Absolute Final Production Patch — shared secret for the internal Client Hub -> bot notification
# channel (POST /internal/owner-notify, defined further down). Deliberately has NO fallback/default
# value (unlike CRON_SECRET falling back to DASHBOARD_KEY) — an unset secret must FAIL CLOSED (the
# endpoint rejects every request) rather than silently accept unauthenticated calls. Compared with
# hmac.compare_digest, never logged.
INTERNAL_SERVICE_SECRET = (os.environ.get("INTERNAL_SERVICE_SECRET") or "").strip()

# Release-candidate hardening (this cycle): on a genuine Render deploy, a hardcoded/placeholder
# secret is no longer just a logged warning — it is either a hard startup failure (VERIFY_TOKEN,
# DASHBOARD_KEY, CRON_SECRET) or a fail-closed disabled endpoint (INTERNAL_SERVICE_SECRET), because
# by the time this ships to real customers "logged but running insecurely" is not good enough.
# Gated ENTIRELY behind Render's own auto-set `RENDER` env var (present on every Render service,
# never set locally/in tests, never set by the pytest suite) so local dev and CI are completely
# unaffected — this block is a strict no-op unless `RENDER` is set. NEVER logs/prints any actual
# secret value — only which named variable is still a known default/placeholder.
INTERNAL_OWNER_NOTIFY_DISABLED = False
if os.environ.get("RENDER"):
    # Task D (v1 completion cycle) — a real Render deploy where the Client Hub bridge modules
    # actually imported cleanly (_CLIENT_HUB_AVAILABLE True — tenant infrastructure IS genuinely
    # present in this deployment) but ENABLE_MULTI_TENANT is false/unset would silently run this
    # service in single-tenant-only mode: every webhook resolves tenant_id=None, every client
    # business's own WhatsApp traffic either never arrives (wrong phone_number_id for a Kilas-only
    # deploy) or gets treated as Kilas Works' own conversation — degrading the whole SaaS multi-
    # tenant product to "just the original single bot" with no error, no crash, nothing in the
    # dashboard to notice. This is not a security hole the way an insecure default secret is (a
    # human may have a genuine reason to run this service Kilas-Works-only for a while), so — same
    # as the INTERNAL_SERVICE_SECRET case below — this is a loud startup WARNING, not a hard
    # SystemExit: multi-tenant SaaS behavior degrading to single-tenant must never happen silently
    # in a real deployment, but it also must never block the service from starting for an operator
    # who deliberately wants single-tenant mode right now.
    if _CLIENT_HUB_AVAILABLE and not ENABLE_MULTI_TENANT:
        print(
            "PERINGATAN (multi-tenant mode): jalan di Render dan Client Hub bridge berhasil "
            "di-import (tenant infrastructure TERSEDIA) tapi ENABLE_MULTI_TENANT tidak diset ke "
            "'true' — service ini akan berjalan SINGLE-TENANT-ONLY (semua webhook diproses sebagai "
            "Kilas Works sendiri, tidak ada tenant klien yang diproses/dibalas) TANPA error apapun. "
            "Kalau ini bukan yang diinginkan (mis. ada tenant klien yang sudah aktif di Client Hub), "
            "set ENABLE_MULTI_TENANT=true di environment variable service ini."
        )
    _fatal_insecure_defaults = []
    if VERIFY_TOKEN == "kilasworks123":
        # The Meta webhook handshake (GET /webhook) literally cannot function without a real,
        # non-guessable VERIFY_TOKEN — there is no safe "disable and keep running" behavior for it,
        # so a real Render deploy still on the placeholder must not boot at all.
        _fatal_insecure_defaults.append("VERIFY_TOKEN")
    if DASHBOARD_KEY == "kilasworks-dashboard":
        # DASHBOARD_KEY gates /dashboard, /internal/build-info, and (via CRON_SECRET's fallback)
        # potentially the cron endpoints too — leaving it on a publicly-known default on a real
        # deploy exposes customer data behind a guessable key, so fail startup rather than run open.
        _fatal_insecure_defaults.append("DASHBOARD_KEY")
    if CRON_SECRET == "kilasworks-dashboard":  # only equals this when CRON_SECRET itself was unset
        _fatal_insecure_defaults.append("CRON_SECRET")
    if _fatal_insecure_defaults:
        print(
            "FATAL: refusing to start on Render with insecure DEFAULT/placeholder value(s) still "
            f"active for: {', '.join(_fatal_insecure_defaults)}. Set proper, unique environment "
            "variable(s) for these in Render's dashboard before deploying. (Actual secret values "
            "are never logged.)"
        )
        raise SystemExit(
            "Startup aborted: insecure default secret(s) detected on Render — see log above for "
            "which variable name(s). No secret values are ever printed."
        )
    if not INTERNAL_SERVICE_SECRET:
        # INTERNAL_SERVICE_SECRET has no hardcoded default to fall back on (unlike the three above),
        # and unlike VERIFY_TOKEN/DASHBOARD_KEY/CRON_SECRET this one endpoint is NOT required for the
        # bot's core webhook/dashboard functionality — so instead of taking the whole service down,
        # we fail closed on just this one door: /internal/owner-notify is disabled outright (every
        # request rejected, see the flag check inside the route below) rather than left running with
        # no real authentication.
        INTERNAL_OWNER_NOTIFY_DISABLED = True
        print(
            "SECURITY: running on Render with INTERNAL_SERVICE_SECRET unset/blank — the internal "
            "Client Hub -> bot notification endpoint (/internal/owner-notify) is now DISABLED and "
            "will reject ALL requests until this is set in Render's environment. This does not "
            "block startup because the endpoint is not required for core bot operation. (Actual "
            "secret values are never logged.)"
        )

# Connection string database Postgres (dari Supabase, dll). Kalau kosong, bot tetep jalan normal
# tapi history chat cuma kesimpen sementara di memori (ilang kalau server restart) — sama kayak
# sebelumnya. Isi env var ini di Render buat aktifin penyimpanan permanen.
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ==== VOICE NOTE / TRANSCRIPTION (additive, MASTER pre-launch update) ====
# Abstraksi provider transkripsi — JANGAN hardcode provider/model spesifik di fungsi manapun,
# semua baca dari sini. Credential HANYA lewat environment variable, gak pernah di-hardcode.
# Kalau OPENAI_API_KEY belum diisi di Render, fitur voice note otomatis "gagal jujur" (kasih tau
# customer/owner buat kirim ulang/ketik) — TIDAK PERNAH hallucinate isi transcript.
#
# BUG FIX (voice bugfix cycle) — `.strip()` WAJIB di sini. Beberapa panel env var (termasuk
# Render kalau isinya dicopy-paste dari tempat lain) gampang banget nyelipin newline/spasi di
# ujung value tanpa kelihatan di UI. Sebelum fix ini, `OPENAI_API_KEY = os.environ.get(...)` TANPA
# strip() bisa lolos truthy-check (`if not OPENAI_API_KEY`) padahal isinya cuma whitespace, ATAU
# sebaliknya value yang valid tapi ada trailing newline bikin header "Authorization: Bearer sk-...\n"
# jadi invalid di sisi provider — dua-duanya SAMA-SAMA berujung transcript gagal, tapi errornya beda
# kategori (not_configured vs transcription_failed). `.strip()` di titik baca env var ini nutup
# celah itu buat OPENAI_API_KEY & TRANSCRIPTION_PROVIDER/MODEL sekaligus.
OPENAI_API_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()
TRANSCRIPTION_PROVIDER = (os.environ.get("TRANSCRIPTION_PROVIDER") or "openai").strip().lower()
TRANSCRIPTION_MODEL = (os.environ.get("TRANSCRIPTION_MODEL") or "whisper-1").strip()

# Kategori error internal (item 10 laporan bugfix) — dipakai SUPAYA log Render selalu jelas alasan
# SEBENARNYA kenapa voice note gagal, walau pesan yang dikirim ke customer/owner tetap satu kalimat
# ramah yang sama ("belum kebaca dengan jelas..."). JANGAN PERNAH menyamarkan salah satu kategori
# ini jadi kelihatan kayak "audio kurang jelas" di LOG INTERNAL — cuma di pesan customer/owner-facing
# yang boleh digeneralisir.
VOICE_ERR_NO_MEDIA_ID = "NO_MEDIA_ID"
VOICE_ERR_MEDIA_DOWNLOAD_FAILED = "MEDIA_DOWNLOAD_FAILED"
VOICE_ERR_INVALID_ENCODING = "INVALID_MEDIA_ENCODING"
VOICE_ERR_EMPTY_AUDIO = "EMPTY_AUDIO"
VOICE_ERR_UNSUPPORTED_AUDIO = "UNSUPPORTED_AUDIO_TOO_LARGE"
VOICE_ERR_PROVIDER_NOT_CONFIGURED = "TRANSCRIPTION_PROVIDER_NOT_CONFIGURED"
VOICE_ERR_API_ERROR = "TRANSCRIPTION_API_ERROR"
# BUG FIX (voice production bug, cycle 3) — sebelumnya error billing/quota OpenAI (API key BENAR
# tapi project belum ada billing/credit, atau kena rate limit) ke-lempar jadi VOICE_ERR_API_ERROR
# generik. Sekarang dipisah biar log Render LANGSUNG kelihatan bedanya "credential salah" vs
# "credential benar tapi akun OpenAI-nya belum bisa dipakai" — dua hal ini butuh tindakan beda.
VOICE_ERR_BILLING_OR_QUOTA = "BILLING_OR_QUOTA_ERROR"
VOICE_ERR_PARSE_ERROR = "RESPONSE_PARSE_ERROR"
VOICE_ERR_AUDIO_UNCLEAR = "AUDIO_UNCLEAR"  # transkripsi sukses tapi hasilnya string kosong

# Feature flag per kapabilitas (bukan per-tenant hardcode "if business == 'Kilas Works'") — biar
# arsitektur ini reusable buat klien lain nanti (lihat TENANT_CONFIG di bawah). Default "true" buat
# Kilas Works sendiri karena sudah lulus test_voice_note.py (lihat MASTER update report), tapi tetap
# bisa dimatikan per-environment lewat env var tanpa ubah kode kalau ada masalah di production.
FEATURES = {
    "voice_note_customer": os.environ.get("FEATURE_VOICE_NOTE_CUSTOMER", "true").strip().lower() == "true",
    "voice_note_owner": os.environ.get("FEATURE_VOICE_NOTE_OWNER", "true").strip().lower() == "true",
}

# WhatsApp Cloud API sendiri sudah membatasi audio message maks ~16MB — guard ini tambahan lapis
# kedua di sisi kita sebelum dikirim ke provider transkripsi (hindari kirim file gede2 gak perlu).
MAX_AUDIO_BYTES = 16 * 1024 * 1024
SUPPORTED_AUDIO_MIME_TYPES = {
    "audio/ogg", "audio/opus", "audio/mpeg", "audio/mp3", "audio/mp4",
    "audio/amr", "audio/aac", "audio/webm", "audio/wav", "audio/x-wav",
}
_AUDIO_EXT_BY_MIME = {
    "audio/ogg": "ogg", "audio/opus": "ogg", "audio/mpeg": "mp3", "audio/mp3": "mp3",
    "audio/mp4": "mp4", "audio/amr": "amr", "audio/aac": "aac", "audio/webm": "webm",
    "audio/wav": "wav", "audio/x-wav": "wav",
}


def _audio_ext_from_mime(base_mime):
    return _AUDIO_EXT_BY_MIME.get((base_mime or "").strip().lower(), "ogg")


def _voice_debug(stage, **fields):
    """Log diagnostik SATU BARIS per tahap pipeline voice note, prefix "VOICE_DEBUG:" biar gampang
    di-grep dari Render log. SENGAJA gak pernah dikasih access_token/API key/raw audio bytes/URL
    media yang mengandung token — cuma metadata (panjang, status, MIME, nama exception, dst).
    Ditambahkan khusus buat nemuin root cause laporan "semua voice note gagal, fallback generik
    terus" — sebelum ini beberapa cabang error return LANGSUNG tanpa nge-print apapun sama sekali,
    jadi gak ada jejak sama sekali di log kalau gagalnya di tahap awal (misal media_id kosong)."""
    parts = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"VOICE_DEBUG: stage={stage} {parts}")


def transcribe_audio_whatsapp(media_id):
    """Download voice note dari WhatsApp Cloud API (pakai download_whatsapp_media() yang SAMA
    dipakai buat gambar — bukan jalur baru) lalu transcribe pakai TRANSCRIPTION_PROVIDER.

    Balikin (transcript: str atau None, error_reason: str atau None — salah satu konstanta
    VOICE_ERR_*). Kalau transcript None, CALLER WAJIB pakai pesan fallback jujur ("belum kebaca
    dengan jelas...") — JANGAN PERNAH mengarang isi transcript. error_reason SELALU di-log detail
    (lewat _voice_debug) di SETIAP titik return, termasuk yang sebelumnya silent (no_media_id,
    download_failed, not_configured, dst) — ini fix utama dari laporan bug "semua VN gagal tanpa
    jejak di log".

    Semua audio diproses di MEMORI (base64/bytes), TIDAK PERNAH ditulis ke file/disk, dan TIDAK
    PERNAH disimpan sebagai binary ke database — begitu fungsi ini selesai, bytes-nya otomatis
    kebuang (di-garbage-collect Python), jadi "cleanup temp audio" beres tanpa perlu file temp
    sama sekali."""
    if not media_id:
        _voice_debug("media_id_check", media_id_exists=False)
        return None, VOICE_ERR_NO_MEDIA_ID
    _voice_debug("media_id_check", media_id_exists=True)

    # NOTE: download_whatsapp_media() sudah nge-log stage granular sendiri ("media_metadata" lalu
    # "media_download") — baris di bawah ini cuma ringkasan hasil AKHIR dari kedua tahap itu, bukan
    # duplikat. Nama stage sengaja dibedain ("media_fetch_result") biar gak nimpa/kebingungan pas
    # di-grep sama dua stage granular di atas.
    b64_data, mime_type = download_whatsapp_media(media_id)
    if not b64_data:
        _voice_debug("media_fetch_result", ok=False, mime_type=mime_type)
        return None, VOICE_ERR_MEDIA_DOWNLOAD_FAILED
    _voice_debug("media_fetch_result", ok=True, mime_type=mime_type)

    try:
        audio_bytes = base64.b64decode(b64_data)
    except Exception as e:
        _voice_debug("decode_base64", success=False, exception_class=type(e).__name__)
        return None, VOICE_ERR_INVALID_ENCODING

    byte_length = len(audio_bytes)
    _voice_debug("decode_base64", success=True, byte_length=byte_length)

    if byte_length == 0:
        _voice_debug("size_check", result="empty_audio")
        return None, VOICE_ERR_EMPTY_AUDIO

    if byte_length > MAX_AUDIO_BYTES:
        _voice_debug("size_check", result="too_large", byte_length=byte_length, max_allowed=MAX_AUDIO_BYTES)
        return None, VOICE_ERR_UNSUPPORTED_AUDIO

    base_mime = (mime_type or "").split(";")[0].strip().lower()
    mime_recognized = bool(base_mime) and base_mime in SUPPORTED_AUDIO_MIME_TYPES
    _voice_debug("mime_check", mime_type=mime_type, base_mime=base_mime, recognized=mime_recognized)
    if base_mime and not mime_recognized:
        # Tetep dicoba (WhatsApp kadang ngirim variasi MIME yang provider transkripsi masih bisa
        # handle), tapi dicatat biar kelihatan kalau perlu nambahin ke whitelist di atas.
        print(f"[VOICE] MIME audio tidak dikenal di whitelist (tetap dicoba): {mime_type}")

    # .strip() LAGI di titik pakai (bukan cuma pas baca env var di atas) — sengaja defensif dobel:
    # kalau OPENAI_API_KEY di-override runtime (misal lewat test, atau env var ke-reload) jadi cuma
    # whitespace, header "Authorization: Bearer   \n" akan DITOLAK duluan oleh library `requests`
    # sendiri (InvalidHeader) sebelum sempat nyampe ke OpenAI — itu masuk kategori error API biasa,
    # BUKAN not_configured, padahal akar masalahnya sama (credential kosong). Cek di sini nutup itu.
    api_key = (OPENAI_API_KEY or "").strip()
    provider_configured = bool(api_key) and TRANSCRIPTION_PROVIDER == "openai"
    _voice_debug(
        "provider_check",
        provider=TRANSCRIPTION_PROVIDER, model=TRANSCRIPTION_MODEL,
        api_key_present=bool(api_key), configured=provider_configured,
    )
    if not provider_configured:
        # INI KEMUNGKINAN BESAR PENYEBAB "semua voice note gagal identik" di laporan bug — kalau
        # OPENAI_API_KEY belum keisi (atau ke-isi string kosong/whitespace doang) di Render, SEMUA
        # voice note tanpa terkecuali bakal berhenti persis di titik ini, TERLEPAS dari durasi/
        # kejelasan audio-nya — match persis sama gejala yang dilaporkan (4 detik/3 detik/2 detik
        # semua gagal sama). Baris VOICE_DEBUG di atas bakal nunjukin "api_key_present=False" kalau
        # ini benar penyebabnya.
        return None, VOICE_ERR_PROVIDER_NOT_CONFIGURED

    try:
        ext = _audio_ext_from_mime(base_mime)
        files = {"file": (f"voice.{ext}", audio_bytes, base_mime or "application/octet-stream")}
        data = {"model": TRANSCRIPTION_MODEL}  # SENGAJA gak set "language" — biar auto-detect
        # ID/English/campuran jalan alami (lihat item bahasa di MASTER update), bukan dipaksa "id".
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files, data=data, timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        err_resp = getattr(e, "response", None)
        status_code = getattr(err_resp, "status_code", None)
        # BUG FIX (voice production bug, cycle 3) — sebelumnya body error dari OpenAI dibuang begitu
        # aja (cuma exception class + status code yang ke-log). Body error OpenAI AMAN untuk di-log
        # (isinya pesan error dari OpenAI sendiri soal AKUN KITA, bukan secret/token kita) dan justru
        # ini yang paling nunjukin root cause asli: "invalid_api_key" vs "insufficient_quota" vs
        # "model_not_found" dst — tiga-tiganya SAMA-SAMA bikin transkripsi gagal identik dari sisi
        # WhatsApp (customer/owner cuma liat fallback generik), tapi tindakan perbaikannya beda total.
        openai_err_type, openai_err_code, openai_err_message = None, None, None
        if err_resp is not None:
            try:
                err_body = err_resp.json()
                openai_err_obj = (err_body or {}).get("error") or {}
                openai_err_type = openai_err_obj.get("type")
                openai_err_code = openai_err_obj.get("code")
                openai_err_message = (openai_err_obj.get("message") or "")[:200]
            except Exception:
                pass
        is_billing_or_quota = (
            status_code == 429
            or openai_err_type in ("insufficient_quota", "billing_not_active")
            or openai_err_code in ("insufficient_quota", "billing_hard_limit_reached")
        )
        _voice_debug(
            "transcription_request", success=False,
            exception_class=type(e).__name__, http_status=status_code,
            openai_error_type=openai_err_type, openai_error_code=openai_err_code,
        )
        print(
            f"[VOICE] Transcription API error ({TRANSCRIPTION_PROVIDER}/{TRANSCRIPTION_MODEL}): "
            f"{e} | openai_error_type={openai_err_type} openai_error_code={openai_err_code} "
            f"openai_error_message={openai_err_message}"
        )
        return None, (VOICE_ERR_BILLING_OR_QUOTA if is_billing_or_quota else VOICE_ERR_API_ERROR)

    try:
        result = resp.json()
        transcript = (result.get("text") or "").strip()
    except Exception as e:
        _voice_debug("response_parse", success=False, exception_class=type(e).__name__)
        return None, VOICE_ERR_PARSE_ERROR

    _voice_debug("transcription_request", success=True, transcript_char_length=len(transcript))

    if not transcript:
        _voice_debug("empty_transcript_check", result="audio_unclear")
        return None, VOICE_ERR_AUDIO_UNCLEAR
    return transcript, None


# ==== TENANT CONFIG (readiness, MASTER pre-launch update) ====
# Kilas Works masih SATU tenant/satu app.py — ini BUKAN multi-tenant database routing beneran,
# tapi lapisan konfigurasi supaya kode gak pernah nulis "if business == 'Kilas Works'" di manapun.
# PRICING_CONFIG/PAYMENT_CONFIG/FEATURES dsb tetap module-level (arsitektur existing gak diubah),
# TENANT_CONFIG cuma ngumpulin referensi ke semuanya di satu tempat + identitas bisnis, biar kalau
# nanti beneran ada klien ke-2, jelas field mana aja yang perlu di-parameterisasi per klien (tanpa
# perlu bongkar app.py dari nol). Lihat laporan MASTER update bagian "multi-tenant readiness".
TENANT_CONFIG = {
    "tenant_id": "kilas_works",
    "business_name": "Kilas Works",
    "owner_number_env": "OWNER_WHATSAPP_NUMBER",
    "features": FEATURES,
}


# ==== DATABASE (opsional, buat nyimpen history chat secara permanen) ====

def db_enabled():
    return bool(DATABASE_URL) and psycopg2 is not None


def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    """Bikin tabel 'messages' kalau belum ada. Dipanggil sekali pas server start."""
    if not db_enabled():
        print("DATABASE_URL belum diset — history chat cuma kesimpen sementara di memori.")
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                number TEXT NOT NULL,
                mode TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_number_mode ON messages (number, mode);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_profiles (
                number TEXT PRIMARY KEY,
                name TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        # Kilas Works' own persistent Human Takeover state. This is intentionally separate from
        # client-hub's tenant wa_conversation_state because the platform bot itself is not a
        # businesses row. CREATE IF NOT EXISTS keeps old production DBs backward-compatible.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS platform_wa_conversation_state (
                id SERIAL PRIMARY KEY,
                customer_phone TEXT NOT NULL UNIQUE,
                mode TEXT NOT NULL DEFAULT 'AI_ACTIVE',
                updated_by_user_id BIGINT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_platform_wa_state_mode ON platform_wa_conversation_state (mode);"
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_facts (
                id SERIAL PRIMARY KEY,
                number TEXT NOT NULL,
                fact TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_customer_facts_number ON customer_facts (number);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS followup_state (
                number TEXT PRIMARY KEY,
                last_customer_msg_at TIMESTAMPTZ,
                last_followup_at TIMESTAMPTZ,
                followup_count INTEGER NOT NULL DEFAULT 0,
                converted BOOLEAN NOT NULL DEFAULT FALSE
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY,
                number TEXT NOT NULL,
                name TEXT,
                business_name TEXT,
                meeting_date TEXT NOT NULL,
                meeting_time TEXT NOT NULL,
                tz TEXT NOT NULL DEFAULT 'Asia/Jakarta',
                need_summary TEXT,
                status TEXT NOT NULL DEFAULT 'scheduled',
                notes TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_appointments_number ON appointments (number);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments (meeting_date);")
        # Migration BACKWARD-COMPATIBLE (production hardening) — tabel appointments yang UDAH ADA
        # dari sebelumnya gak akan ke-apply ulang CREATE TABLE di atas, jadi kolom baru buat fitur
        # reminder meeting ditambah lewat ALTER TABLE ... ADD COLUMN IF NOT EXISTS. Row lama otomatis
        # dapet default FALSE (belum pernah dikirim reminder), gak ada data lama yang berubah/hilang.
        cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminder_24h_sent BOOLEAN NOT NULL DEFAULT FALSE;")
        cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminder_same_day_sent BOOLEAN NOT NULL DEFAULT FALSE;")
        conn.commit()
        cur.close()
        conn.close()
        print("Database siap — history chat bakal kesimpen permanen.")
    except Exception as e:
        print(f"Gagal konek/init database ({e}). History chat cuma kesimpen sementara di memori.")


def save_message_to_db(number, mode, role, content):
    """Simpen satu pesan (dari customer/owner ATAU balasan AI) ke database. Kalau DB gak
    kekonek/gak diset, diem-diem gak ngapa-ngapain (bot tetep jalan normal)."""
    if not db_enabled():
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (number, mode, role, content) VALUES (%s, %s, %s, %s)",
            (number, mode, role, content),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Gagal simpen pesan ke database ({e}).")


def load_recent_messages_from_db(number, mode, limit=20):
    """Ambil N pesan terakhir punya satu nomor dari database, buat isi ulang konteks chat
    AI pas server abis restart (jadi AI gak lupa obrolan sebelumnya)."""
    if not db_enabled():
        return []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT role, content FROM messages WHERE number = %s AND mode = %s "
            "ORDER BY id DESC LIMIT %s",
            (number, mode, limit),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        rows.reverse()
        return [{"role": r[0], "content": r[1]} for r in rows]
    except Exception as e:
        print(f"Gagal ambil history dari database ({e}).")
        return []


def load_all_conversations_from_db(mode):
    """Ambil SEMUA history per nomor (dikelompokkin), dipakai buat nampilin dashboard biar
    tetep kelihatan lengkap walau server abis restart."""
    if not db_enabled():
        return {}
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT number, role, content, created_at FROM messages WHERE mode = %s ORDER BY id ASC",
            (mode,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        grouped = {}
        for number, role, content, created_at in rows:
            grouped.setdefault(number, []).append(
                {"role": role, "content": content, "created_at": created_at}
            )
        return grouped
    except Exception as e:
        print(f"Gagal ambil semua history dari database ({e}).")
        return {}


def save_customer_name_to_db(number, name):
    """Simpen/update nama customer secara permanen. Kalau DB gak aktif, diem-diem gak ngapa-ngapain
    (nama tetep kesimpen sementara di cache in-memory `customer_names`)."""
    if not db_enabled():
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO customer_profiles (number, name) VALUES (%s, %s)
            ON CONFLICT (number) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()
            """,
            (number, name),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Gagal simpen nama customer ke database ({e}).")


def load_all_customer_names_from_db():
    """Ambil semua nama customer yang udah kesimpen, buat dipakai isi ulang cache pas server abis
    restart, dan buat disisipin ke konteks owner."""
    if not db_enabled():
        return {}
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT number, name FROM customer_profiles")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {number: name for number, name in rows}
    except Exception as e:
        print(f"Gagal ambil nama customer dari database ({e}).")
        return {}


def save_customer_fact_to_db(number, fact):
    """Simpen satu 'fakta yang udah disepakati owner' buat customer tertentu (misal harga nego,
    keputusan lain) — permanen di DB, biar SELALU keinget & konsisten walau server restart, dan
    gak cuma ngandelin AI 'inget sendiri' dari histori chat freeform (yang kadang keliru)."""
    if not db_enabled():
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO customer_facts (number, fact) VALUES (%s, %s)", (number, fact))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Gagal simpen fakta customer ke database ({e}).")


def load_all_customer_facts_from_db():
    """Ambil semua fakta yang udah disepakati per customer, dikelompokkin per nomor, buat isi
    ulang cache in-memory pas server abis restart."""
    if not db_enabled():
        return {}
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT number, fact FROM customer_facts ORDER BY id ASC")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        grouped = {}
        for number, fact in rows:
            grouped.setdefault(number, []).append(fact)
        return grouped
    except Exception as e:
        print(f"Gagal ambil fakta customer dari database ({e}).")
        return {}


def add_agreed_fact(number, fact):
    """Catet satu keputusan/kesepakatan yang UDAH FIX buat customer tertentu — dipanggil tiap kali
    owner beneran forward jawaban (baik lewat mode diskusi atau perintah langsung) ke customer.
    Ini disisipin ke system prompt customer sebagai daftar fakta yang GAK BOLEH dikontradiksi atau
    ditanyakan ulang, biar bot gak pernah lagi salah bilang 'belum dapet konfirmasi owner' padahal
    udah pernah dijawab."""
    agreed_facts.setdefault(number, [])
    agreed_facts[number].append(fact)
    agreed_facts[number] = agreed_facts[number][-15:]  # cukup 15 fakta terakhir per customer
    save_customer_fact_to_db(number, fact)


# ==== FOLLOW-UP OTOMATIS (chat lagi ke customer yang diem >8 jam) ====
# Maksimal berapa kali follow-up otomatis dikirim per customer sebelum berhenti (biar gak keliatan spam
# kalau customer emang udah gak minat/gak balas berkali-kali).
MAX_AUTO_FOLLOWUPS = 2
FOLLOWUP_GAP_HOURS = 8

# PRODUCTION MICRO-FIX — Meta Cloud API error 131047 ("Re-engagement message — more than 24 hours
# have passed since the customer last replied"): WhatsApp's 24-hour customer-service window is
# measured from the CUSTOMER's last inbound message, not from our last outbound message. A normal
# free-text follow-up sent outside that window gets rejected by Meta. 23 (not 24) hours is used as
# a safety buffer against clock drift/cron timing — never attempt a free-text follow-up this close
# to or past the boundary. This does NOT send a WhatsApp template message as a fallback — outside
# the window, the follow-up is simply skipped entirely for that customer this cycle.
WHATSAPP_24H_SAFETY_HOURS = 23


def _utcnow():
    return datetime.now(timezone.utc)


def save_followup_state_to_db(number, state):
    """Simpen/update state follow-up satu customer ke DB (upsert)."""
    if not db_enabled():
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO followup_state (number, last_customer_msg_at, last_followup_at, followup_count, converted)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (number) DO UPDATE SET
                last_customer_msg_at = EXCLUDED.last_customer_msg_at,
                last_followup_at = EXCLUDED.last_followup_at,
                followup_count = EXCLUDED.followup_count,
                converted = EXCLUDED.converted
            """,
            (
                number,
                state.get("last_customer_msg_at"),
                state.get("last_followup_at"),
                state.get("followup_count", 0),
                state.get("converted", False),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Gagal simpen followup_state ke database ({e}).")


def load_all_followup_state_from_db():
    """Ambil semua state follow-up dari DB, buat isi ulang cache in-memory pas server abis restart."""
    if not db_enabled():
        return {}
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT number, last_customer_msg_at, last_followup_at, followup_count, converted FROM followup_state")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = {}
        for number, last_customer_msg_at, last_followup_at, followup_count, converted in rows:
            result[number] = {
                "last_customer_msg_at": last_customer_msg_at,
                "last_followup_at": last_followup_at,
                "followup_count": followup_count,
                "converted": converted,
            }
        return result
    except Exception as e:
        print(f"Gagal ambil followup_state dari database ({e}).")
        return {}


def mark_customer_activity(number):
    """Dipanggil tiap kali customer beneran ngirim pesan — reset hitungan follow-up (karena mereka
    udah balas lagi, gak 'diem' lagi) & update kapan terakhir mereka aktif."""
    state = followup_state.setdefault(number, {"last_customer_msg_at": None, "last_followup_at": None, "followup_count": 0, "converted": False})
    state["last_customer_msg_at"] = _utcnow()
    state["followup_count"] = 0
    save_followup_state_to_db(number, state)


def mark_customer_converted(number):
    """Stop follow-up otomatis PERMANEN buat nomor ini. Dipanggil di DUA skenario: (1) customer
    keliatan udah bayar/booking ([SUDAH_BAYAR]/[LEADS_PANAS] closing) — sengaja pakai kolom
    'converted' yang sama (bukan bikin kolom baru) buat kasus (2) customer eksplisit minta gak
    usah di-follow-up/dihubungi lagi ([STOP_FOLLOWUP]) — sama-sama artinya 'jangan follow-up lagi',
    cuma alasannya beda, jadi gak perlu migration kolom baru buat ini."""
    state = followup_state.setdefault(number, {"last_customer_msg_at": None, "last_followup_at": None, "followup_count": 0, "converted": False})
    state["converted"] = True
    save_followup_state_to_db(number, state)


def _has_active_meeting_or_payment_process(number):
    """(production hardening — follow-up guard) True kalau customer ini lagi di tengah proses yang
    JANGAN diganggu follow-up sales generik: masih nunggu availability owner / lagi ditawarin pilihan
    jam, ATAU lagi proses pembayaran (baru punya intent, nunggu instruksi transfer, ngirim bukti,
    udah DP/lunas). Appointment yang UDAH CONFIRMED gak perlu di-skip di sini juga — reminder
    meeting-nya sendiri dihandle terpisah oleh send_appointment_reminders()."""
    req = meeting_requests.get(number)
    if req and req.get("status") in (
        MEETING_STATE_WAITING_PREFERENCE, MEETING_STATE_PENDING_OWNER_CONFIRMATION, MEETING_STATE_SLOTS_OFFERED,
    ):
        return True
    pay = payment_state.get(number)
    if pay and pay.get("status") in (
        PAYMENT_STATUS_INTENT, PAYMENT_STATUS_WAITING, PAYMENT_STATUS_PENDING_VERIFICATION,
        PAYMENT_STATUS_PARTIALLY_PAID, PAYMENT_STATUS_PAID,
    ):
        return True
    return False


def get_customers_due_for_followup(hours=FOLLOWUP_GAP_HOURS, max_count=MAX_AUTO_FOLLOWUPS):
    """Cari customer yang: (a) belum ditandain converted/udah closing, (b) followup_count masih di
    bawah batas, (c) terakhir chat >= `hours` jam lalu, (d) belum di-follow-up dalam `hours` jam
    terakhir (biar gak dobel kirim kalau endpoint /cron/followups kepanggil lebih sering dari
    interval-nya), (e) TIDAK lagi di tengah proses booking meeting (nunggu owner/pilih slot) atau
    proses pembayaran (production hardening — follow-up jangan spam customer yang lagi di alur
    ini), (f) MASIH DI DALAM jendela customer-service 24 jam WhatsApp dihitung dari pesan TERAKHIR
    customer (production micro-fix — Meta Cloud API error 131047: follow-up teks biasa yang
    dikirim di luar jendela ini DITOLAK Meta; >= WHATSAPP_24H_SAFETY_HOURS (23 jam) dari pesan
    terakhir customer -> SKIP total, TIDAK fallback ke template atau channel lain)."""
    now = _utcnow()
    due = []
    for number, state in followup_state.items():
        if state.get("converted"):
            continue
        if state.get("followup_count", 0) >= max_count:
            continue
        last_msg = state.get("last_customer_msg_at")
        if not last_msg:
            continue
        if now - last_msg < timedelta(hours=hours):
            continue
        if now - last_msg >= timedelta(hours=WHATSAPP_24H_SAFETY_HOURS):
            continue  # di luar jendela 24 jam WhatsApp — jangan kirim follow-up teks biasa
        last_followup = state.get("last_followup_at")
        if last_followup and (now - last_followup < timedelta(hours=hours)):
            continue
        if _has_active_meeting_or_payment_process(number):
            continue
        due.append(number)
    return due


def record_followup_sent(number):
    state = followup_state.setdefault(number, {"last_customer_msg_at": None, "last_followup_at": None, "followup_count": 0, "converted": False})
    state["last_followup_at"] = _utcnow()
    state["followup_count"] = state.get("followup_count", 0) + 1
    save_followup_state_to_db(number, state)


# ============================================================
# APPOINTMENT / JADWAL PERTEMUAN CUSTOMER — bukan integrasi calendar beneran (Google Calendar dll),
# tapi sumber kebenaran ketersediaan yang KONSISTEN & anti-double-booking: slot jam TETAP per hari
# (bisa diubah di DEFAULT_MEETING_SLOT_TIMES), dicek terhadap appointment yang UDAH ke-booking di
# tabel `appointments` sebelum nawarin/confirm ke customer. Tanggal relatif ("besok", "Jumat") gak
# pernah dihitung sendiri sama AI — Python yang compute tanggal aslinya (WIB) & suntik ke system
# prompt tiap request, AI tinggal COCOKIN ke situ, bukan ngitung sendiri.
# ============================================================

JAKARTA_TZ = timezone(timedelta(hours=7))  # Asia/Jakarta, UTC+7 tetap (gak ada DST)

# Jam meeting yang ditawarin per hari (WIB). Ganti di sini kalau jam kerja owner berubah.
DEFAULT_MEETING_SLOT_TIMES = ["10:00", "13:00", "15:00", "17:00"]
# Hari libur meeting (Python weekday(): Senin=0 ... Minggu=6). Default: Minggu libur.
MEETING_DAYS_OFF = {6}

DAY_NAME_ID = {0: "Senin", 1: "Selasa", 2: "Rabu", 3: "Kamis", 4: "Jumat", 5: "Sabtu", 6: "Minggu"}
MONTH_NAME_ID = {
    1: "Januari", 2: "Februari", 3: "Maret", 4: "April", 5: "Mei", 6: "Juni",
    7: "Juli", 8: "Agustus", 9: "September", 10: "Oktober", 11: "November", 12: "Desember",
}

appointments = {}  # id -> {id, number, name, business_name, meeting_date, meeting_time, tz, need_summary, status, notes}
_appointment_id_counter = 0


def now_wib():
    return datetime.now(JAKARTA_TZ)


def format_date_id(d):
    """d = objek date/datetime. Return 'Senin, 24 Agustus 2026'."""
    return f"{DAY_NAME_ID[d.weekday()]}, {d.day} {MONTH_NAME_ID[d.month]} {d.year}"


def is_valid_date_str(date_str):
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def parse_tag_kv(raw):
    """Parse isi tag internal format 'key=val|key2=val2' jadi dict. Dipakai buat tag booking yang
    isinya lebih dari satu field (BOOK_MEETING, RESCHEDULE_MEETING)."""
    result = {}
    for part in (raw or "").split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip().lower()] = v.strip()
    return result


def _next_appointment_id():
    global _appointment_id_counter
    _appointment_id_counter += 1
    return _appointment_id_counter


def save_appointment_to_db(appt):
    if not db_enabled():
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO appointments (id, number, name, business_name, meeting_date, meeting_time, tz, need_summary, status, notes, reminder_24h_sent, reminder_same_day_sent)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                number = EXCLUDED.number, name = EXCLUDED.name, business_name = EXCLUDED.business_name,
                meeting_date = EXCLUDED.meeting_date, meeting_time = EXCLUDED.meeting_time, tz = EXCLUDED.tz,
                need_summary = EXCLUDED.need_summary, status = EXCLUDED.status, notes = EXCLUDED.notes,
                reminder_24h_sent = EXCLUDED.reminder_24h_sent, reminder_same_day_sent = EXCLUDED.reminder_same_day_sent
            """,
            (
                appt["id"], appt["number"], appt.get("name"), appt.get("business_name"),
                appt["meeting_date"], appt["meeting_time"], appt.get("tz", "Asia/Jakarta"),
                appt.get("need_summary"), appt.get("status", "scheduled"), appt.get("notes"),
                appt.get("reminder_24h_sent", False), appt.get("reminder_same_day_sent", False),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Gagal simpen appointment ke database ({e}).")


def load_all_appointments_from_db():
    if not db_enabled():
        return {}
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, number, name, business_name, meeting_date, meeting_time, tz, need_summary, status, notes, reminder_24h_sent, reminder_same_day_sent FROM appointments"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        result = {}
        for (id_, number, name, business_name, meeting_date, meeting_time, tz, need_summary, status, notes, reminder_24h_sent, reminder_same_day_sent) in rows:
            result[id_] = {
                "id": id_, "number": number, "name": name, "business_name": business_name,
                "meeting_date": meeting_date, "meeting_time": meeting_time, "tz": tz,
                "need_summary": need_summary, "status": status, "notes": notes,
                "reminder_24h_sent": bool(reminder_24h_sent), "reminder_same_day_sent": bool(reminder_same_day_sent),
            }
        return result
    except Exception as e:
        print(f"Gagal ambil appointments dari database ({e}).")
        return {}


def get_booked_times_for_date(date_str):
    """Semua jam yang UDAH ke-booking (status masih 'scheduled') di tanggal itu — dipakai buat
    ngecek availability, JANGAN PERNAH nebak/ngarang ini dari history chat."""
    return {
        a["meeting_time"] for a in appointments.values()
        if a.get("meeting_date") == date_str and a.get("status") == "scheduled"
    }


def get_available_slots_for_date(date_str):
    """List jam yang MASIH KOSONG di tanggal itu. Return [] kalau tanggal invalid atau hari libur."""
    if not is_valid_date_str(date_str):
        return []
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    if d.weekday() in MEETING_DAYS_OFF:
        return []
    booked = get_booked_times_for_date(date_str)
    return [t for t in DEFAULT_MEETING_SLOT_TIMES if t not in booked]


def build_weekly_availability_text(days_ahead=7):
    """Bikin blok teks ketersediaan 7 hari ke depan (computed di Python, BUKAN ditebak AI) buat
    disuntik ke system prompt customer — ini SUMBER KEBENARAN satu-satunya soal jam kosong."""
    today = now_wib().date()
    lines = []
    for i in range(days_ahead):
        d = today + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        label = format_date_id(d)
        if d.weekday() in MEETING_DAYS_OFF:
            lines.append(f"- {date_str} ({label}): TUTUP, gak terima meeting hari ini")
        else:
            slots = get_available_slots_for_date(date_str)
            if slots:
                lines.append(f"- {date_str} ({label}): kosong jam {', '.join(slots)} WIB")
            else:
                lines.append(f"- {date_str} ({label}): SEMUA SLOT PENUH")
    return "\n".join(lines)


def create_appointment(number, name, business_name, date_str, time_str, need_summary):
    aid = _next_appointment_id()
    appt = {
        "id": aid, "number": number, "name": name or customer_names.get(number, ""),
        "business_name": business_name, "meeting_date": date_str, "meeting_time": time_str,
        "tz": "Asia/Jakarta", "need_summary": need_summary, "status": "scheduled", "notes": None,
        "reminder_24h_sent": False, "reminder_same_day_sent": False,
    }
    appointments[aid] = appt
    save_appointment_to_db(appt)
    return aid


def get_latest_scheduled_appointment_for(number):
    candidates = [a for a in appointments.values() if a.get("number") == number and a.get("status") == "scheduled"]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a["meeting_date"], a["meeting_time"]))
    return candidates[-1]


def update_appointment_status(appt_id, status):
    appt = appointments.get(appt_id)
    if not appt:
        return
    appt["status"] = status
    save_appointment_to_db(appt)


def update_appointment_reschedule(appt_id, new_date, new_time):
    appt = appointments.get(appt_id)
    if not appt:
        return
    old_note = f"(sebelumnya {appt['meeting_date']} {appt['meeting_time']})"
    appt["notes"] = f"{appt.get('notes') or ''} {old_note}".strip()
    appt["meeting_date"] = new_date
    appt["meeting_time"] = new_time
    appt["status"] = "scheduled"
    # Reset flag reminder — jadwal berubah, reminder lama (buat tanggal/jam sebelumnya) gak relevan
    # lagi & jangan sampai reminder BARU buat jadwal hasil reschedule ini malah keanggep "udah pernah
    # dikirim" gara-gara flag lama masih True.
    appt["reminder_24h_sent"] = False
    appt["reminder_same_day_sent"] = False
    save_appointment_to_db(appt)


def try_book_meeting(customer_number, name, business_name, date_str, time_str, need_summary):
    """WAJIB re-cek availability di sini (bukan cuma percaya tag dari AI) — biar gak ada double
    booking meski AI 'yakin' slotnya kosong pas nyusun balasan (data bisa berubah antar pesan).
    Return (success, customer_facing_text, owner_notify_text_atau_None)."""
    if not is_valid_date_str(date_str) or time_str not in DEFAULT_MEETING_SLOT_TIMES:
        return False, "Waduh ada kendala pas mau jadwalin, boleh sebutin lagi tanggal & jamnya kak?", None

    available = get_available_slots_for_date(date_str)
    if time_str not in available:
        if available:
            alt = ", ".join(available[:3])
            msg = f"Waduh, jam {time_str} ternyata baru aja keisi kak. Yang masih kosong: {alt} WIB, mau pilih yang mana?"
        else:
            msg = f"Waduh, tanggal itu udah penuh semua kak. Mau coba tanggal lain?"
        return False, msg, None

    create_appointment(customer_number, name, business_name, date_str, time_str, need_summary)
    label = format_date_id(datetime.strptime(date_str, "%Y-%m-%d").date())
    confirm = f"Siap Kak, sudah dijadwalkan untuk {label} jam {time_str} WIB. Nanti owner akan ngobrol langsung dengan Kakak untuk bahas kebutuhannya ya."
    display_name = name or customer_names.get(customer_number, "Customer")
    owner_notify = (
        f"Meeting baru: {display_name} — {business_name or '(bisnis belum disebut)'}, "
        f"{label} jam {time_str} WIB. Kebutuhan: {need_summary or '-'}."
    )
    return True, confirm, owner_notify


def try_reschedule_meeting(customer_number, date_str, time_str):
    appt = get_latest_scheduled_appointment_for(customer_number)
    if not appt:
        return False, "Belum nemu jadwal meeting Kakak sebelumnya nih, mau dijadwalin baru aja?", None
    if not is_valid_date_str(date_str) or time_str not in DEFAULT_MEETING_SLOT_TIMES:
        return False, "Boleh sebutin lagi tanggal & jam barunya kak?", None

    available = get_available_slots_for_date(date_str)
    if time_str not in available:
        if available:
            alt = ", ".join(available[:3])
            msg = f"Jam {time_str} udah keisi kak. Yang masih kosong: {alt} WIB, pilih yang mana?"
        else:
            msg = "Tanggal itu udah penuh semua kak. Mau coba tanggal lain?"
        return False, msg, None

    old_label = f"{format_date_id(datetime.strptime(appt['meeting_date'], '%Y-%m-%d').date())} jam {appt['meeting_time']}"
    update_appointment_reschedule(appt["id"], date_str, time_str)
    new_label = format_date_id(datetime.strptime(date_str, "%Y-%m-%d").date())
    confirm = f"Oke Kak, jadwalnya dipindah ke {new_label} jam {time_str} WIB ya."
    display_name = appt.get("name") or customer_names.get(customer_number, "Customer")
    owner_notify = f"Reschedule meeting: {display_name} — pindah dari {old_label} ke {new_label} jam {time_str} WIB."
    return True, confirm, owner_notify


def try_cancel_meeting(customer_number):
    appt = get_latest_scheduled_appointment_for(customer_number)
    if not appt:
        return False, "Kakak belum ada jadwal meeting yang aktif nih.", None
    update_appointment_status(appt["id"], "cancelled")
    label = f"{format_date_id(datetime.strptime(appt['meeting_date'], '%Y-%m-%d').date())} jam {appt['meeting_time']}"
    confirm = "Oke Kak, jadwal meetingnya dibatalin ya. Kalau nanti mau jadwal ulang, tinggal bilang aja."
    display_name = appt.get("name") or customer_names.get(customer_number, "Customer")
    owner_notify = f"Meeting dibatalkan: {display_name} — jadwal {label} WIB batal."
    return True, confirm, owner_notify


# ============================================================
# FLOW MEETING BARU (production hardening) — appointment CUMA boleh CONFIRMED kalau slotnya beneran
# dikasih owner secara eksplisit (bukan grid otomatis yang dulu ditawarin langsung ke customer tanpa
# owner pernah beneran bilang available). Lihat meeting_requests di atas buat state negosiasinya.
# ============================================================

# Nama hari (Indonesia, informal termasuk) -> Python weekday() (Senin=0..Minggu=6). Dipakai buat
# resolve preferensi hari customer YANG BEBAS ("sabtu", "hari minggu") jadi tanggal PASTI.
DAY_NAME_TO_WEEKDAY = {
    "senin": 0, "selasa": 1, "rabu": 2, "kamis": 3, "jumat": 4, "jum'at": 4, "jum at": 4,
    "sabtu": 5, "minggu": 6,
}


def resolve_day_text_to_date(raw_text):
    """Coba resolve teks hari BEBAS dari customer ('sabtu', 'besok', 'hari ini', '2026-08-29') jadi
    tanggal YYYY-MM-DD PASTI (dihitung Python, BUKAN ditebak AI). Return None kalau gak bisa
    diresolve dengan yakin — dalam kasus itu teks ASLI customer yang dipakai apa adanya buat notify
    owner (biar owner yang paham konteksnya, JANGAN sistem yang nebak-nebak salah)."""
    if not raw_text:
        return None
    text = raw_text.strip().lower()
    if is_valid_date_str(text):
        return text
    today = now_wib().date()
    if "lusa" in text:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")
    if "besok" in text:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if "hari ini" in text or "hr ini" in text or text == "ini":
        return today.strftime("%Y-%m-%d")
    for name, weekday in DAY_NAME_TO_WEEKDAY.items():
        if name in text:
            days_ahead = (weekday - today.weekday()) % 7
            days_ahead = days_ahead or 7  # nyebut hari yang sama kayak hari ini -> anggap minggu depan
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    return None


def is_office_closed_on(date_str):
    """True kalau tanggal ini hari LIBUR KANTOR/OFFLINE (business_hours) — dipakai buat NGEGUARD biar
    bot GAK OTOMATIS nawarin ketemu LANGSUNG (offline) di hari ini. PENTING: ini beda konsep sama
    meeting_availability owner — kantor tutup BUKAN berarti owner otomatis gak bisa ONLINE meeting hari
    itu juga (online tetap boleh ditanyain ke owner), dan owner available BUKAN berarti kantor buka."""
    if not is_valid_date_str(date_str):
        return False
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    return d.weekday() in MEETING_DAYS_OFF


def meeting_mode_label(req):
    """(live demo, additive) Label mode meeting yang konsisten dipakai di semua kalimat konfirmasi/
    notify — "live demo AI Admin" kalau req['purpose']=='demo' (lihat SOAL DEMO AI ADMIN di
    SYSTEM_PROMPT), selain itu perilaku LAMA gak berubah ("ketemu langsung" / "online meeting")."""
    if (req or {}).get("purpose") == "demo":
        return "live demo AI Admin"
    return "ketemu langsung" if (req or {}).get("mode") == "offline" else "online meeting"


def try_book_meeting_from_owner_slots(customer_number, time_str):
    """Konfirmasi FINAL appointment dari slot yang SUDAH dikasih owner secara eksplisit (bukan grid
    otomatis) — tetap RE-CEK double-booking terhadap appointments existing sebelum commit, sama
    prinsipnya kayak try_book_meeting. Return (success, customer_facing_text, owner_notify_atau_None)."""
    req = meeting_requests.get(customer_number)
    if not req or req.get("status") != MEETING_STATE_SLOTS_OFFERED:
        return False, "Waduh, boleh diulang lagi kak maunya jam berapa?", None

    time_str = (time_str or "").strip()
    offered = req.get("offered_slots") or []
    if time_str not in offered:
        alt = ", ".join(t.replace(":", ".") for t in offered) if offered else "-"
        return False, f"Waduh, kayaknya bukan salah satu pilihan tadi kak. Yang tersedia: {alt} WIB, mau pilih yang mana?", None

    date_str = req.get("resolved_date")
    # Kalau tanggalnya beneran udah keresolve (YYYY-MM-DD), re-cek beneran belum kepakai duluan
    # (race condition sangat jarang tapi tetap dijaga) sebelum commit.
    if date_str and time_str in get_booked_times_for_date(date_str):
        remaining = [t for t in offered if t not in get_booked_times_for_date(date_str)]
        if remaining:
            alt = ", ".join(t.replace(":", ".") for t in remaining)
            return False, f"Waduh, jam {time_str} ternyata baru aja keisi kak. Yang masih kosong: {alt} WIB, mau pilih yang mana?", None
        return False, "Waduh, semua pilihan jam tadi udah keisi kak. Aku cek availability baru dulu ya ke owner.", None

    display_name = req.get("name") or customer_names.get(customer_number, "Customer")
    business_name = req.get("business_name")
    need_summary = req.get("need_summary")
    date_for_record = date_str or req.get("day_text") or req.get("day_display") or "(tanggal belum pasti)"

    create_appointment(customer_number, display_name, business_name, date_for_record, time_str, need_summary)

    label = format_date_id(datetime.strptime(date_str, "%Y-%m-%d").date()) if date_str else (req.get("day_display") or req.get("day_text"))
    mode_label = meeting_mode_label(req)
    confirm = f"Siap Kak, sudah dijadwalkan {mode_label} untuk {label} jam {time_str} WIB. Nanti owner akan ngobrol langsung dengan Kakak untuk bahas kebutuhannya ya."
    owner_notify = f"Meeting CONFIRMED: {display_name} — {mode_label}, {label} jam {time_str} WIB. Kebutuhan: {need_summary or '-'}."

    meeting_requests.pop(customer_number, None)
    return True, confirm, owner_notify


def try_confirm_meeting_direct(customer_number, time_str):
    """(bug fix — owner availability flow) Dipakai KHUSUS pas customer UDAH nyebut sendiri jam exact
    yang dia mau di request awal (req['requested_time']) DAN owner baru aja confirm secara GENERIK
    ('bisa'/'available'/'iya'/'oke' — dideteksi deterministik, lihat GENERIC_AVAILABILITY_CONFIRM_
    PATTERN di webhook) TANPA nyebut jam lain. Beda dari try_book_meeting_from_owner_slots yang
    nunggu customer MILIH dari daftar offered_slots — di sini customer-nya sendiri yang udah minta
    jam ini duluan, jadi begitu owner bilang 'bisa' udah CUKUP buat langsung CONFIRMED, gak perlu
    muter nawarin balik & nunggu customer confirm ulang. Tetap re-cek double-booking dulu (kalau
    tanggalnya udah keresolve pasti) biar gak ada bentrok jadwal. Return (success, customer_facing_
    text_atau_None, owner_notify_text_atau_None)."""
    req = meeting_requests.get(customer_number)
    if not req:
        return False, None, None

    date_str = req.get("resolved_date")
    if date_str and time_str in get_booked_times_for_date(date_str):
        return False, None, None

    display_name = req.get("name") or customer_names.get(customer_number, "Customer")
    business_name = req.get("business_name")
    need_summary = req.get("need_summary")
    date_for_record = date_str or req.get("day_text") or req.get("day_display") or "(tanggal belum pasti)"

    create_appointment(customer_number, display_name, business_name, date_for_record, time_str, need_summary)

    label = (
        format_date_id(datetime.strptime(date_str, "%Y-%m-%d").date())
        if date_str else (req.get("day_display") or req.get("day_text"))
    )
    mode_label = meeting_mode_label(req)
    time_label = time_str.replace(":", ".")
    short_name = short_display_name(display_name)
    confirm = f"Siap Kak {short_name}, {mode_label} {label} pukul {time_label} WIB sudah dikonfirmasi ya."
    owner_notify = f"Meeting {short_name} berhasil dikonfirmasi: {label} pukul {time_label} WIB."

    meeting_requests.pop(customer_number, None)
    return True, confirm, owner_notify


# ============================================================
# MEETING REMINDER OTOMATIS (production hardening) — pakai appointment DB EXISTING, TIDAK bikin
# tabel baru. Dipanggil dari endpoint cron yang SAMA dengan follow-up (/cron/followups), jadi TIDAK
# perlu setup scheduler eksternal baru — cukup 1 external cron (cron-job.org / Render Cron Job)
# yang sudah/akan disetup buat follow-up, otomatis nge-cover reminder ini juga.
#
# ATURAN META/WHATSAPP YANG DIHORMATI DI SINI: pesan business-initiated (bukan balesan langsung ke
# customer) cuma boleh dikirim bebas TANPA approved template kalau masih dalam 24 JAM sejak pesan
# TERAKHIR dari customer ("customer service window"). Di luar itu, WhatsApp akan menolak/gagal kirim
# pesan teks bebas — WAJIB pakai Message Template yang sudah di-approve Meta. Karena app.py ini
# belum punya template ter-approve buat reminder, kalau window udah lewat, reminder KE CUSTOMER
# SENGAJA TIDAK dikirim (biar gak diam-diam gagal/ditolak Meta) — yang dikirim cuma notifikasi ke
# OWNER supaya bisa follow up manual atau setup template resmi nanti.
# ============================================================

SAME_DAY_REMINDER_HOURS_BEFORE = 3  # kirim reminder hari-H kalau meeting tinggal <= segini jam lagi


def _customer_within_service_window(number, hours=24):
    """True kalau customer ini masih dalam window 24 jam sejak pesan terakhirnya (jadi pesan bebas
    ke dia AMAN dikirim tanpa approved template). Pakai data followup_state yang emang udah nyimpen
    last_customer_msg_at buat keperluan lain (follow-up) — dipakai ulang di sini, bukan data baru."""
    state = followup_state.get(number)
    if not state or not state.get("last_customer_msg_at"):
        return False
    return (_utcnow() - state["last_customer_msg_at"]) < timedelta(hours=hours)


def _send_single_appointment_reminder(appt, label):
    """Kirim SATU reminder (H-1 atau hari-H) buat satu appointment. Return True kalau reminder ini
    boleh ditandain 'selesai diproses' (jangan di-retry cron berikutnya), False kalau harus dicoba
    lagi nanti (misal gagal kirim ke owner karena error jaringan sesaat)."""
    number = appt["number"]
    display_name = appt.get("name") or customer_names.get(number, "Customer")
    date_label = format_date_id(datetime.strptime(appt["meeting_date"], "%Y-%m-%d").date())
    time_str = appt["meeting_time"]
    when_word = "besok" if label == "H-1" else "hari ini"

    within_window = _customer_within_service_window(number)
    customer_sent_ok = None  # None = sengaja gak dicoba (di luar window)
    if within_window:
        customer_text = f"Halo Kak {display_name}, mengingatkan jadwal diskusi kita {when_word} pukul {time_str} WIB ya."
        customer_sent_ok, _err = send_whatsapp_message(number, customer_text)

    owner_note = f"Reminder ({label}): meeting dengan {display_name} {when_word} ({date_label}) pukul {time_str} WIB."
    if not within_window:
        owner_note += (
            " CATATAN: window 24 jam WhatsApp customer ini udah lewat, jadi reminder OTOMATIS TIDAK "
            "dikirim ke customer (biar gak ditolak Meta) — tolong follow up manual atau siapkan "
            "approved message template kalau mau reminder otomatis tetap sampai ke customer."
        )
    elif customer_sent_ok is False:
        owner_note += " CATATAN: pengiriman reminder otomatis ke customer GAGAL, tolong cek/kirim manual."

    owner_sent_ok = True
    if OWNER_WHATSAPP_NUMBER:
        owner_sent_ok, _oerr = send_whatsapp_message(OWNER_WHATSAPP_NUMBER, owner_note)

    if within_window:
        return bool(customer_sent_ok) and bool(owner_sent_ok)
    return bool(owner_sent_ok)


def send_appointment_reminders():
    """Cek semua appointment yang masih 'scheduled', kirim reminder H-1 & reminder hari-H (beberapa
    jam sebelum) kalau belum pernah dikirim. Aman dipanggil sesering apapun (idempotent) — flag
    reminder_24h_sent/reminder_same_day_sent yang nyegah dobel kirim, BUKAN presisi jadwal cron."""
    now = now_wib()
    today_str = now.strftime("%Y-%m-%d")
    tomorrow_str = (now.date() + timedelta(days=1)).strftime("%Y-%m-%d")
    results = []

    for appt in list(appointments.values()):
        if appt.get("status") != "scheduled":
            continue

        try:
            if appt.get("meeting_date") == tomorrow_str and not appt.get("reminder_24h_sent"):
                done = _send_single_appointment_reminder(appt, "H-1")
                if done:
                    appt["reminder_24h_sent"] = True
                    save_appointment_to_db(appt)
                results.append({"id": appt["id"], "type": "h-1", "done": done})

            elif appt.get("meeting_date") == today_str and not appt.get("reminder_same_day_sent"):
                meeting_dt = datetime.strptime(
                    f"{appt['meeting_date']} {appt['meeting_time']}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=JAKARTA_TZ)
                hours_left = (meeting_dt - now).total_seconds() / 3600.0
                if 0 < hours_left <= SAME_DAY_REMINDER_HOURS_BEFORE:
                    done = _send_single_appointment_reminder(appt, "hari-H")
                    if done:
                        appt["reminder_same_day_sent"] = True
                        save_appointment_to_db(appt)
                    results.append({"id": appt["id"], "type": "same-day", "done": done})
        except Exception as e:
            print(f"Gagal proses reminder appointment id={appt.get('id')}: {e}")
            results.append({"id": appt.get("id"), "type": "error", "error": str(e)})

    return results


def build_customer_context_summary(max_customers=25, max_messages_per_customer=6, max_msg_len=150):
    """Susun ringkasan SEMUA customer (nama + history chat terakhir mereka), buat disisipin ke system
    prompt mode-owner supaya AI bisa jawab pertanyaan Irvan soal customer mana aja, kapan aja — bukan
    cuma yang lagi pending. Dibatasi jumlah customer & panjang pesan biar prompt-nya gak kebesaran."""

    def trunc(text):
        text = (text or "").replace("\n", " ").strip()
        return text if len(text) <= max_msg_len else text[:max_msg_len] + "..."

    if db_enabled():
        all_convos = load_all_conversations_from_db("customer")  # {number: [{role,content,created_at}]}
        names = load_all_customer_names_from_db()
        items = sorted(
            all_convos.items(),
            key=lambda kv: kv[1][-1]["created_at"] if kv[1] else "",
            reverse=True,
        )
    else:
        # Fallback tanpa database: cuma data yang ada di memori sejak server terakhir nyala.
        items = list(conversations.items())[::-1]
        names = customer_names

    items = items[:max_customers]

    if not items:
        return "\n\nBelum ada history chat customer sama sekali."

    blocks = []
    for number, history in items:
        name = names.get(number)
        label = f"{name} (wa.me/{number})" if name else f"wa.me/{number} (nama belum diketahui)"
        pending_note = " ⏳ [lagi nunggu jawaban kamu]" if number in pending_owner_questions else ""
        recent = history[-max_messages_per_customer:]
        lines = []
        for msg in recent:
            speaker = "Customer" if msg.get("role") == "user" else "AI"
            lines.append(f"  {speaker}: {trunc(msg.get('content'))}")
        blocks.append(f"- {label}{pending_note}\n" + "\n".join(lines))

    return (
        "\n\nDAFTAR CUSTOMER & HISTORY CHAT MEREKA (buat referensi jawab pertanyaan Irvan soal customer "
        f"mana aja — ditampilin {len(items)} customer paling aktif, tiap orang max "
        f"{max_messages_per_customer} pesan terakhir):\n" + "\n\n".join(blocks)
    )

# Nomor WA PRIBADI owner (BUKAN nomor bot) — dipakai buat kirim notifikasi leads panas,
# pertanyaan yang AI-nya gak yakin jawab, dan konfirmasi pembayaran. Format: kode negara +
# nomor, tanpa "+" dan tanpa spasi.
OWNER_WHATSAPP_NUMBER = os.environ.get("OWNER_WHATSAPP_NUMBER", "14048836437")

# Path ke file gambar QR code pembayaran statis — BELUM DIPAKAI (lihat catatan lama di bawah),
# sekarang pembayaran pakai transfer rekening BCA langsung (lihat REKENING_BCA di SYSTEM_PROMPT).
QR_IMAGE_PATH = os.environ.get("QR_IMAGE_PATH", "qr_payment.jpg")

# Path ke file katalog PDF (harga & layanan lengkap) yang dikirim ke customer — ini SATU-SATUNYA
# tempat harga paket ditampilkan ke customer. Bot sendiri gak pernah sebut angka harga paket di teks.
CATALOG_PDF_PATH = os.environ.get("CATALOG_PDF_PATH", "katalog.pdf")
CATALOG_PDF_FILENAME = "Katalog Kilas Works.pdf"

# Cache hasil pencarian file katalog.pdf di disk, biar gak nge-walk seluruh folder tiap kali mau
# kirim katalog (lihat find_catalog_pdf_path() di bawah, dipanggil pas mau upload/kirim PDF).
_CATALOG_PDF_PATH_CACHE = {"path": None, "checked": False}


def find_catalog_pdf_path():
    """Cari file katalog.pdf yang beneran ada di disk. Coba CATALOG_PDF_PATH dulu (default: root
    folder app). Kalau gak ketemu di situ (misal katalog.pdf ada di subfolder repo, bukan di root),
    cari SECARA RECURSIVE dari folder tempat app.py ini berada, cari file bernama 'katalog.pdf'
    (case-insensitive). Hasilnya di-cache biar gak nge-walk folder berkali-kali tiap request."""
    if _CATALOG_PDF_PATH_CACHE["checked"] and _CATALOG_PDF_PATH_CACHE["path"] and os.path.exists(_CATALOG_PDF_PATH_CACHE["path"]):
        return _CATALOG_PDF_PATH_CACHE["path"]

    if CATALOG_PDF_PATH and os.path.exists(CATALOG_PDF_PATH):
        _CATALOG_PDF_PATH_CACHE.update(path=CATALOG_PDF_PATH, checked=True)
        return CATALOG_PDF_PATH

    base_dir = os.path.dirname(os.path.abspath(__file__))
    found = None
    for root, dirs, files in os.walk(base_dir):
        # Skip folder yang gak relevan/berat (git internals, virtualenv, cache) biar walk-nya cepet.
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", "venv", ".venv")]
        for fname in files:
            if fname.lower() == "katalog.pdf":
                found = os.path.join(root, fname)
                break
        if found:
            break

    _CATALOG_PDF_PATH_CACHE.update(path=found, checked=True)
    if not found:
        print("PERINGATAN: katalog.pdf gak ketemu di repo (udah dicari recursive) — kirim katalog bakal gagal.")
    return found

# Simpan histori chat sederhana per nomor (in-memory, reset kalau server restart)
conversations = {}

# Simpan pertanyaan customer yang lagi nunggu jawaban owner (in-memory, reset kalau server
# restart). Owner bisa diskusi bebas dulu sama AI soal pertanyaan ini (lihat call_claude_owner),
# baru pas owner bilang eksplisit suruh forward, jawabannya diterusin ke customer yang paling
# lama nunggu (FIFO).
#
# Task 5 (CRITICAL isolation fix) — Key = _ck(tenant_id, nomor_customer), SAMA compound-key
# convention yang dipakai `conversations`/`customer_names`/`agreed_facts` dkk di seluruh file ini,
# BUKAN nomor mentah. Sebelumnya key-nya nomor customer polos: kalau nomor yang sama kebetulan
# juga chat ke tenant client lain (atau ke Kilas Works langsung), pertanyaan pending tenant A bisa
# nongol/kepilih di interface owner tenant B atau owner Kilas Works sendiri — itu bug isolasi data
# yang nyata, bukan cuma teoretis. Semua baca/tulis/hapus/list di bawah WAJIB lewat _ck() atau
# _pending_owner_questions_for_tenant() supaya gak pernah lagi keliru scope.
pending_owner_questions = {}


def _pending_owner_questions_for_tenant(tenant_id):
    """Task 5 — this tenant's (or, for tenant_id=None, Kilas Works' own) slice of
    pending_owner_questions ONLY, returned as {plain_customer_phone: question} (the _ck prefix is
    unwrapped back off so existing owner-mode code — mention lookup, FIFO fallback pick — keeps
    working with plain phone numbers exactly like before this fix, just correctly scoped now)."""
    out = {}
    for key, question in pending_owner_questions.items():
        if not isinstance(key, str):
            continue
        if tenant_id is None:
            if key.startswith("T"):
                continue
            out[key] = question
        else:
            prefix = f"T{tenant_id}:"
            if key.startswith(prefix):
                out[key[len(prefix):]] = question
    return out


# ORIGINAL_INTENT + TARGET_RESOLUTION + ACTION architecture (production bug fix) — closes a real
# production bug: owner asks to READ a customer's history, the customer name is ambiguous, owner
# picks one from the list ("yang 5699"), and the bot incorrectly interpreted that pure
# TARGET-SELECTION reply as a brand new SEND command and forwarded a message to the customer. Root
# cause: this codebase previously had NO explicit state tracking "what was the owner originally
# trying to DO" across a clarification round — the very next owner message (a bare name/number
# selecting a candidate) fell through the SAME generic parsing as any other message, and a stale
# `pending_customer_number` fallback (active_customer_context / the FIFO pending-question pick)
# combined with build_owner_system_prompt()'s "kalau Irvan bilang 'terusin' tanpa nyebut nomor
# lain, anggap target forward-nya customer ini" instruction meant the model could end up deciding
# to forward purely from ambiguous multi-turn context, with no code-level gate stopping it.
#
# This dict is the fix: whenever the owner's ORIGINAL message resolves to an AMBIGUOUS or
# NOT-YET-RESOLVED customer target, we store {intent, action_hint, candidates} keyed by
# _ck(tenant_id, owner_phone) — SAME tenant-scoping convention as pending_owner_questions, so a
# tenant's clarification state can never leak into another tenant's or into Kilas Works' own. The
# owner's VERY NEXT message is then checked against this state FIRST (see
# _try_resolve_pending_owner_clarification() below) — if it looks like a target-selection reply
# (matches a stored candidate, or a phone-suffix/exact-name resolution), the ORIGINAL intent is
# resumed with the NOW-RESOLVED target — a READ intent stays a READ (never becomes a SEND), and a
# SEND intent resumes with the ORIGINAL instruction text (action_hint), not the bare selection
# reply itself. If the reply does NOT look like a target-selection attempt at all (owner changed
# topic), the pending clarification is abandoned and the new message is processed completely
# normally — this state never blocks or hijacks an unrelated later message.
pending_owner_clarification = {}

# Intents an owner message can resolve to once its target ambiguity is settled — deliberately a
# small, explicit, closed set (not a free-form string) so a typo/new intent name can never
# silently fail to resume correctly.
CLARIFICATION_INTENT_READ_HISTORY = "READ_HISTORY"
CLARIFICATION_INTENT_SEND_ACTION = "SEND_ACTION"


def _resolve_clarification_reply(reply_text, candidates):
    """Try to resolve `reply_text` (the owner's reply to a "which one?" clarification) against a
    known `candidates` list of (number, name) tuples. Returns:
      (number, name)  -- resolved to exactly one candidate
      "ambiguous"     -- reply still matches more than one candidate
      None            -- reply does not look like a target-selection attempt at all

    Priority order (most to least specific), so an exact/unambiguous signal always wins over a
    fuzzy one:
      1. Phone-number suffix (\"yang 5699\", \"5699\", \"...5699\") matched against the END of a
         candidate's number — this is exactly how customers are described to the owner in every
         clarification message this file sends (\"Nama (...1234)\"), so it is the most reliable,
         unambiguous signal available.
      2. Exact name match (case/space/punctuation-insensitive) — \"k\"/\"K\"/\"si K\" resolving to
         a candidate whose stored name is LITERALLY \"k\", even if that string is also a substring
         of a different candidate's name (\"Kristov\") — exact match must never lose to a fuzzy
         substring match on a DIFFERENT, longer candidate.
      3. \"yang terakhir\"/\"terakhir\"/\"paling akhir\" -> last candidate in the list (the order
         they were originally presented in); \"yang pertama\"/\"pertama\" -> first candidate.
      4. Unique substring match as a last resort (only used if it resolves to exactly one
         candidate — if it matches 2+, that's still genuinely ambiguous, never a silent guess).
    """
    if not candidates:
        return None
    reply = (reply_text or "").strip().lower()
    reply = re.sub(r'^(yang|yg|si|itu|nomor)\s+', '', reply).strip()
    if not reply:
        return None

    digits = re.sub(r'\D', '', reply)
    if len(digits) >= 3:
        suffix_matches = [c for c in candidates if c[0].endswith(digits)]
        if len(suffix_matches) == 1:
            return suffix_matches[0]
        if len(suffix_matches) > 1:
            return "ambiguous"

    norm_reply = _normalize_name_key(reply)
    if norm_reply:
        exact_matches = [c for c in candidates if _normalize_name_key(c[1]) == norm_reply]
        if len(exact_matches) == 1:
            return exact_matches[0]
        if len(exact_matches) > 1:
            return "ambiguous"

    if reply in ("terakhir", "yang terakhir", "paling akhir", "paling bawah", "yang paling akhir"):
        return candidates[-1]
    if reply in ("pertama", "yang pertama", "paling atas", "yang paling atas"):
        return candidates[0]

    if norm_reply:
        substr_matches = [c for c in candidates if norm_reply in _normalize_name_key(c[1])]
        if len(substr_matches) == 1:
            return substr_matches[0]
        if len(substr_matches) > 1:
            return "ambiguous"

    return None


def _store_pending_owner_clarification(tenant_id, owner_phone, intent, candidates=None, action_hint=None):
    """See pending_owner_clarification's own module-level comment for the full rationale."""
    key = _ck(tenant_id, owner_phone)
    pending_owner_clarification[key] = {
        "intent": intent, "candidates": candidates, "action_hint": action_hint,
        "created_at": _utcnow(),
    }


def _clarification_options_text(candidates):
    return " atau ".join(f"{name} (...{num[-4:]})" for num, name in candidates[:5])

# Histori chat terpisah antara owner & AI (mode "asisten pribadi owner", beda dari histori
# chat AI dengan customer di variable `conversations`).
owner_conversations = {}

# Nama customer yang udah ketauan (in-memory cache, key = nomor customer, value = nama). Kalau
# database aktif, ini juga kesimpen permanen di tabel customer_profiles.
customer_names = {}

# Fakta/kesepakatan yang UDAH FIX per customer (misal harga hasil nego yang udah di-forward owner),
# key = nomor customer, value = list string. Ini SUMBER KEBENARAN terpisah dari histori chat
# freeform — dipakai biar bot gak pernah lagi bilang "belum dapet konfirmasi owner" utk hal yang
# sebenernya udah pernah dijawab & di-forward. Kalau database aktif, ini permanen di customer_facts.
agreed_facts = {}

# Gambar terakhir yang dikirim owner (misal QR code custom) yang BELUM eksplisit disuruh forward
# ke siapa-siapa pas dikirim. Key = nomor owner, value = {"media_id":..., "mime":...} (media_id ini
# udah upload ulang ke media library kita sendiri, jadi gak bergantung sama media_id asli dari WA
# yang scope/masa berlakunya beda). Dipakai kalau abis kirim gambar, owner nyusul bilang cuma
# "kirim ke <nomor>" doang (gak re-attach gambarnya lagi).
last_owner_image = {}

# Customer TERAKHIR yang beneran chat ke bot, per nomor owner — dipakai sebagai fallback target kalau
# owner bilang "terusin"/"kirim ke dia" pas lagi diskusi soal seorang customer TANPA ada pertanyaan
# formal yang ke-tag [TANYA_OWNER] (misal owner cuma proaktif liat notifikasi customer baru & mau
# langsung nimbrung). Key = nomor owner, value = nomor customer terakhir.
active_customer_context = {}

# State follow-up otomatis per customer (key = nomor customer, value = dict last_customer_msg_at /
# last_followup_at / followup_count / converted). Lihat fungsi-fungsi FOLLOW-UP OTOMATIS di bawah.
followup_state = {}

# Marker yang WAJIB dipakai AI di balasannya (mode owner) kalau owner udah eksplisit nyuruh
# forward jawaban ke customer. Bagian SEBELUM marker ini = balasan ke owner (konfirmasi),
# bagian SETELAHNYA = draft pesan yang dikirim ke customer.
FORWARD_MARKER = "PESAN_UNTUK_CUSTOMER:"

# ============================================================
# MEETING NEGOTIATION STATE (production hardening — perbaikan bug "appointment confirmed tanpa
# availability owner") — in-memory, key = nomor customer. Nampung status NEGOSIASI jadwal SEBELUM
# appointment beneran ke-CONFIRMED (ditulis ke tabel `appointments`, lihat try_book_meeting_from_
# owner_slots). Appointment TETAP CUMA jadi CONFIRMED lewat create_appointment() (status "scheduled")
# — TIDAK PERNAH langsung dari sini. Kalau server restart, data negosiasi ini ilang (customer tinggal
# ulang nyebut preferensinya) — TIDAK bikin appointment yang UDAH CONFIRMED ikut ilang (itu di tabel
# `appointments` yang terpisah & persisten).
# ============================================================

MEETING_STATE_WAITING_PREFERENCE = "waiting_customer_preference"
MEETING_STATE_PENDING_OWNER_CONFIRMATION = "pending_owner_confirmation"
MEETING_STATE_SLOTS_OFFERED = "slots_offered"

# number -> {status, mode, day_text, day_display, resolved_date, offered_slots, name, business_name,
#            need_summary, created_at}
meeting_requests = {}

# Task 3 (multi-tenant runtime safety) — a CLIENT tenant's own appointment requests, COMPLETELY
# separate from Kilas Works' own `meeting_requests`/`appointments` above (which stay Kilas-Works-
# only and untouched). Keyed by _ck(tenant_id, customer_phone) — see _ck's docstring — so the same
# phone number messaging two different tenants always gets two fully separate appointment records.
# _ck(tenant_id, number) -> {status, day_text, time, name, created_at}; status is one of
# "REQUESTED" (customer asked, awaiting that tenant's own owner confirmation), "CANCELLED".
tenant_meeting_requests = {}

# ============================================================
# PAYMENT STATE (production hardening) — in-memory, key = nomor customer. Tracking BASIC doang (bukan
# accounting/ledger beneran), biar AI & owner sama-sama paham posisi customer di proses pembayaran.
# Status PAID/PARTIALLY_PAID di sini SELALU owner yang confirm manual (lihat parse_owner_payment_
# command) — AI/customer TIDAK PERNAH bisa langsung nge-set status ini jadi paid sendiri, cuma bisa
# masuk PENDING_VERIFICATION (lewat tag [SUDAH_BAYAR] yang sudah ada sebelumnya).
# ============================================================

PAYMENT_STATUS_NOT_STARTED = "PAYMENT_NOT_STARTED"
PAYMENT_STATUS_INTENT = "PAYMENT_INTENT"
PAYMENT_STATUS_WAITING = "WAITING_PAYMENT"
PAYMENT_STATUS_PENDING_VERIFICATION = "PENDING_VERIFICATION"
PAYMENT_STATUS_PARTIALLY_PAID = "PARTIALLY_PAID"
PAYMENT_STATUS_PAID = "PAID"
PAYMENT_STATUS_NEEDS_RECHECK = "NEEDS_RECHECK"

# number -> {status, package, dp_requested, updated_at}
payment_state = {}


def get_or_create_payment_state(number):
    return payment_state.setdefault(number, {
        "status": PAYMENT_STATUS_NOT_STARTED, "package": None, "dp_requested": False, "updated_at": None,
    })


# ============================================================
# AI SALES ENGINE — LEAD STAGE (production hardening) — in-memory, key = nomor customer. SENGAJA
# simple (4 tahap, gak ada scoring numerik) & DIINFER dari sinyal/tag DETERMINISTIK yang UDAH ADA di
# webhook (bukan tag baru yang AI kontrol sendiri) — biar gak nambah kompleksitas prompt & gak ada
# resiko AI "ngarang" status lead-nya sendiri. Stage CUMA NAIK (gak pernah otomatis turun) — customer
# yang udah WARM/HOT gak dianggap dingin lagi cuma gara-gara kirim chat basa-basi berikutnya.
# ============================================================

LEAD_STAGE_COLD = "COLD"
LEAD_STAGE_WARM = "WARM"
LEAD_STAGE_HOT = "HOT"
LEAD_STAGE_CLOSING = "CLOSING"
_LEAD_STAGE_ORDER = {LEAD_STAGE_COLD: 0, LEAD_STAGE_WARM: 1, LEAD_STAGE_HOT: 2, LEAD_STAGE_CLOSING: 3}

# number -> {"stage":..., "notified_hot": bool, "notified_closing": bool, "updated_at":...}
lead_stage = {}


def get_or_create_lead_stage(number):
    return lead_stage.setdefault(number, {
        "stage": LEAD_STAGE_COLD, "notified_hot": False, "notified_closing": False, "updated_at": None,
    })


def bump_lead_stage(number, new_stage):
    """Naikkan lead stage customer ini KALAU new_stage lebih 'panas' dari stage sekarang — gak pernah
    turun otomatis. Return dict state (bukan cuma stage-nya doang) biar caller bisa cek notified_hot/
    notified_closing sebelum notify owner (anti-spam, cuma notify SEKALI per transisi)."""
    state = get_or_create_lead_stage(number)
    if _LEAD_STAGE_ORDER[new_stage] > _LEAD_STAGE_ORDER[state["stage"]]:
        state["stage"] = new_stage
    state["updated_at"] = _utcnow()
    return state


# ---- LANGUAGE LAYER (additive) -----------------------------------------
# Nyimpen preferred language per customer (in-memory, sama kayak meeting_requests/
# payment_state/lead_stage) biar chat berikutnya konsisten tanpa AI harus nebak ulang
# dari nol tiap pesan. AI yang deteksi bahasa & kirim tag [SET_LANG: lang=id|en] di
# akhir balasannya; Python cuma nyimpen nilainya, gak ngubah logic sales/appointment/
# payment sama sekali — murni layer tambahan di atas.
LANGUAGE_ID = "id"
LANGUAGE_EN = "en"
customer_language = {}

# ============================================================
# IDEMPOTENCY GUARD — WhatsApp Cloud API bisa NGIRIM ULANG (retry) webhook yang SAMA kalau
# respons kita kelamaan/dianggap gagal. Tanpa guard ini, retry itu bisa bikin webhook diproses
# DUA KALI dari nol — termasuk manggil AI dua kali & KIRIM PESAN YANG SAMA DUA KALI ke customer
# atau owner. Guard ini nge-tandain wamid (message id asli dari WhatsApp) SEBELUM diproses sama
# sekali, jadi kalau ada webhook duplikat masuk (retry ATAU race), langsung di-drop di awal —
# gak ada AI call, gak ada pengiriman apapun, satu event id = satu kali proses, titik.
# ============================================================
PROCESSED_MESSAGE_IDS = set()
PROCESSED_MESSAGE_IDS_ORDER = deque(maxlen=5000)


def is_duplicate_event(message_id):
    """Cek & TANDAI SEKALIAN wamid ini sebagai udah dipegang. Return True kalau ini DUPLIKAT
    (udah pernah masuk sebelumnya -> caller WAJIB langsung return tanpa proses apa-apa).
    PENTING: fungsi ini match-and-mark dalam satu langkah, jadi cuma boleh dipanggil SEKALI per
    event yang beneran mau diproses (biasanya di paling atas, sebelum logic apapun jalan)."""
    if not message_id:
        return False  # gak ada id (jarang) -> gak bisa di-dedup, proses aja apa adanya
    if message_id in PROCESSED_MESSAGE_IDS:
        return True
    if len(PROCESSED_MESSAGE_IDS_ORDER) >= PROCESSED_MESSAGE_IDS_ORDER.maxlen:
        oldest = PROCESSED_MESSAGE_IDS_ORDER.popleft()
        PROCESSED_MESSAGE_IDS.discard(oldest)
    PROCESSED_MESSAGE_IDS_ORDER.append(message_id)
    PROCESSED_MESSAGE_IDS.add(message_id)
    return False

# ===== CENTRALIZED PAYMENT CONFIG (SATU SUMBER KEBENARAN — production hardening) =====
# SATU-SATUNYA tempat data rekening resmi Kilas Works didefinisikan. AI DILARANG KERAS ngetik nomor
# rekening sendiri dari teks bebas (resiko salah ketik/ngarang digit) — nomor rekening SELALU disuntik
# oleh Python lewat tag "[GIVE_PAYMENT_INFO]" (lihat build_payment_info_text() & webhook), AI cuma
# nulis tag-nya doang di posisi yang pas, gak pernah nulis angka rekeningnya sendiri.
PAYMENT_CONFIG = {
    "bank": "BCA",
    "account_number": "7610267551",
    "account_name": "Irvan Karnawi",
}


def build_payment_info_text():
    """Generate teks info rekening resmi dari PAYMENT_CONFIG (SATU-SATUNYA sumber kebenaran).
    Dipanggil Python buat nyuntik ke balasan customer — AI sendiri gak pernah ngetik nomor rekening."""
    return f"{PAYMENT_CONFIG['bank']} {PAYMENT_CONFIG['account_number']} a.n. {PAYMENT_CONFIG['account_name']}"


# ===== CENTRALIZED PRICING CONFIG (SATU SUMBER KEBENARAN) =====
# Ini SATU-SATUNYA tempat harga/paket Kilas Works didefinisikan. SYSTEM_PROMPT (info yang dihafal
# AI WhatsApp Admin) & katalog PDF (lihat generate_katalog_pdf.py / script terpisah) HARUS baca dari
# sini, JANGAN pernah hardcode angka harga di tempat lain. Kalau harga berubah, cukup edit di sini.
PRICING_CONFIG = {
    "ai_admin": {
        "basic": {
            "nama": "AI Admin Basic",
            "harga": 499000,
            "satuan": "bulan",
            "positioning": "AI Customer Service untuk bisnis kecil/UMKM yang butuh respon otomatis dasar.",
            "fitur": [
                "Balas WhatsApp customer otomatis",
                "Menjawab FAQ",
                "Menjelaskan produk/layanan, harga, jam operasional, dan info bisnis lainnya",
                "Bisa memberikan katalog/informasi layanan",
                "Memahami bahasa customer yang informal dan typo dasar",
                "Basic customer history/data",
                "Tone/gaya bahasa bisa disesuaikan dengan bisnis",
            ],
            "catatan": "Fair usage applies.",
            "tidak_termasuk": [
                "Invoice otomatis", "QR payment otomatis", "Payment tracking",
                "Payment gateway custom", "CRM custom", "Inventory/stock integration",
                "POS", "Multi-cabang", "Integrasi API kompleks", "Workflow khusus yang besar",
                "Owner command & appointment (lihat AI Admin Pro)",
            ],
        },
        "pro": {
            "nama": "AI Admin Pro",
            "harga": 999000,
            "satuan": "bulan",
            "positioning": "Semua fitur AI Admin Basic, ditambah workflow advanced untuk bisnis yang butuh lead qualification, appointment, dan kontrol owner penuh lewat chat.",
            "fitur": [
                "Semua fitur AI Admin Basic",
                "Kualifikasi calon customer / lead",
                "Mengumpulkan nama dan kebutuhan customer",
                "Menyimpan data lead",
                "Follow-up dasar ke customer yang sempat diam (aktif setelah scheduler follow-up disetup owner)",
                "Mengenali customer yang mulai menunjukkan ketertarikan",
                "Bisa menawarkan konsultasi/meeting secara natural jika customer sudah tertarik",
                "Appointment: online meeting / ketemu langsung, cek availability owner, reschedule, cancel, riwayat appointment",
                "Payment conversation (DP/full) & pengiriman info pembayaran resmi kalau customer mau membayar",
                "Owner command lewat chat natural: tanya history customer, kirim pesan/katalog/media ke customer, contact matching & alias/partial name matching, active customer context",
                "Owner bisa membaca gambar/screenshot (vision) yang dikirim customer, misalnya bukti transfer",
                "Owner mendapat notifikasi untuk lead penting",
                "Anti duplicate send (pesan tidak terkirim dobel)",
                "Handoff percakapan ke owner — owner bisa ambil alih & chat customer secara bebas, AI tetap memahami konteksnya",
                "Knowledge bisnis bisa disesuaikan + basic maintenance/update knowledge",
            ],
            "catatan": "Fair usage applies.",
            "tidak_termasuk": [
                "Invoice otomatis", "QR payment otomatis", "Payment tracking",
                "Payment gateway custom", "CRM custom", "Inventory/stock integration",
                "POS", "Multi-cabang", "Integrasi API kompleks", "Workflow khusus yang besar",
            ],
        },
    },
    "content_packages": {
        "basic": {
            "nama": "Content Basic", "harga": 1500000,
            "deliverables": ["4 Reels/TikTok", "6 Static Visuals", "Editing", "Basic color", "Caption ideas"],
        },
        "growth": {
            "nama": "Content Growth", "harga": 2750000, "most_popular": True,
            "deliverables": ["8 Reels/TikTok", "10 Static Visuals", "Ide & hook konten", "Editing", "Color", "Caption ideas"],
        },
        "pro": {
            "nama": "Content Pro", "harga": 4250000,
            "deliverables": ["12 Reels/TikTok", "14 Static Visuals", "Content planning", "Ide & hook", "Script ringan", "Editing & color", "Caption ideas"],
        },
    },
    "static_visual_note": (
        "Static Visual bisa berupa kombinasi foto, desain/poster, carousel, dan AI-assisted creative "
        "visual sesuai kebutuhan brand — bukan selalu hasil photography murni."
    ),
    "bundles": {
        "growth_ai_basic": {
            "nama": "Content Growth + AI Admin Basic", "harga": 2990000,
            "isi": ["Semua benefit Content Growth", "AI Admin Basic"],
        },
        "growth_ai": {
            "nama": "Content Growth + AI Admin Pro", "harga": 3490000,
            "isi": ["Semua benefit Content Growth", "AI Admin Pro"],
        },
        "pro_ai": {
            "nama": "Content Pro + AI Admin Pro", "harga": 4990000,
            "isi": ["Semua benefit Content Pro", "AI Admin Pro"],
        },
    },
    "meta_ads": {
        "management": {
            "nama": "Meta Ads Management", "harga": 799000, "satuan": "bulan",
            "fokus": "Instagram & Facebook / Meta Ads",
            "fitur": [
                "Setup dan pengelolaan campaign",
                "Basic audience targeting/research",
                "Setup creative yang diberikan/tersedia",
                "Basic ad copy",
                "Monitoring campaign",
                "Optimasi",
                "A/B testing sederhana",
                "Monthly performance summary/report",
                "Rekomendasi creative berdasarkan performa",
            ],
            "catatan": "Ad spend TIDAK termasuk fee Kilas Works — budget iklan dibayar langsung oleh customer ke Meta.",
        },
        "setup_only": {
            "nama": "Ads Setup Only", "harga": 399000, "satuan": "sekali",
            "deskripsi": (
                "Buat customer yang cuma butuh setup campaign awal, basic targeting, struktur "
                "campaign, basic configuration. Setelah setup, campaign dikelola sendiri oleh customer."
            ),
        },
        "no_guarantee_note": (
            "Campaign dioptimalkan berdasarkan objective bisnis seperti awareness, leads, inquiries "
            "atau conversion — TIDAK PERNAH menjanjikan omzet pasti, ROAS pasti, penjualan pasti, "
            "atau jumlah leads pasti."
        ),
    },
    "ads_bundles": {
        "ai_basic_ads": {
            "nama": "AI Admin Basic + Meta Ads", "harga": 1190000,
            "isi": ["AI Admin Basic", "Meta Ads Management"],
        },
        "ai_ads": {
            "nama": "AI Admin Pro + Meta Ads", "harga": 1690000,
            "isi": ["AI Admin Pro", "Meta Ads Management"],
        },
        "growth_ai_ads": {
            "nama": "Content Growth + AI Admin Pro + Ads", "harga": 4290000, "recommended": True,
            "isi": ["Content Growth", "AI Admin Pro", "Meta Ads Management"],
        },
        "pro_ai_ads": {
            "nama": "Content Pro + AI Admin Pro + Ads", "harga": 5790000,
            "isi": ["Content Pro", "AI Admin Pro", "Meta Ads Management"],
        },
        "ads_landing_page": {
            "nama": "Ads + Landing Page", "harga": 1490000, "satuan": "bulan pertama",
            "isi": ["Landing Page", "Meta Ads Management (bulan pertama)"],
            "harga_lanjutan": 799000,
            "catatan_lanjutan": "Bulan berikutnya kalau Ads diteruskan: Rp799.000/bulan.",
        },
        "ad_spend_note": "Ad spend TIDAK termasuk di semua bundle Ads di atas — dibayar terpisah langsung ke Meta oleh customer.",
    },
    "website": {
        "landing_page": {
            "nama": "Website — Landing Page", "harga": 799000,
            "deskripsi": (
                "1 halaman, sekitar 5-7 section, responsive desktop & mobile, CTA WhatsApp, contact "
                "form, basic SEO, maksimal 2x revisi. Cocok buat campaign/promo/produk-jasa tertentu/"
                "personal & business landing page."
            ),
        },
        "company_profile": {
            "nama": "Website — Company Profile", "harga": 1500000,
            "deskripsi": (
                "Maksimal 5 halaman (Home, About, Services, Portfolio/Gallery, Contact), responsive "
                "desktop & mobile, WhatsApp/contact integration, basic SEO, maksimal 2x revisi."
            ),
        },
        "halaman_tambahan": {"nama": "Halaman Tambahan", "harga": 200000, "satuan": "halaman"},
        "maintenance": {
            "nama": "Website Maintenance", "harga": 199000, "satuan": "bulan",
            "deskripsi": "Update ringan: perubahan teks, update gambar, pengecekan website dasar. Kebutuhan development besar dihitung terpisah.",
        },
    },
    "domain_hosting": {
        "com": {"nama": ".COM + Hosting", "harga": 999000, "satuan": "tahun"},
        "id": {"nama": ".ID + Hosting", "harga": 1099000, "satuan": "tahun"},
        "termasuk": ["Setup domain", "Connect domain", "DNS configuration", "SSL", "Hosting configuration awal"],
        "catatan": (
            "Domain & hosting berlaku 1 tahun. Harga renewal dapat mengikuti harga provider pada saat "
            "perpanjangan. Kalau customer mau beli domain/hosting sendiri, Kilas Works tetap bisa bantu "
            "proses connect ke website."
        ),
    },
    "event": {
        "standard": {"nama": "Acara Standard", "harga": 1200000, "deskripsi": "1 fotografer, hingga 5 jam, semua file foto digital"},
        "lengkap": {"nama": "Acara Lengkap", "harga": 2800000, "deskripsi": "1 fotografer + 1 videografer, hingga 8 jam, video highlight sinematik"},
        "premium": {"nama": "Acara Premium", "harga": 4400000, "deskripsi": "2 fotografer + 1 videografer, hingga 8 jam, video sinematik + teaser Reels + album cetak"},
    },
    "transport_acara": {
        "tangerang_jakarta": 0,
        "bandung": 250000,
        "notes": (
            "Area menengah lain (Sukabumi, Cirebon, dll): estimasi sesuai jarak dari Tangerang (kisaran "
            "Rp300rb-600rb, dikonfirmasi sebelum booking). Area jauh/luar Jawa (Bali, dll): tiket "
            "pesawat, penginapan, perjalanan ditanggung customer, di luar fee jasa."
        ),
    },
    "custom_automation_redirect": (
        "Untuk kebutuhan tersebut bisa dibuat sebagai custom solution. Aku bantu teruskan ke owner "
        "supaya kebutuhan dan biayanya bisa dibahas lebih lanjut ya."
    ),
}


def format_price_short(n):
    """Format angka rupiah jadi gaya singkatan chat natural (999rb, 1,5jt, 2,75jt, dst) — dipakai
    generate teks INFO PAKET & HARGA di SYSTEM_PROMPT, biar konsisten sama gaya chat natural yang
    dipakai bot (bukan format resmi/kaku)."""
    if n >= 1_000_000:
        val = n / 1_000_000
        s = f"{val:.2f}".rstrip("0").rstrip(".")
        return f"{s.replace('.', ',')}jt"
    val = n / 1000
    if val == int(val):
        return f"{int(val)}rb"
    return f"{val:.1f}".replace(".", ",") + "rb"


def format_price_full(n):
    """Format angka rupiah PENUH pakai titik ribuan (buat katalog PDF/tulisan resmi), mis. 2750000
    -> 'Rp2.750.000'."""
    return "Rp" + f"{n:,.0f}".replace(",", ".")


def build_pricing_text_block():
    """Generate teks 'INFO PAKET & HARGA' di SYSTEM_PROMPT LANGSUNG dari PRICING_CONFIG di atas —
    ini yang bikin katalog & bot AI baca dari satu sumber data yang sama, bukan dua daftar harga
    yang dipelihara terpisah (rawan out-of-sync)."""
    cfg = PRICING_CONFIG
    fp = format_price_short
    lines = []

    for tier in ("basic", "pro"):
        ai = cfg["ai_admin"][tier]
        lines.append(f"{ai['nama']} — Rp{fp(ai['harga'])}/{ai['satuan']} ({ai['catatan']}):")
        lines.append(f"  Positioning: {ai['positioning']}")
        for f in ai["fitur"]:
            lines.append(f"  • {f}")
        lines.append(
            "  TIDAK TERMASUK di paket ini: " + ", ".join(ai["tidak_termasuk"]) +
            " — semua ini masuk kategori Custom Automation / Custom Solution (harga berdasarkan kebutuhan)."
        )
        lines.append("")
    lines.append(
        "Catatan AI Admin: Basic (Rp499rb) buat respon-otomatis dasar (FAQ, info produk/harga, katalog, "
        "typo/informal). Pro (Rp999rb) tambahin appointment (booking/reschedule/cancel/availability), "
        "payment conversation, lead qualification, owner command penuh lewat chat, vision/baca gambar, "
        "anti-duplicate-send, & notifikasi owner buat lead penting — Pro = Basic + semua itu, BUKAN "
        "produk terpisah."
    )

    lines.append("")
    lines.append("Content Packages (langganan bulanan produksi konten, TANPA AI Admin):")
    for key in ("basic", "growth", "pro"):
        p = cfg["content_packages"][key]
        label = f"{p['nama']} (paling diminati)" if p.get("most_popular") else p["nama"]
        lines.append(f"- {label} — Rp{fp(p['harga'])}/bulan: " + ", ".join(p["deliverables"]))
    lines.append(f"Catatan Static Visual: {cfg['static_visual_note']}")

    lines.append("")
    lines.append("Bundle Content + AI Admin (paling hemat kalau butuh dua-duanya):")
    for key in ("growth_ai_basic", "growth_ai", "pro_ai"):
        b = cfg["bundles"][key]
        lines.append(f"- {b['nama']} — Rp{fp(b['harga'])}/bulan: " + " + ".join(b["isi"]))

    lines.append("")
    ma = cfg["meta_ads"]
    mgmt = ma["management"]
    setup = ma["setup_only"]
    lines.append(f"Meta Ads Management ({mgmt['fokus']}) — Rp{fp(mgmt['harga'])}/{mgmt['satuan']}:")
    for f in mgmt["fitur"]:
        lines.append(f"  • {f}")
    lines.append(f"  Catatan: {mgmt['catatan']}")
    lines.append(f"- {setup['nama']} — Rp{fp(setup['harga'])} ({setup['satuan']}): {setup['deskripsi']}")
    lines.append(f"Catatan penting Ads: {ma['no_guarantee_note']}")

    lines.append("")
    lines.append("Ads Bundles (Content/AI Admin + Meta Ads):")
    ab = cfg["ads_bundles"]
    for key in ("ai_basic_ads", "ai_ads", "growth_ai_ads", "pro_ai_ads"):
        b = ab[key]
        label = f"{b['nama']} (direkomendasikan)" if b.get("recommended") else b["nama"]
        lines.append(f"- {label} — Rp{fp(b['harga'])}/bulan: " + " + ".join(b["isi"]))
    alp = ab["ads_landing_page"]
    lines.append(f"- {alp['nama']} — Rp{fp(alp['harga'])} ({alp['satuan']}): " + " + ".join(alp["isi"]) + f". {alp['catatan_lanjutan']}")
    lines.append(f"Catatan: {ab['ad_spend_note']}")

    lines.append("")
    lines.append("Website (sekali bayar, bukan bulanan):")
    lp = cfg["website"]["landing_page"]
    cp = cfg["website"]["company_profile"]
    ht = cfg["website"]["halaman_tambahan"]
    mt = cfg["website"]["maintenance"]
    lines.append(f"- {lp['nama']} — Rp{fp(lp['harga'])}: {lp['deskripsi']}")
    lines.append(f"- {cp['nama']} — Rp{fp(cp['harga'])}: {cp['deskripsi']}")
    lines.append(f"- {ht['nama']} — Rp{fp(ht['harga'])}/{ht['satuan']}")
    lines.append(f"- {mt['nama']} — Rp{fp(mt['harga'])}/{mt['satuan']}: {mt['deskripsi']}")

    lines.append("")
    lines.append("Domain & Hosting (opsional, TERPISAH dari harga jasa pembuatan website):")
    dh = cfg["domain_hosting"]
    for key in ("com", "id"):
        d = dh[key]
        lines.append(f"- {d['nama']} — Rp{fp(d['harga'])}/{d['satuan']}")
    lines.append("  Termasuk bantuan: " + ", ".join(dh["termasuk"]) + ".")
    lines.append(f"  Catatan: {dh['catatan']}")

    lines.append("")
    lines.append("Foto & Video Acara (wedding, ulang tahun, corporate, gathering, dll — sekali bayar per acara):")
    for key in ("standard", "lengkap", "premium"):
        e = cfg["event"][key]
        label = f"{e['nama']} (paling diminati)" if key == "lengkap" else e["nama"]
        lines.append(f"- {label} — Rp{fp(e['harga'])}: {e['deskripsi']}")

    return "\n".join(lines)


PRICING_TEXT_BLOCK = build_pricing_text_block()

SYSTEM_PROMPT = """Kamu admin WhatsApp Kilas Works (jasa fotografi, videografi, konten short-form Reels/TikTok,
DAN AI WhatsApp Admin — lihat SOAL CAKUPAN LAYANAN di bawah, di Tangerang & Jakarta). Balas kayak MANUSIA ASLI
lagi WhatsApp-an, tapi tetap PROFESIONAL & fokus bisnis — BUKAN kayak bot atau customer service kaku.

GAYA BALASAN (penting banget):
- Pendek-pendek, natural, kayak orang chat beneran. 1-2 kalimat per bubble chat, JANGAN bikin paragraf
  panjang atau list bullet formal. MAKSIMAL ringkas, to-the-point.
- Boleh santai: "nih", "ya", "sih", "oke", jangan bahasa baku kaku ("Baik, berikut adalah...", "Dengan senang
  hati kami...").
- JANGAN PAKAI EMOJI SAMA SEKALI di balasan ke customer. Nol emoji, bukan "secukupnya" — tulisan biasa aja,
  kayak orang profesional chat kerjaan, bukan kayak asisten AI yang norak.
- JANGAN muji-muji berlebihan atau sok excited kayak gaya AI (contoh yang DILARANG: "Wah keren banget!",
  "Menarik sekali!", "Ide bagus tuh!", "Wow!"). Kamu bukan cheerleader — jawab biasa aja, natural, fokus ke
  bisnis & solusinya, bukan komentarin kerennya sesuatu. Tetap ramah, tapi ramah yang tenang & profesional,
  bukan lebay.
- Jangan ulang-ulang nanya hal yang sama atau interogasi kayak form. Ngobrol aja natural, jangan muter-muter,
  jawab to the point kalau ditanya sesuatu yang jelas.
- Kalau kamu tau ilmu/tips yang relevan dan bisa bantu customer (misal soal foto produk, ide konten, dll),
  kasih tau aja natural kayak orang yang emang paham, jangan pelit info kecil yang nggak masalah dibagi.
- SINGKATKAN angka/harga: kalau customer bilang "1 juta" boleh kamu balas "1 jt", "5 ribu" boleh "5rb" —
  singkat, natural, kayak orang chat. PAHAM SEMUA VARIASI ANGKA (krusial!):
  • jt=juta, rb=ribu, k=ribu, sm=sama
  • Contoh: "1 jt" = "1 juta", paham? Kamu harus paham semua slang/nickname buat angka.
  • INGAT dengan perfect apa arti setiap angka yang customer/owner bilang, jangan pernah kekeliruan.
- Kalau balasanmu wajar dipecah jadi beberapa chat bubble terpisah (kayak orang WA-an beneran, bukan 1
  paragraf gede), pisahkan tiap bubble dengan "|||" di antaranya. Contoh: "Oh siap kak!|||Jadi kebutuhannya
  buat apa nih, konten rutin bulanan atau buat 1 acara aja?" — ini bakal dikirim sebagai 2 pesan terpisah
  dengan jeda "sedang mengetik" di antaranya, biar berasa natural. Jangan kepaksa pecah kalau emang pas 1
  kalimat pendek aja udah cukup.
- INGAT MEMORY: Apa yang customer bilang sekali, kamu HARUS ingat & konsisten. Contoh: customer bilang "1 jt"
  di awal, jangan tiba-tiba bilang "1.5 jt" atau "bisa nego" tanpa persetujuan. Konsisten 100%.
- JANGAN PERNAH bilang "aku gak tau", "kurang tau juga", "gak paham", atau semacamnya ke customer — itu
  gak profesional & bikin customer ilang percaya. Ganti selalu dengan respons yang lebih meyakinkan:
  kalau emang gak yakin jawabannya, bilang "saya cek dulu ya kak, bentar" (terus sertain tag
  "[TANYA_OWNER]", lihat bagian di bawah) — BUKAN ngaku gak tau. Kalau pertanyaannya di luar konteks
  bisnis, arahkan balik ke topik, jangan ngaku gak paham.

BAHASA BALASAN — AUTO-DETECT (WAJIB DIIKUTI):
- Deteksi bahasa customer dari PESAN TERAKHIR MEREKA (bukan histori lama) tiap kali balas: kalau dia nulis
  Bahasa Indonesia, balas Bahasa Indonesia (gaya di atas). Kalau dia nulis English, balas full English
  (natural, kayak native speaker chat santai, bukan translate kaku kata-per-kata dari draft Bahasa
  Indonesia). Kalau pesannya campur Indonesia+English, ikutin bahasa yang PALING DOMINAN di pesan itu &
  tetap kedengeran natural (boleh sisipin istilah yang emang lazim dicampur, jangan dipaksa 100% murni).
- JANGAN PERNAH nanya "mau pakai bahasa apa?" ke customer — cuma boleh nanya balik/klarifikasi kalau
  BENERAN ambigu banget (misal pesannya cuma emoji/angka doang, gak ada kata sama sekali).
- KONSISTENSI: begitu kamu udah mutusin bahasa balasan buat customer ini (pertama kali chat ATAU tiap kali
  ganti), sertakan tag PERSIS di akhir balasan: [SET_LANG: lang=id] (Bahasa Indonesia) atau
  [SET_LANG: lang=en] (English) — SISTEM yang simpen preferensi ini biar chat berikutnya konsisten tanpa
  kamu harus nebak ulang dari nol tiap pesan. Kalau di bawah kamu dikasih tau BAHASA CUSTOMER INI
  SEBELUMNYA, pakai itu sebagai default — TAPI kalau pesan customer SEKARANG jelas-jelas pakai bahasa lain,
  ikutin bahasa yang sekarang (dia boleh ganti bahasa di tengah obrolan, kamu ngikutin, tetap natural &
  konteks obrolan gak berubah) & update tag [SET_LANG: ...]-nya lagi.
- JANGAN PERNAH nerjemahin: nama paket (misal "Content Growth", "Growth + AI Admin"), angka harga, nomor &
  nama rekening bank (yang formatnya dikasih via [GIVE_PAYMENT_INFO], BUKAN kamu ketik manual), nama
  bisnis/orang, atau proper noun lainnya — itu semua tetap PERSIS apa adanya walau balasannya English, cuma
  kalimat di sekitarnya yang ikut bahasa customer. Angka harga tetap format sama (misal "999K"/"Rp999rb"
  boleh disesuaikan gaya native speaker English kalau perlu, tapi ANGKANYA JANGAN PERNAH berubah/dikonversi
  ke mata uang lain).
- Semua aturan lain di system prompt ini (harga, appointment, payment, tone larangan pakai kata ganti
  informal/kasar, dsb) TETAP BERLAKU SAMA PERSIS di kedua bahasa — cuma bahasa penyampaiannya yang beda,
  isi/logic-nya sama.

SOAL CAKUPAN LAYANAN (kalau customer nanya "jasa apa aja", "kalian ngerjain apa aja", dst):
- Kilas Works jasanya BUKAN cuma foto/video/edit/Reels doang — juga ada AI WhatsApp Admin (yang lagi kamu
  jalanin sekarang buat chat ini), Website, Talent Management (Custom Quote), dan layanan lain di data
  paket/live Client Hub di bawah. Kalau customer nanya
  cakupan layanan secara umum, jawab AKURAT & LENGKAP sesuai kategori resmi yang BENERAN ada di data paket
  di bawah — jangan cuma sebut sebagian kalau customer emang nanya semua, tapi juga jangan maksa nge-push
  satu layanan tertentu seolah itu jawaban paling penting. Jawab natural & proporsional aja sesuai yang
  ditanya.
- Boleh natural nyebut AI Admin sebagai contoh nyata kalau emang relevan sama konteks obrolan (misal
  customer nanya soal respon cepat/chat admin) — lihat aturan CROSS-SELL di bawah, tetap harus relevan,
  BUKAN dipaksa disebut di semua balasan.

INFO PAKET & HARGA (kamu WAJIB HAFAL & BISA SEBUT semua angka ini natural kalau ditanya, lihat ATURAN
HARGA di bawah buat gaya nyebutnya — data di bawah ini di-generate dari satu sumber data pricing yang
sama dipakai buat katalog PDF, JANGAN pernah nyebut angka lain selain yang ada di sini):

{pricing_text_block}

Catatan umum: kontrak paket bulanan minimal 1 bulan, bisa diperpanjang fleksibel. Kebutuhan di luar cakupan
paket (shoot lokasi luar kota, talent tambahan, integrasi custom, dsb) dihitung terpisah sebagai Custom
Automation / Custom Solution & didiskusikan case-by-case — JANGAN pernah bilang itu termasuk gratis di
paket manapun. Harga di atas FIX (bukan promo), jadi jawab dengan yakin, bukan ragu-ragu kayak takut salah.

ATURAN HARGA (WAJIB DIIKUTI — PRICE DISCLOSURE, dibaca PERSIS, jangan campur aduk sama RECOMMEND di atas):
- ⭐ PERUBAHAN ATURAN BISNIS (WAJIB, override instruksi harga versi lama di mana pun kamu pernah lihat):
  Customer TIDAK PERNAH boleh dikasih ANGKA NOMINAL harga — bukan harga paket, bukan diskon, bukan custom
  quote, bukan estimasi biaya apapun — WALAUPUN angkanya ADA di data paket, ADA di prompt ini, ATAU pernah
  disebut di obrolan sebelumnya, DAN WALAUPUN customer nanya LANGSUNG/berkali-kali. Ini berlaku ke SEMUA
  jenis angka Rupiah, termasuk biaya transport (lihat SOAL BIAYA TRANSPORT di bawah, aturan lama yang
  ngebolehin nyebut angka transport SUDAH TIDAK BERLAKU).
- Kalau customer nanya harga paket apapun (misal "Growth berapa?", "AI Admin Pro berapa?", "harganya
  berapa?"), JANGAN sebut angka sama sekali. Jawab natural yang intinya: "Untuk detail harganya aku bantu
  cek dulu ke tim ya, biar sesuai kebutuhan kamu." — boleh divariasikan kalimatnya asal TETAP TANPA angka.
  JANGAN bilang "gak tau harganya" (kamu TAU, cuma emang gak boleh sebutin ke customer) — dan jangan
  kedengaran defensif/aneh, tetap natural kayak beneran mau bantu cek ke tim.
- Customer TETAP boleh dapet: penjelasan layanan, benefit, apa aja yang termasuk di paket, proses kerja,
  pertanyaan qualifying, rekomendasi paket mana yang paling cocok (SEBUT NAMA paketnya, JANGAN sebut
  angkanya) — semua ini boleh dan didorong, cuma angka Rupiah-nya aja yang gak boleh keluar.
- KALAU CUSTOMER MINTA SELURUH PRICE LIST / KATALOG (misal "ada pricelist gak", "kirim semua harganya
  dong"): TETAP boleh kirim katalog PDF (tag "[KIRIM_KATALOG]") — katalog itu dokumen resmi yang memang
  didesain buat dibaca customer sendiri, beda dari kamu SEBAGAI AI nyebutin angka langsung di chat. Kalau
  kirim katalog, sertai kalimat singkat TANPA nyebut angka juga di balasan chat-nya sendiri (misal "udah
  aku kirim katalognya ya, di situ ada semua detail paketnya").
- Ada guardrail tambahan di level sistem (bukan cuma instruksi prompt ini) yang otomatis nyaring balasan
  kamu kalau kebetulan kelupaan nyebut angka — tapi JANGAN mengandalkan itu, USAHAKAN dari awal emang gak
  pernah nyebut angka ke customer.

SOAL KEBUTUHAN DI LUAR PAKET (CUSTOM AUTOMATION / CUSTOM SOLUTION) — WAJIB DIIKUTI:
- Bot DILARANG KERAS: ngarang harga sendiri, kasih diskon sendiri tanpa persetujuan owner, bikin paket
  baru yang gak ada di data, nambahin fitur yang gak ada di daftar di atas, bilang invoice/QR/payment
  gateway/CRM/inventory/POS/integrasi API termasuk di paket AI Admin manapun, atau kasih domain/hosting
  gratis.
- Kalau customer nanya/butuh sesuatu yang di luar cakupan paket manapun di atas (misal invoice otomatis,
  integrasi payment gateway, CRM, sistem inventory, POS, multi-cabang, workflow/integrasi custom lainnya),
  jawab pakai kalimat natural yang intinya: "{custom_automation_redirect}" — jangan janjiin itu bisa
  langsung tersedia atau gratis.
- Layanan Custom AI / Digital Automation ini BUKAN produk publik yang ditawarin proaktif atau dipajang
  sebagai paket di katalog — cuma jalur eskalasi ke owner kalau kebutuhan customer emang di luar semua
  paket resmi di atas. Jangan pernah sebut ini seolah ada daftar harga/paket "Custom Automation" tersendiri.

SOAL META ADS (WAJIB DIIKUTI — JANGAN JANJIIN HASIL PASTI):
- Meta Ads Management & Ads Setup Only itu jasa PENGELOLAAN campaign, BUKAN jaminan hasil. Bot DILARANG
  KERAS janji: omzet pasti, ROAS pasti, penjualan pasti, atau jumlah leads pasti dari Ads — walau customer
  maksa nanya angka pasti sekalipun.
- Gaya jawab yang BENER kalau ditanya soal hasil Ads: "Campaign dioptimalkan berdasarkan objective bisnis
  seperti awareness, leads, inquiries, atau conversion" — bukan janji angka.
- Ad spend (budget iklan ke Meta) SELALU TERPISAH dari fee Kilas Works di SEMUA paket/bundle Ads (termasuk
  yang bundling kayak "AI Admin + Ads", "Growth + AI + Ads", dst) — budget dibayar customer LANGSUNG ke
  Meta, bukan lewat Kilas Works, dan BUKAN bagian dari harga bulanan yang disebut di atas. Selalu jelasin
  ini kalau ngomongin paket Ads apapun, jangan sampai customer ngira ad spend udah termasuk.

SOAL BIAYA TRANSPORT ACARA DI LUAR TANGERANG/JAKARTA (WAJIB, override versi lama — JANGAN sebut angka):
- Tangerang & Jakarta: boleh bilang natural "gratis, gak ada biaya tambahan" (ini bukan angka nominal,
  aman disebut).
- SEMUA lokasi lain (Bandung, Sukabumi, Cirebon, luar Jawa, dst) — JANGAN PERNAH sebut angka Rupiah
  apapun, JANGAN hitung/estimasi sendiri berapa biayanya, walaupun ada "patokan" atau kisaran yang
  kelihatan masuk akal. Jawab natural yang intinya: "Untuk biaya transport/akomodasi ke [lokasi] perlu
  aku konfirmasi ke tim dulu ya, biar gak salah hitung." — lalu WAJIB sertakan tag "[TANYA_OWNER]" di
  balasanmu (taruh di mana aja, sistem yang proses, customer gak bakal lihat teks tag-nya) supaya owner
  tau ada acara luar kota yang perlu di-follow-up manual soal biayanya.
- Ini berlaku SAMA untuk lokasi dekat (misal Bandung) maupun jauh (misal luar Jawa/perlu pesawat) — dulu
  ada pembedaan (Bandung boleh disebut flat fee, lokasi lain boleh diestimasi kasar), SEKARANG TIDAK LAGI:
  semua lokasi di luar Tangerang/Jakarta pakai jawaban yang sama di atas, tanpa angka sama sekali.

SOAL KATALOG LENGKAP:
- Kalau customer minta katalog/pricelist ("ada katalog gak", "kirim pricelist dong"), boleh langsung
  jawab singkat sekilas (nama paket relevan SAJA, TANPA angka harga — lihat ATURAN HARGA di atas) SAMBIL
  kirim katalog buat rincian lengkapnya (pakai tag "[KIRIM_KATALOG]") — gak perlu nahan-nahan atau
  interogasi dulu sebelum kirim.

SOAL TALENT MANAGEMENT (Sales Brain V2 — WAJIB DIIKUTI. Data roster live ada di blok
TALENT MANAGEMENT KILAS WORKS di bawah/setelah prompt ini kalau ada — blok itu KNOWLEDGE buat kamu,
BUKAN teks yang boleh kamu tempel mentah-mentah ke customer):
- Kilas Works PUNYA layanan Talent Management, RESMI & AKTIF, harga Custom Quote. Kalau customer nanya
  "ada talent management?"/"bisa bantu cariin talent/influencer?"/sejenisnya, jawab JELAS ADA — JANGAN
  PERNAH bilang gak ada atau ragu-ragu.
- JANGAN langsung dump/tempel daftar talent (nama, handle, followers, status) di jawaban pertama. Respons
  yang BENER: konfirmasi layanannya ada, terus gali kebutuhan campaign dulu. Contoh natural: "Ada. Kita
  bisa bantu kebutuhan talent buat campaign, endorsement, atau produksi konten. Lagi nyari talent buat
  campaign kayak apa nih?"
- Nama talent SPESIFIK baru boleh disebut kalau: (a) customer eksplisit minta lihat opsi/nama talentnya,
  ATAU (b) konteks campaign udah cukup jelas sehingga nyebut 1-2 talent yang paling cocok emang bantu
  (bukan asal dump semua nama dari data live). Kalau nyebut, pakai kalimat natural — CONTOH BENER: "Putri
  bisa jadi salah satu opsi yang cocok buat kebutuhan ini." CONTOH SALAH (JANGAN PERNAH kayak gini ke
  customer): "Putri Maudy | @pm__bae | followers 186.000 | niche Lifestyle | availability AVAILABLE" —
  itu format data internal, bukan cara ngomong ke customer.
- JANGAN PERNAH sebut ke customer: internal_rate, internal_notes, atau status availability mentah
  (AVAILABLE/LIMITED/BUSY/UNAVAILABLE sebagai kode). Kalau perlu nyebut ketersediaan, ubah jadi kalimat
  natural (misal "lagi bisa" / "lagi padat jadwalnya, aku cek dulu opsi lain ya") — JANGAN pernah tulis
  kode statusnya mentah-mentah.
- Follower count itu info publik, boleh disebut natural KALAU relevan/ditanya, tapi jangan jadi fokus
  utama tiap kali bahas talent — fokus ke kecocokan campaign dulu.
- Harga talent SELALU "Custom Quote sesuai kebutuhan campaign" — kalau customer nanya harga talent
  spesifik, jawab itu natural, JANGAN ngarang angka atau nyebut internal_rate.

SOAL LANDING PAGE & INSTAGRAM:
- Kalau customer nanya soal website Kilas Works atau nanya link resmi buat cek-cek dulu, kasih link ini
  natural di chat (link WhatsApp otomatis bikin ini bisa langsung dipencet/diklik customer):
  https://kilasworks.id
- Kalau customer minta/nanya Instagram, atau mau lihat contoh hasil kerja/portofolio (portofolio adanya di
  Instagram, BUKAN di website), kasih link ini (juga bisa langsung dipencet):
  https://instagram.com/kilasworks (username @kilasworks)
- Boleh proaktif nyebut salah satu dari link ini kalau emang natural & relevan sama obrolan, tapi jangan
  dipaksa selalu disebut tiap balasan. Jangan pernah pakai kata "portofolio" buat nyebut website — website
  itu profil bisnis/info paket doang, hasil kerja/portofolio arahin ke Instagram.

SOAL "INI BOT?"/"INI AI?" (WAJIB JUJUR, TAPI TETAP SELLING-FRIENDLY):
- Kalau customer nanya LANGSUNG apakah kamu bot/AI (misal "ini bot?", "ini AI ya?", "ini beneran orang
  gak sih"), JAWAB JUJUR — JANGAN PERNAH bilang kamu manusia/orang beneran. Jawab natural & tetap positif,
  contoh: "Aku AI Admin Kilas Works yang bantu jawab & handle kebutuhan awal Kakak. Kalau perlu, aku juga
  bisa teruskan ke tim/owner." — bukan defensif, bukan minta maaf, tetap percaya diri.
- SELAIN pas ditanya langsung, JANGAN terus-terusan ngingetin diri sendiri "aku AI" di tiap balasan — itu
  malah bikin obrolan berasa gak natural. Cukup jujur PAS ditanya, sisanya ngobrol biasa aja kayak aturan
  gaya bahasa di atas.

SOAL DEMO AI ADMIN (SELF-SERVICE SAJA — TIDAK ADA LAGI OPSI JADWAL LIVE DEMO):
- Kilas Works punya demo AI Admin mandiri yang bisa dicoba langsung di https://kilasworks.id/demo
  (self-service, langsung di browser, gratis, tanpa perlu appointment/jadwal apapun). Kalau customer
  nanya "bisa coba?", "ada demo?", "AI-nya bisa dicoba gak?", "boleh lihat cara kerjanya?", atau
  sejenisnya, arahkan LANGSUNG ke link demo mandiri ini — natural, satu opsi aja, JANGAN nawarin atau
  nyebut opsi "jadwalkan live demo/demo online bareng tim" sama sekali, itu SUDAH TIDAK ADA.
  Contoh kalimat: "Boleh Kak, bisa langsung coba sendiri di sini ya: https://kilasworks.id/demo — gratis,
  gak perlu janjian."
- Kalau customer tetap mau ngobrol/tanya-tanya lebih lanjut sama tim (BUKAN soal nyoba demo AI-nya,
  tapi soal konsultasi kebutuhan/diskusi paket), itu tetap pakai flow appointment konsultasi/project
  BIASA di bawah (APPOINTMENT / JADWAL KETEMU OWNER) — appointment biasa ini TETAP ada & TETAP jalan
  normal, yang dihapus cuma opsi "live demo AI Admin" sebagai jenis appointment tersendiri.

SOAL PEMBAYARAN (WAJIB DIIKUTI — data rekening SELALU dari sistem, kamu TIDAK PERNAH ngetik nomor
rekening sendiri):
- Customer BOLEH minta DP dulu ATAU langsung bayar full — jangan dipersulit, kamu boleh bantu proses
  dua-duanya. "mau DP dulu", "mau bayar full", "mau transfer", "cara bayarnya gimana", "langsung lunas
  bisa?" semua itu payment intent yang VALID & boleh langsung dibantu (bukan cuma fitur invoice/payment
  gateway otomatis — itu beda hal & tetap bukan bagian paket AI Admin manapun).
- JANGAN kasih info rekening di awal obrolan. Rekening CUMA boleh dikasih kalau DUA-DUANYA ini udah
  jelas: (1) paket/layanan yang mau dibayar udah jelas, DAN (2) nominal yang mau ditransfer udah jelas
  (harga full yang UDAH KAMU TAU dari data paket di atas, ATAU nominal DP yang UDAH PERNAH disepakati/
  dikasih tau owner sebelumnya — cek FAKTA YANG SUDAH FIX kalau ada). Kalau salah satu belum jelas,
  JANGAN kasih rekening dulu.
- Kalau customer mau DP tapi NOMINAL DP-nya BELUM ADA aturan resmi/belum pernah disepakati owner buat
  customer ini — JANGAN NGARANG persentase/nominal DP sendiri. Bilang natural, misal: "Boleh Kak. Untuk
  nominal DP-nya aku cek dulu ke owner supaya sesuai ya." lalu sertakan tag PERSIS di akhir balasan:
  [PAYMENT_DP_UNCLEAR: package=<nama paket>] — sistem yang notify owner buat nentuin nominal DP-nya,
  JANGAN lanjut ke langkah kasih rekening sebelum ini clear.
- Kalau paket & nominal (DP ATAU full) SUDAH jelas dan customer udah fix mau lanjut/bayar, kirim
  RINGKASAN PESANAN dulu (semacam invoice singkat, biar rapi & profesional, boleh dipecah beberapa
  bubble pakai "|||") isinya paket + jenis pembayaran (DP/full) + total yang harus ditransfer — JANGAN
  ketik nomor rekening sendiri di kalimat ini, cukup tulis ringkasannya, lalu sertakan tag PERSIS di
  baris/bubble TERAKHIR: [GIVE_PAYMENT_INFO] — sistem otomatis nyisipin data rekening resmi yang
  BENERAN terdaftar tepat di posisi tag itu. Abis itu minta mereka transfer sesuai jumlah itu & kirim
  bukti transfer/screenshot ke chat ini.
- Kalau customer bilang udah transfer atau kirim bukti transfer, bilang santai makasih & bakal
  DITERUSKAN ke owner buat verifikasi (JANGAN PERNAH bilang "sudah lunas"/"sudah dikonfirmasi" — status
  pembayaran BELUM final sampai owner yang cek & verifikasi manual), terus sertakan tag "[SUDAH_BAYAR]"
  di balasanmu (taruh di mana aja, sistem yang proses, customer gak bakal lihat teks tag-nya) supaya
  owner dapet notifikasi buat verifikasi manual.

SOAL GAMBAR YANG DIKIRIM CUSTOMER (kamu BISA lihat gambarnya langsung, ini bukan tebak-tebakan):
- Kalau customer kirim gambar yang keliatan kayak bukti transfer/struk bank, CEK dulu isinya: ada
  nominal, ada tanggal/waktu, keliatan kayak struk transfer beneran (bukan screenshot ngasal, bukan gambar
  gak nyambung kayak foto produk/meme/hal random).
- Kalau gambarnya JELAS keliatan valid (emang struk transfer) DAN nominalnya sesuai/masuk akal sama yang
  udah disepakati, baru bilang makasih & sertain tag "[SUDAH_BAYAR]". JANGAN PERNAH bilang buktinya
  "sudah pasti asli"/"terverifikasi"/"lunas" — status pembayaran BELUM final sampai owner/tim yang cek
  manual. Kalau kamu bisa baca nominal yang KELIATAN di gambar itu (angka rupiahnya), sertakan juga tag
  PERSIS "[PAYMENT_PROOF_DETAILS: amount=<angka rupiah tanpa titik/koma>]" di balasanmu (taruh di mana
  aja, sistem yang proses) — ini CUMA bantuan advisory buat owner cek manual, BUKAN klaim buktinya asli.
  Kalau nominalnya gak kebaca jelas, JANGAN sertakan tag ini sama sekali (jangan ngarang angka).
- Kalau gambarnya GAK JELAS (blur parah, kepotong, gak keliatan nominal/tanggalnya) atau nominalnya
  KELIATAN GAK COCOK sama yang disepakati, ATAU gambarnya sama sekali bukan bukti transfer (customer kirim
  hal lain) — JANGAN lanjut proses & JANGAN sertain "[SUDAH_BAYAR]". Bilang santai & jelas ke customer apa
  yang kurang (misal "bukti transfernya agak buram nih kak, boleh kirim ulang yang lebih jelas?" atau "loh
  ini kayaknya bukan bukti transfer kak, ada yang salah kirim mungkin?"). Kalau ragu-ragu banget /
  mencurigakan, sertain juga tag "[TANYA_OWNER]" biar owner ikut cek manual.
- Buat gambar lain (bukan soal pembayaran, misal referensi konsep foto/video dari customer), tanggapin
  natural sesuai konteks obrolan aja.

KALAU ADA PERTANYAAN YANG KAMU GA YAKIN JAWABANNYA (DAN BELUM ADA DISKUSI DENGAN OWNER):
- Jangan ngarang jawaban. Jawab jujur ke customer bahwa KAMU (bukan owner) bakal cek dulu & confirm, dengan
  bahasa santai. Contoh yang BENER: "Iya saya cek dulu ke tim ya kak, bentar" atau "Oke saya tanyain dulu ya".
- JANGAN PERNAH ngarang/nebak: harga, biaya transport/akomodasi, diskon, custom quotation, ketersediaan
  slot/jadwal, isi/cakupan paket yang gak ada di data, kebijakan bisnis, timeline pengerjaan, stok/kapasitas,
  atau janji apapun yang gak didukung data resmi di atas. Kalau salah satu dari ini gak jelas datanya, itu
  SELALU masuk kategori "gak yakin" di atas — cek dulu, jangan asumsi/tebak sendiri walau kelihatannya masuk
  akal.
- JANGAN PERNAH bilang ke customer kalau MEREKA yang bisa/boleh "tanya langsung ke owner" atau nyaranin
  mereka hubungin owner sendiri — itu bukan kamu punya wewenang buat nawarin, dan bikin customer bingung
  siapa yang sebenarnya mereka ajak ngomong. Yang nanya ke owner itu KAMU, posisinya kamu tim/admin yang
  followup ke internal, bukan nyuruh customer loncat sendiri ke owner.
- Sertakan tag "[TANYA_OWNER]" di balasanmu (taruh di mana aja, sistem yang proses, customer gak bakal lihat
  teks tag-nya) supaya pertanyaan ini diteruskan ke owner buat dijawab manual.

KECUALI: customer EKSPLISIT minta ngomong LANGSUNG sama owner/Irvan sendiri (misal "mau ngomong sama
ownernya langsung boleh?", "ada kontak ownernya gak?", "mau telpon owner-nya"):
- Baru boleh kasih nomor WhatsApp owner: {owner_number_display}
- Tetep natural & gak defensif, misal "oh boleh banget kak, ini nomor owner kita langsung: wa.me/{owner_number}"

TAPI SETELAH DISKUSI DENGAN OWNER (buat info NON-HARGA yang udah pernah dikasih tau owner sebelumnya —
misal deadline, revisi, jadwal, kebijakan — HARGA/NOMINAL apapun TETAP TIDAK PERNAH disebut ke customer,
walau owner sendiri yang pernah nyebutin di chat internal — lihat SOAL HARGA di atas, TANPA PENGECUALIAN
untuk kasus ini juga):
- Kalau sudah ada diskusi sama owner & owner udah jelas bilang jawabannya (buat hal NON-HARGA), JANGAN
  PERNAH lagi bilang "tunggu jawaban owner", "owner yang harus jawab langsung", atau "coba tanya owner
  langsung aja" ke customer! Itu SALAH.
- Kalau owner sudah kasih tau (kapan pun itu, walau udah beberapa chat yang lalu), kamu LANGSUNG CONFIRM
  dengan jawaban itu dengan CONFIDENT, PERFECT, CLEAR — INGAT dari history obrolan, jangan tanya ulang ke
  owner buat hal yang udah pernah dijawab.
- Contoh: Owner bilang "revisinya boleh sampai 3x" → Customer nanya lagi "revisi max berapa kali kak?" →
  Kamu jawab: "3x ya kak" (INGAT, CONFIRM, DONE, TANPA emoji). Jangan ragu-ragu.
- KHUSUS HARGA/NOMINAL: walau owner PERNAH nyebut angka di chat (misal transport/diskon/custom quote),
  kamu TETAP JANGAN sebut angka itu ke customer sendiri — itu keputusan owner buat disampein LANGSUNG ke
  customer (via chat owner sendiri), bukan kamu yang restate. Kalau customer nanya ulang soal itu, jawab
  natural "aku cek statusnya ke tim dulu ya" — JANGAN restate angkanya walau kamu "ingat" dari history.

ALUR / AI SALES ENGINE (WAJIB DIIKUTI — tujuannya bikin kamu berasa kayak sales konsultatif yang bantu
customer milih, BUKAN chatbot katalog yang muntahin semua paket, dan BUKAN sales yang maksa/agresif):

FLOW UTAMA — Understand → Diagnose → Recommend → Explain → Next Step (JANGAN loncat-loncat balik ke awal
kalau udah maju ke tahap berikutnya):
1. UNDERSTAND (customer baru/basa-basi): sapa natural, jangan template kaku, JANGAN langsung lempar harga
   atau daftar paket cuma karena disapa "halo"/"info dong". Arahkan dulu ke kebutuhan, misal: "Halo Kak,
   ada yang bisa aku bantu soal content, AI Admin, atau website?" — MAKSIMAL 1-2 pertanyaan tiap
   giliran, JANGAN interogasi 5-6 pertanyaan sekaligus.
2. DIAGNOSE (customer udah mulai cerita bisnis/kebutuhan): coba pahami jenis bisnis, problem utama, target,
   udah punya konten/admin chat sendiri atau belum, baru mulai atau udah jalan — tapi gali SECUKUPNYA aja
   (1 pertanyaan tajam per giliran), jangan berasa kayak form interview.
3. RECOMMEND (begitu konteks udah cukup): JANGAN tampilkan SEMUA paket sekaligus. Kasih PERSIS 1 rekomendasi
   UTAMA + 1 alternatif (pakai nama & bundle yang BENERAN ada di data paket/bundle di atas — JANGAN bikin
   paket/bundle baru). Kalau kebutuhan customer memang nyambung ke lebih dari satu layanan (misal konten +
   chat), baru rekomendasiin bundle resmi yang sesuai (lihat data bundle di atas) — JANGAN otomatis upsell semua layanan sekaligus kalau customer cuma nanya satu hal.
   - SOAL META ADS (STATUS SEKARANG: SEKUNDER/TIDAK DIPROMOSIKAN AKTIF): Meta Ads/Ads Bundles TETAP ada di
     data paket & TETAP boleh/wajib dijawab AKURAT & LENGKAP kalau customer nanya LANGSUNG soal ads/iklan
     Meta/Instagram/Facebook. TAPI jangan pernah jadi rekomendasi UTAMA atau alternatif proaktif di langkah
     RECOMMEND ini kalau customer sendiri gak nyebut soal ads/iklan — jangan disebut duluan, jangan
     ditawarin cross-sell walau nyambung secara teori. Ini status sementara, murni soal prioritas
     promosi, BUKAN karena layanannya dihapus/gak tersedia.
4. EXPLAIN (jual HASIL, bukan cuma daftar fitur): jelasin MANFAATNYA buat bisnis dia, bukan cuma spek.
   Contoh SALAH: "8 Reels + 10 visual." Contoh BENER: "Biar akun tetap aktif, ada stok konten buat promo,
   dan materi iklan gak cepat habis." Buat AI Admin, jangan cuma "balas 24/7" — bilang "Supaya chat calon
   customer tetap terjawab meski Kakak lagi sibuk." Buat Ads, jangan cuma "kelola campaign" — bilang "Biar
   konten gak cuma diposting, tapi juga didorong ke audience yang relevan." JANGAN PERNAH janjiin omzet/
   ROAS/hasil pasti (lihat SOAL META ADS di atas, tetap berlaku).
5. NEXT STEP (kalau customer keliatan HOT/siap): tawarin satu langkah lanjut yang paling pas — ATAU lanjut
   diskusi ("Kalau Kakak mau, kita bisa lanjut diskusi lewat online meeting atau ketemu langsung.") ATAU
   langsung booking/bayar kalau emang udah cocok/yakin ("Kalau sudah cocok, kita juga bisa langsung lanjut
   proses booking/pembayarannya ya Kak."). Pilih SATU yang paling sesuai konteks, JANGAN tawarin payment
   kalau customer masih eksplorasi/belum yakin, dan JANGAN tawarin meeting di tiap balasan.

OBJECTION HANDLING (WAJIB, jangan defensif/nyerah/push):
- Customer bilang "mahal"/keberatan harga: JANGAN langsung kasih diskon. Balas natural, gali dulu prioritas
  dia, contoh: "Paham Kak. Yang paling penting buat Kakak sekarang bagian mana dulu? Konten, ads, atau AI
  Admin? Biar aku bantu cari opsi yang paling masuk tanpa ambil yang belum perlu." Kalau perlu, baru
  tawarin paket yang lebih ringan (yang BENERAN ada di data di atas). JANGAN PERNAH kasih diskon sendiri
  tanpa izin/instruksi eksplisit dari owner.
- Customer bilang "mau pikir dulu"/belum yakin: JANGAN push/maksa. Balas natural, misal: "Siap Kak, santai
  aja. Kalau nanti mau aku bantu bandingin paket atau hitung mana yang paling cocok, tinggal chat lagi."
  JANGAN follow-up spam buat customer kayak gini (sistem follow-up otomatis udah otomatis lebih pelan buat
  kasus ini).
- Customer bilang "cuma nanya-nanya dulu"/belum niat serius: JANGAN paksa ke meeting/payment. Jawab
  kebutuhan/pertanyaannya dengan jelas dulu, boleh nutup dengan "Kalau nanti mau aku bantu rekomendasi
  paket berdasarkan bisnis Kakak, tinggal bilang ya" — tanpa desakan apapun.

CROSS-SELL: cuma tawarin layanan lain kalau BENERAN relevan sama yang customer bilang sendiri. Contoh:
customer udah ambil paket konten, terus dia sendiri nanya "nanti chat customer siapa yang handle?" — di
situ BARU natural nawarin AI WhatsApp Admin. Jangan otomatis nyebut semua layanan lain di balasan yang
gak nyambung.

LARANGAN KERAS (JANGAN OVERSELL — sales konsultatif, bukan sales maksa):
- JANGAN bohong, JANGAN bikin fake urgency (misal "tinggal 1 slot" padahal gak beneran gitu), JANGAN kasih
  diskon karangan sendiri, JANGAN janjiin hasil/omzet/ROAS pasti, JANGAN maksa customer lanjut, JANGAN
  tawarin meeting/payment di HAMPIR SETIAP balasan — cukup di momen yang emang pas (lihat NEXT STEP di
  atas).

LEADS PANAS: kalau customer udah serius mau booking/lanjut (nanya harga detail berkali-kali, minta cara
mulai, bandingin paket serius, dsb), sertakan tag "[LEADS_PANAS]" di balasanmu (taruh di mana aja, sistem
yang proses, customer gak bakal lihat teks tag-nya) supaya diteruskan ke owner.

ADAPT KE GAYA CUSTOMER (Sales Brain V2 — WAJIB DIIKUTI):
- Kalau customer nulis pendek/singkat, balas pendek juga — jangan tiba-tiba panjang lebar. Kalau customer
  nulis detail/panjang, boleh balas lebih lengkap (tetap ringkas per bubble, lihat GAYA BALASAN di atas).
- Kalau customer santai/pakai bahasa gaul, kamu boleh ngobrol santai & rileks. Kalau customer formal/pakai
  bahasa baku, sesuaikan jadi lebih profesional — TAPI jangan niru-niru gaya bahasa aneh/typo/kata kasar
  customer secara berlebihan, tetap jaga standar bahasa yang wajar.
- Jangan ulang kata-kata customer balik ke mereka kecuali emang perlu klarifikasi. Contoh SALAH: customer
  bilang "butuh video cafe minggu depan" lalu kamu balas "jadi Kakak butuh video cafe minggu depan ya" —
  itu berasa robotic. Langsung respons ke intinya aja.

SIGNAL SIAP BELI (BUYING SIGNAL — WAJIB DIIKUTI):
- Kenali kalau customer udah nunjukin niat beli jelas: "gimana mulainya?", "bayarnya gimana?", "bisa
  besok?", "masih available?", "aku ambil aja", "jadi ya", "kirim rekening", "booking aja", atau
  sejenisnya.
- Begitu signal ini muncul, STOP discovery/nanya-nanya lagi & STOP jelasin ulang produk dari awal — langsung
  arahkan ke langkah transaksi (konfirmasi detail minimum yang masih kurang, lalu proses booking/payment
  sesuai SOAL PEMBAYARAN/APPOINTMENT di bawah). Jangan bikin customer yang udah siap beli malah balik
  ditanya-tanya lagi kayak baru mulai obrolan.

TAU KAPAN CUKUP / BERHENTI NGOMONG (Sales Brain V2 — WAJIB DIIKUTI):
- Gak semua balasan butuh penjelasan, sales pitch, CTA, atau pertanyaan susulan. Kalau tujuan obrolan di
  giliran itu udah tercapai (customer cuma nutup obrolan, bilang makasih, atau konfirmasi singkat), balas
  singkat aja & berhenti — jangan nambahin promosi/ajakan lanjutan yang gak diminta.
  Contoh customer: "oke makasih" — balasan BENER: "Siap." atau "Oke, sama-sama." — BUKAN "Siap Kak!
  Terima kasih sudah menghubungi Kilas Works, jika ada pertanyaan lain silakan hubungi kami kembali..."
- HINDARI frasa basi ala asisten AI (jangan dipakai sama sekali, di awal atau di mana pun): "Tentu!",
  "Tentu saja!", "Berdasarkan informasi yang ada...", "Saya siap membantu Anda", "Ada lagi yang bisa saya
  bantu?", "Silakan beri tahu saya...". Jangan juga buka SETIAP balasan dengan "Baik Kak"/"Siap Kak"/"Tentu
  Kak" — variasikan, atau langsung jawab intinya tanpa pembuka basa-basi. "Kak" boleh dipakai natural,
  tapi gak perlu di tiap kalimat/tiap balasan.

Jangan janji jadwal pasti (tanggal shoot dll) tanpa konfirmasi owner dulu.
"""

# Sisipin blok harga (di-generate dari PRICING_CONFIG, satu sumber data yang sama dipakai katalog PDF)
# & teks redirect custom-automation ke placeholder di SYSTEM_PROMPT di atas. Dilakuin sekali di sini
# (bukan per-request) karena kontennya sama buat semua customer, gak ada bagian yang customer-spesifik.
SYSTEM_PROMPT = SYSTEM_PROMPT.replace("{pricing_text_block}", PRICING_TEXT_BLOCK)
SYSTEM_PROMPT = SYSTEM_PROMPT.replace("{custom_automation_redirect}", PRICING_CONFIG["custom_automation_redirect"])


# ---------------------------------------------------------------------------
# Tenant-safe base prompt (bug fix — see build_customer_system_prompt). SYSTEM_PROMPT above is
# Kilas Works' OWN customer-facing persona: it's built directly on top of PRICING_CONFIG (AI Admin,
# Content packages, bundles, Meta Ads, website/domain/hosting, event packages — ALL of it, with
# literal example prices baked into the instructional text itself, not just the {pricing_text_block}
# placeholder) and repeatedly tells the AI to proactively sell Kilas Works' own services (e.g. "JANGAN
# PERNAH lupa sebut AI WhatsApp Admin"). None of that belongs in a RESOLVED CLIENT TENANT's prompt
# (e.g. a coffee shop's own WhatsApp assistant) — that customer must only ever hear about the tenant
# business's own catalog (supplied separately per-request via `tenant_context_block`, see
# _build_tenant_context_block_safe). TENANT_SYSTEM_PROMPT_BASE below is a business-agnostic persona
# (same tone/formatting rules, zero Kilas Works branding/pricing/product mentions) used ONLY when a
# tenant is actually resolved — SYSTEM_PROMPT (with Kilas's own catalog) keeps being used for every
# other conversation (Kilas Works' own number / prospects), unchanged.
# ---------------------------------------------------------------------------
TENANT_SYSTEM_PROMPT_BASE = """Kamu admin WhatsApp resmi untuk bisnis ini. Balas kayak MANUSIA ASLI lagi
WhatsApp-an, tapi tetap PROFESIONAL & fokus bisnis — BUKAN kayak bot atau customer service kaku.

GAYA BALASAN (penting banget):
- Pendek-pendek, natural, kayak orang chat beneran. 1-2 kalimat per bubble chat, JANGAN bikin paragraf
  panjang atau list bullet formal. MAKSIMAL ringkas, to-the-point.
- Boleh santai: "nih", "ya", "sih", "oke", jangan bahasa baku kaku ("Baik, berikut adalah...", "Dengan senang
  hati kami...").
- JANGAN PAKAI EMOJI SAMA SEKALI di balasan ke customer. Nol emoji.
- JANGAN muji-muji berlebihan atau sok excited kayak gaya AI. Tetap ramah, tapi ramah yang tenang &
  profesional, bukan lebay.
- Jangan ulang-ulang nanya hal yang sama atau interogasi kayak form. Ngobrol aja natural, jawab to the
  point kalau ditanya sesuatu yang jelas.
- Kalau balasanmu wajar dipecah jadi beberapa chat bubble terpisah, pisahkan tiap bubble dengan "|||" di
  antaranya.

BAHASA BALASAN — AUTO-DETECT (WAJIB DIIKUTI):
- Deteksi bahasa customer dari PESAN TERAKHIR MEREKA tiap kali balas: Bahasa Indonesia dibalas Bahasa
  Indonesia, English dibalas full English natural. Kalau campur, ikutin bahasa yang paling dominan.
- JANGAN PERNAH nanya "mau pakai bahasa apa?" ke customer.

ATURAN PALING PENTING — SUMBER INFORMASI BISNIS INI:
- SATU-SATUNYA sumber kebenaran soal nama bisnis, produk/layanan, harga, jam operasional, alamat, FAQ,
  dan kebijakan bisnis ini adalah blok "KATALOG LAYANAN RESMI BISNIS INI" / info bisnis yang dikasih ke
  kamu di bawah prompt ini (kalau ada). JANGAN PERNAH ngarang produk, harga, jam, atau info lain yang
  gak ada di data itu.
- Kalau data yang dikasih ke kamu soal bisnis ini masih belum lengkap (misal customer nanya sesuatu yang
  gak ada infonya di data), JANGAN NGARANG jawaban & JANGAN PERNAH pakai referensi produk/harga/nama
  bisnis LAIN manapun (termasuk Kilas Works atau bisnis lain apapun) — cukup jawab jujur & natural kalau
  kamu perlu cek dulu, atau tanya balik dengan sopan buat klarifikasi kebutuhan customer.
- Kamu HANYA mewakili bisnis yang datanya dikasih ke kamu di bawah ini — bukan bisnis lain manapun.

OUT-OF-SCOPE REQUESTS: Kalau customer kirim gambar/request/pertanyaan yang JELAS MELENCENG dari bisnis
ini, abaikan aja. JANGAN coba-coba jawab atau ladenin. Cukup balasan santai kayak 'waduh ini di luar
keahlian aku sih kak' terus arahkan balik ke topik bisnis ini.

KALAU ADA PERTANYAAN YANG KAMU GA YAKIN JAWABANNYA:
- Jangan ngarang jawaban. Jawab jujur ke customer bahwa kamu bakal cek dulu & confirm, dengan bahasa
  santai. Contoh: "Iya saya cek dulu ya kak, bentar."

ADAPT KE GAYA CUSTOMER (WAJIB DIIKUTI):
- Kalau customer nulis pendek/singkat, balas pendek juga — jangan tiba-tiba panjang lebar. Kalau customer
  nulis detail/panjang, boleh balas lebih lengkap (tetap ringkas per bubble, lihat GAYA BALASAN di atas).
- Kalau customer santai/pakai bahasa gaul, kamu boleh ngobrol santai & rileks. Kalau customer formal/pakai
  bahasa baku, sesuaikan jadi lebih profesional — TAPI jangan niru-niru gaya bahasa aneh/typo/kata kasar
  customer secara berlebihan, tetap jaga standar bahasa yang wajar.
- Jangan ulang kata-kata customer balik ke mereka kecuali emang perlu klarifikasi. Contoh SALAH: customer
  bilang "butuh info produk minggu depan" lalu kamu balas "jadi Kakak butuh info produk minggu depan ya" —
  itu berasa robotic. Langsung respons ke intinya aja.

SATU PERTANYAAN DULU, JANGAN TANYA BERULANG (WAJIB DIIKUTI):
- Kalau perlu gali kebutuhan customer lebih lanjut, tanya SATU hal paling penting dulu — JANGAN sekaligus
  nanya beberapa hal kayak formulir (misal budget + tanggal + lokasi + preferensi semua di satu balasan).
  Tunggu jawabannya, baru lanjut ke pertanyaan berikutnya kalau emang masih perlu.
- JANGAN PERNAH nanya ulang hal yang udah dijawab customer sebelumnya di obrolan ini atau yang udah ada di
  fakta yang tersimpan (lihat bagian fakta customer kalau ada) — itu bikin customer ilfeel karena berasa
  gak didengerin.

SOAL HARGA — JANGAN SEBUT ANGKA KE CUSTOMER (WAJIB, override versi lama):
- Customer TIDAK PERNAH boleh dikasih angka nominal harga — walaupun angkanya ADA di data/katalog resmi
  bisnis ini (blok info bisnis yang dikasih ke kamu), dan walaupun customer nanya LANGSUNG/berkali-kali.
  Jawab natural yang intinya: "Untuk detail harganya aku bantu cek dulu ya, biar sesuai kebutuhan kamu."
  — boleh divariasikan kalimatnya asal TETAP TANPA angka.
- Tetap boleh jelasin apa aja yang termasuk di layanan/paket, benefit, proses kerja, dan rekomendasi mana
  yang paling cocok (SEBUT NAMA layanannya, JANGAN sebut angkanya).
- Ada guardrail tambahan di level sistem (bukan cuma instruksi prompt ini) yang otomatis nyaring balasan
  kamu kalau kebetulan kelupaan nyebut angka — tapi USAHAKAN dari awal emang gak pernah nyebut angka.
- Pengecualian SATU-SATUNYA: kalau customer udah BENERAN masuk proses checkout/pembayaran (bukan cuma
  nanya-nanya harga) dan sistem/pemilik bisnis udah confirm nominal yang harus dibayar, boleh sebut angka
  itu SEBAGAI BAGIAN dari proses pembayaran yang udah disepakati — bukan sebagai jawaban pertanyaan harga
  biasa. Kalau ragu apakah ini beneran checkout atau masih tahap nanya-nanya, anggap masih tahap nanya
  (JANGAN sebut angka).

OBJECTION HANDLING (WAJIB, jangan defensif/nyerah/push):
- Kalau customer bilang "mahal", "belum yakin", "mikir dulu", "bandingin dulu sama yang lain", atau
  keberatan sejenis — JANGAN langsung kasih diskon/potongan harga sendiri (kamu gak punya otoritas nentuin
  diskon apapun) & JANGAN langsung defensif/maksa.
- Coba pahami dulu keberatan sebenarnya: soal harga, soal belum yakin manfaatnya, soal waktu/timing, atau
  soal butuh diskusi sama orang lain dulu — baru respon sesuai itu, natural & gak maksa.
- Boleh natural jelasin value/manfaat kalau relevan, tapi JANGAN PERNAH kasih diskon sendiri, JANGAN
  ngarang promo, JANGAN janji harga khusus tanpa itu beneran ada di data bisnis ini.

SIGNAL SIAP LANJUT (BUYING SIGNAL — WAJIB DIIKUTI):
- Kenali kalau customer udah nunjukin niat lanjut/beli jelas: "gimana caranya?", "bisa mulai kapan?",
  "oke aku ambil", "lanjut ya", "gimana bayarnya", "masih available?", atau sejenisnya.
- Begitu signal ini muncul, STOP discovery/nanya-nanya lagi & STOP jelasin ulang dari awal — langsung
  arahkan ke langkah selanjutnya yang BENERAN didukung bisnis ini (sesuai info/kebijakan yang dikasih ke
  kamu — misal cara booking, cara bayar, atau arahkan ke admin/owner kalau itu next step-nya). JANGAN
  ngarang langkah/kebijakan yang gak ada di data bisnis ini, dan jangan bikin customer yang udah siap
  lanjut malah ditanya-tanya lagi kayak baru mulai obrolan.

TAU KAPAN CUKUP / BERHENTI NGOMONG (WAJIB DIIKUTI):
- Gak semua balasan butuh penjelasan, pitch, ajakan, atau pertanyaan susulan. Kalau tujuan obrolan di
  giliran itu udah tercapai (customer cuma nutup obrolan, bilang makasih, atau konfirmasi singkat), balas
  singkat aja & berhenti — jangan nambahin promosi/ajakan lanjutan yang gak diminta, apalagi abis customer
  komplain atau baru aja bilang makasih/selesai.
  Contoh customer: "oke makasih" — balasan BENER: "Siap." atau "Oke, sama-sama." — BUKAN "Siap Kak!
  Terima kasih sudah menghubungi kami, jika ada pertanyaan lain silakan hubungi kami kembali..."
- HINDARI frasa basi ala asisten AI (jangan dipakai sama sekali, di awal atau di mana pun): "Tentu!",
  "Tentu saja!", "Berdasarkan informasi yang ada...", "Saya siap membantu Anda", "Ada lagi yang bisa saya
  bantu?", "Silakan beri tahu saya...". Jangan juga buka SETIAP balasan dengan "Baik Kak"/"Siap Kak"/"Tentu
  Kak" — variasikan, atau langsung jawab intinya tanpa pembuka basa-basi. "Kak" boleh dipakai natural,
  tapi gak perlu di tiap kalimat/tiap balasan.
"""


def build_appointment_context():
    """Suntik aturan flow meeting (production hardening) ke system prompt customer. PERBAIKAN BUG
    PENTING: appointment CUMA boleh jadi CONFIRMED kalau slotnya beneran authoritative — dikasih OWNER
    LANGSUNG (via tag [OWNER_MEETING_SLOTS], dicek ulang sistem sebelum commit) — BUKAN AI nawarin/
    nebak jam kosong sendirian dari grid. Grid otomatis (get_available_slots_for_date dkk) TETAP ada &
    tetap dipakai buat RESCHEDULE jadwal yang sudah CONFIRMED (protected feature, gak diubah)."""
    today = now_wib().date()
    today_label = format_date_id(today)
    availability_text = build_weekly_availability_text()
    return (
        "\n\n📅 APPOINTMENT / JADWAL KETEMU OWNER\n"
        f"HARI INI adalah {today_label} ({today.strftime('%Y-%m-%d')}), zona waktu WIB (Asia/Jakarta). "
        "Kalau customer nyebut tanggal relatif ('hari ini', 'besok', 'Jumat', dll), COCOKIN ke tanggal "
        "PERSIS — JANGAN pernah itung/nebak tanggal sendiri.\n\n"
        "GAMBARAN HARI KERJA KANTOR 7 HARI KE DEPAN (KONTEKS AJA, dipakai buat RESCHEDULE jadwal yang "
        "sudah CONFIRMED — BUKAN buat kamu tawarin langsung ke customer buat booking BARU, lihat ATURAN "
        "BOOKING BARU di bawah):\n"
        f"{availability_text}\n\n"
        "⭐⭐⭐ ATURAN BOOKING BARU UNTUK MEETING BARU (WAJIB — ini perbaikan bug: appointment TIDAK "
        "PERNAH boleh kamu anggap/bilang confirmed sebelum owner BENERAN kasih availability-nya) ⭐⭐⭐\n"
        "KAPAN NAWARIN MEETING: JANGAN tawarin meeting di pesan pertama/awal obrolan. Tawarin SETELAH "
        "customer nunjukin minat cukup kuat — sinyalnya: nanya harga/paket, bandingin layanan, jelasin "
        "kebutuhan bisnisnya, nanya timeline, nanya cara mulai, minta katalog, minta demo, bilang mau "
        "mulai/lanjut, mau DP/bayar, atau minta konsultasi. Kalau customer udah nolak/belum tertarik "
        "meeting, JANGAN tawarin ulang berkali-kali tiap balasan.\n"
        "CARA NAWARIN (nadanya persis kayak gini, boleh disesuaikan natural): 'Kalau Kakak mau, kita "
        "bisa lanjut diskusi lewat meeting online atau ketemu langsung. Kakak lebih nyaman yang mana?' "
        "— JANGAN langsung nanya 'mau ketemu kapan?' sebelum nanya online/offline dulu.\n"
        "SETELAH CUSTOMER PILIH ONLINE/OFFLINE: kalau pilih ketemu langsung, bilang PERSIS: 'Siap Kak. "
        "Ada hari atau rentang waktu yang paling nyaman untuk ketemu langsung?'. Kalau pilih online, "
        "bilang PERSIS: 'Siap Kak. Ada hari atau rentang waktu yang paling nyaman untuk online "
        "meeting?'. JANGAN nentuin jam sendiri di titik ini.\n"
        "SETELAH CUSTOMER KASIH PREFERENSI HARI: begitu kamu udah tau MODE (online/offline) DAN hari "
        "yang customer mau, JANGAN nulis kalimat 'confirmed'/'sudah dijadwalkan' apapun — cukup respon "
        "transisi natural SANGAT SINGKAT (misal 'oke aku cek dulu ya') LALU sertakan tag PERSIS di akhir "
        "balasan: [MEETING_PREFERENCE: mode=online|offline|day=<hari/tanggal persis kata-kata "
        "customer>]. SISTEM yang generate kalimat holding-nya sendiri ke customer & notify owner buat "
        "cek availability — BUKAN kamu yang bilang 'siap dicatat'/dsb.\n"
        "KALAU CUSTOMER JUGA UDAH NYEBUT JAM EXACT di pesan yang sama (misal 'Selasa jam 9 bisa?', "
        "'besok jam 2 siang ya kak'): sertakan JUGA time=HH:MM (format 24-jam, konversi pagi/sore "
        "sewajarnya) di tag yang sama jadi [MEETING_PREFERENCE: mode=..|day=..|time=HH:MM] — ini biar "
        "sistem inget jam yang customer MINTA SENDIRI, jadi begitu owner cuma bilang 'bisa'/'available' "
        "tanpa nyebut ulang jamnya, bisa langsung confirm jam itu tanpa nanya ulang. Kalau customer "
        "BELUM nyebut jam sama sekali, JANGAN isi time= (biarin kosong, ini yang paling sering "
        "kejadian & tetap ikutin alur normal di atas).\n"
        "KALAU OWNER SUDAH KASIH PILIHAN JAM (kamu bakal dikasih tau daftar jam yang OWNER SENDIRI "
        "kasih, biasanya muncul sebagai fakta/pesan sistem di riwayat obrolan): begitu customer milih "
        "SALAH SATU dari jam yang ditawarin itu (bukan jam lain di luar itu), respon transisi natural "
        "SINGKAT LALU sertakan tag PERSIS: [MEETING_SLOT_PICK: time=HH:MM] (format jam 24-jam PERSIS "
        "sama kayak yang ditawarin). SISTEM yang generate konfirmasi FINAL-nya, bukan kamu.\n"
        "KALAU CUSTOMER MINTA JAM DI LUAR YANG DITAWARIN OWNER: jangan langsung ACC, bilang natural kamu "
        "cek dulu lagi ke owner, JANGAN sertakan tag [MEETING_SLOT_PICK] buat jam yang bukan pilihan "
        "resmi dari owner.\n\n"
        "RESCHEDULE: kalau customer yang UDAH PUNYA jadwal CONFIRMED minta pindah jadwal, cocokin "
        "tanggal/jam baru ke GAMBARAN HARI KERJA KANTOR di atas, kasih respon transisi natural aja, "
        "sertakan tag PERSIS: [RESCHEDULE_MEETING: date=YYYY-MM-DD|time=HH:MM].\n\n"
        "CANCEL: kalau customer mau batalin jadwal meeting yang CONFIRMED, respon transisi natural, "
        "sertakan tag PERSIS: [CANCEL_MEETING] (tag doang, tanpa isi lain).\n\n"
        "JANGAN PERNAH: ngarang/nebak jam meeting BARU sendiri tanpa dikasih owner, menawarkan jam "
        "reschedule di luar GAMBARAN HARI KERJA KANTOR, atau nulis sendiri kalimat konfirmasi FINAL "
        "booking/reschedule/cancel apapun — semua itu tugas sistem, bukan tugas kamu.\n\n"
        "STOP FOLLOW-UP: kalau customer EKSPLISIT bilang gak minat/gak usah dihubungi lagi/jangan "
        "di-follow-up lagi (misal 'gak usah dihubungin lagi ya', 'saya gak minat', 'jangan di-followup "
        "lagi', 'stop aja'), hormati itu dengan sopan (jangan maksa/nanya alasan berkali-kali), lalu "
        "sertakan tag PERSIS di akhir balasan: [STOP_FOLLOWUP]. JANGAN sertain tag ini cuma karena "
        "customer diem/gak nanya lagi/lagi mikir dulu — HARUS ada pernyataan eksplisit nolak/gak minat."
    )


def build_language_context(user_number):
    """(language layer — additive) Kasih tau AI bahasa yang PERNAH kedeteksi buat customer ini
    sebelumnya (kalau ada), biar dipakai sebagai DEFAULT konsisten — tapi AI tetap boleh ikutin kalau
    customer ganti bahasa di pesan yang SEKARANG (lihat aturan BAHASA BALASAN di SYSTEM_PROMPT)."""
    lang = customer_language.get(user_number)
    if lang == LANGUAGE_EN:
        label = "English (dari chat sebelumnya)"
    elif lang == LANGUAGE_ID:
        label = "Bahasa Indonesia (dari chat sebelumnya)"
    else:
        return "\n\nBAHASA CUSTOMER INI: belum ada preferensi tersimpan — deteksi dari pesan pertamanya."
    return (
        f"\n\nBAHASA CUSTOMER INI SEBELUMNYA: {label}. Pakai ini sebagai default balasan, TAPI kalau "
        "pesan customer yang SEKARANG jelas-jelas pakai bahasa lain, ikutin bahasa yang sekarang (dia "
        "boleh ganti kapan aja) & update tag [SET_LANG: ...]."
    )


def build_customer_system_prompt(user_number, tenant_context_block=""):
    """Susun system prompt customer, sisipin konteks soal nama customer ini (kalau udah tau dari
    profil WhatsApp / obrolan sebelumnya, kasih tau AI biar gak nanya lagi; kalau belum, larang AI
    nanya di pembuka obrolan).

    `tenant_context_block` (Business Hub V2 Patch 2/6, default "") — teks tambahan HANYA untuk
    REQUEST INI, TIDAK PERNAH ditulis ke variabel/string prompt global manapun. Default kosong =
    perilaku identik dengan sebelum patch ini ada."""
    name = customer_names.get(user_number)
    if name:
        name_context = (
            f'\n\nNAMA CUSTOMER INI: kamu udah tau namanya, yaitu "{name}" (dari profil WhatsApp dia / '
            "obrolan sebelumnya). JANGAN nanya nama lagi. Boleh sesekali natural manggil pakai nama itu, "
            "tapi gak usah maksa dipakai di tiap balasan."
        )
    else:
        name_context = (
            "\n\nNAMA CUSTOMER INI: kamu belum tau namanya. JANGAN nanya nama di pesan pembuka atau di awal "
            "obrolan (jangan jadiin itu basa-basi pertama). Ngobrol dulu natural soal kebutuhan mereka. "
            "Nanti kalau obrolannya udah jalan & momennya pas (misal pas mau kirim katalog, mau lanjut "
            "booking, dll), boleh sesekali nanya namanya secara natural & santai, gak usah interogasi kalau "
            'mereka keliatan males jawab. BEGITU dia kasih tau namanya (kapan aja momennya), WAJIB sertain '
            'tag "[NAMA: <nama customer>]" di balasanmu (taruh di mana aja, sistem yang proses & simpan, '
            "customer gak bakal lihat teks tag-nya). Cukup sekali aja pas pertama kali dapet namanya."
        )

    is_tenant_context = bool(tenant_context_block)

    if is_tenant_context:
        # Resolved CLIENT tenant (e.g. a coffee shop) — never reference Kilas Works' own business
        # scope/services here, only "bisnis ini" (this specific tenant business).
        scope_context = (
            "\n\nOUT-OF-SCOPE REQUESTS: Kalau customer kirim gambar/request/pertanyaan yang JELAS MELENCENG "
            "dari bisnis ini, abaikan aja. JANGAN coba-coba jawab atau ladenin. Contoh melenceng: nanya soal "
            "astrologi, nanya resep masakan (kalau bisnis ini bukan resto/kafe), nanya soal film, request "
            "sesuatu yang gak ada kaitannya sama bisnis ini. Cukup balasan santai kayak 'waduh ini di luar "
            "keahlian aku sih kak' terus arahkan balik ke topik bisnis ini."
        )
    else:
        scope_context = (
            "\n\nOUT-OF-SCOPE REQUESTS: Kalau customer kirim gambar/request/pertanyaan yang JELAS MELENCENG "
            "dari bisnis Kilas Works (fotografi, videografi, konten Reels/TikTok, AI WhatsApp Admin, website, "
            "acara), abaikan aja. JANGAN coba-coba jawab atau ladenin. Contoh melenceng: nanya soal astrologi, "
            "nanya resep masakan, nanya soal film, request design sesuatu yang bukan buat bisnis, nanya soal "
            "hal yang gak ada kaitannya sama layanan Kilas Works. Cukup balasan santai kayak 'waduh ini di luar "
            "keahlian aku sih kak' terus arahkan balik ke topik bisnis."
        )

    # FAKTA YANG UDAH DISEPAKATI OWNER buat customer ini spesifik — ini SUMBER KEBENARAN yang
    # WAJIB dipatuhi & GAK BOLEH dikontradiksi atau ditanya ulang ke owner. Ditaruh SANGAT eksplisit
    # (bukan cuma ngarep AI "inget sendiri" dari histori chat freeform) karena ini bagian paling
    # penting biar AI gak pernah lagi salah bilang "belum dapet konfirmasi owner" padahal udah
    # pernah dijawab & di-forward sebelumnya.
    customer_facts = agreed_facts.get(user_number) or []
    if customer_facts:
        facts_list = "\n".join(f'- {f}' for f in customer_facts)
        facts_context = (
            "\n\n⭐⭐⭐ FAKTA YANG SUDAH FIX & DISEPAKATI OWNER UNTUK CUSTOMER INI (WAJIB DIPATUHI) ⭐⭐⭐\n"
            "Ini daftar keputusan/jawaban yang UDAH BENERAN di-forward & disampein ke customer ini "
            "sebelumnya. SEMUA ini FINAL — jangan pernah kontradiksi, jangan tanya ulang ke owner soal "
            "ini, jangan bilang 'belum dapet konfirmasi' atau 'tunggu owner' buat hal-hal ini. Kalau "
            "customer nanya/konfirmasi ulang soal salah satu hal di bawah, LANGSUNG jawab CONFIDENT "
            "pakai jawaban yang udah fix ini:\n"
            f"{facts_list}"
        )
    else:
        facts_context = ""

    # Bug fix (Task 7) — build_appointment_context() describes KILAS WORKS' OWN office hours/
    # meeting-slot availability (DEFAULT_MEETING_SLOT_TIMES/is_office_closed_on) and instructs the
    # AI to use the appointment tags that book into Kilas Works' own global appointments store.
    # There is no per-tenant business-hours/availability config yet (known limitation of this
    # cycle — see final report), so a resolved CLIENT tenant must never be handed this block at
    # all — same "" no-op pattern as live_price_sync_note below.
    appointment_context = "" if is_tenant_context else build_appointment_context()
    language_context = build_language_context(user_number)

    # Section 20: only added when a live Client Hub catalog price has actually diverged from the
    # hardcoded PRICING_CONFIG figures above — "" (no-op) otherwise, including whenever Client Hub
    # isn't installed/reachable. Does not run at all for a resolved multi-tenant client
    # (tenant_context_block already carries THAT business's own canonical catalog).
    live_price_sync_note = "" if tenant_context_block else _build_live_price_sync_note_safe()
    live_talent_note = "" if tenant_context_block else _build_live_talent_knowledge_note_safe(for_owner=False)

    # Bug fix: SYSTEM_PROMPT is Kilas Works' OWN persona, built on top of its OWN PRICING_CONFIG
    # (AI Admin, Content packages, bundles, website pricing, etc.) — that must NEVER be the base
    # prompt for a resolved CLIENT tenant (e.g. a coffee shop's own WhatsApp bot). Use the generic,
    # business-agnostic TENANT_SYSTEM_PROMPT_BASE instead whenever a tenant is actually resolved;
    # every other conversation (Kilas Works' own number / prospects) keeps using SYSTEM_PROMPT
    # exactly as before.
    base_prompt = TENANT_SYSTEM_PROMPT_BASE if is_tenant_context else SYSTEM_PROMPT

    owner_number_display = f"wa.me/{OWNER_WHATSAPP_NUMBER}"
    full_prompt = (
        base_prompt + language_context + name_context + scope_context + facts_context
        + appointment_context + live_price_sync_note + live_talent_note + (tenant_context_block or "")
    )
    full_prompt = full_prompt.replace("{owner_number_display}", owner_number_display)
    full_prompt = full_prompt.replace("{owner_number}", OWNER_WHATSAPP_NUMBER)
    return full_prompt


SYSTEM_PROMPT_OWNER_BASE = """Kamu asisten pribadi Irvan, founder Kilas Works (jasa fotografi, videografi, konten
short-form, AI WhatsApp Admin, Website & Talent Management di Tangerang & Jakarta). Kamu lagi chat LANGSUNG sama Irvan (owner-nya sendiri),
BUKAN sama customer — jadi gaya bicara ke dia santai & to the point kayak ngobrol sama partner kerja, bukan
formal.

KONTEKS: kadang ada customer yang tanya sesuatu yang AI customer-service belum yakin jawabnya, jadi
diteruskan ke Irvan buat dijawab manual. Kalau lagi ada pertanyaan customer yang pending, kamu bakal dikasih
tau isinya di bawah. Irvan boleh diskusi bebas dulu sama kamu soal itu — nanya-nanya, mikirin jawaban paling
pas, kasih saran harga, atau ngobrol hal lain sama sekali — SEBELUM dia mutusin jawaban final buat customer.

KNOWLEDGE LAYANAN & HARGA KILAS WORKS (RESMI — SATU-SATUNYA SUMBER, SAMA PERSIS yang dipakai AI
customer-service & katalog PDF. JANGAN PERNAH sebut angka/paket lain di luar ini):
{pricing_text_block}

TALENT MANAGEMENT (PENTING):
- Talent Management adalah layanan RESMI dan AKTIF Kilas Works, model harga Custom Quote.
- Data talent aktif, handle, followers, niche, availability, dan (khusus owner) internal rate akan diberikan
  dari Client Hub secara LIVE di konteks bawah.
- JANGAN PERNAH bilang "Kilas Works tidak punya Talent Management" atau menganggap fitur ini cuma rencana.
- Kalau data live talent sementara gagal dibaca, bilang detail/list talent sedang dicek — jangan mengarang dan
  jangan menghapus keberadaan Talent Management sebagai layanan.

Kalau Irvan nanya soal jasa/paket/harga Kilas Works MILIK SENDIRI (contoh: "jasa kita sekarang apa
aja", "AI Admin sekarang berapa", "paket konten kita apa aja", "website kita berapa", "katalog kita
isinya apa", "domain sama hosting berapa"), JAWAB LANGSUNG pakai data di atas dengan PERCAYA DIRI.
JANGAN PERNAH bilang "aku butuh list jasa dari lo", "aku gak tau layanan yang sekarang ditawarkan",
atau minta Irvan ngirim ulang data yang sebenernya udah ada persis di atas — itu SALAH, datanya udah
ada. Pertanyaan kayak gini itu Irvan tanya soal bisnisnya SENDIRI buat dipakai/dicek, BUKAN instruksi
forward ke customer manapun — jawab natural di chat ini aja, JANGAN pakai format PESAN_UNTUK_CUSTOMER:
buat jenis pertanyaan informasi kayak gini.

ATURAN PALING PENTING:
- JANGAN langsung anggap semua yang Irvan ketik itu otomatis jawaban final buat customer. Ladenin dulu
  obrolannya natural, bantu mikir kalau diminta, kasih saran, jawab pertanyaan dia apa aja, kayak asisten beneran.
- BARU kalau Irvan udah JELAS ngasih instruksi buat forward/kirim/sampein ke customer (bahasa bebas, misal
  "terusin", "sampein ke dia", "bilang ke customer gitu aja", "oke kirim", "gas terusin", "fix segitu,
  terusin" — intinya dia nyuruh forward), baru kamu proses jadi jawaban final.
- Kalau kamu udah yakin ini saatnya di-forward, WAJIB format balasanmu PERSIS kayak ini, 2 bagian:
  Baris pertama: balasan singkat & natural ke Irvan buat konfirmasi (misal "Oke siap, aku terusin ya!").
  Baris berikutnya, PERSIS diawali teks "PESAN_UNTUK_CUSTOMER:" (tanpa embel-embel lain di baris itu),
  diikuti draft pesan yang bakal dikirim ke customer — natural & santai kayak gaya chat WA admin ke
  customer, JANGAN pernah sebut kata "owner" atau "Irvan" ke customer (kamu ngomong sebagai admin/tim,
  bukan nyebut ada pihak ketiga), jangan tambahin janji/info di luar apa yang udah didiskusikan atau
  di luar apa yang Irvan bilang. INGAT: jawaban ke customer harus SINGKAT & TO-THE-POINT (pakai singkatan
  kayak "1 jt" bukan "1 juta", dll), TANPA EMOJI, dan TANPA muji-muji lebay — nada profesional & natural.
- Kalau BELUM ada instruksi jelas buat forward, JANGAN PERNAH tulis teks "PESAN_UNTUK_CUSTOMER:" dalam
  bentuk apapun — balas natural aja kayak obrolan biasa.
- JANGAN PERNAH kirim pesan yang ambigu, gak jelas, atau bisa bikin customer bingung. Contoh: jangan
  bilang "maaf saya salah sebut" atau balasan gak jelas lainnya ke customer. Kalimat harus JELAS,
  ACTIONABLE, dan PASTI (bukan bertanya-tanya atau ragu).
- ⭐ ALWAYS FORWARD: Kalau ada diskusi soal customer question, ujung-ujungnya HARUS ada forward ke customer.
  Jangan ada message tertinggal. Diskusi → Keputusan → FORWARD KE CUSTOMER. Itu flow-nya.
- Kalau emang lagi gak ada pertanyaan customer yang pending, anggap ini obrolan santai/kerjaan lain sama
  Irvan aja, bantu apa yang dia butuhin.

AKSES HISTORY SEMUA CUSTOMER:
- Di bawah ada daftar SEMUA customer yang pernah chat, lengkap sama nama (kalau udah ketauan) dan history
  obrolan mereka sama AI customer-service. Ini data ASLI & LENGKAP, bukan karangan.
- Kalau Irvan nanya soal customer mana aja — "yang tadi chat nanya apa", "si Budi udah tanya apa aja",
  "ada yang chat gak barusan", "siapa aja yang chat hari ini" dll — jawab BERDASARKAN data di daftar itu.
  JANGAN bilang "aku gak tau" atau "gak ada akses" kalau datanya emang ada di situ.
- Kalau customer yang dimaksud Irvan gak ketemu di daftar (belum pernah chat / namanya beda), baru bilang
  jujur kalau gak nemu datanya.

PERINTAH LANGSUNG KE CUSTOMER (nomor ATAU nama, LANGSUNG EKSEKUSI):
- Kalau Irvan bilang "kirim ke [nama/nomor]...", "balas [nama]...", "follow up [nama]...", "tanyain
  dia...", "ingetin [nama]...", dsb — itu PERINTAH LANGSUNG, bukan sekadar diskusi. Target customer-nya
  (nama/nomor, atau "dia"/"customer ini" merujuk ke customer yang lagi dibahas) UDAH DIRESOLVE & DIPASTIIN
  BENAR oleh sistem SEBELUM pesan ini nyampe ke kamu — jadi begitu kamu dikasih tau di bawah "Ini INSTRUKSI
  LANGSUNG", kamu WAJIB LANGSUNG proses ke format PESAN_UNTUK_CUSTOMER: dalam balasan yang SAMA, TANPA
  minta konfirmasi ulang, TANPA nunggu Irvan bilang "oke"/"terusin" lagi — dia sudah bilang itu barusan.
- Perintah ini beda sama Irvan MINTA SARAN/DRAFT (misal "menurut lu gue balas apa", "bikinin draft",
  "kasih saran jawabannya") — kalau itu yang diminta, JANGAN pakai format PESAN_UNTUK_CUSTOMER:, cukup
  kasih saran/draft-nya aja di chat biasa, biar Irvan yang putusin lanjut apa nggak.
- JANGAN PERNAH bilang "saya tidak bisa mengirim" — sistem yang eksekusi pengiriman WhatsApp beneran
  ada & udah jalan; tugas kamu cuma nyusun pesan yang bakal dikirim itu (via format PESAN_UNTUK_CUSTOMER:).

EXECUTION PERFECTION:
- Kalau Irvan sudah decide & bilang forward, kamu LANGSUNG forward dengan CONFIDENT, CLEAR, PERFECT.
- JANGAN PERNAH dalam forward message bilang: "maaf saya salah", "tunggu owner jawab", atau apapun yang
  menunjukkan ragu/bingung. Setiap pesan ke customer harus terdengar seperti keputusan yang sudah pasti.
- Kalau Irvan bilang "1 jt", kamu paham itu 1 juta (bukan 1.5, bukan "sekitar 1 juta"). Jawab customer
  dengan exact itu "1 jt" — PERFECT, no second-guessing.

JANGAN PERNAH (baik pas nyusun draft maupun pas forward):
- Bikin harga/diskon/paket/rekening/bonus/deadline sendiri yang gak pernah disebut Irvan atau gak ada
  di data resmi Kilas Works. Kalau Irvan sendiri yang eksplisit sebutin angkanya, itu boleh & WAJIB dipakai
  persis — yang dilarang cuma AI NGARANG sendiri tanpa dasar dari Irvan/data resmi.
- Nulis kalimat ambigu/ragu-ragu ke customer ("mungkin", "kayaknya", "coba nanti dicek lagi").

GAYA BAHASA KE CUSTOMER (buat draft/forward): natural, ramah, singkat, gak kaku/formal, gak kayak
chatbot, TANPA emoji, TANPA muji-muji lebay. Contoh natural: "Halo Kak, izin follow-up ya, untuk
paymentnya masih mau dilanjutkan hari ini?" — BUKAN "Berdasarkan data yang saya miliki...".
"""

# Sisipin blok harga (SATU sumber data yang sama dipakai SYSTEM_PROMPT customer & katalog PDF) ke
# system prompt owner juga — biar Owner Bot gak pernah lagi bilang "aku butuh list jasa dari lo"
# padahal datanya udah ada.
SYSTEM_PROMPT_OWNER_BASE = SYSTEM_PROMPT_OWNER_BASE.replace("{pricing_text_block}", PRICING_TEXT_BLOCK)


def build_pending_meeting_requests_context():
    """(production hardening) List semua meeting_requests yang lagi PENDING_OWNER_CONFIRMATION, buat
    dikasih tau ke owner AI biar dia ngerti kalau Irvan balas ngasih jam, itu jawaban availability
    buat request ini — BUKAN forward pesan biasa (jangan pakai PESAN_UNTUK_CUSTOMER: buat ini). Return
    string kosong kalau gak ada yang pending."""
    pending = [
        (number, req) for number, req in meeting_requests.items()
        if req.get("status") == MEETING_STATE_PENDING_OWNER_CONFIRMATION
    ]
    if not pending:
        return ""
    lines = []
    for number, req in pending:
        name = customer_names.get(number, f"wa.me/{number}")
        mode_label = meeting_mode_label(req)
        day_label = req.get("day_display") or req.get("day_text") or "(hari belum jelas)"
        req_time = req.get("requested_time")
        time_note = f", customer SENDIRI udah minta jam {req_time.replace(':', '.')}" if req_time else ""
        lines.append(f"- {name}: minta {mode_label} hari {day_label}{time_note}")
    return (
        "\n\n📅 CUSTOMER YANG LAGI NUNGGU AVAILABILITY MEETING (WAJIB DIPROSES kalau Irvan balas kasih "
        "jam untuk salah satu ini):\n" + "\n".join(lines) +
        "\n\n⚠️ TANGGAL/HARI di daftar atas itu FIX & TERKUNCI (date lock) — JANGAN PERNAH kamu sebut "
        "hari lain di luar yang tercantum buat customer ini, KECUALI Irvan SENDIRI eksplisit ganti/kasih "
        "hari lain. Kalau Irvan cuma bilang 'bisa'/'available'/'iya'/'oke' TANPA nyebut jam sama sekali, "
        "SISTEM (bukan kamu) yang udah nanganin itu duluan secara otomatis SEBELUM pesan ini nyampe ke "
        "kamu — jadi kalau kamu tetap nerima pesan ini berarti Irvan-nya nyebut sesuatu yang LEBIH dari "
        "sekadar 'bisa' polos (biasanya ada angka jam atau konteks lain campur). JANGAN nanya ulang "
        "'ada jam yang available?' ke Irvan buat customer yang sama kalau dia baru aja jawab.\n"
        "Kalau Irvan balas ngasih jam kosong buat SALAH SATU customer di atas (bahasa bebas, misal "
        "'sabtu bisa jam 1 3 5', 'jam 3 aja', 'pagi ga bisa sore bisa', 'online jam 2 atau 4'), kamu "
        "WAJIB sertakan tag PERSIS di akhir balasan (SELAIN balasan santai biasa ke Irvan — JANGAN pakai "
        "format PESAN_UNTUK_CUSTOMER: buat kasus ini): [OWNER_MEETING_SLOTS: customer=<nama PERSIS dari "
        "daftar di atas>|times=<daftar jam 24-jam dipisah koma, contoh 13:00,15:00,17:00>]. Kalau Irvan "
        "bilang GAK BISA/tutup buat request itu (misal 'minggu tutup', 'gabisa hari itu') atau nyuruh "
        "pindah hari lain (misal 'suruh dia senin aja'), sertakan tag PERSIS: [OWNER_MEETING_UNAVAILABLE: "
        "customer=<nama PERSIS dari daftar di atas>] — sistem yang bakal minta customer kasih hari lain.\n"
        "PENTING soal jam: WAJIB format 24-jam. Kalau Irvan cuma nyebut angka tanpa konteks pagi/sore "
        "buat meeting bisnis siang (misal 'jam 1 3 5'), asumsikan siang/sore (13:00, 15:00, 17:00) — TAPI "
        "kalau Irvan eksplisit nyebut 'pagi'/'sore'/'malam', ikutin itu. Kalau beneran gak yakin jamnya, "
        "mending tanya balik ke Irvan dulu daripada nebak & salah kasih jam ke customer."
    )


def resolve_meeting_request_target(name_hint):
    """(production hardening) Coba temuin nomor customer yang match `name_hint` DAN lagi punya
    meeting_request berstatus PENDING_OWNER_CONFIRMATION. Kalau name_hint kosong/gak ketemu tapi CUMA
    ADA SATU request pending, pakai itu (kasus obrolan single-thread paling umum, sama prinsipnya
    kayak active_customer_context fallback yang udah ada). Return nomor atau None."""
    pending_numbers = [
        n for n, r in meeting_requests.items() if r.get("status") == MEETING_STATE_PENDING_OWNER_CONFIRMATION
    ]
    if not pending_numbers:
        return None
    if name_hint:
        matches = find_customers_by_name(name_hint)
        for num, _name in matches:
            if num in pending_numbers:
                return num
    if len(pending_numbers) == 1:
        return pending_numbers[0]
    return None


def build_owner_system_prompt(pending_question, pending_customer_number, direct_send=False):
    """Susun system prompt mode-owner, sisipin konteks pertanyaan customer yang lagi pending (kalau ada)
    dan ringkasan history semua customer biar owner bisa nanya soal siapa aja/apa aja kapan aja.

    direct_send=True dipakai kalau pesan owner SAAT INI JUGA udah dideteksi sistem sebagai perintah
    kirim/balas/follow-up eksplisit dengan target yang UDAH DIPASTIIN bener (lihat resolve_owner_target
    di webhook) — kondisi ini paling kuat, bikin AI WAJIB langsung proses forward TANPA nunggu konfirmasi
    tambahan, beda dari kondisi 'customer terakhir yang dibahas' di bawah yang masih butuh kata kunci
    forward eksplisit dulu dari Irvan.

    PENTING: Bot HARUS INGAT (maintain consistency) apa yang sudah owner sepakatin dalam diskusi ini.
    Jangan pernah forward pesan yang contradicts apa yang sudah disepakati."""
    if direct_send and pending_customer_number:
        target_name = customer_names.get(pending_customer_number, f"wa.me/{pending_customer_number}")
        context = (
            f"\n\n⭐⭐⭐ INI INSTRUKSI LANGSUNG DARI IRVAN — target-nya UDAH DIPASTIIN & TUNGGAL: "
            f"{target_name} ({pending_customer_number}). Pesan Irvan barusan ADALAH perintah kirim/balas/"
            f"follow-up ke customer ini. JANGAN minta konfirmasi apapun lagi, JANGAN tanya ulang, LANGSUNG "
            f"susun pesan yang sesuai instruksi & proses ke format PESAN_UNTUK_CUSTOMER: di respons ini juga."
        )
    elif pending_question:
        context = (
            f'\n\nPERTANYAAN CUSTOMER YANG LAGI PENDING (dari wa.me/{pending_customer_number}): '
            f'"{pending_question}"'
        )
    elif pending_customer_number:
        target_name = customer_names.get(pending_customer_number, f"wa.me/{pending_customer_number}")
        context = (
            f"\n\nGak ada pertanyaan customer yang formal pending, TAPI customer TERAKHIR yang chat/lagi "
            f"dibahas adalah {target_name} ({pending_customer_number}). Kalau Irvan diskusi soal customer "
            f"ini terus bilang 'terusin'/'kirim'/'sampein' TANPA nyebut nomor lain secara eksplisit, "
            f"anggap target forward-nya customer INI — WAJIB tetep proses format PESAN_UNTUK_CUSTOMER: "
            f"seperti biasa, JANGAN diem aja cuma karena gak ada 'pertanyaan resmi' yang pending."
        )
    else:
        context = "\n\nGak ada pertanyaan customer yang pending saat ini."

    context += (
        "\n\n⭐ CRITICAL: PERFECT EXECUTION & 100% CONSISTENCY — "
        "Setiap kali kamu forward pesan ke customer, HARUS PERSIS dengan apa yang owner bilang. "
        "Jangan ada interpretasi, jangan ada 'mungkin', jangan ada 'bisa nego'. EXACT. PERFECT. DONE.\n"
        "Contoh INGAT & CONFIRM (paling penting):\n"
        "Owner bilang: '900rb untuk transport ke Jogja'\n"
        "Customer bilang: 'Jadi 900 ribu ya kak?'\n"
        "❌ BAD Bot: 'Tunggu owner jawab dulu, aku gak bisa confirm' (SALAH! Owner sudah bilang!)\n"
        "✅ GOOD Bot: 'Iya bener, 900rb untuk transportnya kak' (INGAT, CONFIRM, DONE)\n\n"
        "Contoh lain:\n"
        "❌ BAD: Owner bilang '1 juta' → Bot kirim '1 juta tapi bisa nego' (contradictory)\n"
        "✅ GOOD: Owner bilang '1 juta' → Bot kirim '1 jt' (exact, singkat, confident)\n"
        "JANGAN PERNAH: bilang 'maaf saya salah sebut', 'tunggu owner jawab', atau ragu-ragu. "
        "Kalau owner sudah decide, kamu LANGSUNG CONFIRM dengan CONFIDENT & CLEAR. ZERO APOLOGIES.\n"
        "PENTING: draft pesan ke customer JANGAN PAKAI EMOJI SAMA SEKALI & jangan muji-muji lebay "
        "('wah keren', 'menarik banget', dll) — nada profesional, natural, fokus bisnis."
    )

    context += (
        "\n\nKALAU IRVAN NANYA SESUATU YANG DATANYA GAK ADA/GAK CUKUP DI KONTEKS INI (WAJIB DIIKUTI):\n"
        "- JANGAN ngarang jawaban — bukan cuma soal harga/pelanggan, ini berlaku buat SEMUA hal: "
        "ketersediaan, kebijakan, jadwal, isi paket, atau fakta bisnis apapun yang gak ada datanya di "
        "atas. Jawab jujur, contoh: \"Aku belum punya data yang cukup untuk memastikan itu.\" — TETAP "
        "boleh natural/singkat, bukan template kaku.\n"
        "- Ini BEDA dari soal harga paket resmi Kilas Works (yang UDAH ADA lengkap di data KNOWLEDGE "
        "LAYANAN & HARGA di atas) — buat itu kamu MEMANG tau & boleh jawab langsung, lihat instruksi "
        "JAWAB LANGSUNG di bawah. Aturan \"jangan ngarang\" ini spesifik buat hal yang BENERAN gak ada "
        "datanya, bukan alasan buat ragu-ragu soal hal yang sebenernya udah kamu tau."
    )

    context += build_pending_meeting_requests_context()
    context += build_customer_context_summary()
    context += _build_business_hub_owner_query_context_safe()
    context += _build_live_talent_knowledge_note_safe(for_owner=True)
    return SYSTEM_PROMPT_OWNER_BASE + context


def log_ai_usage(context_label, model, api_response_json):
    """Log internal (server log doang, TIDAK pernah dikirim ke customer/owner) soal token usage per
    panggilan Claude — biar nanti kelihatan estimasi biaya AI per customer/mode. Aman dipanggil
    walau response gak punya field 'usage' (misal error response), gak bakal nge-crash apapun."""
    try:
        usage = (api_response_json or {}).get("usage") or {}
        in_tok = usage.get("input_tokens")
        out_tok = usage.get("output_tokens")
        if in_tok is not None or out_tok is not None:
            print(f"[AI_USAGE] context={context_label} model={model} input_tokens={in_tok} output_tokens={out_tok}")
    except Exception:
        pass  # logging biaya gak boleh pernah bikin request gagal


def call_claude_owner(owner_number, owner_message, pending_question, pending_customer_number,
                       image_b64=None, image_mime=None, direct_send=False, is_voice_note=False):
    """Panggil Claude buat mode 'asisten pribadi owner' — beda histori & system prompt dari
    call_claude() yang dipakai buat customer. Sama-sama Haiku default + fallback Sonnet.
    Kalau owner kirim gambar, WAJIB pakai Sonnet langsung (Haiku 3.5 gak support vision).

    is_voice_note (additive) — True kalau owner_message ini hasil transkrip voice note (bukan
    ketikan langsung). Transcript TETAP dikirim apa adanya ke API (biar AI proses command persis
    kayak command teks biasa, TIDAK ADA engine AI kedua khusus voice), cuma versi yang disimpen ke
    memory/DB dikasih tag "[OWNER VOICE NOTE]" — dipakai `build_customer_context_summary()` /
    riwayat biar owner-mode AI bisa jawab natural kalau ditanya "dia terakhir bilang apa lewat
    voice note", persis pola yang sama kayak tag "[OWNER KIRIM GAMBAR]" di bawah."""
    history = owner_conversations.get(owner_number)
    if history is None:
        history = load_recent_messages_from_db(owner_number, "owner")  # isi ulang kalau server abis restart

    if image_b64:
        api_content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": image_mime or "image/jpeg", "data": image_b64},
            },
            {"type": "text", "text": owner_message or "(owner kirim gambar tanpa keterangan)"},
        ]
        memory_text = f"[OWNER KIRIM GAMBAR] {owner_message}".strip()
    elif is_voice_note:
        api_content = owner_message
        memory_text = f"[OWNER VOICE NOTE] {owner_message}".strip()
    else:
        api_content = owner_message
        memory_text = owner_message

    history.append({"role": "user", "content": api_content})
    save_message_to_db(owner_number, "owner", "user", memory_text)

    system_prompt = build_owner_system_prompt(pending_question, pending_customer_number, direct_send=direct_send)
    model_to_use = MODEL_FAST if not image_b64 else MODEL_PRIMARY

    try:
        if image_b64:
            raise RuntimeError("skip-haiku-vision-not-supported")
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model_to_use,
                "max_tokens": 400,
                "system": system_prompt,
                "messages": history,
            },
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Haiku (owner mode) gagal ({e}), fallback ke Sonnet...")
        model_to_use = MODEL_FALLBACK
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model_to_use,
                "max_tokens": 400,
                "system": system_prompt,
                "messages": history,
            },
            timeout=30,
        )
        resp.raise_for_status()

    data = resp.json()
    reply_text = data["content"][0]["text"]
    log_ai_usage("owner", model_to_use, data)

    if image_b64:
        history[-1] = {"role": "user", "content": memory_text}

    history.append({"role": "assistant", "content": reply_text})
    owner_conversations[owner_number] = history[-20:]
    save_message_to_db(owner_number, "owner", "assistant", reply_text)

    return reply_text


# Tag internal yang dipakai AI buat kasih sinyal ke sistem. Semua ini di-strip dari pesan
# sebelum dikirim ke customer, supaya customer gak pernah lihat teks tag mentah.
TAG_LEADS_PANAS = "[LEADS_PANAS]"
TAG_TANYA_OWNER = "[TANYA_OWNER]"
TAG_KIRIM_QR = "[KIRIM_QR]"
TAG_KIRIM_KATALOG = "[KIRIM_KATALOG]"
TAG_SUDAH_BAYAR = "[SUDAH_BAYAR]"
TAG_CANCEL_MEETING = "[CANCEL_MEETING]"
# Tag BARU (production hardening) — dipakai AI buat nandain customer yang EKSPLISIT bilang gak
# tertarik / minta jangan dihubungi lagi (mis. "gak usah dihubungin lagi ya", "gak minat"), biar
# follow-up otomatis STOP buat nomor itu. Cuma dipasang kalau customer BENERAN nyebut eksplisit,
# bukan tebakan dari nada bicara — AI diinstruksikan soal ini di SYSTEM_PROMPT customer.
TAG_STOP_FOLLOWUP = "[STOP_FOLLOWUP]"
ALL_TAGS = [
    TAG_LEADS_PANAS, TAG_TANYA_OWNER, TAG_KIRIM_QR, TAG_KIRIM_KATALOG, TAG_SUDAH_BAYAR, TAG_CANCEL_MEETING,
    TAG_STOP_FOLLOWUP,
    "[LEADS PANAS]",  # jaga-jaga variasi lama
]

# Tag dinamis buat nangkep nama customer, formatnya "[NAMA: Budi]" — beda dari tag lain di atas
# karena isinya berubah-ubah, jadi dideteksi pakai regex, bukan exact match di ALL_TAGS.
TAG_NAMA_PATTERN = re.compile(r"\[NAMA:\s*([^\]]+)\]", re.IGNORECASE)

# CODE-LEVEL customer price/transport-quotation guardrail (production bug fix — NOT prompt wording
# only). Business rule: NO customer-facing AI conversation — Kilas Works' own customers AND every
# tenant business's own customers alike — may disclose a nominal Rupiah figure during normal sales
# inquiry: no package price, no discount, no custom quote, no transport/travel/accommodation
# estimate — even if the number exists in the catalog/database/prompt/prior conversation, and even
# if the customer asks directly. This is enforced HERE, as a deterministic post-processing scan of
# the AI's own generated customer-facing reply, specifically because a prompt instruction alone is
# not a guarantee — the exact production incident this closes (an out-of-town transport cost of
# "Rp250.000 sampai Rp300.000an" invented by the model) happened despite prompt wording existing at
# the time; a regex-based scan that unconditionally replaces the ENTIRE reply with a safe, natural,
# price-free fallback whenever ANY Rupiah-shaped figure slips through cannot be argued around by
# the model the way a prompt instruction can.
#
# SCOPE: applies to EVERY customer-facing reply, Kilas Works' own AND every tenant's own — no
# tenant-specific configuration anywhere in this codebase was found that explicitly authorizes a
# tenant to disclose nominal prices to its own customers (confirmed by source search before this
# fix), so the same safe default applies uniformly rather than leaving tenant conversations
# unprotected. Owner/admin-facing replies (a completely separate prompt/call path,
# SYSTEM_PROMPT_OWNER_BASE) are never touched by this function at all — the owner remains able to
# retrieve configured prices whenever they ask.
#
# CHECKOUT/PAYMENT EXCEPTION: once a customer has moved PAST sales inquiry into an actual, already-
# confirmed transaction (see the `_in_active_payment_flow` check at each call site), the amount to
# transfer is a legitimate, system/order-derived checkout detail — not a sales-negotiation price
# quote — and this guardrail is skipped for that turn so the existing payment flow keeps working.
# The bank account itself is never at risk either way — build_payment_info_text()/
# build_tenant_payment_info_text() only ever return bank/account-number/account-name text, which
# never matches the Rp/rb/jt-shaped patterns this guardrail scans for.
CUSTOMER_PRICE_DISCLOSURE_PATTERN = re.compile(
    r'Rp\s?\d[\d.,]*(?:\s?(?:rb|ribu|jt|juta))?'          # "Rp999.000", "Rp 4.250.000", "Rp2jt"
    r'|\b\d[\d.,]*\s?(?:rb|ribu|jt|juta)\b'                # "999rb", "4,25jt", "2 juta" (no Rp prefix)
    r'|\b\d{1,3}(?:[.,]\d{3}){2,}\b',                       # bare thousands-grouped number, e.g. "4.250.000"
    re.IGNORECASE,
)

CUSTOMER_PRICE_SAFE_FALLBACK_REPLY = (
    "Untuk detail harganya aku bantu cek dulu ke tim ya, biar yang dikasih sesuai kebutuhan kamu."
)


def _customer_reply_contains_price_disclosure(text):
    """Returns True if `text` contains a Rupiah-shaped nominal figure anywhere — the actual
    code-level check behind the customer price/transport guardrail (see the constant above's
    docstring for the full rationale)."""
    if not text:
        return False
    return bool(CUSTOMER_PRICE_DISCLOSURE_PATTERN.search(text))


def _enforce_customer_price_guardrail(reply_text, tenant_context_block):
    """Applies the code-level guardrail: for ANY customer-facing reply — Kilas Works' own
    customers AND every tenant business's own customers alike — that contains ANY Rupiah-shaped
    figure, the ENTIRE reply is replaced with a safe, natural, price-free fallback — never just
    the number stripped out (which would risk leaving broken/nonsensical grammar behind, e.g.
    "Content Pro  , Kak." after removing just the price).

    Applies UNIFORMLY to tenant customers too (as of this fix — previously exempted, but no
    explicit per-tenant configuration was ever found anywhere in this codebase that authorizes a
    tenant to disclose nominal prices to ITS OWN customers, so the same safe default now applies
    consistently rather than leaving tenant conversations unprotected from a hallucinated price/
    quote/discount/transport figure). `tenant_context_block` is still accepted as a parameter
    (unused for the block-vs-allow decision itself now) so call sites don't need to change, and so
    a future tenant-specific opt-out config — if one is ever added — has an obvious place to plug
    into this exact function."""
    if _customer_reply_contains_price_disclosure(reply_text):
        return CUSTOMER_PRICE_SAFE_FALLBACK_REPLY
    return reply_text

# Tag booking meeting — isinya key=value dipisah "|" (date, time, name, business, need), dideteksi &
# di-parse pakai parse_tag_kv(). SISTEM (bukan AI) yang generate kalimat konfirmasi final customer-nya,
# biar gak ada resiko AI ngaku "sudah dijadwalkan" padahal slotnya ternyata udah keisi duluan.
TAG_BOOK_MEETING_PATTERN = re.compile(r"\[BOOK_MEETING:\s*([^\]]+)\]", re.IGNORECASE)
TAG_RESCHEDULE_MEETING_PATTERN = re.compile(r"\[RESCHEDULE_MEETING:\s*([^\]]+)\]", re.IGNORECASE)

# Tag FLOW MEETING BARU (production hardening) — customer-facing: dipasang AI setelah tau mode
# online/offline + preferensi hari customer ([MEETING_PREFERENCE]), atau setelah customer milih salah
# satu jam yang UDAH ditawarin dari slot owner ([MEETING_SLOT_PICK]). SISTEM yang tetap validasi ulang
# & generate kalimat final-nya, bukan AI.
TAG_MEETING_PREFERENCE_PATTERN = re.compile(r"\[MEETING_PREFERENCE:\s*([^\]]+)\]", re.IGNORECASE)
TAG_MEETING_SLOT_PICK_PATTERN = re.compile(r"\[MEETING_SLOT_PICK:\s*([^\]]+)\]", re.IGNORECASE)

# Tag FLOW MEETING BARU — owner-facing: dipasang owner AI (call_claude_owner) pas Irvan balas ngasih
# jam kosong ([OWNER_MEETING_SLOTS]) atau bilang gak bisa/tutup ([OWNER_MEETING_UNAVAILABLE]) buat
# salah satu customer yang lagi PENDING_OWNER_CONFIRMATION (lihat build_pending_meeting_requests_context).
TAG_OWNER_MEETING_SLOTS_PATTERN = re.compile(r"\[OWNER_MEETING_SLOTS:\s*([^\]]+)\]", re.IGNORECASE)
TAG_OWNER_MEETING_UNAVAILABLE_PATTERN = re.compile(r"\[OWNER_MEETING_UNAVAILABLE:\s*([^\]]+)\]", re.IGNORECASE)

# --- BUG FIX (owner availability flow) --------------------------------------------------------
# Sebelumnya balesan owner yang GENERIK ("bisa"/"available"/"iya"/"oke", TANPA nyebut jam) buat
# meeting yang lagi PENDING_OWNER_CONFIRMATION diserahin bulat-bulat ke AI buat diinterpretasi —
# riskan: AI bisa nanya ulang pertanyaan yang sama, salah sebut hari (drift dari state asli), atau
# nganggep instruksi "teruskan" cuma draft. Sekarang dideteksi DETERMINISTIK di Python (pola yang
# sama kayak parse_owner_payment_command/parse_meeting_status_command) SEBELUM masuk ke AI sama
# sekali, biar tanggal/jam yang dikirim ke customer 100% dari state (req dict), bukan karangan AI.
# Kalau owner-nya EKSPLISIT nyebut ANGKA JAM (ada digit di teks), regex ini SENGAJA gak match —
# biar tetap lewat jalur AI [OWNER_MEETING_SLOTS] yang udah ada (lebih jago extract/convert jam
# dari bahasa bebas kayak "jam 1 3 5" atau "pagi ga bisa sore bisa").
GENERIC_AVAILABILITY_CONFIRM_PATTERN = re.compile(
    r'^(?:(?:iya+|ya+|yoi+|yup|oke*|ok(?:ay)?|sip|boleh|bisa|available|avail|ready|siap|fix|acc|'
    r'kok|dong|aja|nih|banget|deh|sih|bang|kak|lah)[\s,.!?]*)+$',
    re.IGNORECASE,
)
MEETING_UNAVAILABLE_KEYWORDS_PATTERN = re.compile(
    r'\b(?:(?:gak|ga|nggak|enggak|tidak|blm|belum)\s*(?:bisa|bs|available|ada)|tutup|libur|full|penuh)\b',
    re.IGNORECASE,
)
MEETING_RESEND_ACTION_PATTERN = re.compile(
    r'\b(?:teruskan|terusin|kirim(?:in)?(?:\s+aja)?|lanjut(?:kan|in)?|kasih\s*tau|bilang\s*ke|sampein)\b',
    re.IGNORECASE,
)

# Tag PEMBAYARAN (production hardening) — [GIVE_PAYMENT_INFO] SENGAJA gak exact-string-replace kosong
# kayak ALL_TAGS lain: dia diganti Python jadi teks rekening resmi BENERAN (build_payment_info_text()),
# BUKAN dihapus — biar AI gak pernah ngetik nomor rekening sendiri (lihat webhook). [PAYMENT_DP_UNCLEAR]
# dipasang AI kalau customer minta DP tapi nominalnya belum ada aturan resmi/kesepakatan owner.
TAG_GIVE_PAYMENT_INFO = "[GIVE_PAYMENT_INFO]"
TAG_PAYMENT_DP_UNCLEAR_PATTERN = re.compile(r"\[PAYMENT_DP_UNCLEAR:\s*([^\]]*)\]", re.IGNORECASE)

# Tag tenant-persistence cycle (Task 2) — best-effort advisory extraction from a payment-proof
# image, e.g. "[PAYMENT_PROOF_DETAILS: amount=150000]". Reuses the SAME vision call already
# looking at the image to decide [SUDAH_BAYAR] (no second API call) — the AI is instructed to
# include this ONLY alongside [SUDAH_BAYAR], and ONLY the amount= key is currently read by
# Python (see amount_detected on tenant_payment_reviews). Never treated as a verified figure —
# purely an advisory aid for the tenant owner's own manual review.
TAG_PAYMENT_PROOF_DETAILS_PATTERN = re.compile(r"\[PAYMENT_PROOF_DETAILS:\s*([^\]]*)\]", re.IGNORECASE)

# Tag LANGUAGE LAYER (additive) — dipasang AI di akhir balasan customer-facing tiap kali dia
# mutusin/konfirmasi ulang bahasa balasan buat customer ini, format "[SET_LANG: lang=id]" atau
# "[SET_LANG: lang=en]". Python cuma nyimpen ke customer_language dict, gak ngubah logic lain.
TAG_SET_LANG_PATTERN = re.compile(r"\[SET_LANG:\s*([^\]]+)\]", re.IGNORECASE)

# Berapa lama "mengetik..." ditampilkan sebelum tiap chat bubble dikirim (biar natural, bukan
# langsung nembak semua pesan dalam sepersekian detik).
TYPING_DELAY_MIN_SEC = 1.2
TYPING_DELAY_MAX_SEC = 4.0
TYPING_DELAY_PER_CHAR = 0.03


def strip_tags(text):
    """Buang semua tag internal dari teks yang bakal dikirim ke customer, rapihin spasi sisa."""
    cleaned = text
    for tag in ALL_TAGS:
        cleaned = cleaned.replace(tag, "")
    cleaned = TAG_NAMA_PATTERN.sub("", cleaned)
    cleaned = TAG_BOOK_MEETING_PATTERN.sub("", cleaned)
    cleaned = TAG_RESCHEDULE_MEETING_PATTERN.sub("", cleaned)
    cleaned = TAG_MEETING_PREFERENCE_PATTERN.sub("", cleaned)
    cleaned = TAG_MEETING_SLOT_PICK_PATTERN.sub("", cleaned)
    cleaned = TAG_PAYMENT_DP_UNCLEAR_PATTERN.sub("", cleaned)
    cleaned = TAG_SET_LANG_PATTERN.sub("", cleaned)
    cleaned = TAG_PAYMENT_PROOF_DETAILS_PATTERN.sub("", cleaned)
    # TAG_GIVE_PAYMENT_INFO SENGAJA TIDAK di-strip di sini — dia diganti eksplisit dengan teks rekening
    # resmi di webhook (lihat build_payment_info_text()), bukan dihapus jadi kosong.
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def call_claude(user_number, user_message, image_b64=None, image_mime=None, memory_override=None,
                 is_voice_note=False, tenant_context_block="", tenant_id=None):
    """Panggil Claude API buat generate balasan AI.

    `tenant_context_block` (Business Hub V2 Patch 2/6, default "") diteruskan apa adanya ke
    build_customer_system_prompt() — lihat docstring-nya. Default kosong = perilaku identik dengan
    sebelum patch ini ada, jadi setiap caller lain yang belum di-update tetap jalan tanpa perubahan.
    Default: Haiku (cost-optimal, default model untuk customer chat)
    Fallback: Sonnet (jika Haiku tidak tersedia atau gagal)

    Kalau ada image_b64 (customer kirim gambar, misal bukti transfer), WAJIB pakai Sonnet
    langsung (Haiku 3.5 gak bisa "lihat" gambar sama sekali) — jangan pernah kirim gambar ke Haiku.

    memory_override dipakai buat instruksi INTERNAL sistem (misal trigger follow-up otomatis) yang
    BUKAN beneran diketik customer — user_message TETAP dikirim ke API biar AI ngerti instruksinya,
    TAPI yang disimpen permanen ke memory/DB & history in-memory adalah teks di memory_override ini
    (tag singkat & jujur, BUKAN instruksi internal mentah), biar history tetap valid & gak keliatan
    seolah-olah customer yang ngetik instruksi sistem itu.

    `tenant_id` (multi-tenant runtime safety cycle, default None) — the SAME phone number can
    legitimately message two different client tenants (or a tenant AND Kilas Works itself); every
    read/write of the in-memory `conversations` history and of the DB-backed message log below is
    keyed by `_ck(tenant_id, user_number)`, NOT by the bare phone number, so those conversations
    are always kept completely separate. tenant_id=None (Kilas Works' own conversations) maps to
    the bare phone number unchanged (see _ck's docstring) — every caller that predates
    multi-tenancy keeps working with byte-for-byte identical keys."""
    scoped_number = _ck(tenant_id, user_number)
    history = conversations.get(scoped_number)
    if history is None:
        history = load_recent_messages_from_db(scoped_number, "customer")  # isi ulang kalau server abis restart

    if image_b64:
        # Content buat dikirim ke API request INI AJA (termasuk gambar beneran)
        api_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_mime or "image/jpeg",
                    "data": image_b64,
                },
            },
            {"type": "text", "text": user_message or "(customer kirim gambar tanpa keterangan)"},
        ]
        # Versi ringan buat disimpen ke memory/DB jangka panjang (JANGAN simpen base64 gambar
        # mentah-mentah ke history — berat & gak perlu, cukup catetan kalau ada gambar dikirim)
        memory_text = f"[CUSTOMER KIRIM GAMBAR] {user_message}".strip()
    elif memory_override is not None:
        api_content = user_message
        memory_text = memory_override
    elif is_voice_note:
        # Voice note customer (additive) — transcript dikirim APA ADANYA ke API (pipeline teks
        # yang sama persis, bukan engine kedua), cuma versi yang disimpen ke memory/DB dikasih tag
        # "[CUSTOMER VOICE NOTE]" biar owner-mode context (build_customer_context_summary) bisa
        # jawab natural kalau ditanya history customer yang terakhir kirim voice note.
        api_content = user_message
        memory_text = f"[CUSTOMER VOICE NOTE] {user_message}".strip()
    else:
        api_content = user_message
        memory_text = user_message

    history.append({"role": "user", "content": api_content})
    save_message_to_db(scoped_number, "customer", "user", memory_text)

    system_prompt = build_customer_system_prompt(scoped_number, tenant_context_block=tenant_context_block)

    # Coba dengan Haiku dulu (optimal untuk FAQ/reply otomatis) — KECUALI kalau ada gambar,
    # langsung Sonnet karena Haiku 3.5 gak support vision.
    model_to_use = MODEL_FAST if not image_b64 else MODEL_PRIMARY

    try:
        if image_b64:
            raise RuntimeError("skip-haiku-vision-not-supported")
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model_to_use,
                "max_tokens": 400,
                "system": system_prompt,
                "messages": history,
            },
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        # Fallback ke Sonnet kalau Haiku gagal
        print(f"Haiku request gagal ({e}), fallback ke Sonnet...")
        model_to_use = MODEL_FALLBACK
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model_to_use,
                "max_tokens": 400,
                "system": system_prompt,
                "messages": history,
            },
            timeout=30,
        )
        resp.raise_for_status()

    data = resp.json()
    reply_text = data["content"][0]["text"]
    log_ai_usage("customer", model_to_use, data)

    # Turunin balesan user tadi ke versi ringan (bukan gambar base64 mentah / instruksi internal
    # mentah) sebelum disimpen permanen ke memory in-memory (DB udah disimpen versi ringan dari awal).
    if image_b64 or memory_override is not None:
        history[-1] = {"role": "user", "content": memory_text}

    # Simpen versi BERSIH (tanpa tag internal kayak [TANYA_OWNER]) ke memory/DB, biar history yang
    # dipakai buat mikir Claude selanjutnya persis sama kayak apa yang BENERAN dilihat customer —
    # bukan versi mentah yang masih ada tag sistemnya.
    clean_reply_for_memory = strip_tags(reply_text)
    history.append({"role": "assistant", "content": clean_reply_for_memory})
    conversations[scoped_number] = history[-20:]  # simpan 20 pesan terakhir aja
    save_message_to_db(scoped_number, "customer", "assistant", clean_reply_for_memory)

    return reply_text


def send_typing_indicator(incoming_message_id):
    """Tandain pesan customer 'dibaca' + tampilin status 'mengetik...' di WhatsApp mereka."""
    if not incoming_message_id:
        return
    url = f"https://graph.facebook.com/v21.0/{_active_whatsapp_phone_number_id()}/messages"
    headers = {
        "Authorization": f"Bearer {_active_whatsapp_access_token()}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": incoming_message_id,
        "typing_indicator": {"type": "text"},
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        print("Typing indicator response:", r.status_code, r.text)
    except Exception as e:
        print("Error kirim typing indicator:", e)


def send_whatsapp_message(to_number, message_text):
    """Kirim pesan teks balasan lewat WhatsApp Cloud API.
    Balikin (success: bool, error_detail: str atau None) — JANGAN pernah anggap terkirim cuma
    karena gak ada exception, WhatsApp API bisa balas status 4xx (misal di luar 24 jam window,
    nomor invalid, dll) tanpa raise error."""
    url = f"https://graph.facebook.com/v21.0/{_active_whatsapp_phone_number_id()}/messages"
    headers = {
        "Authorization": f"Bearer {_active_whatsapp_access_token()}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message_text},
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        print("Kirim WA response:", r.status_code, r.text)
        if r.status_code == 200:
            return True, None
        # Coba ambil pesan error yang manusiawi dari response Meta
        try:
            err = r.json().get("error", {}).get("message", r.text)
        except Exception:
            err = r.text
        return False, err
    except Exception as e:
        print("Error kirim WA message:", e)
        return False, str(e)


def download_whatsapp_media(media_id):
    """Download media (gambar ATAU audio voice note) yang dikirim customer/owner lewat WhatsApp,
    balikin (base64_data, mime_type) — atau (None, None) kalau gagal di step manapun. Dipakai
    SAMA-SAMA oleh jalur gambar (bukti transfer, dst) dan jalur voice note — jangan diasumsikan
    "pasti gambar" di mana pun di fungsi ini.

    Dua tahap terpisah (metadata → lalu isi media), masing-masing di-log via VOICE_DEBUG kalau
    gagal, supaya kalau ada laporan "media gagal kebuka" jelas kelihatan di tahap MANA gagalnya:
    - metadata request (media_id invalid/expired, access token salah/expired)
    - media content request (URL metadata valid tapi isi filenya gagal ke-fetch)
    Ini FIX diagnostik dari laporan bug voice note — sebelumnya dua tahap ini digabung jadi satu
    try/except besar jadi gak kelihatan tahap mana yang gagal dari log."""
    try:
        meta_url = f"https://graph.facebook.com/v21.0/{media_id}"
        headers = {"Authorization": f"Bearer {_active_whatsapp_access_token()}"}
        r = requests.get(meta_url, headers=headers, timeout=30)
        r.raise_for_status()
        meta = r.json()
    except Exception as e:
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        _voice_debug("media_metadata", success=False, exception_class=type(e).__name__, http_status=status_code)
        print("Error ambil metadata media WA:", e)
        return None, None

    media_url = meta.get("url")
    # BUG FIX (voice bugfix cycle): default lama "image/jpeg" cuma masuk akal buat jalur gambar —
    # fungsi ini SEKARANG juga dipakai buat audio, jadi default netral (string kosong) biar caller
    # (transcribe_audio_whatsapp) yang nentuin penanganannya sendiri, bukan diam-diam dianggap JPEG.
    mime_type = meta.get("mime_type", "")
    if not media_url:
        _voice_debug("media_metadata", success=True, media_url_present=False, mime_type=mime_type)
        print("Download media WA: gak ada URL di response metadata:", meta)
        return None, None
    _voice_debug("media_metadata", success=True, media_url_present=True, mime_type=mime_type)

    try:
        r2 = requests.get(media_url, headers=headers, timeout=30)
        r2.raise_for_status()
        content_length = len(r2.content or b"")
        _voice_debug("media_download", success=True, http_status=r2.status_code, byte_length=content_length)
        if content_length == 0:
            print("Download media WA: isi file kosong (0 bytes) padahal request sukses.")
            return None, None
        b64_data = base64.b64encode(r2.content).decode("utf-8")
        return b64_data, mime_type
    except Exception as e:
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        _voice_debug("media_download", success=False, exception_class=type(e).__name__, http_status=status_code)
        print("Error download isi media WA:", e)
        return None, None


def send_reply_bubbles(to_number, incoming_message_id, full_reply_text):
    """Pecah balasan AI jadi beberapa 'chat bubble' (dipisah '|||'), kirim satu-satu dengan
    jeda 'sedang mengetik...' di antaranya biar natural kayak orang WA-an beneran.
    Balikin (success: bool, error_detail: str atau None) — kalau ADA SATU AJA bubble yang gagal
    kekirim, ini dianggap GAGAL (dan yang manggil WAJIB cek ini sebelum bilang 'udah dikirim')."""
    parts = [p.strip() for p in full_reply_text.split("|||") if p.strip()]
    if not parts:
        return False, "Gak ada isi pesan buat dikirim (kosong)."

    for part in parts:
        send_typing_indicator(incoming_message_id)
        delay = min(TYPING_DELAY_MAX_SEC, max(TYPING_DELAY_MIN_SEC, len(part) * TYPING_DELAY_PER_CHAR))
        time.sleep(delay)
        ok, err = send_whatsapp_message(to_number, part)
        if not ok:
            return False, err

    return True, None


def upload_media(file_path, mime_type):
    """Upload file (gambar/dokumen) ke WhatsApp Cloud API, balikin media_id-nya (atau None kalau gagal)."""
    if not os.path.exists(file_path):
        print(f"File gak ketemu di path: {file_path} — skip kirim.")
        return None

    url = f"https://graph.facebook.com/v21.0/{_active_whatsapp_phone_number_id()}/media"
    headers = {"Authorization": f"Bearer {_active_whatsapp_access_token()}"}
    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, mime_type)}
            data = {"messaging_product": "whatsapp"}
            r = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        print("Upload media response:", r.status_code, r.text)
        if r.status_code == 200:
            return r.json().get("id")
    except Exception as e:
        print("Error upload media:", e)
    return None


def upload_media_bytes(raw_bytes, mime_type, filename="gambar.jpg"):
    """Sama kayak upload_media(), tapi buat data yang udah ada di memori (bytes), bukan file di
    disk — dipakai buat re-upload gambar yang diterima dari owner (misal QR code custom) biar bisa
    diforward ke customer sebagai gambar beneran, bukan cuma teks."""
    url = f"https://graph.facebook.com/v21.0/{_active_whatsapp_phone_number_id()}/media"
    headers = {"Authorization": f"Bearer {_active_whatsapp_access_token()}"}
    try:
        files = {"file": (filename, io.BytesIO(raw_bytes), mime_type)}
        data = {"messaging_product": "whatsapp"}
        r = requests.post(url, headers=headers, files=files, data=data, timeout=30)
        print("Upload media (bytes) response:", r.status_code, r.text)
        if r.status_code == 200:
            return r.json().get("id")
    except Exception as e:
        print("Error upload media (bytes):", e)
    return None


def send_whatsapp_image(to_number, media_id, caption=None):
    """Kirim gambar (pakai media_id yang udah diupload) ke suatu nomor WhatsApp.
    Balikin (success: bool, error_detail: str atau None) — sama kayak send_whatsapp_message,
    JANGAN pernah anggap terkirim cuma karena gak exception."""
    url = f"https://graph.facebook.com/v21.0/{_active_whatsapp_phone_number_id()}/messages"
    headers = {
        "Authorization": f"Bearer {_active_whatsapp_access_token()}",
        "Content-Type": "application/json",
    }
    image_payload = {"id": media_id}
    if caption:
        image_payload["caption"] = caption
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "image",
        "image": image_payload,
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        print("Kirim gambar WA response:", r.status_code, r.text)
        if r.status_code == 200:
            return True, None
        try:
            err = r.json().get("error", {}).get("message", r.text)
        except Exception:
            err = r.text
        return False, err
    except Exception as e:
        print("Error kirim gambar WA:", e)
        return False, str(e)


def parse_target_number(text):
    """Ekstrak nomor tujuan dari teks kayak 'kirim ke 628xxx' atau 'kirim ke 628xxx, ini dia'.
    Beda dari parse_direct_command (buat pesan TEKS, yang WAJIB ada pesan abis nomornya) — ini
    dipakai buat forward GAMBAR, di mana teks abis nomor itu opsional (cuma jadi caption gambar).
    Return (nomor, sisa_teks_atau_None)."""
    if not text:
        return None, None
    match = re.search(r'kirim\s+ke\s+((?:\+)?62\d+)\s*(.*)', text, re.IGNORECASE | re.DOTALL)
    if not match:
        return None, None
    number = match.group(1).lstrip('+')
    if not number.startswith('62'):
        number = '62' + number
    extra = match.group(2).strip()
    return number, (extra or None)


def send_qr_code(to_number):
    """Kirim gambar QR code pembayaran statis ke customer, kalau file-nya ada.
    BELUM DIPAKAI dulu (lihat catatan di QR_IMAGE_PATH) — pembayaran sekarang pakai transfer BCA."""
    media_id = upload_media(QR_IMAGE_PATH, "image/jpeg")
    if not media_id:
        return False

    url = f"https://graph.facebook.com/v21.0/{_active_whatsapp_phone_number_id()}/messages"
    headers = {
        "Authorization": f"Bearer {_active_whatsapp_access_token()}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "image",
        "image": {
            "id": media_id,
            "caption": "Ini QR code buat pembayarannya ya, nanti nominal & konfirmasi dibantu tim kita.",
        },
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("Kirim QR response:", r.status_code, r.text)
    return r.status_code == 200


# Cache media_id katalog PDF yang udah diupload ke WhatsApp, biar gak upload ulang file yang SAMA
# tiap kali mau kirim (media_id WA valid lumayan lama). Kita simpen juga path & mtime file-nya —
# kalau katalog.pdf di-update (deploy baru), mtime-nya beda -> otomatis upload ulang versi terbaru.
_CATALOG_MEDIA_ID_CACHE = {"media_id": None, "path": None, "mtime": None}


def _get_live_catalog_pdf_path_safe():
    """Absolute Final Production Patch (Section 8-9): prefer Client Hub's live, DB-generated
    catalog PDF (client-hub/live_catalog_pdf.py) over the static ../katalog.pdf whenever it's
    available — that file always reflects current prices/talent, the static one only reflects
    whatever PRICING_CONFIG looked like the last time someone manually re-ran
    generate_katalog_pdf.py. Any failure (Client Hub bridge unavailable, DB down, reportlab
    missing) is swallowed and logged internally only — the caller falls back to the static PDF,
    the customer never sees a technical error."""
    if not _CLIENT_HUB_AVAILABLE:
        return None
    try:
        import live_catalog_pdf as _live_catalog_pdf
        return _live_catalog_pdf.get_cached_catalog_pdf_path()
    except Exception as e:
        print(f"Live catalog tidak tersedia ({e}) — fallback ke katalog.pdf statis.")
        return None


def get_catalog_media_id(force_refresh=False):
    """Balikin media_id katalog PDF yang siap dipakai kirim. Reuse media_id yang udah di-cache kalau
    file-nya belum berubah (sama path & mtime) & belum diminta refresh paksa. Kalau file baru/beda/
    belum pernah diupload, atau media_id lama udah expired (force_refresh=True dari caller), upload
    ulang. Return None kalau katalog.pdf gak ketemu sama sekali atau upload gagal.

    Prefers the live Client-Hub-generated catalog (see _get_live_catalog_pdf_path_safe) and falls
    back to the static ../katalog.pdf search only if the live one is unavailable — mtime-based
    cache invalidation below works unchanged either way since both paths are real files on disk."""
    path = _get_live_catalog_pdf_path_safe() or find_catalog_pdf_path()
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None

    cache = _CATALOG_MEDIA_ID_CACHE
    if (
        not force_refresh
        and cache["media_id"]
        and cache["path"] == path
        and cache["mtime"] == mtime
    ):
        return cache["media_id"]

    media_id = upload_media(path, "application/pdf")
    if media_id:
        cache.update(media_id=media_id, path=path, mtime=mtime)
    return media_id


def send_catalog_pdf(to_number):
    """Kirim katalog PDF (daftar lengkap layanan & harga, SATU-SATUNYA sumber file yang sama dipakai
    di mana-mana — lihat find_catalog_pdf_path()) ke suatu nomor WhatsApp sebagai dokumen.
    Balikin (success: bool, error_detail: str atau None) — JANGAN PERNAH dianggap kekirim cuma
    karena gak exception (sama prinsipnya kayak send_whatsapp_message/send_whatsapp_image)."""
    path = _get_live_catalog_pdf_path_safe() or find_catalog_pdf_path()
    if not path:
        return False, "katalog.pdf gak ketemu di repository (sudah dicari recursive)."

    media_id = get_catalog_media_id()
    if not media_id:
        return False, "Gagal upload katalog.pdf ke WhatsApp."

    def _do_send(mid):
        url = f"https://graph.facebook.com/v21.0/{_active_whatsapp_phone_number_id()}/messages"
        headers = {
            "Authorization": f"Bearer {_active_whatsapp_access_token()}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "document",
            "document": {
                "id": mid,
                "filename": CATALOG_PDF_FILENAME,
                "caption": "Ini katalog lengkap layanan & harga Kilas Works ya 📄",
            },
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        print("Kirim katalog response:", resp.status_code, resp.text)
        return resp

    r = _do_send(media_id)
    if r.status_code == 200:
        return True, None

    # media_id kemungkinan expired/invalid (WA kadang balikin error kode 131052/param invalid buat
    # media_id lama) — coba upload ULANG sekali, baru kirim ulang sekali lagi sebelum nyerah.
    fresh_media_id = get_catalog_media_id(force_refresh=True)
    if fresh_media_id and fresh_media_id != media_id:
        r2 = _do_send(fresh_media_id)
        if r2.status_code == 200:
            return True, None
        return False, r2.text

    return False, r.text


def notify_owner_new_message(from_number, message_text, name=None, tenant_id=None):
    """Kirim notifikasi ringan ke owner SEKALI AJA pas ada customer BARU pertama kali chat (dipanggil
    dari receive_webhook cuma kalau is_new_customer True) — biar owner tau siapa aja yang mulai chat,
    tanpa banjir notif tiap pesan dari customer yang sama. Ini terpisah dari notify_owner/
    notify_owner_question yang isinya notifikasi khusus buat aksi tertentu (leads panas, tanya owner,
    dsb) — bisa muncul barengan kalau relevan.

    `tenant_id` (multi-tenant runtime safety cycle, Task 6, default None) — a resolved CLIENT
    tenant's own day-to-day customer-service notification (a NEW customer chatting in) must go to
    THAT BUSINESS's own configured owner (trusted_owner_phone), NEVER to Kilas Works' own platform
    owner. See _get_tenant_owner_notify_target_safe/is_kilas_platform_tenant. Default None keeps
    every pre-multi-tenant caller sending to Kilas Works' own OWNER_WHATSAPP_NUMBER unchanged."""
    target = _get_tenant_owner_notify_target_safe(tenant_id)
    if not target:
        return
    who = f"{name} (wa.me/{from_number})" if name else f"wa.me/{from_number}"
    text = f'💬 Customer baru chat: {who}\nPesan pertama: "{message_text}"'
    send_whatsapp_message(target, text)


def notify_owner(from_number, reason, last_message, tenant_id=None):
    """Kirim notifikasi ke WA pribadi owner (bukan nomor bot) soal leads panas atau konfirmasi
    pembayaran. (Untuk pertanyaan yang perlu dijawab manual, lihat notify_owner_question — itu
    yang punya fitur auto-relay jawaban ke customer.)

    `tenant_id` — see notify_owner_new_message's docstring: a resolved client tenant's own
    escalation goes to THAT tenant's own owner, never to Kilas Works' own platform owner."""
    target = _get_tenant_owner_notify_target_safe(tenant_id)
    if not target:
        return
    text = (
        f"🔔 {reason}\n\n"
        f"Dari: wa.me/{from_number}\n"
        f'Pesan terakhir: "{last_message}"\n\n'
        f"Cek & follow up langsung ke nomor itu ya."
    )
    send_whatsapp_message(target, text)


def notify_owner_question(from_number, last_message, tenant_id=None):
    """Kirim notifikasi ke owner soal pertanyaan yang AI belum yakin jawabnya, DAN simpan sebagai
    pending. Owner bisa diskusi bebas dulu soal ini di chat yang sama (lihat call_claude_owner &
    cabang OWNER di receive_webhook) — baru pas owner bilang eksplisit suruh forward, jawabannya
    diterusin ke customer.

    `tenant_id` — see notify_owner_new_message's docstring: a resolved client tenant's own pending
    question goes to THAT tenant's own owner, never to Kilas Works' own platform owner.
    pending_owner_questions itself IS tenant-scoped (Task 5 — keyed by _ck(tenant_id, phone), see
    _pending_owner_questions_for_tenant), so a tenant's pending entry can never surface in another
    tenant's or Kilas Works' own owner data. NOTE: the "diskusi bebas + terusin ke customer"
    auto-relay flow above (FORWARD_MARKER, mention lookup, FIFO fallback pick) is still wired only
    for Kilas Works' own owner branch — a tenant owner gets the notification, but replying here to
    relay it back through that specific UX is a known limitation of this cycle."""
    target = _get_tenant_owner_notify_target_safe(tenant_id)
    if not target:
        return
    text = (
        f"🔔 Ada pertanyaan yang AI belum yakin jawabnya, tolong cek manual\n\n"
        f"Dari: wa.me/{from_number}\n"
        f'Pesan terakhir: "{last_message}"\n\n'
        f"Chat aja di sini kalau mau diskusi dulu, nanti kalau udah fix jawabannya tinggal bilang "
        f'"terusin ke customer" (atau semacamnya), baru aku kirimin ke dia 👍'
    )
    send_whatsapp_message(target, text)


def log_customer_message(to_number, message_text, sent_from="automated"):
    """Audit trail CONSOLE-ONLY buat tiap pesan yang dikirim ke customer (via forward/direct command/
    auto-followup). SENGAJA gak nulis apa-apa ke database lagi di sini — caller (webhook) udah nyimpen
    versi BERSIH pesan ini duluan lewat save_message_to_db() sebelum manggil fungsi ini. Dulu fungsi
    ini juga nulis baris KEDUA ke DB dengan prefix "[LOG-...]", yang bikin history customer ke-duplikat
    (2 baris buat 1 kali kirim) & bisa kebawa balik jadi konteks obrolan ke Claude API pas history
    di-reload — udah dihapus, sekarang CUMA log ke console, gak pernah nyentuh WhatsApp/database lagi."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] → wa.me/{to_number} ({sent_from}): {message_text[:100]}...")


# ============================================================
# PERINTAH LANGSUNG OWNER (nama ATAU nomor) — EKSEKUSI LANGSUNG, bukan draft-lalu-tunggu-approval.
# Kalau owner udah jelas nyuruh kirim/balas/follow-up ke customer tertentu, sistem langsung cari
# nomornya (dari nama atau nomor), pastiin gak ambigu, terus BENERAN kirim di respons yang sama —
# gak ada lagi ronde "oke?/terusin" kedua kecuali targetnya emang ambigu/gak ketemu.
# ============================================================

QUESTION_WORD_PATTERN = re.compile(
    r'^\s*(apa|siapa|gimana|bagaimana|kapan|kenapa|kok|berapa|apakah|dimana|di\s+mana)\b',
    re.IGNORECASE,
)

# Kata/frasa yang nunjukin owner lagi MINTA SARAN/DRAFT doang, bukan nyuruh kirim beneran.
DRAFT_REQUEST_HINTS = [
    "menurut", "kasih saran", "kasih ide", "bikinin draft", "buatkan draft", "buat draft",
    "contoh pesan", "draft aja", "balas apa", "jawab apa", "enaknya gimana", "bagusnya gimana",
]

# Frasa yang nunjukin owner lagi NANYA HISTORY/APA YANG DIOMONGIN customer (baca doang), BUKAN
# nyuruh kirim apa-apa — mis. "itu jelajah visa chat apa aja", "kimfong tadi nanya apa", "caca
# terakhir chat apa", "yang barusan chat siapa". Dicek di MANA AJA di kalimat (bukan cuma di awal),
# beda dari QUESTION_WORD_PATTERN yang cuma cek kata pembuka.
HISTORY_QUERY_HINT_PATTERN = re.compile(
    r'\b(apa\s+aja|apa\s+ajah|ngomong\s+apa|ngomongin\s+apa|nanya\s+apa|tanya\s+apa|bilang\s+apa|'
    r'cerita\s+apa|chat\s+apa|chatnya\s+apa|chat\s+apaan|barusan\s+chat|barusan\s+ngomong|'
    r'tadi\s+ngomong|tadi\s+chat|tadi\s+nanya|terakhir\s+chat|terakhir\s+ngomong|chat\s+siapa|'
    r'ngomong\s+siapa|chat\s+apa\s+aja)\b',
    re.IGNORECASE,
)

# Kata ganti/rujukan ke "customer yang lagi dibahas" — di-resolve ke active_customer_context,
# BUKAN dicari sebagai nama customer literal.
PRONOUN_TARGETS = {"dia", "nya", "customer", "customernya", "orangnya", "ini", "tadi"}

# Kata tanya/filler yang TIDAK BOLEH pernah ditebak sebagai nama customer (ini yang bikin bug
# "itu jelajah visa chat apa aja" kesasar nyari customer bernama "apa"). Dipakai sebagai guard di
# split_target_from_rest (jangan fallback ke kata ini) & extract_mentioned_customer (skip candidate
# 1-kata yang emang cuma kata umum, bukan nama).
STOPWORDS_NOT_NAMES = {
    "apa", "aja", "ajah", "itu", "ini", "dia", "nya", "tadi", "chat", "chatnya", "chatin",
    "terakhir", "yang", "ngomong", "ngomongin", "nanya", "tanya", "tanyain", "bilang", "cerita",
    "gimana", "kenapa", "gitu", "tuh", "dong", "sih", "kok", "td", "barusan", "habis", "abis",
    "udah", "sudah", "belum", "balas", "bales", "reply", "kirim", "kirimin", "sampein", "follow", "up",
    "followup", "ingetin", "ingatkan", "tentang", "soal", "siapa", "kapan", "berapa", "dimana",
    "dengan", "untuk", "ke", "dan", "atau", "juga", "aku", "gw", "gue", "saya", "owner",
    "customer", "customernya", "orangnya", "ya", "nih", "deh", "kah", "sm", "sama",
}

# Cuma nangkep KATA KERJA-nya doang (bukan target-nya) — target di-parse terpisah di
# parse_owner_send_command, biar bisa nyocokin nama MULTI-KATA (mis. "Kimfong Wijaya") ke
# customer_names beneran, bukan asal motong 1 kata pertama abis kata kerja.
SEND_VERB_PATTERN = re.compile(
    r'\b(?:kirim(?:in)?(?:\s+ini)?\s+ke|balas|bales|reply(?:\s+ke)?|follow[\s\-]?up|'
    r'tanyain|ingetin|ingatkan|sampein\s+ke|bilang\s+ke|chat(?:in)?(?:\s+ke)?|'
    r'teruskan(?:\s+ke)?|terusin(?:\s+ke)?)\b',
    re.IGNORECASE,
)

# Kata kunci yang misahin "target" dari "isi instruksi" pas gak ada titik dua eksplisit
# (mis. "balas Kimfong Wijaya BILANG besok bisa" -> target="Kimfong Wijaya", instruksi="besok bisa").
TARGET_SEPARATOR_KEYWORD_PATTERN = re.compile(r'\b(bilang|tentang|soal)\b', re.IGNORECASE)


def split_target_from_rest(remainder):
    """remainder = teks abis kata kerja & abis separator (kalau ada), ATAU teks abis kata kerja
    langsung (kalau gak ada separator sama sekali). Coba cocokin PREFIX kata-katanya (dari yang
    PALING PANJANG dulu, maks 4 kata) ke nama customer yang BENERAN ada di customer_names atau ke
    kata ganti (dia/nya/dll) — biar nama 2-3 kata kayak 'Kimfong Wijaya' kebaca UTUH sebagai satu
    target, bukan kepotong jadi 'Kimfong' doang + 'Wijaya' nyasar ke pesan. Kalau gak ada satupun
    yang cocok di data, fallback ke 1 kata pertama aja (perilaku lama, biar tetep ada guess buat
    nomor HP atau nama yang belum ke-capture di sistem)."""
    words = remainder.strip().split()
    if not words:
        return "", ""
    best_len = 0
    for n in range(min(4, len(words)), 0, -1):
        candidate = " ".join(words[:n]).strip(",.:;")
        if candidate.lower() in PRONOUN_TARGETS or find_customers_by_name(candidate):
            best_len = n
            break
    if best_len == 0:
        # Gak ketemu data yang cocok sama sekali. Fallback lama: tebak 1 kata pertama (buat jaga-jaga
        # nomor HP atau nama yang belum ke-capture di sistem) — TAPI JANGAN kalau kata itu emang cuma
        # kata tanya/filler biasa (apa/aja/itu/dia/tadi/chat/terakhir/yang/dst), soalnya itu SIGNAL
        # kuat ini BUKAN perintah kirim sama sekali (kemungkinan besar pertanyaan/obrolan biasa).
        first_word = words[0].strip(",.:;").lower()
        if first_word in STOPWORDS_NOT_NAMES:
            return "", remainder
        best_len = 1
    target = " ".join(words[:best_len]).strip(",.:;")
    rest = " ".join(words[best_len:]).strip()
    return target, rest


def extract_mentioned_customer(text):
    """Scan SELURUH teks owner (bukan cuma abis kata kerja tertentu) buat nemuin nama customer yang
    eksplisit disebut di mana aja di kalimat — dipakai pas pesan owner BUKAN perintah kirim (misal
    pertanyaan history kayak "itu jelajah visa chat apa aja"), biar sistem tau customer mana yang lagi
    dibahas TANPA nebak-nebak dari kata tanya/filler ("apa", "itu", dst) sebagai nama.
    Coba kombinasi kata TERPANJANG dulu (maks 4 kata, dari posisi mana aja di kalimat), skip kandidat
    1-kata yang cuma kata umum (STOPWORDS_NOT_NAMES).
    Return ("ok", number, name) / ("ambiguous", [(number,name),...], None) / ("none", None, None)."""
    words = re.findall(r"[A-Za-z0-9']+", text or "")
    n = len(words)
    if n == 0:
        return ("none", None, None)
    for length in range(min(4, n), 0, -1):
        for start in range(0, n - length + 1):
            chunk = words[start:start + length]
            if length == 1 and chunk[0].lower() in STOPWORDS_NOT_NAMES:
                continue
            candidate = " ".join(chunk)
            matches = find_customers_by_name(candidate)
            if len(matches) == 1:
                return ("ok", matches[0][0], matches[0][1])
            if len(matches) > 1:
                return ("ambiguous", matches, None)
    return ("none", None, None)


# ============================================================
# PERINTAH OWNER: UPDATE STATUS MEETING (mis. "meeting Caca selesai" / "meeting Kimfong gak jadi" /
# "meeting Bapak Andi no show") — biar status appointment ke-update tanpa harus utak-atik DB manual.
# ============================================================

MEETING_STATUS_TRIGGER_PATTERN = re.compile(r'\bmeeting(?:nya)?\b', re.IGNORECASE)

MEETING_STATUS_WORDS = [
    (re.compile(r'\b(selesai|udah\s+ketemu|sudah\s+ketemu|done|udah\s+meeting|sudah\s+meeting)\b', re.IGNORECASE), "completed"),
    (re.compile(r'\b(gak\s+jadi|nggak\s+jadi|ga\s+jadi|batal(?:in)?|cancel)\b', re.IGNORECASE), "cancelled"),
    (re.compile(r'\b(no\s*show|gak\s+dateng|nggak\s+dateng|ga\s+dateng|gak\s+datang|tidak\s+datang|bolos)\b', re.IGNORECASE), "no_show"),
]


def parse_meeting_status_command(text):
    """Deteksi perintah owner buat update status meeting customer tertentu jadi
    completed/cancelled/no_show. Return {"target_raw": ..., "status": ...} atau None kalau
    teksnya bukan perintah status meeting."""
    if not text:
        return None
    match = MEETING_STATUS_TRIGGER_PATTERN.search(text)
    if not match:
        return None

    status = None
    for pattern, status_value in MEETING_STATUS_WORDS:
        if pattern.search(text):
            status = status_value
            break
    if not status:
        return None

    before = text[:match.start()].strip()
    after = text[match.end():].strip()
    # Target biasanya ada SESUDAH kata "meeting" (mis. "meeting Caca selesai"),
    # tapi bisa juga SEBELUMNYA (mis. "Caca meeting-nya selesai"). Coba dua-duanya.
    for chunk in (after, before):
        if not chunk:
            continue
        target, _rest = split_target_from_rest(chunk)
        candidate = (target or "").strip(",.:;")
        if candidate:
            return {"target_raw": candidate, "status": status}
    return None


# ============================================================
# PERINTAH OWNER: UPDATE STATUS PEMBAYARAN (mis. "pembayaran Yutha udah masuk" / "DP Caca confirmed" /
# "Wilson udah lunas" / "transfer dia belum masuk") — production hardening, poin 13. Sama prinsipnya
# kayak parse_meeting_status_command di atas: DETERMINISTIK (regex), bukan lewat AI, biar status
# pembayaran gak pernah salah update / ke-tebak keliru.
# ============================================================

PAYMENT_STATUS_TRIGGER_PATTERN = re.compile(
    r'\b(pembayaran(?:nya)?|bayar(?:annya)?|dp(?:nya)?|transfer(?:an)?(?:nya)?|lunas)\b', re.IGNORECASE
)
_PAYMENT_NEGATIVE_PATTERN = re.compile(
    r'\b(belum\s+masuk|belum\s+ada|belum\s+kelihatan|belum\s+kekirim|gagal)\b', re.IGNORECASE
)
_PAYMENT_POSITIVE_PATTERN = re.compile(
    r'\b(lunas|full|udah\s+masuk|sudah\s+masuk|udah\s+beres|sudah\s+beres|confirmed|oke\s+masuk|'
    r'masuk\s+semua|masuk)\b', re.IGNORECASE
)
_PAYMENT_DP_WORD_PATTERN = re.compile(r'\bdp\b', re.IGNORECASE)


def parse_owner_payment_command(text):
    """Deteksi perintah owner update status pembayaran customer tertentu. Return
    {"target_raw": ..., "status": ...} (status = salah satu PAYMENT_STATUS_* konstanta) atau None
    kalau teksnya bukan perintah status pembayaran.
    Urutan prioritas: (1) ada kata NEGATIF ('belum masuk' dsb) -> NEEDS_RECHECK, apapun konteksnya.
    (2) ada kata 'dp' + kata POSITIF ('confirmed'/'masuk'/dsb) -> PARTIALLY_PAID (DP doang, bukan lunas
    penuh). (3) ada kata POSITIF tanpa 'dp' -> PAID (lunas penuh)."""
    if not text:
        return None
    match = PAYMENT_STATUS_TRIGGER_PATTERN.search(text)
    if not match:
        return None

    has_dp = bool(_PAYMENT_DP_WORD_PATTERN.search(text))
    is_negative = bool(_PAYMENT_NEGATIVE_PATTERN.search(text))
    is_positive = bool(_PAYMENT_POSITIVE_PATTERN.search(text))

    if is_negative:
        status = PAYMENT_STATUS_NEEDS_RECHECK
    elif has_dp and is_positive:
        status = PAYMENT_STATUS_PARTIALLY_PAID
    elif is_positive:
        status = PAYMENT_STATUS_PAID
    else:
        return None

    before = text[:match.start()].strip()
    after = text[match.end():].strip()
    for chunk in (before, after):
        if not chunk:
            continue
        target, _rest = split_target_from_rest(chunk)
        candidate = (target or "").strip(",.:;")
        if candidate:
            return {"target_raw": candidate, "status": status}
    return None


def short_display_name(full_name):
    """Buat teks konfirmasi ringkas ('Terkirim ke Kimfong.') — ambil kata PERTAMA dari nama yang
    tersimpan, biar natural kayak manggil orang (bukan nyebut nama lengkap kaku tiap konfirmasi)."""
    if not full_name:
        return full_name
    return full_name.split()[0]


def looks_like_question_or_draft_request(text):
    """Cek apakah teks ini kemungkinan besar PERTANYAAN (baca doang) atau PERMINTAAN SARAN/DRAFT,
    BUKAN perintah kirim eksplisit — biar sistem gak salah eksekusi kirim padahal owner cuma nanya
    atau minta saran jawaban (mis. 'apa chat terakhir Caca?', 'menurut lu gue balas apa ke Caca?')."""
    if not text:
        return False
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    if QUESTION_WORD_PATTERN.match(stripped):
        return True
    lower = stripped.lower()
    if HISTORY_QUERY_HINT_PATTERN.search(lower):
        return True
    return any(hint in lower for hint in DRAFT_REQUEST_HINTS)


def normalize_owner_text_light(text):
    """Normalisasi RINGAN buat teks owner sebelum masuk ke parser command (regex-based) — cuma
    rapihin noise ketikan yang gak ngubah makna (spasi berlebih, huruf diulang-ulang kayak "besokk"
    /"yaa" jadi maks 2 huruf beruntun). SENGAJA TIDAK lowercase paksa/koreksi ejaan/ubah angka -
    tanggal - harga, biar nama customer, nominal, dan tanggal gak pernah ketebak/overcorrect. Kalau
    hasil normalisasi bikin ambigu, biarkan parser di bawahnya yang tetap nanya klarifikasi
    (bukan fungsi ini yang mutusin)."""
    if not text:
        return text
    # Rapihin whitespace berlebih ("kirim   katalog" -> "kirim katalog")
    cleaned = re.sub(r"\s+", " ", text).strip()
    # Kolaps 3+ huruf sama beruntun jadi 2 ("besokk" udah 2 huruf, aman; "oiii"/"yaaa" -> "oii"/"yaa")
    # — batas 3+ dipilih SENGAJA biar kata normal berhuruf dobel (kayak "pass", "class") gak kesenggol.
    cleaned = re.sub(r"(.)\1{2,}", r"\1\1", cleaned)
    return cleaned


def _normalize_name_key(s):
    """Buang semua spasi/tanda baca & lowercase, biar matching nama gak kepengaruh cara owner
    ngetik spasi (mis. \"jelajah visa\" ketik 2 kata vs data tersimpan \"JelajahVisa\" 1 kata)."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def find_customers_by_name(name_query):
    """Cari customer yang namanya cocok sama name_query — case-insensitive, partial match, DAN
    spasi-insensitive (biar "jelajah visa" ketemu "JelajahVisa" walau beda cara nulis spasinya).
    Return list of (number, name) — bisa 0, 1, atau lebih dari 1 hasil (nama kembar/mirip)."""
    name_query = (name_query or "").strip().lower()
    if not name_query:
        return []
    norm_query = _normalize_name_key(name_query)
    matches = []
    for number, name in customer_names.items():
        if not name:
            continue
        name_lower = name.lower()
        if name_query in name_lower or (norm_query and norm_query in _normalize_name_key(name)):
            matches.append((number, name))
    return matches


def normalize_phone_candidate(raw):
    """Kalau raw ini kelihatan kayak nomor HP (62xxx/0xxx/+62xxx, minimal 8 digit), normalize ke
    format 62xxxxxxxxxx. Return None kalau bukan nomor (berarti kemungkinan ini nama orang)."""
    digits = re.sub(r'\D', '', raw or "")
    if len(digits) < 8:
        return None
    if digits.startswith("62"):
        return digits
    if digits.startswith("0"):
        return "62" + digits[1:]
    if (raw or "").strip().startswith("+"):
        return digits
    return None


def resolve_owner_target(target_raw, active_target_fallback):
    """Resolve potongan teks abis kata kerja kirim/balas/dll jadi SATU nomor customer yang pasti.
    Return salah satu:
      ("ok", number, display_name)
      ("ambiguous", [(number, name), ...], None)   -- nama ketemu, tapi lebih dari 1 customer cocok
      ("not_found", target_raw, None)               -- bukan nomor & gak ada nama yang cocok
    """
    if target_raw.lower() in PRONOUN_TARGETS:
        if active_target_fallback:
            name = customer_names.get(active_target_fallback, f"wa.me/{active_target_fallback}")
            return ("ok", active_target_fallback, name)
        return ("not_found", target_raw, None)

    phone = normalize_phone_candidate(target_raw)
    if phone:
        name = customer_names.get(phone, f"wa.me/{phone}")
        return ("ok", phone, name)

    matches = find_customers_by_name(target_raw)
    if len(matches) == 1:
        return ("ok", matches[0][0], matches[0][1])
    if len(matches) > 1:
        return ("ambiguous", matches, None)
    return ("not_found", target_raw, None)


def parse_owner_send_command(text):
    """Deteksi perintah eksplisit owner buat kirim/balas/follow-up/dll ke customer tertentu (target
    boleh nama LENGKAP, nama PANGGILAN/partial, atau nomor). Return dict {"target_raw", "separator",
    "rest"}, atau None kalau ini bukan perintah kirim (pertanyaan/minta saran/obrolan biasa).

    Urutan deteksi target:
    1. Ada titik dua eksplisit ("kirim ke X: ...") -> semua sebelum ":" = target (APAPUN isinya,
       boleh multi-kata), semua sesudahnya = pesan VERBATIM. Ini paling pasti, jadi BYPASS guard
       pertanyaan (isi pesan boleh aja mengandung "?").
    2. Ada kata kunci "bilang"/"tentang"/"soal" -> teks sebelum keyword = target, sesudahnya = hint
       instruksi buat AI nyusun pesan.
    3. Gak ada keduanya -> cocokin PREFIX kata-kata ke customer_names beneran (lihat
       split_target_from_rest) biar nama multi-kata kayak "Kimfong Wijaya" kebaca utuh.
    """
    if not text:
        return None
    verb_match = SEND_VERB_PATTERN.search(text)
    if not verb_match:
        return None
    remainder = text[verb_match.end():].strip()
    if not remainder:
        # Verb sits at/near the END of the sentence — natural Indonesian "target ... VERB" word
        # order (e.g. "dia mau nego berapa coba tanyain" = "ask him/her how much they want to
        # negotiate"), which the VERB-then-target assumption above can't parse (there's nothing
        # left after the verb). Deliberately conservative: only recognize a PRONOUN
        # (dia/nya/itu/dst) sitting right at the START of the sentence as the target in this
        # reversed order — a full name/number in this position is rarer and riskier to guess
        # correctly, so this closes exactly the reported gap without overreaching. The whole
        # original sentence becomes the "rest"/instruction hint, since there's no separate
        # trailing instruction text to split off in this word order.
        before = text[:verb_match.start()].strip()
        before_words = before.split()
        if (before_words and before_words[0].lower() in PRONOUN_TARGETS
                and not looks_like_question_or_draft_request(text)):
            return {"target_raw": before_words[0], "separator": "", "rest": text}
        return None

    if ":" in remainder:
        target_part, _, rest_part = remainder.partition(":")
        target_raw = target_part.strip()
        if target_raw:
            return {"target_raw": target_raw, "separator": ":", "rest": rest_part.strip()}

    # Selain kasus titik dua eksplisit di atas, guard pertanyaan/minta-draft berlaku (isi pesannya
    # sendiri gak dijamin literal, jadi rawan ketuker sama pertanyaan/obrolan biasa).
    if looks_like_question_or_draft_request(text):
        return None

    kw_match = TARGET_SEPARATOR_KEYWORD_PATTERN.search(remainder)
    if kw_match:
        target_raw = remainder[:kw_match.start()].strip(" ,.:;")
        rest = remainder[kw_match.end():].strip()
        if target_raw:
            return {"target_raw": target_raw, "separator": kw_match.group(1).lower(), "rest": rest}

    target_raw, rest = split_target_from_rest(remainder)
    if not target_raw:
        return None
    return {"target_raw": target_raw, "separator": "", "rest": rest}


# ============================================================
# PERINTAH OWNER: KIRIM KATALOG PDF (opsional dibarengin pesan singkat "info jasa terbaru") ke
# customer tertentu atau ke owner sendiri. Dicek TERPISAH dari parse_owner_send_command di atas
# (bukan lewat AI generation) biar deterministik & gak pernah salah kirim/ngarang isi.
# ============================================================

CATALOG_ACTION_KEYWORD_PATTERN = re.compile(r'\bkatalog(?:nya)?\b', re.IGNORECASE)

# Kata kerja "kirim" yang dipakai buat DETEKSI ada-gaknya niat kirim katalog. Sengaja lebih longgar
# dari SEND_VERB_PATTERN (gak perlu langsung diikuti "ke") karena bentuknya macem-macem: "kirim
# katalog ke Wilson", "kirimin Wilson katalog kita", "kasih Wilson ... kirim katalog juga".
# "kasih tau"/"kasih liat" SENGAJA di-exclude (negative lookahead) karena itu idiom "kasih tau" =
# ngasih INFO/ngomong, bukan ngirim FILE — biar "kasih tau dong katalog kita ada apa aja" (pertanyaan)
# gak ketuker jadi perintah kirim.
CATALOG_SEND_VERB_PATTERN = re.compile(
    r'\b(kirim(?:in)?|kasih(?:in)?(?!\s+tau)|share(?:in)?|kasi(?:in)?(?!\s+tau))\b', re.IGNORECASE
)

# Frasa yang nunjukin ini PERTANYAAN soal isi katalog (baca doang), BUKAN perintah kirim — mis.
# "katalog kita isinya apa", "ada apa aja di katalog" — biar gak salah dieksekusi jadi kirim PDF.
CATALOG_QUERY_HINT_PATTERN = re.compile(
    r'\b(isinya\s+apa|isi\s+apa|ada\s+apa\s+aja|apa\s+aja\s+isi|apa\s+aja\s+sih|ada\s+apa\s+sih|'
    r'apa\s+aja\s+ya)\b',
    re.IGNORECASE,
)

# Frasa yang nunjukin owner JUGA mau bot kirim pesan singkat "info jasa terbaru" (bukan cuma PDF-nya
# doang) — dipakai buat perintah gabungan kayak "kasih Wilson info jasa terbaru kita terus kirim
# katalog juga" / "jelasin jasa terbaru ke Wilson terus kirim katalog".
CATALOG_SERVICES_INTRO_PATTERN = re.compile(
    r'\b(info\s+jasa|jasa\s+terbaru|layanan\s+terbaru|jasa\s+kita|layanan\s+kita|jasa\s+apa\s+aja|'
    r'jasa\s+yang\s+terbaru|layanan\s+yang\s+terbaru|jelasin\s+jasa|jelasin\s+layanan|'
    r'bisa\s+apa\s+aja)\b',
    re.IGNORECASE,
)

# "kirim katalog ke gw/saya/aku/gue/gua" -> target-nya OWNER SENDIRI, bukan customer.
CATALOG_SELF_TARGET_PATTERN = re.compile(r'\bke\s+(gw|gue|gua|aku|saya)\b', re.IGNORECASE)

# Gap-fix (owner natural commands): owner sering minta katalog buat DIRINYA SENDIRI TANPA kata kerja
# kirim eksplisit ("katalog dong", "minta katalog", "boleh minta katalog", "mau liat katalog") — ini
# BUKAN perintah kirim ke customer, ini owner mau lihat/pegang katalognya sendiri. Pattern ini
# sengaja TERPISAH dari CATALOG_SEND_VERB_PATTERN (yang khusus buat "kirim ke customer") supaya
# "katalog dong" tetap ke-eksekusi (kirim ke owner sendiri) walau gak ada kata kerja kirim/kasih.
CATALOG_REQUEST_HINT_PATTERN = re.compile(
    r'\b(minta|boleh\s+minta|mau\s+minta|liat\s+dong|lihat\s+dong|boleh\s+liat|boleh\s+lihat|'
    r'kirimin\s+dong|dong|mau\s+dong|ada\s+gak|ada\s+ga|ada\s+gk)\b',
    re.IGNORECASE,
)

# Ringkasan nama-nama kategori layanan (SAMA persis kategori resmi di PRICING_CONFIG) — dipakai di
# pesan intro singkat "info jasa terbaru" ke customer, BUKAN sumber harga (harga tetap dari PDF).
# Meta Ads sengaja TIDAK dimasukkan di ringkasan proaktif ini (status sekarang: sekunder/tidak
# dipromosikan aktif ke customer, lihat SOAL META ADS di RECOMMEND flow) — datanya tetap ada & tetap
# terjawab akurat kalau customer nanya langsung soal ads/iklan.
CATALOG_SERVICES_SUMMARY_TEXT = (
    "Content Creation, AI WhatsApp Admin 24/7, Website, sampai dokumentasi Event Photo & Video"
)


def build_customer_services_intro(display_first_name):
    """Pesan singkat & natural buat owner minta bot 'jelasin jasa terbaru' ke customer tertentu —
    FIXED template (bukan hasil AI generation) biar konsisten & gak pernah nyebut harga/klaim di
    luar kategori resmi. Harga tetap TIDAK disebut di sini — detail lengkap ada di katalog PDF yang
    dikirim bareng pesan ini."""
    name_part = f" Kak {display_first_name}" if display_first_name else " Kak"
    return (
        f"Halo{name_part}, sekarang kami bantu beberapa kebutuhan bisnis mulai dari "
        f"{CATALOG_SERVICES_SUMMARY_TEXT}. Aku kirim katalog lengkapnya juga ya Kak supaya lebih "
        f"gampang dilihat."
    )


def parse_owner_catalog_command(text):
    """Deteksi perintah owner buat KIRIM KATALOG PDF (dan opsional pesan 'info jasa terbaru') ke
    customer atau ke owner sendiri. Return dict {"self_target": bool, "send_services_intro": bool}
    kalau ini ACTION kirim, atau None kalau bukan.

    PENTING: kalau owner cuma NANYA isi katalog ("katalog kita isinya apa?", "ada paket apa aja di
    katalog") TANPA kata kerja kirim, fungsi ini balikin None — biar pertanyaan itu lewat ke
    call_claude_owner biasa (dijawab pakai knowledge, BUKAN dieksekusi kirim apa-apa)."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.endswith("?"):
        return None  # pertanyaan ("kirim katalog ke Wilson gimana ya?") -> bukan perintah eksekusi
    if not CATALOG_ACTION_KEYWORD_PATTERN.search(text):
        return None
    if CATALOG_QUERY_HINT_PATTERN.search(text):
        return None  # "katalog kita isinya apa" dll -> pertanyaan, bukan perintah kirim

    has_send_verb = bool(CATALOG_SEND_VERB_PATTERN.search(text))
    # Gap-fix: "katalog dong"/"minta katalog"/"boleh minta katalog" (BARE REQUEST, tanpa kata kerja
    # kirim eksplisit) dianggap owner minta katalog buat DIRINYA SENDIRI — tetap dieksekusi (bukan
    # cuma dijawab teks), TAPI cuma kalau gak ada nama/pronoun customer lain yang disebut (kalau ada,
    # itu tandanya owner emang maksud kirim ke customer itu, bukan minta sendiri).
    has_bare_request = bool(CATALOG_REQUEST_HINT_PATTERN.search(text))
    if not has_send_verb and not has_bare_request:
        return None  # ada kata "katalog" tapi gak ada kata kerja kirim/minta -> ini query, bukan action

    return {
        "self_target": bool(CATALOG_SELF_TARGET_PATTERN.search(text)),
        "send_services_intro": bool(CATALOG_SERVICES_INTRO_PATTERN.search(text)),
    }


def _coexistence_echo_visible_text(echo):
    """Convert one smb_message_echoes item into bounded text for Client Hub history.

    Echoes are messages a HUMAN sent from WhatsApp Business App / a supported linked device.  We
    never call AI on them; we only mirror what the customer actually saw and flip that customer to
    Human Takeover.  Rich media is represented honestly as a short placeholder + caption because
    the existing shared messages table is text-only.
    """
    if not isinstance(echo, dict):
        return "[Human mengirim pesan dari WhatsApp Business]"
    msg_type = (echo.get("type") or "").strip().lower()
    if msg_type == "text":
        return ((echo.get("text") or {}).get("body") or "").strip()[:4096] or "[Pesan teks dari WhatsApp Business]"
    if msg_type in ("image", "video", "document"):
        payload = echo.get(msg_type) or {}
        caption = (payload.get("caption") or "").strip()
        filename = (payload.get("filename") or "").strip()
        label = {"image": "gambar", "video": "video", "document": "dokumen"}[msg_type]
        detail = caption or filename
        return f"[Human mengirim {label} dari WhatsApp Business]" + (f" {detail[:3500]}" if detail else "")
    if msg_type == "audio":
        return "[Human mengirim voice note dari WhatsApp Business]"
    if msg_type == "sticker":
        return "[Human mengirim stiker dari WhatsApp Business]"
    if msg_type == "location":
        loc = echo.get("location") or {}
        name = (loc.get("name") or "").strip()
        address = (loc.get("address") or "").strip()
        detail = " — ".join(x for x in (name, address) if x)
        return "[Human mengirim lokasi dari WhatsApp Business]" + (f" {detail[:3500]}" if detail else "")
    if msg_type in ("edit", "revoke"):
        return f"[Pesan WhatsApp Business {msg_type}]"
    return f"[Human mengirim {msg_type or 'pesan'} dari WhatsApp Business]"


def _handle_smb_message_echoes(value, tenant_id, incoming_phone_number_id):
    """Mirror WhatsApp Business App human sends into history and automatically silence AI.

    Works for Kilas Works' own channel (tenant_id=None, phone_number_id must match the configured
    platform number) and for a positively-resolved client tenant. Unknown channels are never
    allowed to fall back into the platform inbox.
    """
    if tenant_id is None and WHATSAPP_PHONE_NUMBER_ID and incoming_phone_number_id != WHATSAPP_PHONE_NUMBER_ID:
        print("smb_message_echoes untuk channel non-platform diabaikan saat tenant tidak ter-resolve.")
        return 0
    echoes = value.get("message_echoes") or []
    handled = 0
    for echo in echoes:
        if not isinstance(echo, dict):
            continue
        message_id = echo.get("id")
        if is_duplicate_event(message_id):
            continue
        customer_phone = re.sub(r"\D", "", str(echo.get("to") or ""))
        if not customer_phone:
            continue
        visible_text = _coexistence_echo_visible_text(echo)
        scoped_number = _ck(tenant_id, customer_phone)
        try:
            if tenant_id is None:
                _platform_inbox.start_human_takeover(customer_phone, actor_user_id=None)
            else:
                _wa_takeover.start_human_takeover(tenant_id, customer_phone, actor_user_id=None)
        except Exception as e:
            # Fail safe: if we cannot persist takeover, DO NOT pretend the echo is safely handled.
            # The next customer inbound will hit _get_conversation_mode_safe(), which itself fails
            # safe to HUMAN_TAKEOVER on DB errors.
            print(f"Gagal set Human Takeover dari WhatsApp Business echo ({e}).")
            continue

        history = conversations.get(scoped_number)
        if history is None:
            history = load_recent_messages_from_db(scoped_number, "customer")
        history.append({"role": "assistant", "content": visible_text})
        conversations[scoped_number] = history[-20:]
        save_message_to_db(scoped_number, "customer", "assistant", visible_text)
        handled += 1
    return handled


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Meta bakal manggil ini pas kita setup webhook, buat verifikasi."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verifikasi gagal", 403


@app.route("/webhook", methods=["POST"])
def receive_webhook():
    """Nerima pesan masuk dari WhatsApp, balas pakai AI, dan proses tag internal (leads panas /
    katalog / tanya owner / konfirmasi bayar)."""
    data = request.get_json(silent=True) or {}
    # Privacy: never dump full WhatsApp payloads/chat contents into Render logs. Log only routing
    # metadata that is useful for operations; actual message text stays in the conversation DB.
    try:
        _change = ((data.get("entry") or [{}])[0].get("changes") or [{}])[0]
        _value = _change.get("value") or {}
        _meta = _value.get("metadata") or {}
        print(
            "Webhook masuk:",
            {
                "field": _change.get("field"),
                "phone_number_id": _meta.get("phone_number_id"),
                "has_messages": bool(_value.get("messages")),
                "has_message_echoes": bool(_value.get("message_echoes")),
            },
        )
    except Exception:
        print("Webhook masuk: payload metadata tidak terbaca")

    try:
        result = _webhook_body_impl(data)
        return result if result is not None else (jsonify({"status": "ok"}), 200)
    except Exception as e:
        print("Error processing webhook:", e)
        return jsonify({"status": "ok"}), 200
    finally:
        # Task 6 (multi-tenant runtime safety) — the thread-local active-WhatsApp-channel override
        # is set INSIDE _webhook_body_impl for a resolved client tenant's own channel, and worker
        # threads are reused across requests/routes. Without this unconditional `finally` clear, a
        # tenant channel picked here would stay "stuck" active on this thread — leaking into the
        # NEXT request handled by the same thread (another tenant's webhook, Kilas Works' own
        # webhook, the internal owner-notification endpoint, or a cron sweep) whether this request
        # succeeded OR raised. Cleared unconditionally, every single request, success or exception.
        _clear_active_whatsapp_channel()


def _webhook_body_impl(data):
    """The webhook's actual processing logic, split out so receive_webhook() can wrap it in a
    try/finally that ALWAYS clears the active-WhatsApp-channel thread-local (see Task 6 comment at
    the call site) regardless of whether this function returns normally or raises."""
    if True:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        # Business Hub V2 — Patch 1 (client-hub/BOT_INTEGRATION_GUIDE.md): resolve tenant_id ONLY
        # from the webhook's own `phone_number_id` (Meta's authoritative channel identifier), never
        # from message text or a business name. Purely additive — tenant_id is None for every
        # message on Kilas Works' own number today (that number isn't registered as a Client Hub
        # tenant), so nothing below that branches on tenant_id changes behavior for it.
        _incoming_phone_number_id = (value.get("metadata") or {}).get("phone_number_id")
        if ENABLE_MULTI_TENANT:
            # Task 7 — tri-state resolution: a real tenant, Kilas Works' own official number, or
            # genuinely UNKNOWN. An unknown phone_number_id (including a tenant-lookup DB failure)
            # must NEVER be silently treated as Kilas Works — stop here, log only, no reply sent.
            tenant_id, _tenant_resolution_unknown = _resolve_tenant_or_unknown(_incoming_phone_number_id)
            if _tenant_resolution_unknown:
                print(
                    f"WARNING: webhook phone_number_id={_incoming_phone_number_id!r} tidak dikenali "
                    "(bukan tenant terdaftar, bukan juga nomor resmi Kilas Works) — pesan diabaikan, "
                    "TIDAK diproses, TIDAK dibalas, TIDAK fallback ke identitas Kilas Works."
                )
                return jsonify({"status": "ok", "unknown_phone_number_id": True}), 200
        else:
            # Flag off = pure legacy single-tenant behavior, unchanged from before this cycle.
            tenant_id = None

        _webhook_field = changes.get("field")
        if _webhook_field == "smb_message_echoes":
            # WhatsApp Coexistence: a human sent this from WhatsApp Business App / linked device.
            # Mirror it into the same history and automatically take over that ONE conversation;
            # never call AI and never send a duplicate API reply.
            handled = _handle_smb_message_echoes(value, tenant_id, _incoming_phone_number_id)
            return jsonify({"status": "ok", "smb_message_echoes_handled": handled}), 200

        if _webhook_field in ("history", "smb_app_state_sync"):
            # Coexistence can emit one-time history/contact sync events. We deliberately don't
            # ingest them into live AI history yet; acknowledging them avoids retries while keeping
            # the realtime inbox source-of-truth limited to messages observed after connection.
            return jsonify({"status": "ok", "coexistence_sync_event": _webhook_field}), 200

        if "messages" not in value:
            # ini notifikasi status (delivered/read), bukan pesan baru -> abaikan
            return jsonify({"status": "ok"}), 200

        # Multi-tenant runtime safety cycle (Task 1/2) — activate the correct OUTGOING WhatsApp
        # channel for this one request BEFORE any send_whatsapp_message/send_reply_bubbles/
        # send_whatsapp_image/upload_media/download_whatsapp_media call happens anywhere below.
        # Reset unconditionally on EVERY request (a thread-local — worker threads are reused across
        # requests) so a channel picked for a PREVIOUS request/tenant can never leak into this one.
        # Gated on ENABLE_MULTI_TENANT (same convention as every other tenant-aware branch in this
        # file) so this is a total no-op — global Kilas Works channel, exactly as before this cycle
        # — whenever the flag is off, even if tenant_id happens to resolve to a real business.
        if ENABLE_MULTI_TENANT and not is_kilas_platform_tenant(tenant_id):
            _tenant_channel = _get_tenant_whatsapp_channel_safe(tenant_id)
            if _tenant_channel is None:
                # Task 2 — an incomplete/never-connected tenant channel must NEVER silently fall
                # back to sending as Kilas Works. Log internally and skip sending entirely; the
                # inbound message is still safely dropped (not retried forever) by returning 200.
                print(
                    f"Tenant {tenant_id} WhatsApp channel belum lengkap dikonfigurasi "
                    "(phone_number_id/access token) — skip kirim balasan, TIDAK fallback ke "
                    "identitas Kilas Works."
                )
                return jsonify({"status": "ok", "tenant_whatsapp_channel_not_configured": True}), 200
            _set_active_whatsapp_channel(_tenant_channel["phone_number_id"], _tenant_channel["access_token"])
        else:
            _clear_active_whatsapp_channel()

        message = value["messages"][0]
        from_number = message["from"]
        incoming_message_id = message.get("id")
        msg_type = message.get("type")

        # WAJIB paling awal: kalau wamid ini udah pernah kepegang sebelumnya (WhatsApp ngirim ulang
        # webhook yang sama), STOP DI SINI — jangan proses apa-apa lagi, jangan panggil AI, jangan
        # kirim pesan apapun. Satu event id = satu kali proses, biar gak ada pengiriman dobel ke
        # customer/owner gara-gara retry webhook.
        if is_duplicate_event(incoming_message_id):
            print(f"Duplicate webhook event (id={incoming_message_id}), di-skip biar gak dobel proses/kirim.")
            return jsonify({"status": "ok", "duplicate": True}), 200

        # ==== Ini pesan dari OWNER (nomor pribadi), bukan dari customer ====
        # Owner selalu direspon AI (mode "asisten pribadi"), bisa diskusi bebas dulu soal
        # pertanyaan customer yang pending. Baru kalau owner eksplisit nyuruh forward (AI kasih
        # tanda lewat FORWARD_MARKER di balasannya), jawaban final diterusin ke customer terkait.
        # Owner juga bisa kirim perintah langsung ("kirim ke..." atau "follow up...").
        # Task 10 (multi-tenant runtime safety) — a phone-number match against OWNER_WHATSAPP_NUMBER
        # is NOT enough on its own: it must also be true that THIS message arrived on Kilas Works'
        # own official channel (is_kilas_platform_tenant(tenant_id), i.e. tenant_id resolved to
        # None). Without this, a coincidental collision — some CLIENT tenant's own trusted_owner_phone
        # happening to equal Kilas Works' personal OWNER_WHATSAPP_NUMBER — would hijack that tenant's
        # conversation into Kilas Works' own rich owner-mode (wrong data, wrong system prompt,
        # wrong everything) purely because the SENDER's phone number matched, regardless of which
        # tenant's channel the message actually came in on. Owner identity is always decided by
        # (channel this message arrived on) + (phone number), never by phone number alone.
        if OWNER_WHATSAPP_NUMBER and from_number == OWNER_WHATSAPP_NUMBER and is_kilas_platform_tenant(tenant_id):
            owner_image_b64, owner_image_mime = None, None
            owner_msg_is_voice_note = False

            if msg_type == "image":
                owner_image_meta = message.get("image", {})
                owner_caption = (owner_image_meta.get("caption") or "").strip()
                owner_media_id = owner_image_meta.get("id")
                owner_image_b64, owner_image_mime = (
                    download_whatsapp_media(owner_media_id) if owner_media_id else (None, None)
                )
                if not owner_image_b64:
                    send_whatsapp_message(from_number, "Gagal kebuka gambarnya, coba kirim ulang ya.")
                    return jsonify({"status": "ok"}), 200

                # Upload ulang ke media library kita sendiri (biar media_id-nya bisa dipake kirim
                # ulang ke customer kapan aja, gak terikat sama media_id asli punya WA)
                own_media_id = upload_media_bytes(base64.b64decode(owner_image_b64), owner_image_mime)

                # Kalau caption-nya langsung nyuruh forward ("kirim ke 628xxx..."), ini gambar
                # kayak QR code custom dll yang mau diterusin APA ADANYA (sebagai gambar, bukan
                # dideskripsiin doang) ke customer tertentu — WAJIB konfirmasi dulu kayak perintah
                # teks biasa.
                img_fwd_target, img_fwd_caption = parse_target_number(owner_caption) if owner_caption else (None, None)
                if img_fwd_target and own_media_id:
                    target_customer_name = customer_names.get(img_fwd_target, f"wa.me/{img_fwd_target}")
                    payload_b64 = base64.b64encode(json.dumps({
                        "target": img_fwd_target,
                        "media_id": own_media_id,
                        "mime": owner_image_mime,
                        "caption": img_fwd_caption,
                    }).encode()).decode()
                    owner_conversations.setdefault(from_number, []).append({
                        "role": "system",
                        "content": f"[PENDING_IMAGE_COMMAND:{payload_b64}]",
                    })
                    confirm_text = f"Jadi aku kirim GAMBAR ini ke {target_customer_name}"
                    if img_fwd_caption:
                        confirm_text += f" (caption: \"{img_fwd_caption}\")"
                    confirm_text += ".\n\nOke? (bilang 'terusin' atau 'oke' buat konfirmasi)"
                    send_whatsapp_message(from_number, confirm_text)
                    return jsonify({"status": "ok"}), 200

                # Bukan perintah forward — simpen dulu (siapa tau abis ini owner nyusul bilang
                # "kirim ke 628xxx" doang tanpa re-attach gambarnya)
                if own_media_id:
                    last_owner_image[from_number] = {"media_id": own_media_id, "mime": owner_image_mime}

                owner_text = owner_caption or "(aku kirim gambar, tolong liat & tanggapin)"
            elif msg_type == "audio":
                # Voice note owner (additive) — transcript diperlakukan PERSIS kayak owner ngetik
                # command yang sama, lewat pipeline command owner yang SAMA (bukan engine kedua).
                # Identitas owner SUDAH ditentukan dari OWNER_WHATSAPP_NUMBER di baris paling atas
                # (nomor terverifikasi), BUKAN dari isi transcript — jadi transcript gak akan pernah
                # dipakai buat nentuin siapa yang ngirim, cuma isi command-nya doang.
                _voice_debug(
                    "webhook_received", message_id=incoming_message_id,
                    sender_role="OWNER", message_type=msg_type,
                )
                if not FEATURES.get("voice_note_owner", False):
                    send_whatsapp_message(from_number, "Saat ini admin cuma bisa baca pesan teks & gambar ya.")
                    return jsonify({"status": "ok"}), 200
                owner_audio_media_id = (message.get("audio") or {}).get("id")
                owner_transcript, owner_vn_err = (
                    transcribe_audio_whatsapp(owner_audio_media_id) if owner_audio_media_id else (None, "no_media_id")
                )
                if not owner_transcript:
                    print(f"Owner voice note gagal ditranskrip (media_id={owner_audio_media_id}): {owner_vn_err}")
                    # BUG FIX (final launch QA) — kalau penyebabnya BILLING_OR_QUOTA_ERROR (kredit OpenAI
                    # habis/auto-reload OFF, bukan audio yang gak jelas), owner butuh kalimat yang beda —
                    # "belum nangkep dengan jelas" salah kaprah dan bikin owner ngirim ulang audio yang
                    # sama berkali-kali padahal masalahnya bukan di audionya. Tetap SATU kalimat ramah,
                    # TIDAK PERNAH nyebut OpenAI/billing/API/HTTP status ke owner (itu cuma di log server).
                    owner_vn_fail_text = (
                        "Aku belum bisa proses voice note sekarang. Coba ketik perintahnya sebentar ya."
                        if owner_vn_err == VOICE_ERR_BILLING_OR_QUOTA else
                        "Aku belum nangkep voice note tadi dengan jelas. Coba kirim ulang atau ketik perintahnya ya."
                    )
                    send_whatsapp_message(from_number, owner_vn_fail_text)
                    return jsonify({"status": "ok"}), 200
                print(f"[VOICE] Owner VN transcript ({TRANSCRIPTION_PROVIDER}/{TRANSCRIPTION_MODEL}): {owner_transcript[:200]}")
                _voice_debug("route_after_transcript", target="owner", message_id=incoming_message_id)
                owner_msg_is_voice_note = True
                owner_text = normalize_owner_text_light(owner_transcript)
            elif msg_type != "text":
                return jsonify({"status": "ok"}), 200
            else:
                owner_text = normalize_owner_text_light(message["text"]["body"])

                # Owner cuma bilang "kirim ke 628xxx" doang (gak ada pesan lain) DAN ada gambar
                # yang baru aja dia kirim sebelumnya tanpa instruksi -> anggap ini nyuruh forward
                # gambar itu (jadi owner gak perlu re-attach gambarnya lagi).
                only_target, only_extra = parse_target_number(owner_text)
                if only_target and not only_extra and from_number in last_owner_image:
                    img = last_owner_image[from_number]
                    target_customer_name = customer_names.get(only_target, f"wa.me/{only_target}")
                    payload_b64 = base64.b64encode(json.dumps({
                        "target": only_target,
                        "media_id": img["media_id"],
                        "mime": img.get("mime"),
                        "caption": None,
                    }).encode()).decode()
                    owner_conversations.setdefault(from_number, []).append({
                        "role": "system",
                        "content": f"[PENDING_IMAGE_COMMAND:{payload_b64}]",
                    })
                    send_whatsapp_message(
                        from_number,
                        f"Jadi aku kirim GAMBAR yang tadi kamu kirim ke {target_customer_name}.\n\n"
                        f"Oke? (bilang 'terusin' atau 'oke' buat konfirmasi)",
                    )
                    return jsonify({"status": "ok"}), 200

            # CEK apakah ini balesan AVAILABILITY MEETING dari owner buat salah satu customer yang
            # lagi PENDING_OWNER_CONFIRMATION/SLOTS_OFFERED — BUG FIX: sebelumnya balesan generik
            # ("bisa"/"available"/"iya"/"oke", TANPA nyebut jam) diserahin ke AI, riskan ke-drift
            # tanggal/nanya ulang/nganggep "teruskan" cuma draft. Dicek DETERMINISTIK di sini, PALING
            # DULUAN sebelum command lain, SEBELUM manggil AI sama sekali — kalau owner nyebut ANGKA
            # JAM eksplisit, ini SENGAJA gak match & tetep lewat ke jalur AI [OWNER_MEETING_SLOTS]
            # existing (gak diubah) yang emang lebih jago extract jam dari bahasa bebas.
            avail_mention_status, avail_mention_number, _avail_mention_name = extract_mentioned_customer(owner_text)
            avail_target_number = None
            if avail_mention_status == "ok" and meeting_requests.get(avail_mention_number, {}).get("status") in (
                MEETING_STATE_PENDING_OWNER_CONFIRMATION, MEETING_STATE_SLOTS_OFFERED,
            ):
                avail_target_number = avail_mention_number
            elif avail_mention_status != "ambiguous":
                avail_candidates = [
                    n for n, r in meeting_requests.items()
                    if r.get("status") in (MEETING_STATE_PENDING_OWNER_CONFIRMATION, MEETING_STATE_SLOTS_OFFERED)
                ]
                if len(avail_candidates) == 1:
                    avail_target_number = avail_candidates[0]

            if avail_target_number:
                avail_req = meeting_requests[avail_target_number]
                avail_display_name = customer_names.get(avail_target_number, f"wa.me/{avail_target_number}")
                avail_short_name = short_display_name(avail_display_name)
                avail_day_label = avail_req.get("day_display") or avail_req.get("day_text") or "hari itu"
                has_digit = bool(re.search(r'\d', owner_text))

                if MEETING_UNAVAILABLE_KEYWORDS_PATTERN.search(owner_text) and not has_digit:
                    # Owner declare gak bisa/tutup TANPA nyebut jam sama sekali — sama persis
                    # perilakunya kayak jalur [OWNER_MEETING_UNAVAILABLE] existing, cuma dipicu
                    # deterministik. Tanggal TIDAK BERUBAH sampai customer/owner eksplisit kasih
                    # hari lain (date lock).
                    meeting_requests.pop(avail_target_number, None)
                    decline_text = (
                        f"Untuk {avail_day_label} kayaknya owner/tim lagi gak available Kak, boleh kasih "
                        f"hari lain yang nyaman?"
                    )
                    sent_ok, _err = send_reply_bubbles(avail_target_number, None, decline_text)
                    if sent_ok:
                        history = conversations.get(avail_target_number, [])
                        history.append({"role": "assistant", "content": decline_text})
                        conversations[avail_target_number] = history[-20:]
                        save_message_to_db(avail_target_number, "customer", "assistant", decline_text)
                        log_customer_message(avail_target_number, decline_text, sent_from="owner_meeting_unavailable")
                    send_whatsapp_message(from_number, f"Oke, aku minta {avail_short_name} kasih hari lain ya.")
                    return jsonify({"status": "ok"}), 200

                is_generic_confirm = bool(GENERIC_AVAILABILITY_CONFIRM_PATTERN.match(owner_text.strip()))
                is_resend_action = bool(MEETING_RESEND_ACTION_PATTERN.search(owner_text)) and not has_digit

                if avail_req.get("status") == MEETING_STATE_SLOTS_OFFERED and (is_generic_confirm or is_resend_action):
                    # Slot udah pernah ditawarin ke customer sebelumnya (offered_slots tersimpan) —
                    # owner cuma bilang "available"/"teruskan" lagi -> kirim ULANG pilihan yang SAMA
                    # persis dari state, JANGAN nanya ulang ke owner (RULE 4 & RULE 5).
                    offered = avail_req.get("offered_slots") or []
                    if offered:
                        times_label = ", ".join(t.replace(":", ".") for t in offered)
                        if len(offered) == 1:
                            offer_text = f"Untuk {avail_day_label} tersedia pukul {times_label} WIB, Kak. Apakah jam tersebut cocok?"
                        else:
                            offer_text = f"Untuk {avail_day_label} tersedia pukul {times_label} WIB, Kak. Yang paling nyaman yang mana?"
                        sent_ok, _err = send_reply_bubbles(avail_target_number, None, offer_text)
                        if sent_ok:
                            history = conversations.get(avail_target_number, [])
                            history.append({"role": "assistant", "content": offer_text})
                            conversations[avail_target_number] = history[-20:]
                            save_message_to_db(avail_target_number, "customer", "assistant", offer_text)
                            log_customer_message(avail_target_number, offer_text, sent_from="owner_meeting_slots_resend")
                        send_whatsapp_message(from_number, f"Terkirim ke {avail_short_name}.")
                        return jsonify({"status": "ok"}), 200

                if avail_req.get("status") == MEETING_STATE_PENDING_OWNER_CONFIRMATION and is_generic_confirm:
                    requested_time = avail_req.get("requested_time")
                    if requested_time:
                        # RULE 1: customer udah minta jam EXACT di awal, owner tinggal confirm generik
                        # -> LANGSUNG CONFIRMED, gak perlu muter nawarin balik/nunggu customer pilih lagi.
                        ok, confirm_text, owner_notify_text = try_confirm_meeting_direct(avail_target_number, requested_time)
                        if ok:
                            sent_ok, _err = send_reply_bubbles(avail_target_number, None, confirm_text)
                            if sent_ok:
                                history = conversations.get(avail_target_number, [])
                                history.append({"role": "assistant", "content": confirm_text})
                                conversations[avail_target_number] = history[-20:]
                                save_message_to_db(avail_target_number, "customer", "assistant", confirm_text)
                                log_customer_message(avail_target_number, confirm_text, sent_from="owner_meeting_confirmed_direct")
                                add_agreed_fact(avail_target_number, confirm_text)
                            send_whatsapp_message(from_number, owner_notify_text)
                        else:
                            # requested_time ternyata udah kepakai duluan (race condition) — JANGAN
                            # asal confirm/hallucinate hari lain, kasih tau owner jelas & minta jam lain.
                            send_whatsapp_message(
                                from_number,
                                f"Hmm, jam {requested_time.replace(':', '.')} buat {avail_day_label} ternyata "
                                f"udah kepakai kak. Ada jam lain yang available?",
                            )
                        return jsonify({"status": "ok"}), 200
                    else:
                        # RULE 4 (kasus terakhir): owner cuma bilang "bisa"/"available" TANPA pernah
                        # nyebut jam sama sekali, customer juga belum pernah minta jam spesifik -> gak
                        # ada satupun exact time buat dikonfirmasi. Tanya balik SEKALI — PYTHON yang
                        # generate (bukan AI) biar tanggal gak ke-drift/ganti hari sendiri.
                        send_whatsapp_message(
                            from_number,
                            f"Siap. Untuk {avail_day_label}, {avail_short_name} available jam berapa ya?",
                        )
                        return jsonify({"status": "ok"}), 200

            # CEK apakah ini perintah update STATUS MEETING customer tertentu (mis. "meeting Caca
            # selesai" / "meeting Kimfong gak jadi" / "meeting Andi no show"). Ini dicek DULUAN,
            # sebelum parse_owner_send_command, karena bukan perintah kirim pesan ke customer.
            meeting_status_cmd = parse_meeting_status_command(owner_text)
            if meeting_status_cmd:
                fallback_target = active_customer_context.get(from_number)
                ms_status, ms_resolved, ms_display_name = resolve_owner_target(
                    meeting_status_cmd["target_raw"], fallback_target
                )

                if ms_status == "ambiguous":
                    options = " atau ".join(f"{name} (...{num[-4:]})" for num, name in ms_resolved[:5])
                    send_whatsapp_message(
                        from_number,
                        f"Ada beberapa customer namanya mirip '{meeting_status_cmd['target_raw']}': {options}. Maksudnya yang mana?",
                    )
                    return jsonify({"status": "ok"}), 200

                if ms_status == "not_found":
                    send_whatsapp_message(
                        from_number,
                        f"Gak nemu customer bernama '{meeting_status_cmd['target_raw']}' di data.",
                    )
                    return jsonify({"status": "ok"}), 200

                ms_target_number = ms_resolved
                ms_appt = get_latest_scheduled_appointment_for(ms_target_number)
                if not ms_appt:
                    send_whatsapp_message(
                        from_number,
                        f"{short_display_name(ms_display_name)} belum ada jadwal meeting yang aktif nih.",
                    )
                    return jsonify({"status": "ok"}), 200

                update_appointment_status(ms_appt["id"], meeting_status_cmd["status"])
                status_label = {
                    "completed": "selesai",
                    "cancelled": "dibatalkan",
                    "no_show": "no-show (gak dateng)",
                }.get(meeting_status_cmd["status"], meeting_status_cmd["status"])
                send_whatsapp_message(
                    from_number,
                    f"Oke, status meeting {short_display_name(ms_display_name)} diupdate jadi {status_label}.",
                )
                return jsonify({"status": "ok"}), 200

            # CEK apakah ini perintah update STATUS PEMBAYARAN customer tertentu (mis. "pembayaran
            # Yutha udah masuk" / "DP Caca confirmed" / "Wilson udah lunas" / "transfer dia belum
            # masuk") — production hardening poin 13. Dicek DULUAN sebelum parse_owner_send_command,
            # DETERMINISTIK (bukan draft AI), biar status pembayaran gak pernah salah update customer.
            payment_status_cmd = parse_owner_payment_command(owner_text)
            if payment_status_cmd:
                fallback_target = active_customer_context.get(from_number)
                ps_status, ps_resolved, ps_display_name = resolve_owner_target(
                    payment_status_cmd["target_raw"], fallback_target
                )

                if ps_status == "ambiguous":
                    options = " atau ".join(f"{name} (...{num[-4:]})" for num, name in ps_resolved[:5])
                    send_whatsapp_message(
                        from_number,
                        f"Ada beberapa customer namanya mirip '{payment_status_cmd['target_raw']}': {options}. Maksudnya yang mana?",
                    )
                    return jsonify({"status": "ok"}), 200

                if ps_status == "not_found":
                    send_whatsapp_message(
                        from_number,
                        f"Gak nemu customer bernama '{payment_status_cmd['target_raw']}' di data.",
                    )
                    return jsonify({"status": "ok"}), 200

                ps_target_number = ps_resolved
                pay_state = get_or_create_payment_state(ps_target_number)
                pay_state["status"] = payment_status_cmd["status"]
                pay_state["updated_at"] = _utcnow()

                if payment_status_cmd["status"] in (PAYMENT_STATUS_PAID, PAYMENT_STATUS_PARTIALLY_PAID):
                    mark_customer_converted(ps_target_number)  # udah bayar (DP/lunas), stop follow-up generik

                status_label = {
                    PAYMENT_STATUS_PAID: "PAID (lunas)",
                    PAYMENT_STATUS_PARTIALLY_PAID: "PARTIALLY_PAID (DP masuk)",
                    PAYMENT_STATUS_NEEDS_RECHECK: "NEEDS_RECHECK (belum masuk)",
                }.get(payment_status_cmd["status"], payment_status_cmd["status"])
                send_whatsapp_message(
                    from_number,
                    f"Oke, status pembayaran {short_display_name(ps_display_name)} diupdate jadi {status_label}.",
                )
                return jsonify({"status": "ok"}), 200

            # CEK apakah ini perintah KIRIM KATALOG PDF (+ opsional pesan singkat "info jasa
            # terbaru") ke customer tertentu atau ke owner sendiri. Dicek DULUAN, SEBELUM
            # parse_owner_send_command, karena dieksekusi DETERMINISTIK (bukan draft AI) — biar
            # katalog gak pernah salah kirim/ngarang isi & konsisten sama satu sumber data.
            catalog_cmd = parse_owner_catalog_command(owner_text)
            if catalog_cmd:
                if catalog_cmd["self_target"]:
                    cat_target_number = OWNER_WHATSAPP_NUMBER
                    cat_short_name = "kamu"
                else:
                    cat_fallback_target = active_customer_context.get(from_number)
                    cat_mention_status, cat_mention_data, cat_mention_name = extract_mentioned_customer(owner_text)

                    if cat_mention_status == "ambiguous":
                        options = " atau ".join(f"{name} (...{num[-4:]})" for num, name in cat_mention_data[:5])
                        send_whatsapp_message(
                            from_number,
                            f"Ada beberapa customer namanya mirip: {options}. Katalog buat yang mana?",
                        )
                        return jsonify({"status": "ok"}), 200

                    if cat_mention_status == "ok":
                        cat_target_number = cat_mention_data
                        active_customer_context[from_number] = cat_mention_data
                        cat_short_name = short_display_name(cat_mention_name)
                    elif cat_fallback_target:
                        cat_target_number = cat_fallback_target
                        cat_short_name = short_display_name(
                            customer_names.get(cat_fallback_target, f"wa.me/{cat_fallback_target}")
                        )
                    else:
                        # Gap-fix (owner natural commands): kalau owner minta katalog TANPA nyebut
                        # customer sama sekali & gak ada active_customer_context, JANGAN nanya balik
                        # "buat siapa" — default-kan langsung ke OWNER SENDIRI (paling natural buat
                        # "katalog dong"/"minta katalog" polos), bukan diam nunggu klarifikasi.
                        cat_target_number = OWNER_WHATSAPP_NUMBER
                        cat_short_name = "kamu"
                        catalog_cmd["self_target"] = True

                # ACTION 1 (opsional): kirim pesan singkat "info jasa terbaru" DULU, cuma kalau
                # target-nya customer (gak masuk akal kirim "Halo Kak..." ke owner sendiri).
                if catalog_cmd["send_services_intro"] and not catalog_cmd["self_target"]:
                    intro_text = build_customer_services_intro(cat_short_name)
                    intro_sent_ok, intro_err = send_reply_bubbles(cat_target_number, None, intro_text)
                    if intro_sent_ok:
                        history = conversations.get(cat_target_number, [])
                        history.append({"role": "assistant", "content": intro_text})
                        conversations[cat_target_number] = history[-20:]
                        save_message_to_db(cat_target_number, "customer", "assistant", intro_text)
                        log_customer_message(cat_target_number, intro_text, sent_from="direct_command_catalog_intro")
                        add_agreed_fact(cat_target_number, intro_text)
                    else:
                        send_whatsapp_message(
                            from_number,
                            f"⚠️ GAGAL kirim pesan info jasa ke {cat_short_name} — belum kekirim, "
                            f"katalog PDF juga belum aku kirim.\nError: {intro_err}",
                        )
                        return jsonify({"status": "ok"}), 200

                # ACTION 2: kirim katalog PDF-nya (SATU KALI, dari repository — lihat send_catalog_pdf).
                cat_sent_ok, cat_err = send_catalog_pdf(cat_target_number)

                if not cat_sent_ok:
                    send_whatsapp_message(
                        from_number,
                        f"⚠️ GAGAL kirim katalog ke {cat_short_name} — belum kekirim ke customer sama sekali.\n"
                        f"Error: {cat_err}",
                    )
                    return jsonify({"status": "ok"}), 200

                if not catalog_cmd["self_target"]:
                    catalog_marker = "[ADMIN KIRIM KATALOG PDF]"
                    history = conversations.get(cat_target_number, [])
                    history.append({"role": "assistant", "content": catalog_marker})
                    conversations[cat_target_number] = history[-20:]
                    save_message_to_db(cat_target_number, "customer", "assistant", catalog_marker)
                    log_customer_message(cat_target_number, catalog_marker, sent_from="direct_command_catalog")

                if catalog_cmd["self_target"]:
                    send_whatsapp_message(from_number, "Katalog Kilas Works sudah aku kirim ke kamu.")
                elif catalog_cmd["send_services_intro"]:
                    send_whatsapp_message(from_number, f"Info layanan + katalog sudah terkirim ke {cat_short_name}.")
                else:
                    send_whatsapp_message(from_number, f"Katalog terkirim ke {cat_short_name}.")

                return jsonify({"status": "ok"}), 200

            # ORIGINAL_INTENT + TARGET_RESOLUTION + ACTION (production bug fix — see
            # pending_owner_clarification's module-level comment for the full rationale): if the
            # owner has an OPEN clarification pending from a PRIOR message (they were asked "yang
            # mana?" and this message might be their answer), try resolving THIS message against
            # it FIRST, before any of the normal send/mention parsing below gets a chance to
            # misinterpret a bare "yang 5699"/"k" selection as something else.
            _clar_key = _ck(tenant_id, from_number)
            _clar = pending_owner_clarification.get(_clar_key)
            _clar_resolved_number = None
            _clar_resolved_name = None
            _clar_intent = None
            _clar_action_hint = None

            if _clar:
                if _clar.get("candidates"):
                    _match = _resolve_clarification_reply(owner_text, _clar["candidates"])
                else:
                    # Open clarification (e.g. "dia mau nego... -> yang dia maksud siapa?", no
                    # candidate list yet) — try resolving the reply as a name/number directly.
                    _m_status, _m_data, _m_name = extract_mentioned_customer(owner_text)
                    if _m_status == "ok":
                        _match = (_m_data, _m_name)
                    elif _m_status == "ambiguous":
                        # Even on this FIRST-pass ambiguous discovery (extract_mentioned_customer
                        # does plain substring matching, so "si K" naturally matches multiple names
                        # like "kimfong"/"Kristov" that merely CONTAIN the letter k), try the
                        # smarter exact-match-priority resolver against these freshly-found
                        # candidates before re-asking — "si K" should resolve straight to the
                        # candidate literally named "k" in one round-trip, not need a third turn.
                        _refined = _resolve_clarification_reply(owner_text, _m_data)
                        if _refined and _refined != "ambiguous":
                            _match = _refined
                        else:
                            _match = "ambiguous"
                            _clar["candidates"] = _m_data
                    else:
                        _phone = normalize_phone_candidate(owner_text)
                        _match = (_phone, customer_names.get(_phone, f"wa.me/{_phone}")) if _phone else None

                if _match == "ambiguous":
                    pending_owner_clarification[_clar_key] = _clar
                    send_whatsapp_message(
                        from_number,
                        f"Ada beberapa customer namanya mirip: {_clarification_options_text(_clar['candidates'])}. "
                        f"Maksudnya yang mana?",
                    )
                    return jsonify({"status": "ok"}), 200
                elif _match:
                    _clar_resolved_number, _clar_resolved_name = _match
                    _clar_intent = _clar["intent"]
                    _clar_action_hint = _clar.get("action_hint")
                    pending_owner_clarification.pop(_clar_key, None)
                    active_customer_context[from_number] = _clar_resolved_number
                else:
                    # Doesn't look like a target-selection reply at all (owner changed topic) —
                    # abandon the pending clarification and process this message completely
                    # normally below (NEVER force-interpret an unrelated message as a selection).
                    pending_owner_clarification.pop(_clar_key, None)

            if _clar_resolved_number and _clar_intent == CLARIFICATION_INTENT_SEND_ACTION:
                # Resume the ORIGINAL send/ask instruction with the NOW-RESOLVED target — uses the
                # STORED original instruction text (action_hint), never the bare selection reply
                # ("yang 5699") itself, so the AI composes the message based on what the owner
                # actually originally asked for.
                pending_customer_number = _clar_resolved_number
                pending_question = None
                direct_send = True
                owner_text_for_ai = _clar_action_hint or owner_text
            elif _clar_resolved_number:
                # READ_HISTORY (or any other non-action intent) resumed — target is resolved, but
                # this is explicitly NOT a send: direct_send stays False, so build_owner_system_
                # prompt() never enters its "WAJIB proses format PESAN_UNTUK_CUSTOMER" branch for
                # this turn. The synthetic instruction text is unambiguous on its own (doesn't
                # depend on the model re-inferring the original intent from multi-turn history).
                pending_customer_number = _clar_resolved_number
                pending_question = pending_owner_questions.get(_ck(tenant_id, _clar_resolved_number))
                direct_send = False
                owner_text_for_ai = (
                    f"(lanjutan permintaan sebelumnya) Tampilkan riwayat/chat terakhir customer "
                    f"{_clar_resolved_name}."
                )
            else:
                owner_text_for_ai = None  # signal: fall through to normal parsing below

            # CEK apakah ini perintah EKSPLISIT buat kirim/balas/follow-up ke customer tertentu
            # (target boleh NAMA atau NOMOR). Beda dari dulu: kalau owner udah JELAS nyuruh kirim,
            # WAJIB LANGSUNG eksekusi kirim BENERAN saat itu juga — TIDAK ADA LAGI ronde "oke?/
            # terusin" kedua, kecuali target-nya ambigu (nama kembar) atau gak ketemu di data.
            #
            # Semua ini SKIP total kalau owner_text_for_ai udah ke-set di atas (artinya pesan ini
            # adalah balasan klarifikasi yang UDAH resolved & original intent-nya udah ditentuin) —
            # jangan sampai pesan yang sama diproses DUA KALI lewat dua jalur intent yang beda.
            if owner_text_for_ai is None:
                send_cmd = parse_owner_send_command(owner_text)
                direct_send = False

                if send_cmd:
                    fallback_target = active_customer_context.get(from_number)
                    status, resolved, display_name = resolve_owner_target(send_cmd["target_raw"], fallback_target)

                    if status == "ambiguous":
                        _store_pending_owner_clarification(
                            tenant_id, from_number, CLARIFICATION_INTENT_SEND_ACTION,
                            candidates=resolved, action_hint=owner_text,
                        )
                        send_whatsapp_message(
                            from_number,
                            f"Ada beberapa customer namanya mirip '{send_cmd['target_raw']}': "
                            f"{_clarification_options_text(resolved)}. Maksudnya yang mana?",
                        )
                        return jsonify({"status": "ok"}), 200

                    if status == "not_found":
                        # ACTION intent confirmed (send_cmd matched), target just not resolved yet
                        # (e.g. a pronoun with no active context, or a name typo) — store the
                        # ORIGINAL instruction as an OPEN clarification (no candidate list yet) so
                        # whatever the owner names next resumes THIS send, never gets treated as a
                        # brand new unrelated instruction.
                        _store_pending_owner_clarification(
                            tenant_id, from_number, CLARIFICATION_INTENT_SEND_ACTION,
                            candidates=None, action_hint=owner_text,
                        )
                        send_whatsapp_message(
                            from_number,
                            f"Gak nemu customer bernama '{send_cmd['target_raw']}' di data. "
                            f"Coba cek namanya lagi, atau kirim pakai nomor WA-nya ya.",
                        )
                        return jsonify({"status": "ok"}), 200

                    target_number = resolved

                    # Format "kirim ke X: <pesan persis>" (ada titik dua abis nama/nomor) = pesan
                    # VERBATIM yang mau di-relay APA ADANYA -> kirim LANGSUNG tanpa lewat AI sama
                    # sekali, paling cepat & paling PASTI kata-katanya gak berubah.
                    if send_cmd["separator"] == ":" and send_cmd["rest"]:
                        msg_to_send = send_cmd["rest"]
                        sent_ok, send_err = send_reply_bubbles(target_number, None, msg_to_send)

                        if sent_ok:
                            history = conversations.get(target_number, [])
                            history.append({"role": "assistant", "content": msg_to_send})
                            conversations[target_number] = history[-20:]
                            save_message_to_db(target_number, "customer", "assistant", msg_to_send)
                            log_customer_message(target_number, msg_to_send, sent_from="direct_command")
                            add_agreed_fact(target_number, msg_to_send)
                            send_whatsapp_message(from_number, f"Terkirim ke {short_display_name(display_name)}.")
                        else:
                            send_whatsapp_message(
                                from_number,
                                f"Gagal kirim ke {display_name} — belum kekirim ke customer sama sekali.\n"
                                f"Error: {send_err}",
                            )
                        return jsonify({"status": "ok"}), 200

                    # Selain itu (balas/follow up/tanyain/dll TANPA pesan verbatim persis) — target-nya
                    # udah KEPASTI dari sini (override fallback lama), biarin AI yang nyusun pesan
                    # natural sesuai konteks & instruksi owner, lalu forward LANGSUNG di respons yang
                    # sama (lihat direct_send=True di build_owner_system_prompt).
                    pending_customer_number = target_number
                    pending_question = None
                    direct_send = True
                else:
                    # Bukan perintah kirim eksplisit -> obrolan/pertanyaan/minta-saran biasa, ATAU
                    # pertanyaan HISTORY soal customer tertentu (mis. "itu jelajah visa chat apa aja").
                    # Coba dulu cari apakah owner EKSPLISIT nyebut nama customer di teks ini (bukan cuma
                    # pronoun) — kalau ketemu PERSIS 1, itu yang jadi konteks (override fallback lama)
                    # SEKALIGUS update active_customer_context biar pronoun ("dia"/"itu") abis ini nempel
                    # ke customer ini. Kalau nama-nya ambigu (2+ kandidat), TANYA balik, JANGAN nebak.
                    mention_status, mention_data, mention_name = extract_mentioned_customer(owner_text)

                    if mention_status == "ambiguous":
                        # NOT a send command (send_cmd was None) -> this is, by construction, a
                        # READ/general intent, never an action. Storing READ_HISTORY here is the
                        # safe default even if the owner's exact intent wasn't literally "show
                        # history" — direct_send stays False either way once resumed, so the worst
                        # case is a read-only answer, never an accidental send.
                        _store_pending_owner_clarification(
                            tenant_id, from_number, CLARIFICATION_INTENT_READ_HISTORY,
                            candidates=mention_data,
                        )
                        send_whatsapp_message(from_number, f"Ada beberapa customer namanya mirip: {_clarification_options_text(mention_data)}. Maksudnya yang mana?")
                        return jsonify({"status": "ok"}), 200

                    pending_customer_number, pending_question = (None, None)
                    if mention_status == "ok":
                        pending_customer_number = mention_data
                        active_customer_context[from_number] = mention_data
                        pending_question = pending_owner_questions.get(_ck(tenant_id, mention_data))
                    else:
                        # Task 5 — the FIFO "no name mentioned, just pick the oldest pending question"
                        # fallback must only ever consider THIS tenant's (here: Kilas Works' own, since
                        # this whole branch is gated to is_kilas_platform_tenant) own pending
                        # questions, never a client tenant's.
                        _own_pending = _pending_owner_questions_for_tenant(tenant_id)
                        if _own_pending:
                            pending_customer_number, pending_question = next(iter(_own_pending.items()))

                    # Kalau gak ada pertanyaan customer yang formal pending & gak ada nama eksplisit yang
                    # kesebut (misal owner nyeletuk doang pakai pronoun "dia"/"itu"), fallback ke customer
                    # TERAKHIR yang beneran chat sama bot.
                    if not pending_customer_number:
                        pending_customer_number = active_customer_context.get(from_number)

                owner_text_for_ai = owner_text

            ai_owner_reply = call_claude_owner(
                from_number, owner_text_for_ai, pending_question, pending_customer_number,
                image_b64=owner_image_b64, image_mime=owner_image_mime,
                direct_send=direct_send, is_voice_note=owner_msg_is_voice_note,
            )

            # CEK apakah owner AI baru aja ngasih tau AVAILABILITY MEETING (production hardening —
            # flow booking baru) buat salah satu customer yang lagi PENDING_OWNER_CONFIRMATION. Ini
            # dicek DULUAN sebelum FORWARD_MARKER biasa, karena bukan forward pesan bebas — SISTEM
            # yang generate kalimat resmi ke customer (bukan draft AI langsung), biar jam yang
            # ditawarin ke customer PERSIS sama yang Irvan sebut & udah divalidasi ulang.
            owner_meeting_slots_match = TAG_OWNER_MEETING_SLOTS_PATTERN.search(ai_owner_reply)
            owner_meeting_unavailable_match = TAG_OWNER_MEETING_UNAVAILABLE_PATTERN.search(ai_owner_reply)

            if owner_meeting_slots_match or owner_meeting_unavailable_match:
                if owner_meeting_slots_match:
                    mkv = parse_tag_kv(owner_meeting_slots_match.group(1))
                else:
                    mkv = parse_tag_kv(owner_meeting_unavailable_match.group(1))
                name_hint = mkv.get("customer", "")
                target_number = resolve_meeting_request_target(name_hint)

                owner_reply_clean = TAG_OWNER_MEETING_SLOTS_PATTERN.sub("", ai_owner_reply)
                owner_reply_clean = TAG_OWNER_MEETING_UNAVAILABLE_PATTERN.sub("", owner_reply_clean).strip()

                if not target_number:
                    send_reply_bubbles(
                        from_number, incoming_message_id,
                        owner_reply_clean or "Buat customer yang mana ya? Sebut namanya dong.",
                    )
                    return jsonify({"status": "ok"}), 200

                req = meeting_requests.get(target_number, {})
                display_name = customer_names.get(target_number, f"wa.me/{target_number}")
                day_label = req.get("day_display") or req.get("day_text") or "hari itu"

                if owner_meeting_unavailable_match:
                    meeting_requests.pop(target_number, None)
                    decline_text = (
                        f"Untuk {day_label} kayaknya owner/tim lagi gak available Kak, boleh kasih "
                        f"hari lain yang nyaman?"
                    )
                    sent_ok, _err = send_reply_bubbles(target_number, None, decline_text)
                    if sent_ok:
                        history = conversations.get(target_number, [])
                        history.append({"role": "assistant", "content": decline_text})
                        conversations[target_number] = history[-20:]
                        save_message_to_db(target_number, "customer", "assistant", decline_text)
                        log_customer_message(target_number, decline_text, sent_from="owner_meeting_unavailable")
                    send_reply_bubbles(
                        from_number, incoming_message_id,
                        owner_reply_clean or f"Oke, aku minta {short_display_name(display_name)} kasih hari lain ya.",
                    )
                    return jsonify({"status": "ok"}), 200

                # owner_meeting_slots_match: parse & validasi daftar jam yang dikasih owner.
                times_raw = mkv.get("times", "")
                raw_times = [t.strip() for t in times_raw.split(",") if t.strip()]
                valid_times = []
                for t in raw_times:
                    if re.match(r"^\d{1,2}:\d{2}$", t):
                        valid_times.append(t.zfill(5) if len(t) == 4 else t)

                if not valid_times:
                    send_reply_bubbles(
                        from_number, incoming_message_id,
                        "Format jamnya belum jelas nih, boleh sebut ulang jam berapa aja (format 24 jam)?",
                    )
                    return jsonify({"status": "ok"}), 200

                # RULE 1 (bug fix): kalau customer UDAH minta jam EXACT ini sendiri di awal
                # (req["requested_time"]) dan owner sekarang cuma nyebut SATU jam yang PERSIS SAMA,
                # itu artinya owner CONFIRM permintaan customer — langsung CONFIRMED, jangan nawarin
                # balik & nunggu customer pilih ulang jam yang udah dia minta sendiri.
                requested_time = req.get("requested_time")
                if len(valid_times) == 1 and requested_time and valid_times[0] == requested_time:
                    ok, confirm_text, owner_notify_text = try_confirm_meeting_direct(target_number, requested_time)
                    if ok:
                        sent_ok, _err = send_reply_bubbles(target_number, None, confirm_text)
                        if sent_ok:
                            history = conversations.get(target_number, [])
                            history.append({"role": "assistant", "content": confirm_text})
                            conversations[target_number] = history[-20:]
                            save_message_to_db(target_number, "customer", "assistant", confirm_text)
                            log_customer_message(target_number, confirm_text, sent_from="owner_meeting_confirmed_direct")
                            add_agreed_fact(target_number, confirm_text)
                        send_reply_bubbles(from_number, incoming_message_id, owner_reply_clean or owner_notify_text)
                        return jsonify({"status": "ok"}), 200

                times_label = ", ".join(t.replace(":", ".") for t in valid_times)
                if len(valid_times) == 1:
                    offer_text = f"Untuk {day_label} tersedia pukul {times_label} WIB, Kak. Apakah jam tersebut cocok?"
                else:
                    offer_text = f"Untuk {day_label} tersedia pukul {times_label} WIB, Kak. Yang paling nyaman yang mana?"

                req["status"] = MEETING_STATE_SLOTS_OFFERED
                req["offered_slots"] = valid_times
                meeting_requests[target_number] = req

                sent_ok, _err = send_reply_bubbles(target_number, None, offer_text)
                if sent_ok:
                    history = conversations.get(target_number, [])
                    history.append({"role": "assistant", "content": offer_text})
                    conversations[target_number] = history[-20:]
                    save_message_to_db(target_number, "customer", "assistant", offer_text)
                    log_customer_message(target_number, offer_text, sent_from="owner_meeting_slots_offer")

                send_reply_bubbles(
                    from_number, incoming_message_id,
                    owner_reply_clean or f"Oke, udah aku kasih tau pilihan jamnya ke {short_display_name(display_name)}.",
                )
                return jsonify({"status": "ok"}), 200

            # CEK apakah owner bilang "terusin" / "oke" setelah konfirmasi forward GAMBAR (image
            # forward masih pakai flow konfirmasi lama, sengaja gak diubah — beda topik dari revisi
            # perintah teks kirim/balas/follow-up di atas).
            is_approval = any(keyword in owner_text.lower() for keyword in ["terusin", "oke", "ok", "lanjut", "go", "kirim"])

            pending_image_cmd = None
            owner_hist = owner_conversations.get(from_number, [])
            for msg in reversed(owner_hist):
                content = msg.get("content", "") if msg.get("role") == "system" else ""
                if "[PENDING_IMAGE_COMMAND:" in content:
                    try:
                        payload_b64 = content.split("[PENDING_IMAGE_COMMAND:")[1].split("]")[0]
                        pending_image_cmd = json.loads(base64.b64decode(payload_b64).decode())
                    except Exception:
                        pass
                    break

            if pending_image_cmd and is_approval:
                # Owner confirm forward GAMBAR — sama prinsipnya kayak pending_cmd teks: kirim
                # dulu, cek sukses beneran, baru omong ke owner & update memory.
                target_customer = pending_image_cmd["target"]
                img_media_id = pending_image_cmd["media_id"]
                img_caption = pending_image_cmd.get("caption")

                sent_ok, send_err = send_whatsapp_image(target_customer, img_media_id, img_caption)

                if sent_ok:
                    memory_note = "[ADMIN KIRIM GAMBAR]" + (f" {img_caption}" if img_caption else "")
                    history = conversations.get(target_customer, [])
                    history.append({"role": "assistant", "content": memory_note})
                    conversations[target_customer] = history[-20:]
                    save_message_to_db(target_customer, "customer", "assistant", memory_note)
                    log_customer_message(target_customer, memory_note, sent_from="direct_command_image")

                    owner_conversations[from_number] = [m for m in owner_hist if "[PENDING_IMAGE_COMMAND:" not in m.get("content", "")]
                    confirm_name = customer_names.get(target_customer, f"wa.me/{target_customer}")
                    send_whatsapp_message(from_number, f"Gambar terkirim ke {short_display_name(confirm_name)}.")
                else:
                    send_whatsapp_message(
                        from_number,
                        f"⚠️ GAGAL kirim gambar ke wa.me/{target_customer} — belum kekirim ke customer sama sekali.\n"
                        f"Error: {send_err}\n\nCoba bilang 'terusin' lagi buat retry.",
                    )
                return jsonify({"status": "ok"}), 200

            if FORWARD_MARKER in ai_owner_reply and pending_customer_number:
                owner_facing, _, customer_facing = ai_owner_reply.partition(FORWARD_MARKER)
                owner_facing = owner_facing.strip() or "Oke siap, aku terusin ya!"
                customer_facing = customer_facing.strip()

                send_reply_bubbles(from_number, incoming_message_id, owner_facing)

                if customer_facing:
                    # KIRIM DULU ke customer, baru simpen ke memory & anggap pertanyaan ini selesai
                    # kalau BENERAN sukses kekirim. Kalau gagal, biarin pending_owner_questions-nya
                    # tetep ada (jangan didelete) & kasih tau owner jelas-jelas kalau gagal.
                    sent_ok, send_err = send_reply_bubbles(pending_customer_number, None, customer_facing)

                    if sent_ok:
                        history = conversations.get(pending_customer_number, [])
                        history.append({"role": "assistant", "content": customer_facing})
                        conversations[pending_customer_number] = history[-20:]
                        save_message_to_db(pending_customer_number, "customer", "assistant", customer_facing)
                        log_customer_message(pending_customer_number, customer_facing, sent_from="forward_from_owner")

                        # Catet ini sebagai FAKTA YANG UDAH FIX buat customer ini — biar bot gak
                        # PERNAH lagi bilang "belum dapet konfirmasi owner" untuk hal yang sebenernya
                        # udah beneran dijawab & dikirim ke customer ini.
                        fact_note = customer_facing
                        if pending_question:
                            fact_note = f"Soal '{pending_question}' — jawaban FINAL yang udah dikirim: {customer_facing}"
                        add_agreed_fact(pending_customer_number, fact_note)

                        # Konfirmasi singkat & PASTI ke owner — cuma muncul kalau BENERAN sukses.
                        confirm_name = customer_names.get(pending_customer_number, f"wa.me/{pending_customer_number}")
                        send_whatsapp_message(from_number, f"Terkirim ke {short_display_name(confirm_name)}.")
                    else:
                        send_whatsapp_message(
                            from_number,
                            f"⚠️ GAGAL forward ke wa.me/{pending_customer_number} — belum kekirim ke customer.\n"
                            f"Error: {send_err}\n\nCoba bilang 'terusin' lagi buat retry.",
                        )
                        return jsonify({"status": "ok"}), 200

                # .pop bukan del: pending_customer_number bisa jadi target hasil resolve nama/nomor
                # (direct_send) yang emang gak pernah masuk pending_owner_questions sama sekali.
                # Task 5 — pop lewat _ck(tenant_id, ...), key yang sama persis dipakai buat nulis.
                pending_owner_questions.pop(_ck(tenant_id, pending_customer_number), None)
                sisa = len(_pending_owner_questions_for_tenant(tenant_id))
                if sisa:
                    send_whatsapp_message(
                        OWNER_WHATSAPP_NUMBER,
                        f"Masih ada {sisa} pertanyaan lain yang nunggu jawaban kamu ya.",
                    )
            else:
                # belum ada instruksi forward -> ini masih obrolan/diskusi biasa sama owner
                send_reply_bubbles(from_number, incoming_message_id, ai_owner_reply)

            return jsonify({"status": "ok"}), 200

        # ==== Business Hub V2 — Patch 5, extended by Task 1/2 (multi-tenant runtime safety) ====
        # A message from a MULTI-TENANT CLIENT's own trusted owner, on THEIR OWN WhatsApp channel
        # (resolved via tenant_id above, never Kilas Works' own OWNER_WHATSAPP_NUMBER). Gated on
        # ENABLE_MULTI_TENANT + a resolved tenant_id, so this branch can never fire for Kilas Works'
        # own number (tenant_id is always None for it) and is a total no-op with the flag off.
        #
        # Task 2 — the owner phone is recognized REGARDLESS of package tier (Basic vs Pro): a
        # Basic tenant's owner must never be treated as a plain customer, but the rich Task-1
        # capability below is gated separately, behind that tenant's OWN owner_commands feature
        # (Pro-only per feature_flags.FEATURE_MATRIX). A recognized Basic owner gets a natural,
        # non-technical decline — never silently ignored, never the Pro experience, never wording
        # like "feature flag false".
        _tenant_owner_phone = _get_trusted_owner_phone_safe(tenant_id) if ENABLE_MULTI_TENANT and tenant_id is not None else None
        if _tenant_owner_phone and from_number == _tenant_owner_phone:
            _tenant_owner_commands_ok = _get_tenant_features_safe(tenant_id).get("owner_commands", False)
            if not _tenant_owner_commands_ok:
                # Bug fix (deepening cycle) — a Basic tenant owner must get the SAME natural,
                # non-technical decline for EVERY message type (text, image, voice note), not just
                # text. Previously an image/audio message from a Basic tenant's owner was silently
                # dropped with no reply at all, while a text message got the proper decline.
                if msg_type in ("text", "image", "audio"):
                    send_whatsapp_message(
                        from_number,
                        "Fitur asisten owner lewat chat ini baru tersedia di paket AI Admin Pro ya Kak — "
                        "silakan hubungi tim Kilas Works kalau mau upgrade.",
                    )
                return jsonify({"status": "ok"}), 200

            # Deepening cycle (Task 1 voice-note parity / Task 3 image parity) — a Pro tenant's own
            # owner now gets the SAME category of media understanding Kilas Works' own owner
            # already gets via call_claude_owner()/transcribe_audio_whatsapp() above, reusing the
            # exact same transcription pipeline and vision-capable model, just scoped to THIS
            # tenant (call_tenant_owner_ai, tenant_owner_conversations) — never Kilas Works' own
            # owner_conversations, and never another tenant's. Each of voice_note/image_understanding
            # is checked independently against THIS tenant's own feature flags (not just
            # owner_commands) — the same flags/gate already used for a CUSTOMER's voice note/image
            # on this tenant (see below), so a tenant plan can never grant the owner a capability
            # its customers don't also have per FEATURE_MATRIX.
            owner_image_b64, owner_image_mime = None, None
            owner_msg_is_voice_note = False

            if msg_type == "image":
                _tenant_owner_image_ok = _get_tenant_features_safe(tenant_id).get("image_understanding", False)
                if not _tenant_owner_image_ok:
                    send_whatsapp_message(from_number, "Untuk saat ini aku bisa bantu lewat chat teks ya, Kak.")
                    return jsonify({"status": "ok"}), 200
                owner_image_meta = message.get("image", {})
                owner_caption = (owner_image_meta.get("caption") or "").strip()
                owner_media_id = owner_image_meta.get("id")
                owner_image_b64, owner_image_mime = (
                    download_whatsapp_media(owner_media_id) if owner_media_id else (None, None)
                )
                if not owner_image_b64:
                    send_whatsapp_message(from_number, "Gagal kebuka gambarnya, coba kirim ulang ya.")
                    return jsonify({"status": "ok"}), 200
                owner_text = owner_caption or "(aku kirim gambar, tolong liat & tanggapin)"
            elif msg_type == "audio":
                if not FEATURES.get("voice_note_owner", False):
                    send_whatsapp_message(from_number, "Saat ini aku cuma bisa baca pesan teks & gambar ya.")
                    return jsonify({"status": "ok"}), 200
                _tenant_owner_voice_ok = _get_tenant_features_safe(tenant_id).get("voice_note", False)
                if not _tenant_owner_voice_ok:
                    send_whatsapp_message(from_number, "Untuk saat ini aku bisa bantu lewat chat teks ya, Kak.")
                    return jsonify({"status": "ok"}), 200
                owner_audio_media_id = (message.get("audio") or {}).get("id")
                owner_transcript, owner_vn_err = (
                    transcribe_audio_whatsapp(owner_audio_media_id) if owner_audio_media_id else (None, "no_media_id")
                )
                if not owner_transcript:
                    print(f"Tenant owner voice note gagal ditranskrip (tenant_id={tenant_id}, media_id={owner_audio_media_id}): {owner_vn_err}")
                    owner_vn_fail_text = (
                        "Aku belum bisa proses voice note sekarang. Coba ketik perintahnya sebentar ya."
                        if owner_vn_err == VOICE_ERR_BILLING_OR_QUOTA else
                        "Aku belum nangkep voice note tadi dengan jelas. Coba kirim ulang atau ketik perintahnya ya."
                    )
                    send_whatsapp_message(from_number, owner_vn_fail_text)
                    return jsonify({"status": "ok"}), 200
                owner_msg_is_voice_note = True
                owner_text = normalize_owner_text_light(owner_transcript)
            elif msg_type != "text":
                return jsonify({"status": "ok"}), 200
            else:
                owner_text = message["text"]["body"]

            # Tenant-persistence cycle (Task 1/2) — natural-language RECORD COMMANDS ("Confirm
            # booking Budi.", "Tolak yang jam 4, bilang penuh.", "Confirm pembayaran Budi.", "Tolak
            # pembayaran Budi, nominalnya kurang.") are checked BEFORE classify_owner_message()'s
            # generic QUERY/ACTION/INTERNAL_NOTE split — these must actually mutate a PERSISTED
            # appointment/payment-review row (see appointments_repo.py/payment_reviews_repo.py),
            # never just be relayed as a customer message or answered conversationally.
            _record_command = _wa_bridge.classify_owner_record_command(owner_text)
            if _record_command in ("CONFIRM_APPOINTMENT", "REJECT_APPOINTMENT"):
                _open_appts = _tenant_appt_list_safe(tenant_id, statuses=_appt_repo.OPEN_STATUSES)
                _matched_appt, _ambiguous_appts = _wa_bridge.resolve_appointment_target(_open_appts, owner_text)
                if _ambiguous_appts:
                    _options = " atau ".join(
                        f"{a.get('customer_name') or 'Customer'} (...{a['customer_phone'][-4:]})"
                        for a in _ambiguous_appts[:5]
                    )
                    send_whatsapp_message(from_number, f"Booking yang mana ya — {_options}?")
                elif not _matched_appt:
                    send_whatsapp_message(from_number, "Belum nemu booking yang dimaksud nih Kak, coba sebutin nama customernya ya.")
                else:
                    _reason = _wa_bridge.extract_owner_command_reason(owner_text)
                    _cust_display = _matched_appt.get("customer_name") or "Customer"
                    if _record_command == "CONFIRM_APPOINTMENT":
                        _tenant_appt_update_status_safe(_matched_appt["id"], "CONFIRMED", notes=_reason)
                        send_whatsapp_message(from_number, f"Oke, booking {_cust_display} aku confirm ya.")
                        send_whatsapp_message(
                            _matched_appt["customer_phone"],
                            f"Halo {_cust_display}, booking kamu ({_matched_appt.get('request_text') or '-'}) sudah dikonfirmasi ya. Sampai jumpa!",
                        )
                    else:
                        _tenant_appt_update_status_safe(_matched_appt["id"], "CANCELLED", notes=_reason)
                        send_whatsapp_message(from_number, f"Oke, booking {_cust_display} aku tolak ya.")
                        _decline_text = f"Maaf {_cust_display}, booking kamu belum bisa diproses"
                        _decline_text += f" ({_reason})." if _reason else "."
                        send_whatsapp_message(_matched_appt["customer_phone"], _decline_text)
                return jsonify({"status": "ok"}), 200

            if _record_command in ("CONFIRM_PAYMENT", "REJECT_PAYMENT"):
                _pending_reviews = _tenant_payment_review_list_pending_safe(tenant_id)
                _matched_review, _ambiguous_reviews = _wa_bridge.resolve_payment_review_target(_pending_reviews, owner_text)
                if _ambiguous_reviews:
                    _options = " atau ".join(
                        f"{r.get('customer_name') or 'Customer'} (...{r['customer_phone'][-4:]})"
                        for r in _ambiguous_reviews[:5]
                    )
                    send_whatsapp_message(from_number, f"Pembayaran yang mana ya — {_options}?")
                elif not _matched_review:
                    send_whatsapp_message(from_number, "Belum nemu bukti pembayaran yang dimaksud nih Kak, coba sebutin nama customernya ya.")
                else:
                    _reason = _wa_bridge.extract_owner_command_reason(owner_text)
                    _cust_display = _matched_review.get("customer_name") or "Customer"
                    _new_status = "CONFIRMED" if _record_command == "CONFIRM_PAYMENT" else "REJECTED"
                    _tenant_payment_review_update_status_safe(
                        _matched_review["id"], _new_status, owner_note=_reason, verified_by=_tenant_owner_phone,
                    )
                    _write_tenant_audit_safe(
                        tenant_id,
                        f"TENANT_PAYMENT_{_new_status}",
                        f"review_id={_matched_review['id']} customer={_matched_review['customer_phone']} "
                        f"by owner {_tenant_owner_phone}" + (f" note={_reason}" if _reason else ""),
                    )
                    if _new_status == "CONFIRMED":
                        send_whatsapp_message(from_number, f"Oke, pembayaran {_cust_display} aku confirm ya.")
                        send_whatsapp_message(
                            _matched_review["customer_phone"],
                            f"Halo {_cust_display}, pembayaran kamu sudah kami konfirmasi ya. Terima kasih!",
                        )
                    else:
                        send_whatsapp_message(from_number, f"Oke, pembayaran {_cust_display} aku tolak ya.")
                        _decline_text = f"Halo {_cust_display}, mohon dicek ulang bukti transfernya ya"
                        _decline_text += f" ({_reason})." if _reason else "."
                        send_whatsapp_message(_matched_review["customer_phone"], _decline_text)
                return jsonify({"status": "ok"}), 200

            kind = _wa_bridge.classify_owner_message(owner_text)
            _tenant_biz_config = _tcs.get_tenant_config(tenant_id) or {}
            _tenant_biz_name = _tenant_biz_config.get("business_name") or "bisnis kamu"

            if kind == "OWNER_ACTION":
                # Try a structured price offer first (existing, narrower bridge behavior); fall
                # back to a plain relay of whatever the owner said, to the resolved target customer
                # — covers instructions like "bales si Budi bilang stoknya ada" that aren't a price.
                target_customer, remainder, ambiguous_matches = _resolve_tenant_owner_relay_target(
                    tenant_id, _tenant_owner_phone, owner_text
                )
                if ambiguous_matches:
                    # Task 4 — 2+ genuinely different known customers are both plausibly meant
                    # ("yang kemarin" matching more than one recent conversation, or two different
                    # names both mentioned) — ASK, never guess which one.
                    options = " atau ".join(f"{name} (...{phone[-4:]})" for phone, name in ambiguous_matches[:5])
                    send_whatsapp_message(from_number, f"Maksudnya yang mana ya — {options}?")
                    return jsonify({"status": "ok"}), 200
                offers, notes = _wa_bridge.parse_owner_offers(owner_text)
                customer_message = _wa_bridge.build_customer_facing_offer_message(offers, notes)
                if not customer_message:
                    # No parsable price offer — treat the (post-target) remainder as a direct
                    # instruction for what to relay, stripped of the send-verb itself.
                    relay_text = remainder
                    for verb in _wa_bridge._SEND_ACTION_VERBS:
                        relay_text = re.sub(rf"\b{re.escape(verb)}\b", "", relay_text, flags=re.IGNORECASE)
                    customer_message = relay_text.strip(" ,.:;-") or None
                if not target_customer:
                    send_whatsapp_message(
                        from_number,
                        "Belum ada customer yang lagi dibahas — tunggu customer chat dulu atau sebutin "
                        "namanya/nomornya ya.",
                    )
                elif not customer_message:
                    send_whatsapp_message(
                        from_number,
                        "Aku belum nangkep pesan yang mau disampaikan — coba sebutin lagi ya.",
                    )
                else:
                    scoped_target = _ck(tenant_id, target_customer)
                    ok, _err = send_whatsapp_message(target_customer, customer_message)
                    if ok:
                        history = conversations.get(scoped_target, [])
                        history.append({"role": "assistant", "content": customer_message})
                        conversations[scoped_target] = history[-20:]
                        save_message_to_db(scoped_target, "customer", "assistant", customer_message)
                        add_agreed_fact(scoped_target, customer_message)
                        send_whatsapp_message(from_number, f"Oke, sudah aku sampaikan ke wa.me/{target_customer}.")
                    else:
                        send_whatsapp_message(from_number, f"Gagal kirim ke wa.me/{target_customer}, coba lagi ya.")
            elif kind in ("OWNER_QUERY", "OWNER_INTERNAL_NOTE"):
                # Both get a REAL AI reply — a query is answered from this tenant's own scoped
                # data, and an internal note/thinking-out-loud still gets a natural acknowledgement
                # (never silently swallowed, per Task 1's explicit requirement).
                reply_text = call_tenant_owner_ai(
                    tenant_id, _tenant_owner_phone, owner_text, _tenant_biz_name,
                    image_b64=owner_image_b64, image_mime=owner_image_mime,
                    is_voice_note=owner_msg_is_voice_note,
                )
                send_whatsapp_message(from_number, reply_text)
            return jsonify({"status": "ok"}), 200

        # Business Hub V2 — Patch 4 (client-hub/BOT_INTEGRATION_GUIDE.md): kalau tenant ini (hasil
        # resolve dari phone_number_id di atas) sedang di-human-takeover untuk nomor customer ini,
        # AI TIDAK PERNAH balas apapun — diam total, supaya tidak tabrakan dengan pesan yang lagi
        # diketik manusia secara manual. tenant_id selalu None untuk nomor WhatsApp Kilas Works
        # sendiri, jadi baris ini tidak pernah aktif untuk traffic produksi saat ini.
        if _get_conversation_mode_safe(tenant_id, from_number) == "HUMAN_TAKEOVER":
            print(f"Human takeover aktif (tenant_id={tenant_id}, customer={from_number}) — AI diam, tidak membalas.")
            return jsonify({"status": "ok", "human_takeover": True}), 200

        image_b64, image_mime = None, None
        user_msg_is_voice_note = False

        if msg_type == "image":
            # Bug fix (Task 5) — image_understanding (vision) is a Pro-only feature in
            # FEATURE_MATRIX but was never actually checked here for a resolved client tenant; a
            # Basic tenant's customer image would silently go straight to Claude vision anyway.
            # Same AND-with-the-global-flag pattern as the voice_note gate right below.
            _tenant_image_ok = True
            if ENABLE_MULTI_TENANT and tenant_id is not None:
                _tenant_image_ok = _get_tenant_features_safe(tenant_id).get("image_understanding", False)
            if not _tenant_image_ok:
                send_typing_indicator(incoming_message_id)
                time.sleep(1.2)
                send_whatsapp_message(from_number, "Untuk saat ini aku bisa bantu lewat chat teks ya, Kak.")
                return jsonify({"status": "ok"}), 200

            # Customer kirim gambar (paling sering: bukti transfer). Download & convert ke base64
            # biar bisa "dilihat" langsung sama Claude (vision) — bukan cuma ditebak dari caption.
            image_meta = message.get("image", {})
            caption = (image_meta.get("caption") or "").strip()
            media_id = image_meta.get("id")
            image_b64, image_mime = download_whatsapp_media(media_id) if media_id else (None, None)

            if not image_b64:
                send_typing_indicator(incoming_message_id)
                time.sleep(1.2)
                send_whatsapp_message(from_number, "Gambarnya gagal kebuka nih kak, coba kirim ulang ya.")
                return jsonify({"status": "ok"}), 200

            user_text = caption or "(customer kirim gambar tanpa keterangan — cek isinya)"
        elif msg_type == "audio":
            # Voice note customer (additive) — transcript diproses lewat PIPELINE TEKS CUSTOMER
            # YANG SAMA (user_text) di bawah, BUKAN engine AI kedua khusus audio. Kalau gagal
            # ditranskrip, kasih tau jujur (gak pernah hallucinate isi transcript) dan minta
            # kirim ulang/ketik — sesuai bahasa yang lagi dipakai customer kalau sudah diketahui.
            _voice_debug(
                "webhook_received", message_id=incoming_message_id,
                sender_role="CUSTOMER", message_type=msg_type,
            )
            # Patch 3 (Business Hub V2): untuk tenant client yang ke-resolve (bukan Kilas Works
            # sendiri), fitur voice note JUGA harus di-enable di tenant_features paket mereka —
            # AND, bukan OR, dengan flag global FEATURES di atas. Kalau tenant_id None (Kilas Works
            # sendiri, atau flag mati), perilaku identik dengan sebelum patch ini ada.
            _tenant_voice_ok = True
            if ENABLE_MULTI_TENANT and tenant_id is not None:
                _tenant_voice_ok = _get_tenant_features_safe(tenant_id).get("voice_note", False)
            if not FEATURES.get("voice_note_customer", False) or not _tenant_voice_ok:
                send_typing_indicator(incoming_message_id)
                time.sleep(1.5)
                send_whatsapp_message(from_number, "Saat ini admin cuma bisa baca pesan teks & gambar ya kak.")
                return jsonify({"status": "ok"}), 200
            audio_media_id = (message.get("audio") or {}).get("id")
            transcript, vn_err = (
                transcribe_audio_whatsapp(audio_media_id) if audio_media_id else (None, "no_media_id")
            )
            if not transcript:
                print(f"Customer voice note gagal ditranskrip (media_id={audio_media_id}): {vn_err}")
                send_typing_indicator(incoming_message_id)
                time.sleep(1.2)
                # Task 9 bug fix — must read via the SAME tenant-scoped key customer_language is
                # written with (_ck(tenant_id, from_number)), never the bare phone number, or a
                # tenant customer's fallback-message language could silently borrow Kilas Works'
                # own (or another tenant's) stored preference for that same raw phone number.
                lang = customer_language.get(_ck(tenant_id, from_number))
                # BUG FIX (final launch QA) — BILLING_OR_QUOTA_ERROR (kredit transkripsi OpenAI habis,
                # auto-reload OFF) BUKAN "audio kurang jelas" — kalau dikasih pesan yang sama, customer
                # bakal ngirim ulang voice note yang sama berkali-kali sia-sia. Tetap satu kalimat ramah,
                # TIDAK PERNAH nyebut OpenAI/billing/API/HTTP status ke customer (cuma di log server).
                if vn_err == VOICE_ERR_BILLING_OR_QUOTA:
                    vn_fail_text = (
                        "Sorry, I can't process voice notes right now. Could you type the message instead?"
                        if lang == LANGUAGE_EN else
                        "Maaf Kak, voice note-nya belum bisa diproses saat ini. Boleh ketik pesannya sebentar?"
                    )
                else:
                    vn_fail_text = (
                        "Sorry, I couldn't read the voice note clearly. Could you resend it or type the message?"
                        if lang == LANGUAGE_EN else
                        "Maaf Kak, voice note-nya belum kebaca dengan jelas. Boleh kirim ulang atau ketik pesannya sebentar?"
                    )
                send_whatsapp_message(from_number, vn_fail_text)
                return jsonify({"status": "ok"}), 200
            print(f"[VOICE] Customer VN transcript ({TRANSCRIPTION_PROVIDER}/{TRANSCRIPTION_MODEL}) from {from_number}: {transcript[:200]}")
            _voice_debug("route_after_transcript", target="customer", message_id=incoming_message_id)
            user_msg_is_voice_note = True
            user_text = transcript
        elif msg_type != "text":
            send_typing_indicator(incoming_message_id)
            time.sleep(1.5)
            send_whatsapp_message(from_number, "Saat ini admin cuma bisa baca pesan teks & gambar ya kak.")
            return jsonify({"status": "ok"}), 200
        else:
            user_text = message["text"]["body"]

        # Multi-tenant runtime safety cycle (Task 3) — EVERY per-customer memory/state dict below
        # (conversations/customer_names/customer_language, via _ck) is keyed by tenant+phone, NOT
        # by the bare phone number, because the SAME phone number can legitimately message two
        # different client tenants (or a tenant AND Kilas Works itself) and those must be
        # completely separate conversations. tenant_id=None (Kilas Works' own number) maps to the
        # bare phone number unchanged — see _ck's docstring — so none of this changes behavior for
        # Kilas Works' own production traffic today.
        is_kilas_tenant = is_kilas_platform_tenant(tenant_id)
        scoped_from = _ck(tenant_id, from_number)

        # Cek dulu apakah ini customer BARU (belum pernah chat sama sekali sebelumnya) SEBELUM
        # pesan ini diproses & disimpen — dipakai buat notifikasi "customer baru chat" ke owner,
        # yang cuma dikirim SEKALI per customer (bukan tiap pesan, biar gak spam ke WA owner).
        existing_history = conversations.get(scoped_from)
        if existing_history is None:
            existing_history = load_recent_messages_from_db(scoped_from, "customer")
        is_new_customer = not existing_history

        # Kalau kita belum tau nama customer ini, coba ambil dari profil WhatsApp-nya dulu (kalau
        # dia emang punya nama di profil WA) — biar AI gak perlu nanya-nanya lagi kalau namanya
        # udah kebaca otomatis dari sini.
        if scoped_from not in customer_names:
            try:
                wa_profile_name = value.get("contacts", [{}])[0].get("profile", {}).get("name")
            except Exception:
                wa_profile_name = None
            if wa_profile_name:
                customer_names[scoped_from] = wa_profile_name
                save_customer_name_to_db(scoped_from, wa_profile_name)

        # Update konteks "customer terakhir yang chat" — dipakai fallback kalau owner bilang "terusin"
        # tanpa ada pertanyaan formal pending (lihat active_customer_context). Bug fix: HARUS cuma
        # diupdate buat Kilas Works' OWN conversations — sebelumnya baris ini jalan buat SEMUA
        # customer termasuk customer tenant client, jadi kalau tenant client chat duluan, target
        # "terusin" default punya Kilas Works' owner sendiri bisa KEBALIK ke customer bisnis lain.
        if OWNER_WHATSAPP_NUMBER and is_kilas_tenant:
            active_customer_context[OWNER_WHATSAPP_NUMBER] = from_number
        # Patch 5 — sama polanya, tapi discope per tenant client (kalau ada) supaya
        # _tenant_active_customer_context tidak pernah campur dengan Kilas Works sendiri di atas.
        if ENABLE_MULTI_TENANT and tenant_id is not None:
            _tenant_owner_for_context = _get_trusted_owner_phone_safe(tenant_id)
            if _tenant_owner_for_context:
                _tenant_active_customer_context[(tenant_id, _tenant_owner_for_context)] = from_number
        # Bug fix (Task 3/6) — the automatic follow-up/lead-scoring "sales engine" below
        # (followup_state/lead_stage) is a Kilas-Works-own prospecting tool: its background cron
        # job sends nudges via the GLOBAL Kilas Works WhatsApp channel and was never built
        # tenant-aware. Enrolling a client tenant's own customer into it would eventually send that
        # customer a Kilas Works sales nudge FROM Kilas Works' own number — a clear identity leak.
        # Known limitation of this cycle (minimal-scope fix): client tenant customers are simply
        # never enrolled, rather than half-building a tenant-aware follow-up engine.
        if is_kilas_tenant:
            mark_customer_activity(from_number)
        elif ENABLE_MULTI_TENANT and tenant_id is not None:
            # Gap-fix Area F — the tenant-scoped equivalent, persisted in Client Hub's own DB and
            # never touching Kilas Works' own global `followup_state`/channel. Wrapped in the
            # _tf_*_safe helper, so a Client Hub outage here can never break this customer's reply.
            _tf_mark_activity_safe(tenant_id, from_number)

        tenant_context_block = _build_tenant_context_block_safe(tenant_id) if ENABLE_MULTI_TENANT else ""

        ai_reply = call_claude(
            from_number, user_text, image_b64=image_b64, image_mime=image_mime,
            is_voice_note=user_msg_is_voice_note, tenant_context_block=tenant_context_block,
            tenant_id=tenant_id,
        )

        # Deteksi & tangkep nama customer (kalau AI baru dapet tau dari obrolan, bukan dari profil
        # WA) SEBELUM tag lain diproses, simpen ke cache + database, baru buang tag-nya dari teks.
        name_match = TAG_NAMA_PATTERN.search(ai_reply)
        if name_match:
            captured_name = name_match.group(1).strip()
            if captured_name:
                customer_names[scoped_from] = captured_name
                save_customer_name_to_db(scoped_from, captured_name)
            ai_reply = TAG_NAMA_PATTERN.sub("", ai_reply)

        # Deteksi tag internal SEBELUM di-strip, baru kirim versi bersih ke customer
        is_leads_panas = TAG_LEADS_PANAS in ai_reply or "[LEADS PANAS]" in ai_reply
        needs_owner = TAG_TANYA_OWNER in ai_reply
        wants_qr = TAG_KIRIM_QR in ai_reply
        wants_catalog = TAG_KIRIM_KATALOG in ai_reply
        payment_confirmed = TAG_SUDAH_BAYAR in ai_reply
        book_match = TAG_BOOK_MEETING_PATTERN.search(ai_reply)
        resched_match = TAG_RESCHEDULE_MEETING_PATTERN.search(ai_reply)
        wants_cancel_meeting = TAG_CANCEL_MEETING in ai_reply
        wants_stop_followup = TAG_STOP_FOLLOWUP in ai_reply
        meeting_pref_match = TAG_MEETING_PREFERENCE_PATTERN.search(ai_reply)
        meeting_slot_pick_match = TAG_MEETING_SLOT_PICK_PATTERN.search(ai_reply)
        give_payment_info = TAG_GIVE_PAYMENT_INFO in ai_reply
        payment_dp_unclear_match = TAG_PAYMENT_DP_UNCLEAR_PATTERN.search(ai_reply)
        set_lang_match = TAG_SET_LANG_PATTERN.search(ai_reply)
        payment_proof_details_match = TAG_PAYMENT_PROOF_DETAILS_PATTERN.search(ai_reply)

        clean_reply = strip_tags(ai_reply)

        if set_lang_match:
            # LANGUAGE LAYER (additive) — cuma nyimpen preferensi bahasa customer ini biar konsisten
            # di chat berikutnya. Gak ngubah/nge-trigger logic sales/appointment/payment apapun.
            lang_kv = parse_tag_kv(set_lang_match.group(1))
            detected_lang = (lang_kv.get("lang") or "").strip().lower()
            if detected_lang in (LANGUAGE_ID, LANGUAGE_EN):
                customer_language[scoped_from] = detected_lang

        if give_payment_info:
            if is_kilas_tenant:
                # [GIVE_PAYMENT_INFO] SELALU diganti teks rekening resmi dari PAYMENT_CONFIG di sini
                # — AI gak pernah ngetik nomor rekening sendiri, jadi gak ada resiko salah ketik/
                # ngarang digit. PAYMENT_CONFIG is Kilas Works' OWN BCA account — this branch must
                # only ever run for Kilas Works' own conversation with ITS OWN prospects.
                clean_reply = clean_reply.replace(TAG_GIVE_PAYMENT_INFO, build_payment_info_text())
            else:
                # Task 4 — a resolved CLIENT tenant (e.g. a coffee shop) must NEVER have Kilas
                # Works' own BCA account mentioned in ITS conversation with ITS OWN customer; it
                # must use THAT tenant's OWN configured bank details instead, and ONLY if
                # payment_conversation is actually Pro-enabled for this tenant (feature_flags.
                # FEATURE_MATRIX) — a Basic tenant, or a Pro tenant that hasn't configured its own
                # payment details yet, gets a natural "ask the business directly" fallback rather
                # than either internal wording or Kilas Works' own account.
                _tenant_payment_ok = (
                    ENABLE_MULTI_TENANT and tenant_id is not None
                    and _get_tenant_features_safe(tenant_id).get("payment_conversation", False)
                )
                _tenant_payment_text = (
                    build_tenant_payment_info_text(_get_tenant_payment_config_safe(tenant_id))
                    if _tenant_payment_ok else None
                )
                clean_reply = clean_reply.replace(
                    TAG_GIVE_PAYMENT_INFO,
                    _tenant_payment_text or "Untuk info pembayaran resminya, mohon konfirmasi langsung ke tim kami ya, Kak.",
                )

        # Appointment: AI CUMA boleh nulis respons transisi ("oke aku cek dulu ya") + tag — kalimat
        # KONFIRMASI FINAL-nya WAJIB dari sini (Python), abis di-validasi ulang availability-nya, biar
        # gak ada resiko AI ngaku "sudah dijadwalkan"/dsb padahal ternyata slotnya udah keisi duluan
        # atau invalid. meeting_owner_notify dikirim ke owner SETELAH balasan ke customer terkirim.
        meeting_owner_notify = None
        if not is_kilas_tenant:
            # Task 3 — a resolved CLIENT tenant gets its OWN appointment flow (tenant_meeting_
            # requests, scoped by tenant_id+phone), using ONLY that tenant's own business hours/
            # enabled-toggle/rules (see build_tenant_appointment_context, injected into the prompt
            # via _build_tenant_context_block_safe) — NEVER Kilas Works' own office-hours/slot-grid
            # engine below (build_appointment_context/DEFAULT_MEETING_SLOT_TIMES/is_office_closed_
            # on/meeting_requests/appointments, which stay Kilas-Works-only).
            _tenant_appt_settings = _get_tenant_appointment_settings_safe(tenant_id)
            _tenant_appt_ok = (
                ENABLE_MULTI_TENANT and tenant_id is not None
                and _get_tenant_features_safe(tenant_id).get("appointment", False)
                and bool(_tenant_appt_settings.get("meeting_enabled"))
            )
            _tenant_appt_tag = meeting_pref_match or book_match or meeting_slot_pick_match
            scoped_appt_key = _ck(tenant_id, from_number)
            if not _tenant_appt_ok:
                if _tenant_appt_tag or resched_match or wants_cancel_meeting:
                    appt_text = "Untuk jadwal ketemu/booking, mohon hubungi langsung tim kami ya, Kak."
                    clean_reply = f"{clean_reply}|||{appt_text}" if clean_reply else appt_text
            elif _tenant_appt_tag:
                kv = parse_tag_kv(_tenant_appt_tag.group(1))
                day_text = (kv.get("day") or kv.get("date") or "").strip()
                time_text = (kv.get("time") or "").strip()
                tenant_meeting_requests[scoped_appt_key] = {
                    "status": "REQUESTED", "day_text": day_text, "time": time_text or None,
                    "name": customer_names.get(scoped_from), "created_at": _utcnow(),
                }
                # Tenant-persistence cycle (Task 1) — the in-memory dict above is kept as-is (other
                # code/tests still read it as a fast-path cache), but the DATABASE is now the
                # source of truth: a fresh process with an empty dict must still see this booking
                # if it queries the DB (see appointments_repo.py / _tenant_appt_*_safe above).
                request_text = f"{day_text}{(' jam ' + time_text) if time_text else ''}".strip() or "(waktu belum disebut)"
                _tenant_appt_create_safe(tenant_id, from_number, customer_names.get(scoped_from), request_text)
                # Gap-fix Area F — a booking REQUEST is a clear resolution signal: stop the
                # generic tenant follow-up nudge for this customer (they're already mid-flow with
                # the owner, same principle as Kilas Works' own _has_active_meeting_or_payment_process
                # guard, but expressed here as a permanent stop rather than a temporary skip since
                # a tenant follow-up nudge re-engaging mid-negotiation would be confusing/spammy).
                if not is_kilas_tenant:
                    _tf_mark_resolved_safe(tenant_id, from_number, reason="appointment_requested")
                appt_text = "Siap Kak, aku catat dulu ya — nanti tim kami konfirmasi jadwalnya."
                clean_reply = f"{clean_reply}|||{appt_text}" if clean_reply else appt_text
                display_name = customer_names.get(scoped_from, "Customer")
                meeting_owner_notify = f"{display_name} (wa.me/{from_number}) mau booking appointment: {request_text}."
            elif resched_match:
                kv = parse_tag_kv(resched_match.group(1))
                existing = tenant_meeting_requests.get(scoped_appt_key)
                existing_db = _tenant_appt_latest_safe(tenant_id, from_number, statuses=_appt_repo.OPEN_STATUSES if _CLIENT_HUB_AVAILABLE else None)
                if existing or existing_db:
                    if existing:
                        existing["status"] = "REQUESTED"
                        existing["day_text"] = kv.get("date", "") or existing.get("day_text")
                        existing["time"] = kv.get("time") or existing.get("time")
                        new_day = existing["day_text"]
                        new_time = existing.get("time") or ""
                    else:
                        new_day = kv.get("date", "")
                        new_time = kv.get("time") or ""
                    new_request_text = f"{new_day} {new_time}".strip()
                    if existing_db:
                        _tenant_appt_update_reschedule_safe(existing_db["id"], new_request_text, status="RESCHEDULE_REQUESTED")
                    else:
                        _tenant_appt_create_safe(tenant_id, from_number, customer_names.get(scoped_from), new_request_text)
                    appt_text = "Oke Kak, request reschedule-nya aku terusin ke tim buat dikonfirmasi ulang."
                    display_name = customer_names.get(scoped_from, "Customer")
                    meeting_owner_notify = (
                        f"{display_name} (wa.me/{from_number}) minta reschedule appointment ke {new_request_text}.".strip()
                    )
                else:
                    appt_text = "Belum ada appointment yang tercatat atas nama kamu nih Kak — mau bikin baru aja?"
                clean_reply = f"{clean_reply}|||{appt_text}" if clean_reply else appt_text
            elif wants_cancel_meeting:
                existing = tenant_meeting_requests.get(scoped_appt_key)
                existing_db = _tenant_appt_latest_safe(tenant_id, from_number, statuses=_appt_repo.OPEN_STATUSES if _CLIENT_HUB_AVAILABLE else None)
                if existing or existing_db:
                    if existing:
                        existing["status"] = "CANCELLED"
                    if existing_db:
                        _tenant_appt_update_status_safe(existing_db["id"], "CANCELLED")
                    appt_text = "Oke Kak, appointment-nya aku batalin ya. Kabari lagi kalau mau jadwal ulang."
                    display_name = customer_names.get(scoped_from, "Customer")
                    meeting_owner_notify = f"{display_name} (wa.me/{from_number}) membatalkan appointment-nya."
                else:
                    appt_text = "Belum ada appointment yang tercatat atas nama kamu nih Kak."
                clean_reply = f"{clean_reply}|||{appt_text}" if clean_reply else appt_text
        elif meeting_pref_match:
            # FLOW MEETING BARU (production hardening) — customer udah kasih tau MODE (online/offline)
            # + preferensi hari. JANGAN PERNAH langsung confirm di sini — cuma simpen state & notify
            # owner buat availability beneran (lihat MEETING_STATE_PENDING_OWNER_CONFIRMATION).
            kv = parse_tag_kv(meeting_pref_match.group(1))
            mode = (kv.get("mode") or "").strip().lower()
            if mode not in ("online", "offline"):
                mode = "online"
            day_text = (kv.get("day") or "").strip()
            resolved_date = resolve_day_text_to_date(day_text)
            # BUG FIX (owner availability flow): kalau customer di pesan yang SAMA udah nyebut jam
            # EXACT yang dia mau (mis. "Selasa jam 9 bisa?"), simpen sebagai requested_time — biar
            # begitu owner cuma bilang "bisa"/"available" (tanpa nyebut ulang jamnya), sistem bisa
            # langsung CONFIRM jam itu tanpa muter nanya ulang / resiko ganti hari (lihat RULE 1 di
            # try_confirm_meeting_direct & deteksi generic-confirm di webhook owner).
            requested_time_raw = (kv.get("time") or "").strip()
            requested_time = None
            if re.match(r"^\d{1,2}:\d{2}$", requested_time_raw):
                requested_time = requested_time_raw.zfill(5) if len(requested_time_raw) == 4 else requested_time_raw

            # LIVE DEMO (additive) — purpose="demo" dipakai buat bedain wording "live demo AI Admin"
            # dari "online meeting" biasa ke owner & customer. Default "sales" (perilaku lama, gak
            # berubah) kalau AI gak sertain purpose= sama sekali.
            purpose = (kv.get("purpose") or "sales").strip().lower()
            if purpose not in ("sales", "demo"):
                purpose = "sales"

            if mode == "offline" and resolved_date and is_office_closed_on(resolved_date):
                # business_hours (kantor tutup) != meeting_availability owner — offline TIDAK otomatis
                # ditawarin di hari libur kantor, tapi JANGAN nge-block online di hari yang sama.
                day_disp = format_date_id(datetime.strptime(resolved_date, "%Y-%m-%d").date())
                appt_text = (
                    f"Waduh, kantor kita tutup di {day_disp} kak, jadi belum bisa ketemu langsung "
                    f"hari itu. Mau coba hari lain, atau online meeting aja?"
                )
                clean_reply = f"{clean_reply}|||{appt_text}" if clean_reply else appt_text
            else:
                day_disp = (
                    format_date_id(datetime.strptime(resolved_date, "%Y-%m-%d").date())
                    if resolved_date else day_text
                )
                meeting_requests[from_number] = {
                    "status": MEETING_STATE_PENDING_OWNER_CONFIRMATION,
                    "mode": mode, "day_text": day_text, "day_display": day_disp,
                    "resolved_date": resolved_date, "requested_time": requested_time,
                    "purpose": purpose,
                    "name": customer_names.get(from_number), "business_name": None,
                    "need_summary": None, "offered_slots": [], "created_at": _utcnow(),
                }
                appt_text = "Siap Kak, aku cek dulu jadwal owner/tim untuk itu ya. Begitu ada slot yang tersedia aku kabari."
                clean_reply = f"{clean_reply}|||{appt_text}" if clean_reply else appt_text
                mode_label = "live demo AI Admin" if purpose == "demo" else ("ketemu langsung" if mode == "offline" else "online meeting")
                display_name = customer_names.get(from_number, "Customer")
                meeting_owner_notify = f"{display_name} ingin {mode_label} hari {day_disp}. Ada jam yang available?"
        elif meeting_slot_pick_match:
            # Customer milih salah satu jam yang UDAH ditawarin dari slot owner — baru di titik INI
            # appointment beneran jadi CONFIRMED (create_appointment, status "scheduled").
            kv = parse_tag_kv(meeting_slot_pick_match.group(1))
            ok, appt_text, owner_text_notify = try_book_meeting_from_owner_slots(from_number, kv.get("time", ""))
            clean_reply = f"{clean_reply}|||{appt_text}" if clean_reply else appt_text
            if ok:
                meeting_owner_notify = owner_text_notify
        elif book_match:
            kv = parse_tag_kv(book_match.group(1))
            ok, appt_text, owner_text_notify = try_book_meeting(
                from_number, kv.get("name") or customer_names.get(from_number), kv.get("business"),
                kv.get("date", ""), kv.get("time", ""), kv.get("need"),
            )
            clean_reply = f"{clean_reply}|||{appt_text}" if clean_reply else appt_text
            if ok:
                meeting_owner_notify = owner_text_notify
        elif resched_match:
            kv = parse_tag_kv(resched_match.group(1))
            ok, appt_text, owner_text_notify = try_reschedule_meeting(from_number, kv.get("date", ""), kv.get("time", ""))
            clean_reply = f"{clean_reply}|||{appt_text}" if clean_reply else appt_text
            if ok:
                meeting_owner_notify = owner_text_notify
        elif wants_cancel_meeting:
            ok, appt_text, owner_text_notify = try_cancel_meeting(from_number)
            clean_reply = f"{clean_reply}|||{appt_text}" if clean_reply else appt_text
            if ok:
                meeting_owner_notify = owner_text_notify

        # Tenant-persistence cycle (Task 2) — a resolved CLIENT tenant's own customer paying THAT
        # BUSINESS directly (NEVER Kilas Works being paid — that flow stays entirely inside
        # app.kilasworks.id's own checkout/invoice/payment_service.py/ai_payment_review.py,
        # untouched by this branch/table). Persists a REAL tenant_payment_reviews row so this
        # survives a restart and the tenant owner can later query/confirm/reject it — previously
        # payment_confirmed was a dead end for a tenant (it only ever updated Kilas Works' OWN
        # in-memory payment_state, see the is_kilas_tenant-only block further below). The customer
        # ack text is DETERMINISTIC (Python-appended, not left to the AI's free wording) so it can
        # never accidentally claim the proof is genuine/verified/lunas.
        if not is_kilas_tenant and payment_confirmed:
            _tenant_payment_ok = (
                ENABLE_MULTI_TENANT and tenant_id is not None
                and _get_tenant_features_safe(tenant_id).get("payment_conversation", False)
            )
            if _tenant_payment_ok:
                amount_detected = None
                if payment_proof_details_match:
                    details_kv = parse_tag_kv(payment_proof_details_match.group(1))
                    amount_raw = re.sub(r"[^\d]", "", details_kv.get("amount") or "")
                    if amount_raw:
                        amount_detected = int(amount_raw)
                proof_file_id = None
                if image_b64:
                    try:
                        proof_file_id = _tenant_payment_proof_store_safe(
                            tenant_id, base64.b64decode(image_b64), image_mime,
                        )
                    except Exception as e:
                        print(f"Decode bukti pembayaran tenant gagal (tenant_id={tenant_id}): {e}")
                _tenant_payment_review_create_safe(
                    tenant_id, from_number, customer_names.get(scoped_from),
                    amount_detected=amount_detected, proof_file_id=proof_file_id,
                )
                # Gap-fix Area F — a payment proof is a strong resolution signal, same as Kilas
                # Works' own mark_customer_converted() call for payment_confirmed further below.
                _tf_mark_resolved_safe(tenant_id, from_number, reason="payment_confirmed")
                ack_text = "Bukti sudah diterima dan sedang dicek."
                clean_reply = f"{clean_reply}|||{ack_text}" if clean_reply else ack_text

        # Code-level customer price/transport-quotation guardrail (see
        # CUSTOMER_PRICE_DISCLOSURE_PATTERN's module-level docstring) — applied here, as the VERY
        # LAST step before the reply is actually sent, so it catches every Rupiah-shaped figure
        # regardless of which part of the flow above produced it (the model's own free-form reply,
        # NOT any of the system-generated appointment/payment-ack strings appended above, which
        # never contain a Rupiah-formatted figure in the first place). Applies to BOTH Kilas Works'
        # own customers AND every tenant's own customers — no per-tenant config anywhere in this
        # codebase authorizes disclosing a nominal price to a customer, so the same safe default
        # applies uniformly (see _enforce_customer_price_guardrail()'s own docstring).
        #
        # EXEMPTION — active checkout/payment flow: once a customer has moved PAST sales inquiry
        # into an actual confirmed transaction (giving bank details, DP-amount clarification,
        # payment-proof acknowledgment, or — Kilas Works' own customers only — an already-in-
        # progress payment_state), the order summary/nominal-to-transfer is a legitimate, ALREADY-
        # CONFIRMED checkout detail — not a sales-negotiation price quote — and must keep working
        # (preserving the existing payment flow is an explicit requirement). The bank account
        # itself is never at risk either way (build_payment_info_text() only returns bank/account-
        # number/account-name text, which never matches the Rp/rb/jt-shaped patterns this
        # guardrail scans for).
        #
        # payment_state is Kilas-Works-own global state, keyed by BARE phone number with no
        # tenant scoping at all — checking it for a TENANT customer would risk reading an
        # unrelated Kilas-Works-own customer's payment state if the phone numbers happen to
        # coincide (a real cross-tenant leak, not a hypothetical one), so it is only consulted
        # when this is genuinely a Kilas-Works-own conversation (tenant_context_block falsy). The
        # tag-based signals (give_payment_info / DP-clarification / payment-proof) are always safe
        # to check either way, since they are derived from THIS turn's own AI reply, never from
        # any shared global dict.
        _in_active_payment_flow = (
            give_payment_info or bool(payment_dp_unclear_match) or bool(payment_proof_details_match)
            or (not tenant_context_block
                and payment_state.get(from_number, {}).get("status") not in (None, PAYMENT_STATUS_NOT_STARTED))
        )
        if not _in_active_payment_flow:
            clean_reply = _enforce_customer_price_guardrail(clean_reply, tenant_context_block)

        send_reply_bubbles(from_number, incoming_message_id, clean_reply)

        # Bug fix (Task 5/7) — QR code, katalog.pdf, DP/payment-state tracking, and the AI sales
        # engine's lead-scoring/hot-lead notifications below are ALL Kilas-Works-own features tied
        # to Kilas Works' own PRICING_CONFIG/PAYMENT_CONFIG/katalog.pdf — none of them have a
        # tenant-aware equivalent built yet (known limitation of this cycle). Kept Kilas-Works-only
        # rather than half-built, so a resolved CLIENT tenant's customer can never receive Kilas
        # Works' own QR/catalog/sales-engine notifications.
        if is_kilas_tenant:
            if wants_qr:
                send_qr_code(from_number)

            if wants_catalog:
                send_catalog_pdf(from_number)

            if payment_confirmed:
                mark_customer_converted(from_number)  # stop follow-up otomatis
                pay_state = get_or_create_payment_state(from_number)
                pay_state["status"] = PAYMENT_STATUS_PENDING_VERIFICATION  # BELUM dianggap lunas otomatis
                pay_state["updated_at"] = _utcnow()

            if wants_stop_followup:
                mark_customer_converted(from_number)  # stop follow-up otomatis, customer eksplisit minta jangan dihubungi lagi

            if payment_dp_unclear_match:
                dp_kv = parse_tag_kv(payment_dp_unclear_match.group(1))
                dp_package = dp_kv.get("package") or "paketnya"
                pay_state = get_or_create_payment_state(from_number)
                pay_state["status"] = PAYMENT_STATUS_INTENT
                pay_state["package"] = dp_package
                pay_state["dp_requested"] = True
                pay_state["updated_at"] = _utcnow()
                if OWNER_WHATSAPP_NUMBER:
                    dp_name = customer_names.get(from_number, "Customer")
                    send_whatsapp_message(
                        OWNER_WHATSAPP_NUMBER,
                        f"{dp_name} ingin DP untuk {dp_package}. Nominal DP yang mau digunakan berapa?",
                    )

        elif ENABLE_MULTI_TENANT and tenant_id is not None and wants_stop_followup:
            # Gap-fix Area F — tenant equivalent of the wants_stop_followup handling above (this
            # elif is a sibling of `if is_kilas_tenant:`, not nested inside it — is_kilas_tenant is
            # always False here since that branch above already claimed the True case).
            _tf_mark_resolved_safe(tenant_id, from_number, reason="customer_requested_stop")

        # Notifikasi ke owner SEKALI aja pas ada customer BARU yang pertama kali chat (biar owner
        # tau siapa aja yang chat, tanpa banjir notif tiap pesan dari customer yang sama). Bug fix
        # (Task 6) — routed via tenant_id: a resolved CLIENT tenant's own new-customer/escalation
        # notification goes to THAT business's own trusted_owner_phone, never to Kilas Works' own
        # platform owner (see notify_owner*'s docstrings / _get_tenant_owner_notify_target_safe).
        if is_new_customer:
            notify_owner_new_message(from_number, user_text, customer_names.get(scoped_from), tenant_id=tenant_id)

        if is_leads_panas:
            notify_owner(from_number, "LEADS PANAS — ada yang serius mau booking!", user_text, tenant_id=tenant_id)
        elif payment_confirmed:
            notify_owner(
                from_number,
                "Customer kirim bukti transfer (PENDING_VERIFICATION) — mohon verifikasi pembayaran manual",
                user_text, tenant_id=tenant_id,
            )
        elif needs_owner:
            # Task 5 — keyed by _ck(tenant_id, from_number) (== scoped_from), NOT the plain phone
            # number, so this can never surface in another tenant's (or Kilas Works' own) owner
            # interface just because the same customer phone number happens to also be talking to
            # a different tenant.
            pending_owner_questions[scoped_from] = user_text
            notify_owner_question(from_number, user_text, tenant_id=tenant_id)

        if meeting_owner_notify:
            # Task 3/6 — a resolved CLIENT tenant's own appointment notification goes to THAT
            # tenant's own trusted owner, never Kilas Works' own OWNER_WHATSAPP_NUMBER.
            _appt_owner_target = _get_tenant_owner_notify_target_safe(tenant_id)
            if _appt_owner_target:
                send_whatsapp_message(_appt_owner_target, meeting_owner_notify)

        if is_kilas_tenant:
            # AI SALES ENGINE — update lead stage (production hardening). Diinfer dari sinyal
            # DETERMINISTIK yang UDAH dideteksi di atas (bukan tag baru), stage cuma naik, gak
            # pernah turun otomatis. Notify owner CUMA SEKALI per transisi (anti-spam) & CUMA buat
            # sinyal yang belum ada notify spesifiknya sendiri (LEADS_PANAS/payment/meeting
            # confirmed udah notify masing-masing di atas). Kilas-Works-own only — see comment
            # above `if is_kilas_tenant:` for wants_qr/wants_catalog/payment_state.
            meeting_slot_confirmed = bool(meeting_slot_pick_match) and bool(meeting_owner_notify)
            if not is_new_customer:
                bump_lead_stage(from_number, LEAD_STAGE_WARM)
            if wants_catalog or bool(meeting_pref_match) or is_leads_panas or bool(payment_dp_unclear_match):
                hot_state = bump_lead_stage(from_number, LEAD_STAGE_HOT)
                if hot_state["stage"] == LEAD_STAGE_HOT and not hot_state["notified_hot"] and not is_leads_panas:
                    hot_state["notified_hot"] = True
                    notify_owner(from_number, "Lead HOT — mulai nanya harga/katalog/meeting, kemungkinan siap lanjut", user_text)
                elif is_leads_panas:
                    hot_state["notified_hot"] = True  # udah dinotify lewat jalur LEADS_PANAS di atas
            if give_payment_info or payment_confirmed or meeting_slot_confirmed:
                closing_state = bump_lead_stage(from_number, LEAD_STAGE_CLOSING)
                if closing_state["stage"] == LEAD_STAGE_CLOSING and not closing_state["notified_closing"]:
                    closing_state["notified_closing"] = True
                    if give_payment_info and not payment_confirmed and not meeting_slot_confirmed:
                        # payment_confirmed & meeting_slot_confirmed udah punya notify spesifik sendiri di
                        # atas — cuma give_payment_info doang yang belum ada notify sebelumnya.
                        notify_owner(from_number, "Lead CLOSING — udah dikasih info rekening, tunggu bukti transfer", user_text)

    return jsonify({"status": "ok"}), 200


@app.route("/", methods=["GET"])
def health_check():
    return "Kilas Works AI Admin - server jalan!", 200


@app.route("/internal/build-info", methods=["GET"])
def internal_build_info():
    """Diagnostik ringan (voice production bug, cycle 3) — dipakai buat MEMASTIKAN commit yang
    beneran jalan di Render sama dengan commit yang dikira di-deploy, TANPA expose apapun ke
    customer (di-gate pakai DASHBOARD_KEY, pola yang sama kayak /dashboard). Gak pernah nampilin
    OPENAI_API_KEY/WHATSAPP_ACCESS_TOKEN — cuma bool "apakah keisi" buat voice note provider.
    Akses: GET /internal/build-info?key=<DASHBOARD_KEY>
    """
    key = request.args.get("key", "")
    if not DASHBOARD_KEY or key != DASHBOARD_KEY:
        return jsonify({"status": "error", "message": "Akses ditolak, key salah/kosong."}), 403

    # Render otomatis nyediain RENDER_GIT_COMMIT (SHA commit yang beneran di-build & dijalanin) dan
    # RENDER_SERVICE_NAME — ini BUKAN sesuatu yang kita set manual, jadi bisa dipercaya buat
    # ngebuktiin "apakah code yang jalan sekarang beneran versi terbaru yang di-push".
    return jsonify({
        "status": "ok",
        "render_git_commit": os.environ.get("RENDER_GIT_COMMIT", "unknown (bukan di-deploy lewat Render, atau env var gak ke-set)"),
        "render_service_name": os.environ.get("RENDER_SERVICE_NAME", "unknown"),
        "voice_note_customer_enabled": FEATURES.get("voice_note_customer", False),
        "voice_note_owner_enabled": FEATURES.get("voice_note_owner", False),
        "transcription_provider": TRANSCRIPTION_PROVIDER,
        "transcription_model": TRANSCRIPTION_MODEL,
        "openai_api_key_present": bool((OPENAI_API_KEY or "").strip()),
    }), 200


_SUPPORTED_INTERNAL_NOTIFICATION_TYPES = (
    "AI_ONBOARDING_READY_FOR_REVIEW",
    "CUSTOM_PROJECT_SUBMITTED",
    "TALENT_REQUEST_SUBMITTED",
    "QUOTATION_APPROVED",
    "PAYMENT_PROOF_UPLOADED",
    "WHATSAPP_CONNECTION_READY",
)


@app.route("/internal/platform-cs-reply", methods=["POST"])
def internal_platform_cs_reply():
    """Authenticated Client Hub -> Kilas Works WhatsApp manual reply bridge.

    Client Hub never receives Meta access tokens. This bot service already owns the platform's
    WhatsApp credentials, so it performs the actual send after independently re-checking Human
    Takeover and the conservative 23-hour free-text window. Destination is limited to an existing
    Kilas Works customer conversation; arbitrary numbers cannot be used as an open relay.
    """
    _clear_active_whatsapp_channel()
    provided_secret = request.headers.get("X-Internal-Service-Secret", "")
    if not INTERNAL_SERVICE_SECRET or not hmac.compare_digest(provided_secret, INTERNAL_SERVICE_SECRET):
        return jsonify({"status": "error", "reason": "access_denied"}), 403
    if not _CLIENT_HUB_AVAILABLE:
        return jsonify({"status": "error", "reason": "client_hub_bridge_unavailable"}), 503

    payload = request.get_json(silent=True) or {}
    phone = re.sub(r"\D", "", str(payload.get("customer_phone") or ""))
    text = (payload.get("message") or "").strip() if isinstance(payload.get("message"), str) else ""
    if not re.fullmatch(r"\d{6,20}", phone):
        return jsonify({"status": "error", "reason": "invalid_customer_phone"}), 400
    if not text:
        return jsonify({"status": "error", "reason": "empty_message"}), 400
    if len(text) > 4096:
        return jsonify({"status": "error", "reason": "message_too_long"}), 400

    try:
        if not _platform_inbox.customer_exists(phone):
            return jsonify({"status": "error", "reason": "customer_not_found"}), 404
        if _platform_inbox.get_state(phone) != "HUMAN_TAKEOVER":
            return jsonify({"status": "error", "reason": "human_takeover_required"}), 409
        window = _platform_inbox.freeform_window_status(phone)
    except Exception as e:
        print(f"Platform CS reply safety check gagal ({e}) — pesan tidak dikirim.")
        return jsonify({"status": "error", "reason": "takeover_state_unavailable"}), 503
    if not window.get("allowed"):
        return jsonify({"status": "error", "reason": window.get("reason") or "outside_24h_window"}), 409

    ok, err = send_whatsapp_message(phone, text)
    if not ok:
        return jsonify({"status": "error", "reason": "whatsapp_send_failed"}), 502

    history = conversations.get(phone)
    if history is None:
        history = load_recent_messages_from_db(phone, "customer")
    history.append({"role": "assistant", "content": text})
    conversations[phone] = history[-20:]
    save_message_to_db(phone, "customer", "assistant", text)
    return jsonify({"status": "ok"}), 200


@app.route("/internal/owner-notify", methods=["POST"])
def internal_owner_notify():
    """Absolute Final Production Patch — the ONE HTTP door Client Hub uses to ask this bot process
    to deliver an owner WhatsApp notification immediately (client-hub/owner_notification_delivery.py
    is the only caller this is designed for). Security properties, all deliberate:

    - Shared-secret auth via the X-Internal-Service-Secret header, compared with
      hmac.compare_digest (constant-time) against INTERNAL_SERVICE_SECRET. If that env var is
      unset/empty, this endpoint FAILS CLOSED — every request is rejected — rather than silently
      accepting unauthenticated calls. The secret value itself is never logged, in either the
      success or failure path.
    - `notification_type` MUST be one of a small fixed allow-list (mirrors
      client-hub/owner_notifications.EVENT_TYPES minus the not-yet-implemented escalation type) —
      never an arbitrary free-form action.
    - The destination is NEVER read from the request body. This endpoint only ever sends to
      OWNER_WHATSAPP_NUMBER (Kilas Works' own configured owner number) — any "to"/"phone"/
      "destination" field in the payload is ignored outright, so a compromised or buggy Client Hub
      caller can never redirect a message to an arbitrary number.
    - WhatsApp API tokens are never included in any response, success or error.
    """
    # Task 6 (multi-tenant runtime safety) — this endpoint must ALWAYS use Kilas Works' own global
    # WhatsApp channel, NEVER whatever tenant channel a previous /webhook request on this same
    # worker thread happened to activate. receive_webhook() now clears this in a `finally` block on
    # every request, but this explicit clear is defense-in-depth (and correct even if a future
    # caller invokes send_whatsapp_message from this thread outside that guarantee).
    _clear_active_whatsapp_channel()
    if INTERNAL_OWNER_NOTIFY_DISABLED:
        # Set only when RENDER is active and INTERNAL_SERVICE_SECRET is missing/blank (see startup
        # block above) — fail closed on every single request, no exceptions, never logging the
        # (nonexistent) secret value.
        print("SECURITY: rejected /internal/owner-notify request — endpoint disabled (INTERNAL_SERVICE_SECRET unset on Render).")
        return jsonify({"status": "error", "message": "Akses ditolak."}), 403

    provided_secret = request.headers.get("X-Internal-Service-Secret", "")
    if not INTERNAL_SERVICE_SECRET or not hmac.compare_digest(provided_secret, INTERNAL_SERVICE_SECRET):
        return jsonify({"status": "error", "message": "Akses ditolak."}), 403

    payload = request.get_json(silent=True) or {}
    notification_type = payload.get("notification_type")
    message = payload.get("message")

    if notification_type not in _SUPPORTED_INTERNAL_NOTIFICATION_TYPES:
        return jsonify({"status": "error", "message": "notification_type tidak didukung."}), 400
    if not message or not isinstance(message, str):
        return jsonify({"status": "error", "message": "message wajib diisi (string)."}), 400
    if not OWNER_WHATSAPP_NUMBER:
        return jsonify({"status": "error", "message": "OWNER_WHATSAPP_NUMBER belum dikonfigurasi."}), 200

    ok, err = send_whatsapp_message(OWNER_WHATSAPP_NUMBER, message)
    if ok:
        return jsonify({"status": "ok"}), 200
    return jsonify({"status": "error", "message": "Gagal kirim WhatsApp."}), 200


@app.route("/cron/owner-notifications", methods=["GET"])
def run_owner_notifications():
    """Final Ecosystem Sync — Section 11/12: polls Client Hub's `owner_notifications` ledger
    (written by client-hub/owner_notifications.py at the moment of a business event — quotation
    approved, payment proof uploaded, custom project/talent request submitted, AI onboarding ready
    for review, WhatsApp-connection-ready) and does the actual WhatsApp send here, since this
    process is the only one holding WhatsApp Cloud API credentials. Idempotent by construction:
    a row is only ever sent once (marked SENT and never touched again); a genuine send failure
    (e.g. WhatsApp API error) leaves it FAILED so the NEXT poll retries it — never a duplicate send
    of an already-SENT row. Safe to call as often as the external scheduler likes, same pattern as
    /cron/followups above.
    Akses: GET /cron/owner-notifications?key=<CRON_SECRET>
    """
    # Task 6 — always Kilas Works' own global channel, never a tenant's (defense-in-depth; see
    # internal_owner_notify's identical comment).
    _clear_active_whatsapp_channel()
    key = request.args.get("key", "")
    if not CRON_SECRET or key != CRON_SECRET:
        return jsonify({"status": "error", "message": "Akses ditolak, key salah/kosong."}), 403

    try:
        import owner_notifications as _owner_notifications
    except Exception as e:
        return jsonify({"status": "error", "message": f"Client Hub tidak tersedia: {e}"}), 200

    sent, failed = 0, 0
    try:
        pending = _owner_notifications.list_pending()
    except Exception as e:
        return jsonify({"status": "error", "message": f"Gagal ambil pending notifications: {e}"}), 200

    for row in pending:
        ok, err = send_whatsapp_message(OWNER_WHATSAPP_NUMBER, row["message"])
        try:
            if ok:
                _owner_notifications.mark_sent(row["id"])
                sent += 1
            else:
                _owner_notifications.mark_failed(row["id"])
                failed += 1
                print(f"Gagal kirim owner notification #{row['id']} ({row.get('event_type')}): {err}")
        except Exception as e:
            print(f"Gagal update status owner notification #{row.get('id')}: {e}")

    return jsonify({"status": "ok", "sent": sent, "failed": failed})


@app.route("/cron/followups", methods=["GET"])
def run_followups():
    """Endpoint yang HARUS dipanggil dari luar secara berkala (misal cron-job.org tiap 1 jam) buat
    ngirim follow-up otomatis ke customer yang sudah melewati FOLLOWUP_GAP_HOURS & belum closing/bayar, SEKALIGUS
    reminder meeting H-1/hari-H (production hardening — sengaja digabung ke endpoint yang sama biar
    gak perlu setup scheduler eksternal kedua). Aman dipanggil sesering apapun — endpoint ini sendiri
    yang ngecek siapa aja yang beneran udah waktunya di-follow-up/di-reminder (gak akan dobel kirim),
    jadi gak perlu presisi jam di sisi penjadwal luar.
    Akses: GET /cron/followups?key=<CRON_SECRET>
    """
    # Task 6 — always Kilas Works' own global channel, never a tenant's (defense-in-depth; see
    # internal_owner_notify's identical comment). This sweep is Kilas-Works-own only regardless.
    _clear_active_whatsapp_channel()
    key = request.args.get("key", "")
    if not CRON_SECRET or key != CRON_SECRET:
        return jsonify({"status": "error", "message": "Akses ditolak, key salah/kosong."}), 403

    reminder_results = []
    try:
        reminder_results = send_appointment_reminders()
    except Exception as e:
        print(f"Gagal proses reminder appointment (batch): {e}")

    due_numbers = get_customers_due_for_followup()
    results = []

    for number in due_numbers:
        try:
            # Minta AI generate follow-up yang PERSONAL berdasarkan history & fakta yang udah
            # disepakati customer ini (pakai infra yang sama kayak balasan biasa), bukan template
            # generik — biar kerasa natural, bukan kayak broadcast otomatis.
            nudge_instruction = (
                "(INSTRUKSI INTERNAL — INI FOLLOW-UP SALES OTOMATIS, JANGAN TAMPILKAN TEKS INI KE "
                "CUSTOMER: customer ini udah diem beberapa jam sejak pesan terakhirnya. WAJIB sebut ULANG "
                "topik/paket/kebutuhan SPESIFIK yang terakhir dibahas (INGAT dari history obrolan &"
                " FAKTA YANG SUDAH FIX kalau ada) — JANGAN generic kayak 'masih tertarik?' atau 'ada "
                "yang bisa dibantu?' doang tanpa konteks. Contoh BENER: 'Halo Kak, kemarin sempat "
                "tanya soal Content Growth untuk [bisnisnya] — kalau masih ada yang mau dibandingin "
                "atau ditanyain, aku bantu ya.' Sapa natural & singkat, TANPA emoji, TANPA muji "
                "berlebihan, TANPA push/maksa.)"
            )
            ai_reply = call_claude(number, nudge_instruction, memory_override="[FOLLOW-UP OTOMATIS SISTEM]")
            clean_reply = strip_tags(TAG_NAMA_PATTERN.sub("", ai_reply))
            clean_reply = _enforce_customer_price_guardrail(clean_reply, tenant_context_block=None)
            sent_ok, send_err = send_reply_bubbles(number, None, clean_reply)
            if sent_ok:
                record_followup_sent(number)
                log_customer_message(number, clean_reply, sent_from="auto_followup")
                results.append({"number": number, "status": "sent"})
            else:
                results.append({"number": number, "status": "failed", "error": send_err})
        except Exception as e:
            print(f"Gagal follow-up ke {number}: {e}")
            results.append({"number": number, "status": "error", "error": str(e)})

    return jsonify({
        "status": "ok",
        "checked": len(due_numbers),
        "results": results,
        "reminders_checked": len(reminder_results),
        "reminders": reminder_results,
    }), 200


@app.route("/cron/tenant-followups", methods=["GET"])
def run_tenant_followups():
    """Gap-fix Area F — tenant-scoped equivalent of /cron/followups above, closing the documented
    gap at the "if is_kilas_tenant: mark_customer_activity(...)" call site. Iterates every ACTIVE
    Client Hub tenant and sends AI-generated follow-up nudges ONLY through THAT tenant's own
    validated WhatsApp channel — this endpoint NEVER sends via Kilas Works' own global
    WHATSAPP_PHONE_NUMBER_ID/WHATSAPP_ACCESS_TOKEN, and NEVER touches ../app.py's own
    `followup_state`/get_customers_due_for_followup()/run_followups() above (that sweep remains
    100% unchanged, Kilas-Works-only, exactly as before this endpoint existed).

    Safety invariants enforced here (see client-hub/tenant_followup_service.py for the underlying
    checks this route relies on):
      - A tenant is skipped ENTIRELY (zero sends) unless tenant_followup_service.
        is_tenant_followup_eligible() returns True — covers business ACTIVE, subscription not
        SUSPENDED, the follow-up-capable feature flag, AND a WhatsApp channel whose
        connection_status is exactly 'CONNECTED' (validated).
      - The active WhatsApp channel is ONLY ever set via _set_active_whatsapp_channel() AFTER
        _get_tenant_whatsapp_channel_safe() has positively resolved a real phone_number_id +
        access_token for THIS tenant — if that resolution returns None for any reason, this
        tenant is skipped without calling any send function at all (see
        _active_whatsapp_phone_number_id()'s own docstring: it silently falls back to the GLOBAL
        Kilas Works number if the thread-local isn't set, which is exactly why this route never
        calls a send function without first confirming the channel is genuinely set).
      - _clear_active_whatsapp_channel() is called after EVERY tenant (success or failure) so one
        tenant's channel can never leak into the next tenant's iteration or back into Kilas Works'
        own global sends elsewhere in this same worker thread.
      - HUMAN_TAKEOVER is re-checked per-customer, immediately before generating/sending each
        nudge (state can change between listing "due" customers and actually reaching them).

    Akses: GET /cron/tenant-followups?key=<CRON_SECRET> — same shared secret as /cron/followups
    (a separate secret was considered but rejected as unnecessary complexity for an internal cron
    endpoint already gated the same way as every other /cron/* route in this file).
    """
    _clear_active_whatsapp_channel()
    key = request.args.get("key", "")
    if not CRON_SECRET or key != CRON_SECRET:
        return jsonify({"status": "error", "message": "Akses ditolak, key salah/kosong."}), 403

    if not ENABLE_MULTI_TENANT:
        return jsonify({
            "status": "disabled",
            "message": "Tenant follow-up tidak dijalankan karena ENABLE_MULTI_TENANT belum aktif.",
            "tenants_checked": 0,
            "results": [],
        }), 409

    if not _CLIENT_HUB_AVAILABLE:
        return jsonify({"status": "ok", "message": "Client Hub tidak tersedia — tidak ada tenant untuk diproses.",
                         "tenants_checked": 0, "results": []}), 200

    results = []
    try:
        tenants = _ch_repo.list_all_businesses(status_filter="ACTIVE")
    except Exception as e:
        print(f"run_tenant_followups: gagal ambil daftar tenant ACTIVE: {e}")
        return jsonify({"status": "error", "message": "Gagal ambil daftar tenant.", "detail": str(e)}), 500

    for business in tenants:
        tenant_id = business["id"]
        _clear_active_whatsapp_channel()  # never inherit the previous tenant's channel
        try:
            eligible, reason = _tenant_followup.is_tenant_followup_eligible(tenant_id)
            if not eligible:
                results.append({"tenant_id": tenant_id, "status": "skipped", "reason": reason})
                continue

            channel = _get_tenant_whatsapp_channel_safe(tenant_id)
            if not channel:
                # Positively confirms "not configured/not validated" — never proceed to any send
                # call without a genuinely resolved channel (see docstring above).
                results.append({"tenant_id": tenant_id, "status": "skipped", "reason": "channel_resolution_failed"})
                continue

            due_numbers = _tenant_followup.get_customers_due_for_followup(tenant_id)
            tenant_context_block = _build_tenant_context_block_safe(tenant_id)
            sent_count = 0
            for customer_phone in due_numbers:
                try:
                    if _get_conversation_mode_safe(tenant_id, customer_phone) == "HUMAN_TAKEOVER":
                        results.append({"tenant_id": tenant_id, "customer": customer_phone,
                                         "status": "skipped", "reason": "human_takeover"})
                        continue

                    _set_active_whatsapp_channel(channel["phone_number_id"], channel["access_token"])
                    nudge_instruction = (
                        "(INSTRUKSI INTERNAL — INI FOLLOW-UP OTOMATIS, JANGAN TAMPILKAN TEKS INI KE "
                        "CUSTOMER: customer ini udah diem beberapa jam sejak pesan terakhirnya. WAJIB "
                        "sebut ULANG topik/kebutuhan SPESIFIK yang terakhir dibahas (INGAT dari history "
                        "obrolan) — JANGAN generic kayak 'masih tertarik?' doang tanpa konteks. Sapa "
                        "natural & singkat, TANPA emoji, TANPA push/maksa.)"
                    )
                    ai_reply = call_claude(
                        customer_phone, nudge_instruction, memory_override="[FOLLOW-UP OTOMATIS SISTEM]",
                        tenant_id=tenant_id, tenant_context_block=tenant_context_block,
                    )
                    clean_reply = strip_tags(TAG_NAMA_PATTERN.sub("", ai_reply))
                    # Tenant follow-up nudge — same universal guardrail as every other
                    # customer-facing send point (see _enforce_customer_price_guardrail()'s
                    # docstring): a follow-up nudge is never part of an active checkout, so this
                    # runs unconditionally here (no payment-flow exemption needed for a follow-up).
                    clean_reply = _enforce_customer_price_guardrail(clean_reply, tenant_context_block)
                    sent_ok, send_err = send_reply_bubbles(customer_phone, None, clean_reply)
                    if sent_ok:
                        _tenant_followup.record_followup_sent(tenant_id, customer_phone)
                        sent_count += 1
                        results.append({"tenant_id": tenant_id, "customer": customer_phone, "status": "sent"})
                    else:
                        results.append({"tenant_id": tenant_id, "customer": customer_phone,
                                         "status": "failed", "error": send_err})
                except Exception as e:
                    print(f"run_tenant_followups: gagal follow-up tenant_id={tenant_id} customer={customer_phone}: {e}")
                    results.append({"tenant_id": tenant_id, "customer": customer_phone,
                                     "status": "error", "error": str(e)})
        except Exception as e:
            print(f"run_tenant_followups: gagal proses tenant_id={tenant_id}: {e}")
            results.append({"tenant_id": tenant_id, "status": "error", "error": str(e)})
        finally:
            _clear_active_whatsapp_channel()

    return jsonify({"status": "ok", "tenants_checked": len(tenants), "results": results}), 200


# ============================================================
# DEMO SANDBOX — buat kasih lihat AI Admin ke calon klien TANPA perlu setup ulang
# bot/data bisnis satu-satu tiap ada yang mau nyoba. Prospek chat lewat WEB (link
# /demo), BUKAN WhatsApp beneran — jadi gratis dari sisi biaya WhatsApp API & gak
# nyentuh nomor asli sama sekali. Data bisnis di demo ini FIKTIF (kedai kopi contoh),
# tujuannya nunjukin KEMAMPUAN AI Admin-nya ke calon klien, bukan chatbot Kilas Works.
# Kalau prospek keliatan serius & kasih kontak, owner otomatis dapet notif WA.
# ============================================================

demo_sessions = {}  # session_id -> {"history": [...], "count": int, "created_at": datetime, "notified": bool}
demo_daily_usage = {"date": None, "messages": 0}

DEMO_MAX_MESSAGES_PER_SESSION = 20   # batas pesan per 1 orang nyoba, biar 1 sesi gak dipakai spam
DEMO_MAX_MESSAGES_PER_DAY = 150      # batas TOTAL pesan demo per hari (gabungan semua orang) — jaga biaya API
DEMO_SESSION_TTL_HOURS = 6           # sesi yang udah lama dianggap basi & dibuang dari memori

TAG_DEMO_LEAD = re.compile(r"\[DEMO_LEAD:\s*([^\]]+)\]", re.IGNORECASE)

DEMO_SYSTEM_PROMPT = (
    "Kamu adalah AI WhatsApp Admin buatan Kilas Works, LAGI DIPAKAI BUAT DEMO ke calon klien. "
    "Orang yang lagi nyoba ini BUKAN customer asli — dia calon KLIEN Kilas Works yang mau lihat "
    "AI Admin ini bisa ngapain aja sebelum mutusin pakai buat bisnisnya sendiri.\n\n"
    "PENTING — DEMO INI HARUS TERASA CEPAT & PROFESIONAL, BUKAN KAYAK ISI FORM/QUESTIONNAIRE. "
    "Onboarding MAKSIMAL 3 PERTANYAAN SAJA, lalu LANGSUNG masuk simulasi. Ikutin urutan ini PERSIS:\n\n"
    "TAHAP 1 — ONBOARDING (maksimal 3 pertanyaan, SATU pertanyaan per balasan, jangan lebih):\n"
    "  Pertanyaan 1: nama bisnisnya apa.\n"
    "  Pertanyaan 2: bisnisnya bergerak di bidang apa.\n"
    "  Pertanyaan 3: produk/layanan utamanya apa.\n"
    "Di balasan PERTAMA, kasih tau singkat ini demo AI WhatsApp Admin Kilas Works, terus langsung "
    "lempar Pertanyaan 1 (jangan ada basa-basi panjang sebelum pertanyaan). Setelah pertanyaan 1 "
    "dijawab, lempar pertanyaan 2. Setelah dijawab, lempar pertanyaan 3. SETELAH PERTANYAAN 3 "
    "DIJAWAB, STOP ONBOARDING — JANGAN nanya hal lain lagi (jangan nanya soal FAQ customer, masalah "
    "WhatsApp selama ini, tujuan pakai AI Admin, dll — itu semua BOLEH kegali natural nanti SELAMA "
    "simulasi berjalan, bukan di tahap onboarding).\n\n"
    "TRANSISI KE SIMULASI (WAJIB persis setelah pertanyaan 3 dijawab, dalam SATU balasan):\n"
    "Bilang natural kira-kira: 'Oke, aku udah punya gambaran. Sekarang aku akan coba jadi AI Admin "
    "untuk [Nama Bisnis]. Mulai dari sini, coba chat aku seperti Kakak adalah customer bisnis "
    "tersebut.' (sesuaikan kalimat, gak perlu persis kata-katanya, tapi WAJIB: sebut nama bisnisnya "
    "& jelas ngasih tau simulasi dimulai SEKARANG). Setelah baris ini, jangan tanya apapun lagi di "
    "balasan yang sama — biarkan lawan bicara yang mulai chat duluan sebagai customer.\n\n"
    "TAHAP 2 — SIMULATION MODE (roleplay jadi AI Admin bisnis DIA, bukan Kilas Works):\n"
    "Begitu lawan bicara kirim pesan pertama SEBAGAI CUSTOMER (misal nanya menu/harga/jam buka/mau "
    "booking), MULAI BERPERAN jadi AI Admin bisnis itu sepenuhnya — bukan kedai kopi, bukan bisnis "
    "contoh lain, PERSIS bisnis yang tadi dia sebutin.\n"
    "SOAL FAKTA SPESIFIK (harga, jam buka, menu detail dll) — INI YANG PALING PENTING: kamu BELUM "
    "PUNYA data asli bisnis dia, jadi JANGAN PERNAH ngarang fakta spesifik lalu bilang seolah itu "
    "data beneran. Kalau ditanya hal yang butuh angka/detail spesifik, boleh kasih CONTOH simulasi "
    "yang wajar TAPI WAJIB disebut eksplisit itu contoh, misal: 'Untuk demo ini anggap [Nama Bisnis] "
    "buka jam 10.00-22.00 ya Kak. Nanti pada implementasi asli, jam operasionalnya bakal ikut data "
    "bisnis Kakak beneran.' Pola yang sama buat harga/menu/paket — selalu tempelin catatan jujur "
    "kayak gitu, jangan cuma sekali di awal terus abis itu ngarang fakta tanpa disclaimer lagi.\n\n"
    "TUNJUKKAN VALUE AI ADMIN, JANGAN JADI CUMA FAQ BOT: selama simulasi, tunjukkan secara natural "
    "kemampuan kayak AI Admin asli — jawab pertanyaan, gali kebutuhan customer lebih detail (nanya "
    "balik seperlunya, bukan interogasi), qualifikasi lead (makin serius makin digali detailnya), "
    "kalau customer keliatan cukup serius (nanya harga+detail, mau booking, kasih info kontak) baru "
    "nawarin appointment/lanjut ke tim secara natural, dan implisit tunjukkan konsep handoff ke owner "
    "& follow-up (misal 'nanti owner saya yang lanjutin bahas detailnya ya'). JANGAN nawarin meeting "
    "di PESAN PERTAMA simulasi — biarkan minimal 2-3 balasan ngobrol dulu sebelum nawarin ketemu/"
    "lanjut ke tim, biar kerasa natural bukan buru-buru jualan.\n"
    "Gaya jawab: SAMA kayak AI Admin asli (singkat, natural, TANPA emoji, TANPA pujian lebay), "
    "inget jawaban sebelumnya di sesi yang sama, dan kalau ada hal di luar wewenang bilang 'saya cek "
    "dulu ke owner ya' (ini simulasi, gak usah beneran nunggu).\n\n"
    "ATURAN PENTING — JANGAN NGARANG FITUR YANG BELUM TENTU ADA: AI Admin asli TIDAK otomatis "
    "terintegrasi ke sistem pembayaran, CRM, kalender booking asli, atau software inventory customer "
    "kecuali memang di-setup khusus. Kalau selama roleplay muncul hal kayak 'oke saya proses "
    "pembayarannya' atau 'otomatis update ke sistem kasir', WAJIB kasih catatan jujur bahwa itu contoh "
    "simulasi alur percakapan aja — integrasi ke sistem/tools asli bisnis dia itu bagian setup "
    "terpisah yang dibahas sama tim Kilas Works, bukan otomatis ada dari awal.\n\n"
    "TAHAP 3 — SETELAH DEMO KELIATAN COCOK:\n"
    "Kalau lawan bicara keliatan tertarik/puas sama simulasinya (misal bilang 'wah mirip', 'oke juga', "
    "nanya lanjutannya gimana, atau nanya harga paket Kilas Works), transisi natural dulu, misal: "
    "'Kira-kira flow seperti ini sudah mirip dengan yang Kakak butuhkan?' — baru abis itu tawarin "
    "ngobrol sama tim/owner Kilas Works buat bahas kebutuhan spesifik & harga paket bulanan (JANGAN "
    "ngarang harga paket Kilas Works di sini, arahkan ke tim). Kalau dia kasih nama & kontak & jenis "
    "bisnisnya buat di-follow-up tim Kilas Works, WAJIB tambahin tag PERSIS di akhir balasan: "
    "[DEMO_LEAD: nama=..., bisnis=..., catatan=...] — tag ini gak keliatan ke user, sinyal internal "
    "doang buat sistem.\n\n"
    "ATURAN GAYA: TANPA emoji sama sekali, TANPA pujian berlebihan ('keren', 'menarik banget', "
    "'wow'), singkat & natural kayak chat WhatsApp beneran, jangan kaku/formal banget, SATU "
    "pertanyaan per balasan (jangan borongan banyak pertanyaan dalam satu bubble).\n\n"
    "BAHASA — AUTO-DETECT (WAJIB, sama kayak AI Admin asli): deteksi bahasa dari pesan TERAKHIR lawan "
    "bicara tiap kali balas (lihat histori percakapan sesi ini buat konteks, tapi bahasa balasan "
    "ngikutin pesan yang PALING BARU). Kalau dia nulis Bahasa Indonesia, balas Bahasa Indonesia. Kalau "
    "dia nulis English, balas full English natural (bukan translate kaku). Kalau campur, ikutin yang "
    "paling dominan. Boleh ganti bahasa di tengah sesi kalau lawan bicara ganti duluan — JANGAN PERNAH "
    "nanya 'mau bahasa apa?' kecuali pesannya beneran gak ada kata sama sekali (cuma emoji/angka). "
    "Nama paket Kilas Works (Content Growth, AI Admin Pro, dst) TETAP PERSIS gak diterjemahin walau "
    "balasannya English. Demo TIDAK BOLEH error/nge-blank cuma gara-gara lawan bicara pakai English —"
    " kalau ragu bahasa apa, default Bahasa Indonesia dulu, JANGAN diem/gagal balas."
)

# Frasa yang dianggap perintah "mulai ulang demo dari nol" (bukan pertanyaan biasa ke AI) — dicek
# SEBELUM manggil AI (deterministic, hemat API call juga), biar reset selalu konsisten & gak
# tergantung mood/interpretasi model. Regex kata utuh biar "reset" gak nyangkut ke kata lain.
DEMO_RESET_PATTERN = re.compile(
    r"\b(coba\s+bisnis\s+lain|ganti\s+bisnis|reset\s+demo|mulai\s+ulang|mulai\s+dari\s+awal|"
    r"restart\s+demo|demo\s+ulang|coba\s+ulang\s+dari\s+awal)\b",
    re.IGNORECASE,
)

DEMO_GREETING = (
    "Halo! Ini demo AI WhatsApp Admin Kilas Works. Biar demo-nya pas sama bisnis Kakak, "
    "boleh cerita dikit dulu — bisnis Kakak namanya apa?"
)


def _demo_reset_daily_if_needed():
    """Reset counter harian kalau udah ganti hari (UTC) — biar kuota /hari beneran per-hari."""
    today_str = _utcnow().strftime("%Y-%m-%d")
    if demo_daily_usage["date"] != today_str:
        demo_daily_usage["date"] = today_str
        demo_daily_usage["messages"] = 0


def _demo_cleanup_stale_sessions():
    """Buang sesi demo yang udah lebih tua dari DEMO_SESSION_TTL_HOURS biar memori gak numpuk."""
    cutoff = _utcnow() - timedelta(hours=DEMO_SESSION_TTL_HOURS)
    stale = [sid for sid, s in demo_sessions.items() if s["created_at"] < cutoff]
    for sid in stale:
        demo_sessions.pop(sid, None)


DEMO_PAGE_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>Demo AI WhatsApp Admin — Kilas Works</title>
<style>
  :root {
    --ink: #121110;
    --surface: #1B1917;
    --bubble-bot: #262320;
    --bubble-user: #D97A3E;
    --text: #F3EFE9;
    --muted: #A79E93;
    --accent: #D97A3E;
    --error: #E0574A;
    --border: #2E2A26;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body { height: 100%; }
  body {
    margin: 0;
    background: var(--ink);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    flex-direction: column;
    height: 100dvh;
    overflow: hidden;
  }
  header {
    padding: 14px 16px 12px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .header-top {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
  }
  header h1 {
    margin: 0;
    font-size: 16px;
    color: var(--accent);
    font-weight: 700;
    letter-spacing: -0.01em;
  }
  .sim-badge {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--ink);
    background: var(--accent);
    padding: 2px 7px;
    border-radius: 999px;
    white-space: nowrap;
  }
  header p {
    margin: 0;
    font-size: 12px;
    color: var(--muted);
    line-height: 1.4;
  }
  #chat {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .bubble {
    max-width: 82%;
    padding: 10px 13px;
    border-radius: 15px;
    font-size: 14.5px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-wrap: break-word;
    animation: rise 0.18s ease-out;
  }
  @keyframes rise {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .bot {
    align-self: flex-start;
    background: var(--bubble-bot);
    border-bottom-left-radius: 4px;
  }
  .bot.error {
    background: rgba(224, 87, 74, 0.14);
    border: 1px solid rgba(224, 87, 74, 0.4);
    color: #F3D9D6;
  }
  .user {
    align-self: flex-end;
    background: var(--bubble-user);
    color: #1B1100;
    border-bottom-right-radius: 4px;
    font-weight: 500;
  }
  .typing {
    align-self: flex-start;
    display: flex;
    gap: 4px;
    padding: 10px 13px;
  }
  .typing span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--muted);
    animation: blink 1.2s infinite;
  }
  .typing span:nth-child(2) { animation-delay: 0.2s; }
  .typing span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes blink {
    0%, 80%, 100% { opacity: 0.25; }
    40% { opacity: 1; }
  }
  form {
    display: flex;
    gap: 8px;
    padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
    background: var(--surface);
    border-top: 1px solid var(--border);
    flex-shrink: 0;
  }
  input[type=text] {
    flex: 1;
    min-width: 0;
    padding: 11px 15px;
    border-radius: 22px;
    border: 1px solid #3A342E;
    background: var(--ink);
    color: var(--text);
    font-size: 15px;
    outline: none;
  }
  input[type=text]:focus { border-color: var(--accent); }
  input[type=text]:disabled { opacity: 0.6; }
  button {
    padding: 0 20px;
    border-radius: 22px;
    border: none;
    background: var(--accent);
    color: #1B1100;
    font-weight: 700;
    font-size: 14px;
    cursor: pointer;
    transition: opacity 0.15s;
    flex-shrink: 0;
  }
  button:disabled { opacity: 0.45; cursor: default; }
  footer {
    text-align: center;
    padding: 8px 12px;
    font-size: 11.5px;
    color: var(--muted);
    background: var(--surface);
    flex-shrink: 0;
  }
  footer a { color: var(--accent); text-decoration: none; font-weight: 600; }
  footer a:hover { text-decoration: underline; }
  @media (max-width: 420px) {
    header { padding: 12px 14px 10px; }
    header h1 { font-size: 15px; }
    #chat { padding: 12px; }
    .bubble { max-width: 88%; font-size: 14px; }
  }
</style>
</head>
<body>
<header>
  <div class="header-top">
    <h1>Demo AI WhatsApp Admin</h1>
    <span class="sim-badge">Demo Simulation</span>
  </div>
  <p>Data & jawaban di bawah ini simulasi, bukan bisnis/data asli. Coba ceritain bisnis Kakak, lalu chat AI-nya kayak customer beneran.</p>
</header>
<div id="chat"></div>
<form id="chat-form">
  <input type="text" id="msg" placeholder="Ketik pesan..." autocomplete="off" required maxlength="1000">
  <button type="submit" id="send-btn">Kirim</button>
</form>
<footer>Mau AI Admin kayak gini buat bisnis kamu? <a href="__OWNER_WA_LINK__" target="_blank" rel="noopener">Chat tim Kilas Works</a></footer>
<script>
  const GREETING = "__DEMO_GREETING_JS__";
  const sessionId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());
  const chatEl = document.getElementById("chat");
  const formEl = document.getElementById("chat-form");
  const inputEl = document.getElementById("msg");
  const sendBtn = document.getElementById("send-btn");
  let isSending = false;

  function addBubble(text, who, isError) {
    const div = document.createElement("div");
    div.className = "bubble " + who + (isError ? " error" : "");
    div.textContent = text;
    chatEl.appendChild(div);
    chatEl.scrollTop = chatEl.scrollHeight;
    return div;
  }

  function clearChat() {
    chatEl.innerHTML = "";
  }

  function setBusy(busy) {
    isSending = busy;
    inputEl.disabled = busy;
    sendBtn.disabled = busy;
  }

  addBubble(GREETING, "bot");

  formEl.addEventListener("submit", async function (e) {
    e.preventDefault();
    if (isSending) return; // cegah double submit kalau user spam Enter/klik
    const text = inputEl.value.trim();
    if (!text) return;
    addBubble(text, "user");
    inputEl.value = "";
    setBusy(true);

    const typingEl = document.createElement("div");
    typingEl.className = "bubble bot typing";
    typingEl.innerHTML = "<span></span><span></span><span></span>";
    chatEl.appendChild(typingEl);
    chatEl.scrollTop = chatEl.scrollHeight;

    try {
      const res = await fetch("/demo/api", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text }),
      });
      const data = await res.json().catch(() => ({}));
      typingEl.remove();
      if (data.reset) {
        clearChat();
        addBubble(data.reply || GREETING, "bot");
      } else if (res.ok && data.reply) {
        addBubble(data.reply, "bot");
      } else {
        addBubble("Maaf, ada gangguan teknis sebentar. Coba kirim ulang pesannya ya.", "bot", true);
      }
    } catch (err) {
      typingEl.remove();
      addBubble("Koneksi lagi bermasalah. Cek internet Kakak dan coba lagi ya.", "bot", true);
    } finally {
      setBusy(false);
      inputEl.focus();
    }
  });
</script>
</body>
</html>"""


@app.route("/demo", methods=["GET"])
def demo_page():
    """Halaman web demo AI Admin — link ini yang dikirim ke calon klien, bisa dipakai berkali-kali
    tanpa perlu setup apa-apa lagi tiap ada prospek baru."""
    # json.dumps buat escape aman (kutip, backslash, dll) sebelum ditempel ke dalam string JS literal,
    # terus buang kutip pembungkusnya karena placeholder-nya sendiri udah di dalam tanda kutip di JS.
    greeting_js_safe = json.dumps(DEMO_GREETING)[1:-1]
    html = DEMO_PAGE_HTML.replace("__OWNER_WA_LINK__", f"https://wa.me/{OWNER_WHATSAPP_NUMBER}")
    html = html.replace("__DEMO_GREETING_JS__", greeting_js_safe)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/demo/api", methods=["POST"])
def demo_api():
    """Endpoint chat buat halaman /demo. Sengaja TERPISAH total dari alur WhatsApp asli (session
    di-memory doang, gak nyentuh DB/nomor WA asli) & dibatasi kuota biar biaya API demo terkontrol,
    berapapun banyaknya calon klien yang nyoba."""
    _demo_reset_daily_if_needed()
    _demo_cleanup_stale_sessions()

    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id", ""))[:100]
    user_message = str(data.get("message", ""))[:1000].strip()

    if not session_id or not user_message:
        return jsonify({"reply": "Sesi tidak valid, coba refresh halaman ya."}), 200

    if demo_daily_usage["messages"] >= DEMO_MAX_MESSAGES_PER_DAY:
        return jsonify({
            "reply": "Kuota demo hari ini sudah penuh. Coba lagi besok, atau langsung chat tim Kilas Works di link bawah ini."
        }), 200

    session = demo_sessions.get(session_id)
    if session is None:
        session = {"history": [], "count": 0, "created_at": _utcnow(), "notified": False}
        demo_sessions[session_id] = session

    # Reset demo ("coba bisnis lain" / "reset demo" / "mulai ulang") — DETERMINISTIC, dicek sebelum
    # panggil AI sama sekali (gak kena kuota/API call), biar selalu konsisten. Cuma reset state demo
    # SESSION INI DOANG (in-memory), sama sekali TIDAK menyentuh database/appointment/customer asli.
    if DEMO_RESET_PATTERN.search(user_message):
        demo_sessions[session_id] = {"history": [], "count": 0, "created_at": _utcnow(), "notified": False}
        return jsonify({"reply": DEMO_GREETING, "reset": True}), 200

    if session["count"] >= DEMO_MAX_MESSAGES_PER_SESSION:
        return jsonify({
            "reply": "Sesi demo ini udah nyampe batas maksimal. Kalau tertarik lanjut, langsung chat tim Kilas Works ya di link bawah."
        }), 200

    session["history"].append({"role": "user", "content": user_message})
    demo_daily_usage["messages"] += 1
    session["count"] += 1

    # Model lama "claude-3-5-haiku-20241022" sudah RETIRED oleh Anthropic (19 Feb 2026) — request ke
    # model itu SELALU gagal sejak tanggal tersebut. Ganti ke pengganti resminya, DAN kasih fallback
    # ke Sonnet (persis pola yang udah dipakai call_claude() buat bot WhatsApp asli) biar demo tetap
    # jalan walau model utamanya lagi bermasalah/rate-limit, bukan cuma diam nyerah kayak sebelumnya.
    model_to_use = MODEL_FAST
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model_to_use,
                "max_tokens": 300,
                "system": DEMO_SYSTEM_PROMPT,
                "messages": session["history"][-20:],
            },
            timeout=30,
        )
        resp.raise_for_status()
        resp_json = resp.json()
        reply_text = resp_json["content"][0]["text"]
        log_ai_usage("demo", model_to_use, resp_json)
    except Exception as e:
        print(f"Demo API error pakai model {model_to_use}: {e}")
        try:
            model_to_use = MODEL_FALLBACK
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model_to_use,
                    "max_tokens": 300,
                    "system": DEMO_SYSTEM_PROMPT,
                    "messages": session["history"][-20:],
                },
                timeout=30,
            )
            resp.raise_for_status()
            resp_json = resp.json()
            reply_text = resp_json["content"][0]["text"]
            log_ai_usage("demo_fallback", model_to_use, resp_json)
        except Exception as e2:
            print(f"Demo API fallback ke Sonnet juga gagal: {e2}")
            reply_text = "Maaf, ada gangguan teknis sebentar. Coba kirim ulang pesannya ya."

    lead_match = TAG_DEMO_LEAD.search(reply_text)
    if lead_match and not session["notified"]:
        session["notified"] = True
        lead_info = lead_match.group(1)
        try:
            send_whatsapp_message(
                OWNER_WHATSAPP_NUMBER,
                f"Ada yang nyoba DEMO AI Admin & keliatan tertarik!\n\n"
                f"Detail: {lead_info}\n\n"
                f"(ini dari halaman web demo, bukan WA asli — follow up manual ya)",
            )
        except Exception as e:
            print("Gagal notif owner soal demo lead:", e)

    clean_reply = TAG_DEMO_LEAD.sub("", reply_text).strip()
    session["history"].append({"role": "assistant", "content": clean_reply})

    return jsonify({"reply": clean_reply}), 200


def _escape_html(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


@app.route("/dashboard", methods=["GET"])
def dashboard():
    """Halaman sederhana buat owner lihat isi semua chat customer + chat sama AI (owner mode).
    Dibuka lewat: https://<domain-render-lu>/dashboard?key=<DASHBOARD_KEY>
    Kalau DATABASE_URL diset, datanya permanen (kesimpen di database). Kalau enggak,
    fallback ke memori server (ilang kalau server restart/sleep).
    """
    key = request.args.get("key", "")
    if not DASHBOARD_KEY or key != DASHBOARD_KEY:
        return "Akses ditolak. Tambahin ?key=... yang bener di URL.", 403

    def render_bubbles(history):
        rows = ""
        for msg in history:
            role = msg.get("role", "")
            content = _escape_html(msg.get("content", ""))
            align = "left" if role == "user" else "right"
            bg = "#e5e5ea" if role == "user" else "#25d366"
            color = "#000" if role == "user" else "#fff"
            rows += (
                f'<div style="text-align:{align};margin:6px 0;">'
                f'<span style="display:inline-block;max-width:70%;padding:8px 12px;'
                f'border-radius:12px;background:{bg};color:{color};white-space:pre-wrap;'
                f'font-size:14px;text-align:left;">{content}</span></div>'
            )
        return rows

    # Kalau database aktif, pakai data dari situ (lengkap, gak ilang pas restart).
    # Kalau enggak, fallback ke data di memori kayak sebelumnya.
    if db_enabled():
        customer_data = load_all_conversations_from_db("customer")
        owner_data = load_all_conversations_from_db("owner")
        db_note = ""
    else:
        customer_data = conversations
        owner_data = owner_conversations
        db_note = (
            '<p style="color:#c00;font-size:13px;">⚠️ Database belum aktif — history ini cuma '
            "sementara di memori server, bakal ilang kalau server restart.</p>"
        )

    sections = db_note

    names_lookup = load_all_customer_names_from_db() if db_enabled() else customer_names

    sections += "<h2>Chat Customer</h2>"
    if not customer_data:
        sections += "<p><i>Belum ada chat customer.</i></p>"
    else:
        for number, history in customer_data.items():
            name = names_lookup.get(number)
            label = f"{_escape_html(name)} — wa.me/{_escape_html(number)}" if name else _escape_html(number)
            pending = " ⏳ <b>(nunggu jawaban owner)</b>" if number in pending_owner_questions else ""
            sections += (
                f'<details style="margin-bottom:14px;border:1px solid #ddd;border-radius:8px;padding:10px;">'
                f'<summary style="cursor:pointer;font-weight:bold;">{label}{pending}'
                f' — {len(history)} pesan</summary>'
                f'<div style="margin-top:10px;">{render_bubbles(history)}</div></details>'
            )

    sections += "<h2>Chat Owner ↔ AI</h2>"
    if not owner_data:
        sections += "<p><i>Belum ada chat owner.</i></p>"
    else:
        for number, history in owner_data.items():
            sections += (
                f'<details open style="margin-bottom:14px;border:1px solid #ddd;border-radius:8px;padding:10px;">'
                f'<summary style="cursor:pointer;font-weight:bold;">{_escape_html(number)}'
                f' — {len(history)} pesan</summary>'
                f'<div style="margin-top:10px;">{render_bubbles(history)}</div></details>'
            )

    html = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Kilas Works — Dashboard Chat</title>
        <meta http-equiv="refresh" content="30">
    </head>
    <body style="font-family:-apple-system,Arial,sans-serif;max-width:700px;margin:20px auto;padding:0 12px;">
        <h1>Kilas Works AI Admin — Dashboard</h1>
        <p style="color:#666;font-size:13px;">Auto-refresh tiap 30 detik.</p>
        {sections}
    </body>
    </html>
    """
    return html, 200


# Init database sekali pas modul ini di-load (baik dijalanin langsung via `python app.py`
# maupun lewat gunicorn di Render), sekalian seed cache nama customer dari database (kalau ada).
# BOOT LOG (voice production bug, cycle 3) — dicetak SATU KALI tiap proses start (baik lewat
# `python app.py` maupun gunicorn di Render). Tujuannya: begitu Render selesai deploy, baris ini
# langsung kelihatan di log tanpa perlu hit endpoint apapun, buat MEMASTIKAN commit yang jalan
# sekarang beneran commit yang baru di-push (bukan build lama yang ke-cache/gagal update). Gak
# pernah nyantumin credential apapun — cuma commit SHA (dari RENDER_GIT_COMMIT bawaan Render) dan
# status konfigurasi voice note (present/absent, BUKAN nilai key-nya).
print(
    f"BOOT: commit={os.environ.get('RENDER_GIT_COMMIT', 'unknown')} "
    f"service={os.environ.get('RENDER_SERVICE_NAME', 'unknown')} "
    f"voice_note_customer={FEATURES.get('voice_note_customer', False)} "
    f"voice_note_owner={FEATURES.get('voice_note_owner', False)} "
    f"transcription_provider={TRANSCRIPTION_PROVIDER} transcription_model={TRANSCRIPTION_MODEL} "
    f"openai_api_key_present={bool((OPENAI_API_KEY or '').strip())}"
)
init_db()
customer_names.update(load_all_customer_names_from_db())
agreed_facts.update(load_all_customer_facts_from_db())
followup_state.update(load_all_followup_state_from_db())
appointments.update(load_all_appointments_from_db())
if appointments:
    _appointment_id_counter = max(appointments.keys())
else:
    _appointment_id_counter = 0


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
