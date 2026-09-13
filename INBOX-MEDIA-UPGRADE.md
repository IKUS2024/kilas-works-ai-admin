# Inbox media upgrade

Baseline: `01d71337ab2bc2b052e763f2d19073a09d4d2013` on production main.

## Included
- Inbound customer image (JPEG/PNG), video (MP4/3GP), audio/voice note (AAC/MP4/MPEG/AMR/OGG), document and WebP sticker metadata, in platform and tenant Inboxes.
- Images/stickers preview inline, audio/video have native players, documents download through authenticated routes. Captions, time and message direction remain in the existing bubbles. Text markup remains unchanged.
- Human outbound JPEG/PNG (5 MiB maximum) and PDF (10 MiB maximum), with takeover and service-window checks before upload and again before send. No automatic retry, template changes or outbound audio/video/sticker sending.
- Safe unavailable response for expired, unsupported or failed downloads. Supported documents: PDF, TXT, DOC/DOCX, XLS/XLSX, PPT/PPTX. Downloads are capped at 32 MiB; larger inbound events remain in history but cannot be opened here.

## Storage and authorization
Migration 0023 adds `inbox_media`; no existing history is rewritten. Each media event has a scoped unique event key and links to one regular message row. Metadata and its message row are written in one transaction. Captions/transcripts reuse that row; no binary or private media URL is stored in the database or added to AI prompts.

Media bytes are fetched on demand into a temporary spool (1 MiB in RAM, larger files temporary disk) and discarded after serving. There is no permanent media archive or persistent cache. A fresh Meta URL is obtained for each download; expired/deleted Meta media cannot be recovered by this patch. Access is checked on every request, responses are private/no-store, documents are attachments, redirects and arbitrary URL destinations are rejected.

Platform traffic uses authenticated Client Hub -> bot routes `/internal/platform-inbox-media` and `/internal/platform-inbox-media/<key>` and the bot's platform credentials. These URLs use the same configured bot origin as existing manual text replies. Tenant traffic uses the existing tenant channel resolver and membership authorization. Internal media routes never accept a tenant scope supplied by the caller.

## Deployment
1. Upload the ZIP contents at the repository root, preserving all paths. Review against the baseline before replacing files if main has advanced.
2. Install the updated root requirements (Pillow is now explicit); the Client Hub already declares Pillow.
3. Before the new bot receives media, apply migration 0023 to the SAME PostgreSQL database used by both services: `python client-hub/scripts/run_migrations.py`. The existing runner is idempotent. If using the existing Render boot-migration option instead, set `RUN_MIGRATIONS_ON_BOOT=true` on Client Hub for the migration deploy, then restore its previous setting. Do not start the updated bot before the migration completes.
4. Deploy both bot and Client Hub from the uploaded revision. No new required ENV keys, bucket, shared disk or Redis are needed. Existing bridge URL/secret and tenant credential references must remain configured.
5. No new WhatsApp template or webhook field is required: media uses the existing messages webhook and existing WhatsApp messaging credentials. Live token permissions and Meta delivery were not tested from this workspace.
6. On a test conversation: send an image, voice note and PDF; open them from the correct Inbox; take over and send one image/PDF while the customer-service window is open. Confirm the other tenant cannot open that media. Return to AI when done.

## Validation scope
Focused local suites only: new media service/UI/authorization tests, new real Flask webhook/bridge tests, existing Inbox unification, existing Platform Takeover and manual-reply diagnostic tests. Meta/bridge network operations are mocked. SQLite persistence and migration idempotency are tested; the PostgreSQL migration uses portable CREATE TABLE/INDEX and PostgreSQL-compatible transaction SQL, but no live PostgreSQL or Render deployment was exercised.

## Changed files / ZIP manifest
- app.py
- client-hub/db.py
- client-hub/inbox_service.py
- client-hub/platform_inbox_service.py
- client-hub/routes_admin.py
- client-hub/routes_client.py
- client-hub/templates/inbox.html
- client-hub/templates/platform_inbox.html
- requirements.txt
- client-hub/inbox_media_service.py
- client-hub/migrations/0023_inbox_media_postgres.sql
- client-hub/migrations/0023_inbox_media_sqlite.sql
- client-hub/templates/_inbox_media.html
- client-hub/tests/test_inbox_media.py
- test_inbox_media_webhook.py
- INBOX-MEDIA-UPGRADE.md
