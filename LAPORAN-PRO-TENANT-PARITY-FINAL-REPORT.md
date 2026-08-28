# KILAS WORKS BUSINESS HUB V2 — PRO TENANT PARITY FINAL REPORT

Pro owner assistant parity: DONE. A Pro client tenant's own recognized owner (that tenant's `trusted_owner_phone`) now gets the same category of natural, conversational assistant experience Kilas Works' own owner already has — implemented via `call_tenant_owner_ai()` / `build_tenant_owner_system_prompt()` / `_build_tenant_owner_query_context()` in `app.py`, with its own scoped conversation history (`tenant_owner_conversations`, keyed by `_ck(tenant_id, owner_phone)`), gated on the Pro-only `owner_commands` feature flag.

Basic owner gating: DONE. A Basic tenant's owner is still recognized as the owner (the `_tenant_owner_phone == from_number` check fires regardless of tier) but is denied the Task-1 assistant when `owner_commands` is `False` in that tenant's feature set, and receives a natural, non-technical WhatsApp reply ("Fitur asisten owner lewat chat ini baru tersedia di paket AI Admin Pro ya Kak...") rather than silence or internal wording.

Pro appointment runtime: DONE. Booking/reschedule/cancel for a resolved client tenant is handled entirely by `build_tenant_appointment_context()` and `_get_tenant_appointment_settings_safe()`, using that tenant's OWN `business_hours_raw`/`closed_days`/`appointment_rules`, gated on `appointment` (Pro-only) AND that tenant's own `meeting_enabled` toggle, state scoped by `_ck(tenant_id, from_number)` into `tenant_meeting_requests` — completely separate from Kilas Works' own `meeting_requests`/slot-grid engine.

Pro tenant payment runtime: DONE. `[GIVE_PAYMENT_INFO]` for a non-Kilas tenant is resolved via `_get_tenant_payment_config_safe()` + `build_tenant_payment_info_text()`, gated on the Pro-only `payment_conversation` flag; confirmed this path can never read or emit Kilas Works' own `PAYMENT_CONFIG`/BCA account, and a Basic or unconfigured Pro tenant gets a natural "ask the business directly" fallback line instead.

Tenant onboarding operational settings: DONE. New `client-hub/templates/business_settings.html` screen plus `wizard.html`/`review.html` updates let a tenant configure its own appointment and payment settings during onboarding, backed by `client-hub/tenant_config_service.py` additions and new migrations `0012_appointment_payment_settings_{postgres,sqlite}.sql`.

Request-scoped channel cleanup: DONE (real bug fixed). `_set_active_whatsapp_channel()`/`_clear_active_whatsapp_channel()` (thread-local) are now wrapped so `_clear_active_whatsapp_channel()` runs unconditionally in a `finally` around `_webhook_body_impl()` inside `receive_webhook()` — previously a tenant channel picked for one request could leak into the next request served by the same reused worker thread (another tenant, Kilas Works' own webhook, or the internal owner-notify endpoint).

Unknown Phone Number ID fail-closed: DONE. `_resolve_tenant_or_unknown()` returns a tri-state result — Kilas Works' own number `(None, False)`, a real active tenant `(tenant_id, False)`, or genuinely unknown/lookup-failed `(None, True)`. The webhook checks `is_unknown` explicitly and, when true, logs a warning and returns `200` with no reply sent and no processing — it never falls back to treating the message as Kilas Works traffic, including when the Client Hub DB lookup itself raises.

Owner phone collision safety: DONE. Kilas Works' own `OWNER_WHATSAPP_NUMBER` branch now requires `is_kilas_platform_tenant(tenant_id)` in addition to the phone match, so a client tenant whose own `trusted_owner_phone` happens to equal Kilas Works' personal owner number can never hijack Kilas Works' own rich owner mode — owner identity is decided by (channel the message arrived on) + (phone), never phone alone.

Credential architecture: Documented design — Kilas Works operates every tenant's WhatsApp number under one Meta Business/WABA "Portfolio", so a single system-user access token is shared across all Phone Number IDs; each tenant's Client Hub row stores only its own `phone_number_id` (never a duplicated/separate token), and `_get_tenant_whatsapp_channel_safe()` pairs that `phone_number_id` with the one shared token at send time. This is a documented assumption, not something verified against a live Meta account from this sandbox (see Known limitations).

Render-per-client env required: NO — under the shared-credential design above, onboarding a new tenant requires recording only its `phone_number_id` in Client Hub; it does not require any new Render environment variable per client.

Tenant history isolation: DONE — every per-customer memory/state dict (`conversations`, `customer_names`, `customer_language`) is keyed via `_ck(tenant_id, phone)`, never the bare phone number, so the same phone number messaging two different tenants (or a tenant and Kilas Works itself) never shares a conversation.

Tenant appointment isolation: DONE — `tenant_meeting_requests` is keyed by `_ck(tenant_id, phone)`, entirely separate from Kilas Works' own `meeting_requests`/`appointments` tables and engine.

Tenant payment isolation: DONE — tenant payment info is sourced only from `_get_tenant_payment_config_safe(tenant_id)`; the Kilas-Works-only `is_kilas_tenant` branch is the only code path that can ever reference `PAYMENT_CONFIG`.

Human takeover isolation: DONE — `_get_conversation_mode_safe(tenant_id, from_number)` is tenant-scoped; `tenant_id` is always `None` for Kilas Works' own number, so this is a total no-op for existing production traffic while giving each tenant its own takeover state.

Basic feature enforcement: DONE — every Pro-only capability (owner assistant, appointment, payment_conversation, image_understanding, voice_note, advanced_history, lead_qualification) is checked per-request against `_get_tenant_features_safe(tenant_id)` (backed by `feature_flags.FEATURE_MATRIX`), not inferred from prompt wording.

Pro feature enforcement: DONE — `FEATURE_MATRIX["AI_ADMIN_PRO"]` enables all of the above; runtime checks are AND'd with the global `ENABLE_MULTI_TENANT` flag and `tenant_id is not None`, so behavior for Kilas Works' own number is unchanged.

Kilas platform owner isolation: DONE — `is_kilas_platform_tenant(tenant_id)` gates every Kilas-Works-only code path (own catalog/pricing, own PAYMENT_CONFIG, own appointment slot-grid, own sales/follow-up engine, own OWNER_WHATSAPP_NUMBER branch).

Existing owner notifications: unchanged this cycle — `_get_tenant_owner_notify_target_safe()` continues to route a client tenant's day-to-day customer-service notifications only to that tenant's own `trusted_owner_phone`, never Kilas Works' own owner.

Existing live catalog: unchanged this cycle — `_build_tenant_context_block_safe()` continues to source a resolved tenant's own catalog from `tenant_config_service.get_tenant_config()`, never Kilas Works' own `service_catalog` table.

Existing payment gate: unchanged this cycle — the Basic/Pro gate on `payment_conversation` predates this cycle's work; this cycle extended it to also require the tenant's own payment config actually being populated (`build_tenant_payment_info_text` returns `None` when bank/account fields are missing).

Security: no new secrets introduced; `INTERNAL_SERVICE_SECRET` continues to gate the internal owner-notify endpoint; no credential values appear anywhere in this diff (see Secret scan below).

Migration: two new additive migrations, `client-hub/migrations/0012_appointment_payment_settings_postgres.sql` and `..._sqlite.sql`, adding appointment/payment settings columns; no destructive statements (no DROP/ALTER...DROP), consistent with every prior migration in this repo.

Root tests: 18 files, 231 test cases (per-`def test_*` count, plus `test_appointment_reminders.py`/`test_demo_ux.py`/`test_production_hardening.py`, which use inline `Test N` assertion blocks instead of `def test_*` — counted from their `print("Test N ...")` markers: 5 + 6 + 6 = 17), all passing (`python3 test_*.py`, exit 0 for every file).

Client Hub tests: 10 files under `client-hub/tests/`, 189 `def test_*` functions, all passing when run with cwd `client-hub/` (`cd client-hub && python3 tests/test_*.py`) — this is the suite's documented invocation convention (each file's own docstring), not a bug; running from inside `tests/` itself fails on a relative `open("routes_client.py")` check, which is expected per that test's own working-directory assumption.

Postgres smoke: `client-hub/scripts/postgres_smoke_test.py` and `postgres_smoke_test_v2.py` each run twice, all four runs exit 0. No `DATABASE_URL` is reachable from this sandbox — a local PostgreSQL 16 server was started for a real end-to-end connection check, but no `psycopg2`/`psycopg` driver and no package index are reachable here to install one, so all four runs exercised the scripts' documented SQLite dry-run fallback path (each prints an explicit WARNING that this is not a PostgreSQL validation). This is the scripts' own designed behavior, not a workaround introduced this cycle.

Total tests: 231 (root) + 189 (client-hub) = 420 distinct test functions/cases, all passing, plus 4/4 passing postgres-smoke-script runs (SQLite dry-run path).

Secret scan: clean. `git ls-files | grep -E '\.(log)$|__pycache__|\.pytest_cache|shot_.*\.png|\.env$|\.env\.[^e]'` returned nothing tracked. Grepped the working tree for `WHATSAPP_ACCESS_TOKEN=`, `ANTHROPIC_API_KEY=`, `DATABASE_URL=`, `SECRET_KEY=`, `INTERNAL_SERVICE_SECRET=`, `DASHBOARD_KEY=`, `CRON_SECRET=`, `credentials_reference=` followed by a real value — every hit was either an empty `client-hub/.env.example` line, `os.environ.get(...)` code, a documentation mention, or an obvious test-fixture placeholder (`test_pro_tenant_parity.py`'s `appmod.INTERNAL_SERVICE_SECRET = "test-internal-secret"`). No real assigned secret value anywhere.

REAL GITHUB MAIN SYNC VERIFIED: NO
Reason: this sandboxed environment has no `origin` git remote configured (`git remote -v` returns empty) — there is no real GitHub main reachable from here to diff against. The local `master` branch is present and is a git ancestor of `business-hub-v2` (`git merge-base --is-ancestor master business-hub-v2` succeeds), which is supporting local context only, not a GitHub sync check. A final reviewer must diff this ZIP against the actual GitHub main separately, outside this sandbox.

Final commit: b95518c97970d3c2104b7fc5c60f76aeb86f5f0f (short: b95518c), branch `business-hub-v2`. This is the code commit the ZIP below is archived from; a small follow-up docs commit adds this report file on top of it.

ZIP filename: kilas-works-business-hub-v2-b95518c-pro-tenant-parity-final.zip

SHA256: 1cc2a949b97c85ccc96769f7e8f0c306734c8ce105e0fb7e5b052b8f444aafc1

File count: 145 files (per `unzip -l <zip> | tail -1`)

Known limitations:
- No live Meta Graph API is reachable from this sandbox, so the shared-credential/multi-Phone-Number-ID assumption described in "Credential architecture" is a documented design assumption based on Meta's standard WABA/Business Portfolio model (one system-user token valid across every Phone Number ID under the same Business/WABA), not independently verified against a live Meta account from here.
- No live PostgreSQL (Render) database is reachable from this sandbox and no `psycopg2`/`psycopg` driver could be installed (no package index reachable), so both smoke scripts only exercised their SQLite dry-run fallback path this cycle, not a real Postgres round-trip.
- The Pro tenant owner assistant (Task 1) only handles `msg_type == "text"` from the owner this cycle; image/audio from a tenant owner gets a plain "I can only read text for now" acknowledgement rather than vision/transcription support.
- Kilas Works' own automatic follow-up/lead-scoring engine (`followup_state`/`lead_stage`) remains intentionally not tenant-aware; client tenant customers are never enrolled in it (a deliberate scope decision from the prior cycle, unchanged here), rather than half-building a tenant-aware version.
- `git status`/local testing left one harmless untracked SQLite dev DB file (`client-hub/client_hub_dev.db`, already `.gitignore`d) with smoke-test rows created and cleaned up during this session's own test runs; nothing from this ever entered git.

Meta production assumptions: this bridge assumes every tenant's WhatsApp Business number lives under the SAME Meta Business Portfolio/WABA as Kilas Works' own number, so ONE system-user access token (`WHATSAPP_ACCESS_TOKEN`) is valid for sending/receiving on every tenant's own `phone_number_id` — onboarding a new tenant is expected to require recording only that tenant's `phone_number_id`, never a second Render env var or a second token. Before relying on this in production, manually verify: (1) a real send call succeeds using the shared token against a newly-added tenant's actual `phone_number_id` (not just Kilas Works' own), (2) the token's granted permissions/scopes cover every tenant number added so far, and (3) Meta's webhook subscription for each tenant's number is actually pointed at this same app/callback URL so inbound messages for that number reach this webhook at all.

External validation still required: a live Meta Graph API smoke test (send + receive) against at least one real non-Kilas tenant Phone Number ID using the shared token; a real PostgreSQL round-trip of both smoke scripts against the actual Render database; a manual diff of this ZIP against the real GitHub main branch, since no `origin` remote exists in this sandbox.

Required Render env vars: `SECRET_KEY`, `ANTHROPIC_API_KEY`, `DATABASE_URL` (Client Hub service), `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `OWNER_WHATSAPP_NUMBER` (main bot service), `KILAS_BOT_INTERNAL_URL` + `INTERNAL_SERVICE_SECRET` (shared between both services, same value on each side), `CLIENT_HUB_ENV=production` (Client Hub), `TRANSCRIPTION_PROVIDER`/model-related vars if voice notes are enabled. No additional per-tenant Render env var is required under the shared-credential design (see above) — new tenants are onboarded purely through Client Hub data (their own `phone_number_id`, config, and feature package).

Exact production deploy sequence: (1) apply new migrations `0012_appointment_payment_settings_postgres.sql` against the Render Postgres database (idempotent/additive, no destructive statements); (2) deploy the updated Client Hub service (new `business_settings.html`, `tenant_config_service.py`, `provisioning.py`, `repo.py`, `routes_admin.py`, `routes_client.py` changes); (3) deploy the updated main bot service (`app.py`); (4) smoke-test by messaging from a known Pro tenant's configured owner phone ("test owner query") and a known Pro tenant's customer number (booking + payment questions) against the live webhook before enabling for real customers; (5) run `client-hub/scripts/postgres_smoke_test.py` and `postgres_smoke_test_v2.py` by hand against the live `DATABASE_URL` immediately after deploy, per their own docstrings.

READY FOR FINAL EXTERNAL AUDIT: YES

## Manual trace summary (Part A)

1. Owner asks about customer Budi (Pro coffee shop): webhook -> `_resolve_tenant_or_unknown(phone_number_id)` resolves the coffee shop's `tenant_id` -> `_set_active_whatsapp_channel()` activates that tenant's own channel -> `_get_trusted_owner_phone_safe(tenant_id)` matches `from_number`, recognizing this sender as that tenant's own owner (not a customer) -> `_get_tenant_features_safe(tenant_id).get("owner_commands")` confirms Pro -> `_wa_bridge.classify_owner_message()` classifies it `OWNER_QUERY` -> `call_tenant_owner_ai()` builds the prompt via `build_tenant_owner_system_prompt()` / `_build_tenant_owner_query_context()`, which pulls Budi's history from `conversations[_ck(tenant_id, budi_phone)]` (tenant-scoped only) -> reply sent with `send_whatsapp_message(from_number, reply_text)` over the tenant's own active channel.

2. Salon customer books 3pm tomorrow (Pro): webhook -> `_resolve_tenant_or_unknown` resolves the salon's `tenant_id` and activates its channel -> not the owner, so falls through to the normal customer path -> `_build_tenant_context_block_safe(tenant_id)` injects `build_tenant_appointment_context(_get_tenant_appointment_settings_safe(tenant_id))` (that salon's own business hours) into the prompt -> Claude replies with a `[MEETING_PREFERENCE: ...]` tag -> gated by `_get_tenant_features_safe(tenant_id).get("appointment")` AND `meeting_enabled` -> state written to `tenant_meeting_requests[_ck(tenant_id, from_number)]` -> confirmation sent via `send_whatsapp_message()` on the salon's own active channel.

3. Client-services customer asks where to transfer (Pro): webhook resolves that tenant, activates its channel -> customer path -> Claude emits `[GIVE_PAYMENT_INFO]` -> `is_kilas_tenant` is `False`, so the non-Kilas branch runs: `_get_tenant_features_safe(tenant_id).get("payment_conversation")` gates it, `_get_tenant_payment_config_safe(tenant_id)` + `build_tenant_payment_info_text()` render THAT tenant's own bank/account fields (never `PAYMENT_CONFIG`/Kilas's BCA account) -> reply sent on that tenant's own active channel.

4. Basic tenant owner says "please reply to the earlier customer": webhook resolves the Basic tenant -> `_tenant_owner_phone == from_number` still recognizes them as the owner -> `_get_tenant_features_safe(tenant_id).get("owner_commands")` is `False` (Basic) -> the rich relay/`_resolve_tenant_owner_relay_target` path is skipped entirely -> owner receives the fixed natural-language decline: "Fitur asisten owner lewat chat ini baru tersedia di paket AI Admin Pro ya Kak — silakan hubungi tim Kilas Works kalau mau upgrade." via `send_whatsapp_message()`.

5. Message on an unrecognized Phone Number ID: webhook -> `_resolve_tenant_or_unknown(phone_number_id)` finds no match against `WHATSAPP_PHONE_NUMBER_ID` and no active tenant row (or the lookup itself raises) -> returns `(None, True)` -> `_webhook_body_impl` logs `"WARNING: webhook phone_number_id=... tidak dikenali..."` and returns `jsonify({"status": "ok", "unknown_phone_number_id": True}), 200` immediately — no tenant/Kilas fallback, no `send_whatsapp_message` call anywhere on this path, only the internal log line.
