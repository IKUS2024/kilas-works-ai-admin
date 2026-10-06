# Kilas Trading managed implementation — 2026-10-06

## Reconciliation and source

Remote main and Render Client Hub LIVE baseline: `7ea4ac552e19e4b961bf6341993fcfa72b18b5ca`, deploy `dep-db1tin0u01pc73fvm220`. Existing target: `srv-da7ti2psrm7s73dh9i2g`, root `client-hub`, workspace `tea-da34t2gu01pc73ft7uf0`; autoDeploy off. Read-only production query verified exactly one pilot user and matching Google identity. No credentials retrieved.

Old task source was NOT recovered: absent local files/Git objects, GitHub HTTP422 for foundation/final commits, no Trader remote ref. One final Library search returned unrelated reports/screenshots, no usable source/bundle. Continuation explicitly authorized a minimal new in-app implementation. Historical 45/52 tests do not apply.

## Foundation checkpoint (local, not deployed)

- Existing Kilas Services entry now opens `/products/services`, retaining legacy catalog and WhatsApp consultation links. Pilot-only Trading card opens `/products/services/trading`.
- Current stored email must exactly match `irvankarnavi@gmail.com` and have a matching Google OAuth identity, established through the existing verified-email login flow. Other owners/admins and support sessions are denied server-side. No session policy changes.
- Four isolated additive Trader tables including migration checksum tracker; transactions lock only the Trader account. No Finance ledger/table writes, existing balance integration, credential access, model calls or broker calls.
- Deterministic synthetic replay, fresh-snapshot enforcement, paper BUY/SELL, mandatory SL/TP, tighten-only protective edits, close/P&L, conservative stop-first gap settlement, configurable trailing, per-trade risk/exposure/daily loss limits, pause and locked kill switch, unique request fingerprints, per-candle strategy dedup, persistent journals.
- Truthful activity panel: idle/paused/error persisted; processing only while browser request is pending. Source/replay time/snapshot timestamp displayed. No fake development or background activity.
- Foundation tests: 23 SQLite tests PASS; same 23 native PostgreSQL 18 tests PASS with additive/idempotence and old-table readback; real Chromium login→Service→Trading and operations PASS at 1440/768/390/320. Browser wait race and PostgreSQL test cleanup were fixed in test harness. Scoped visual inspection found inherited dark form styles; corrected only within `.trading` for the established light world. Final confirmation will cover subsequent risk additions.

Next stage: owner clarified bounded paper autonomy, modeled costs/spread, stop-derived sizing, aggregate stop risk and losing-streak cooldown, breakeven/profit protection. These are not yet claimed in this foundation checkpoint. No main push/deploy has occurred.

## Release and rollback plan

Only existing Client Hub may deploy after relevant checks/CI. Recheck fresh main before publishing; no force push. `KILAS_TRADING_ENABLED=false` denies Trader routes and removes its pilot card, while preserving Service catalog/data. Apply ONLY 0087 via `KILAS_TRADING_SCHEMA_APPLY=true` for one release, then return it to false. Never enable historical migrations. Trader schema is additive and retained for old-code rollback; previous LIVE SHA above is the code rollback point. No separate DB/resource/site/DNS changes.
