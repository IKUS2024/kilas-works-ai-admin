# Personal catalog initialization and exact33 operator cleanup — 2026-10-18

This release fixes initialization and delivers an operator-only command. **Production deletion has not been executed. All33 approved rows remain pending authorized Render Shell execution.** No new HTTP endpoint, startup action, data migration, production financial write, credential change, paid API/model/VM call or automatic deletion is added. Translator, sandbox source/configuration and existing Finance accounting are unchanged.

## Proven defect and narrow correction

The old initializer could run superseded v2 before v3 when an older `housing` identity existed, even after v3 had completed but v2 metadata was missing. A synthetic reproduction showed `food.1` change from `Makan di Luar` to the old combined `Restoran / Makanan Cepat Saji`. That would invalidate the reviewed identity of approved ID18482. Fresh initialization also created obsolete scaffolding before retiring it.

Personal Expense now initializes directly into the final11-root/45-child v3 catalog. A completed v3 marker returns before any superseded bootstrap. Partial v3 roots can be reused by their proven immutable identity. Existing v2 records still upgrade directly, preserving obsolete identities/names while performing the previously approved reversible metadata retirement. Fresh Personal Income and Business seeding remain unchanged. Unknown/custom or renamed records are not inferred from their names, merged or deleted. A completed catalog does not recreate rows removed by the exact cleanup or reset deliberate names/icons/order/archive state.

Changed runtime modules: `client-hub/finance_category_catalog.py`, `client-hub/finance_service.py`. New operator files: `client-hub/tools/finance_approved33_cleanup.py` and `finance_approved33_manifest.json`.

## Finite scope and safeguards

Manifest SHA256: **923b4e559633a764209ed951716759d6f9bd170be12909a4ab2687e4bf93e077**. It contains only the reviewed33 IDs and built-in/scope/storage identities; no email, private financial contents, credentials or private backup is committed.

- Business2 / Personal owner2 / branch11:29 category rows.
- Business10 / Personal owner9 / branch23:4 category rows.
- Related deletion counts:33 scoped settings,33 catalog identities,26 preferences,30 hierarchy rows,33 base categories. No transactions/accounts, version journals or audit rows are deleted. No excluded/custom/final row is moved, reclassified or removed.
- Both normal final-v3 initializations are prerequisites. Before initialization the CLI writes a protected snapshot. It invokes only the existing catalog service in the exact two owner/Personal contexts; it does not call account/default-account initialization. Normal authorization and emergency write-disable still apply. Each scope uses its normal atomic service transaction; this stage is separate from the final atomic deletion and can complete one scope before another fails. Its existing version journal records metadata changes. **It does not delete categories.**
- After initialization a new protected snapshot is required. Expected retirement/active-state changes are recorded in that new snapshot, not ignored by apply. Names, raw storage identities, canonical provenance, parent identities, scope/owner association and all33 target IDs must still match the finite manifest. If anything differs, stop for reconciliation; do not broaden the manifest or use the old pre-v3 snapshot.
- Apply verifies that reviewed post-v3 snapshot SHA and exact current metadata still match; zero fresh transaction/split/budget/Bill/installment references, no outside child or shared scope, exact metadata counts and both v3 markers are mandatory. Unexpected category FK schema/cascade or unvalidated constraints stop the operation.
- A bounded transaction locks the category table against concurrent category writes/DDL, both businesses/owners, exact target and retained parent rows and relevant metadata. Target FK row locks prevent a new financial reference racing the zero-ref check.5s lock timeout/30s per-statement timeout, no automatic retry. Unrelated financial activity during protected-hash checks can conservatively abort the operation.
- A fresh exclusive0600 backup in a0700 directory is flushed/fsynced before deletion. Apply requires operator acknowledgment that a protected off-host backup exists: Render `/tmp` is ephemeral and is not durable recovery.
- Only the finite dependent metadata and base rows are deleted, children before the combined parent. Exact row counts plus unchanged financial/account/audit/version and all outside-target category fingerprints are checked before commit. Any failed precommit check rolls everything back. A lost commit acknowledgment reports **unknown**, never false success/zero deletion, and requires read-only reconciliation without replay.
- There is no product Undo. Recovery requires an explicitly reviewed operator restore of the backed-up original IDs/metadata/links in dependency order. The33-row backup does not contain private transaction contents and is not a full database backup. The normal v3 journal describes its separate metadata transition.

## Exact operator procedure (not performed by this agent)

Use the existing authenticated Render service Shell: `https://dashboard.render.com/web/srv-da7ti2psrm7s73dh9i2g`. Existing service environment supplies DATABASE_URL; do not copy, display or change it. No new credentials or database exposure is needed. The source checkout must match this release. From Render Shell:

```sh
cd /opt/render/project/src/client-hub
umask 077
cleanup_backup_dir=$(mktemp -d /tmp/kilas-approved33.XXXXXX)
chmod 700 "$cleanup_backup_dir"
python tools/finance_approved33_cleanup.py initialize --backup-output "$cleanup_backup_dir/before-init.json"
python tools/finance_approved33_cleanup.py snapshot --backup-output "$cleanup_backup_dir/reviewed-post-v3.json"
```

`snapshot` is the **dry-run**: it performs locked validation, writes the fresh backup and prints its SHA256; deleted0. Protect/export both backups off-host through the existing authorized operator workflow and review the post-v3 metadata before continuing. If that cannot be done, stop. Substitute the exact printed digest below only after that review/backup step:

```sh
python tools/finance_approved33_cleanup.py apply \
  --backup-output "$cleanup_backup_dir/execution-backup.json" \
  --reviewed-snapshot "$cleanup_backup_dir/reviewed-post-v3.json" \
  --reviewed-snapshot-sha256 <EXACT_PRINTED_SHA256> \
  --protected-off-host-backup-confirmed
```

`<EXACT_PRINTED_SHA256>` is a placeholder to replace, not a literal shell argument. Preserve the new execution backup off-host too. A failure/partial absence/unknown commit is a stop condition; do not rerun automatically, edit approved IDs, disable checks or alter historical financial data. Successful output must show the exact counts above. These operator commands have been tested through the real CLI against disposable PostgreSQL; actual Render Shell initialization/apply are **not run**.

## Verification and evidence

- **48 focused SQLite/application contracts PASS:** initialization5, existing reference8, purchase plans14, expense entries9, final-package9 and3 Personal canonical/conflict guards. The earlier13-test run is a subset, not additional coverage. Fresh/existingv2/partialv3/older/repeated-after-cleanup lifecycle checks are explicit. Unknown/custom names, historical transactions, IDs and links, archives, splits/reports, receipt/Income contracts and genuine multi-Personal conflict protection are retained.
- **10 native PostgreSQL18 contracts PASS**, synthetic isolated local Docker database only. Real atomic33 commit,5 reference types, provenance/name/scope failures, v3 prerequisite, outside-child denial, unknownFK/cascade, changed snapshot, missing durable-backup acknowledgment, full rollback on postcheck failure, concurrent FK insertion blocked, actual CLI snapshot/apply, no replay and unknown commit acknowledgment. These are58 unique tests total; no production deletion or authenticated UI/physical-device test is implied.
- Disposable official PostgreSQL image digest: `sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873`; the fixture schema models the relevant production FK/reference contracts and uses synthetic metadata, not a full production DB clone. Normal initialization is tested through the actual application SQLite fixture; a full PostgreSQL application initialization is not claimed.
- Logs: `/tmp/kilas-approved33-regression.log`, `/tmp/kilas-approved33-postgres.log`; original failing reproduction `/tmp/kilas-catalog-init-before.log`. No UI changed, so the previous release's browser checks are not counted as newly rerun.
- Protected pre-initialization backup: `/workspace/.finance-cleanup-backups/approved33-fresh-20261018.json`, SHA256 `051066bb4507fa1f9bc2c314b8dbd77f4588c2d45a266c244092787ab2bdd35c`, captured11:59:51UTC/checks12:01:08UTC. Not committed. Old prepared script outside the repository is superseded by this runtime CLI and must not be used.
- Pre-release production read-only checks:69 transactions / `e439175f48160db657b0fe659a92a196`;38 accounts / `6e92d18b2cbaa67f7a05409436e0102b` (whole-row fingerprints ordered by ID). FK schema is the ten known default-NO-ACTION relationships. No production writes were attempted through the read-only connector.

Release identity/LIVE and post-release aggregate/state evidence are recorded separately in `/tmp/kilas-approved33-live-evidence.json` to avoid a documentation-only redeploy. Remaining blocker is an authenticated write-capable **existing Render Shell operator**, with protected backup export. The connector exposes only read-only SQL; no cleanup via it, an added migration or public endpoint is implemented. The data deletion itself is already approved, not awaiting another permission request.
