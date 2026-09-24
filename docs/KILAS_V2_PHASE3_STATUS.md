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

## Resume — fixture verification
Starting head: `0b6d1fe688d710a096cff1338e24e1ddb8488dbd`.
Phase 2 is accepted as passed per user confirmation and successful CI run `36009442066`.
Read all four requested documents completely. Phase 3 CI run `36009442153`, job `107666042108`,
failed at SQLite fixture setup and the incorrectly shared owner membership; later gates were skipped.
Planned narrow changes: test_kilas_customers.py (import module instead of exposing unittest class;
separate test owners; retain/add read/edit isolation assertions), test_kilas_customers_postgres.py
(seed required WEB channel parents), and this status. Existing Customers implementation retained.
Next: pass SQLite, checkpoint, execute existing isolated CI PostgreSQL/browser gates; review coverage
and exact scope before COMPLETE. No production data, Finance/WhatsApp modifications or deployment.

Fixture milestone: offline `--only test_kilas_customers.py` PASS, exactly 7 Customers tests; no imported Phase 2 unittest class rediscovered. PostgreSQL/browser validation pending CI.
