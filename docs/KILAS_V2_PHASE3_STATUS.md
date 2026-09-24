# Kilas V2 Phase 3 status

Status: CHECKPOINT — core Customers implementation present; verification/tests still pending.

Branch: `feature/kilas-core-v2`.
Checkpoint head inspected: `6dc8f4c1c303cb6130dd5cce89d851813ed9ca1c`.

## Phase 2 prerequisite
Phase 2 implementation is complete and the latest full QA run observed by Sol passed:
- GitHub Actions run `36008092809`
- Phase 1 regression: PASS
- Phase 2 SQLite focused regression: PASS
- existing Inbox/tenant regressions on disposable SQLite: PASS
- PostgreSQL 18 migration/runtime validation: PASS
- Chromium mobile browser QA: PASS
- no production deploy performed

A pre-existing syntax bug in `0053_kilas_order_catalog_sqlite.sql` was corrected without changing its data semantics so fresh disposable SQLite regression fixtures can initialize.

## Phase 3 completed at this checkpoint
- additive SQLite/PostgreSQL customer schema `0056`
- explicit Phase 3 schema installer
- tenant-scoped Core customer store
- WEB visitor identity -> Core customer resolution
- WEB conversation -> Core customer linkage
- customer activity touch on WEB messages
- owner Customers list/search
- owner Customer detail/edit
- WEB Inbox shows linked customer display name
- Customers entry exposed in Kilas Assist
- Finance customer/accounting tables not reused

## Remaining before COMPLETE
1. Add dedicated Phase 3 tests covering identity isolation, dedupe rules, access control, owner edit, Inbox naming, no Finance/WhatsApp side effects.
2. Add disposable PostgreSQL 0056 runtime validation.
3. Add/extend mobile browser QA for Customers list/detail + linked Inbox.
4. Rerun Phase 1 and Phase 2 regression gates.
5. Verify exact diff, Finance untouched, WhatsApp production untouched, no production deploy.
6. Mark this file COMPLETE and STOP before Phase 4.

Do not start Jobs/Phase 4 automatically.
