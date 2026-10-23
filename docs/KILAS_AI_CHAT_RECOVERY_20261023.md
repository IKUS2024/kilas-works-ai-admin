# Kilas AI Chat recovery — 2026-10-23

Baseline GitHub main and verified live Client Hub: `c542491ae10323d7167a1b4fadb02c3bfd459421`, deploy `dep-dbdgiljncjis73a4jfkg`. The owner authorized fixing all six audited Chat issues through production deployment. Existing dirty checkouts are preserved; implementation uses a separate clean clone and feature branch.

1. Composer keys are bound to the submitted payload. An uncertain identical retry keeps its key; changed text/model/files and terminal completion/failure/cancel get a new key. Server claims bind owner, conversation and a SHA-256 fingerprint in an atomic transaction. A conflicting key cannot replay a different request or dispatch again. Admission rejection before provider dispatch reports a terminal operation so an explicit retry can recover.
2. Stream admission recovers expired streams for the correct owner under the same owner lock used for admission. An independent heartbeat protects a live worker during silent provider periods. No request is automatically regenerated after uncertainty; active streams and other owners remain protected.
3. Thread sends carry prepared scan pages into their first provider context. Stored scan/visual PDFs reconstruct bounded pages from owner-scoped attachment bytes for regeneration/follow-up. Rendering still uses the existing isolated PDF renderer and upload/page/pixel limits; failures explicitly warn against guessing.
4. Relevant visual follow-ups reattach the most recent owned visual upload turn, capped at five files. Unrelated questions do not attach prior image bytes; no cross-owner lookup is added.
5. Conversation context uses a persisted, owner-scoped extractive checkpoint before its recent-turn window. Each request processes at most 1024 old rows in batches and retains at most 3000 characters. Existing long histories catch up incrementally, disclose an unindexed gap, and preserve chronological corrections. No model summarization, unbounded history prompt, transcript logging or invented facts.
6. Interrupted/failed thread answers replay as `incomplete`, never successful `done`. Their partial text remains available with a visible status in the bubble/history; regeneration is explicit. Complete cached answers keep their normal success lifecycle.

The additive `0111_kilas_chat_recovery` migration creates two Chat-only tables for payload fingerprints and bounded context checkpoints. It does not alter/delete existing history or other product tables. PostgreSQL uses the existing checksum/advisory-lock targeted release runner; SQLite appends the migration to the existing local initializer. No quota, pricing, credential, model-selection or external account-action changes.

Validation evidence:
- Ten focused route/state regressions cover all six findings, concurrent claims/stream admission, heartbeat, owner isolation, actual mocked provider image blocks, reconstruction limits, >100 messages and bounded historical backfill, incomplete replay and explicit new operation after failure.
- Node checks cover stable uncertain retries, changed payloads, terminal failure/cancel, models and attachments.
- Chromium at 390/1440 pixels exercises real persisted composer requests: terminal provider failure then identical explicit retry; lost HTTP response after server processing then replay with one provider dispatch; cancellation then a new message; zero page errors/overflow. All provider outputs are synthetic and browser traffic is loopback-only.
- Existing Chat model, preferences, sent attachments, workspace runtime, quality, search and selected artifacts suites are rerun. Linux CI adds native PostgreSQL migration/idempotency and concurrent claims/admission checks, plus the browser and offline regressions.
- Production deploy ID, exact revision, terminal status and health checks must be reported from actual deployment results; this source note does not claim an unperformed deploy.

No paid provider acceptance calls, production submissions, deletion, unrelated Translator/Voice Over/Finance improvements, infrastructure purchases or configuration changes are authorized by this implementation.
