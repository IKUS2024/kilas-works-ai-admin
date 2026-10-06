# Offline market-observation checkpoint — 2026-10-06

## Scope and recovered baseline

Continued the same saved executor; no additional worker/environment, broker call, paid inference or upload. Inspected the existing analyst and pilot-gated routes first. Remote main was `5a448b98e54bf6ba6bc5e4a9b134b348c2f286ee`; local checkout fast-forwarded to it without overwriting changes. Existing production code remains `f5a40445c0ca9cb988b705c24b68aae75e213af4`, deploy `dep-db2bi34s728c73bs2bj0`. This phase is offline only: no main push, deployment, activation or production data mutation.

Parent reports the existing Windows/XM DEMO GOLD ticks advance but raw epochs are about three hours ahead of independently verified UTC. That is reported context, not verified by this executor and not justification for subtracting three hours. No real sample or account data was copied into this checkpoint.

## Minimal changes

`observation.py` validates TEST_FIXTURE-only market fields: `kind`, `source_symbol`, decimal-string `bid`/`ask`, integer raw `time`/`time_msc`, and timezone-explicit `observed_at_utc`. It rejects extra fields (including account IDs, balances, positions, credentials and capability/freshness claims), malformed/nonfinite prices, inconsistent seconds/milliseconds and non-UTC receipt timestamps. It preserves the raw epochs; no offset, epoch-to-UTC event conversion or receipt-age calculation exists.

Server-owned output always has `event_time_utc=null`, `source_time_status=unverified`, `freshness=unknown`, `ai_analysis=false`, `paper_execution=false`, and `ingestion_enabled=false`. `canonical_symbol=null` and `mapping_status=unknown` remain even for a source spelling XAUUSD; GOLD is not silently aliased. Observation fields cannot enter action endpoints. Existing analyst strict validation also rejects the observation shape. Synthetic replay continues independently and never consumes these observations.

No ingestion endpoint, transport, persistent table, source adapter or scheduler was added. Fixtures are injected only in Flask TESTING mode. Production ignores fixture configuration and direct fixture validation fails outside testing. The scoped dashboard panel shows UNAVAILABLE by default; local fixture mode labels synthetic data, unknown freshness/mapping, raw times and null event time. There are no upload/analysis/order controls on this panel. Existing UI, authentication, Finance and USD5 Sol analyst budget policy were preserved.

## Verification and deliverables

- Eight observation tests PASS: ambiguous future raw epoch unchanged; receipt time never establishes freshness; no symbol alias; private/capability fields rejected; invalid prices/clocks/nonfixture sources rejected; production ignores fixtures; observations rejected by analyst/order routes without orders/provider calls; pilot-only rendered UI and missing/rejected states.
- Original paper 38 and analyst 17 tests PASS: 63 local tests total. Outbound provider HTTP is forbidden by fixtures.
- Local Chromium PASS: existing functional paper entry/protection/pause/resume/no-signal/replay/close/risk/journal at widths 1440/768/390/320; fixture panel at 1440/320 with expanded raw-time details, no overflow/page errors, AI disabled.
- Screenshots: `/tmp/kilas-trading-browser/observation-fixture-1440.png` and `observation-fixture-320.png`; test logs `/tmp/kilas-observation-{tests,paper,analysis,browser}.log`.
- `git diff --check` PASS. No new PostgreSQL or production acceptance run in this offline phase; no schema/storage/transaction implementation changed. Existing PostgreSQL acceptance from the prior release remains separate evidence.

## Exact next handoff and approvals

1. Obtain explicit approval to transfer **market observations only** from the user's existing XM DEMO terminal to the existing Kilas app: allowlisted GOLD bid/ask, raw `time`/`time_msc`, UTC observation receipt time, and a reviewed source label. Exclude terminal/account identifiers, balances, positions, credentials and logs containing those values. Decide bounded manual sampling and retention before actual transfer. No upload is authorized by this checkpoint.
2. Review the destination and authentication design on the existing app: HTTPS, existing verified pilot authorization, CSRF/replay/body-size/rate boundaries, and server-owned capability state. No endpoint or grant/token exists for an exporter yet; do not create credentials, expose an unauthenticated listener or paste secrets into chat. Any new credential/grant setup needs explicit approval. Existing login does not automatically authorize a background Windows exporter.
3. Resolve source clock semantics with authoritative terminal/server encoding and DST evidence. Preserve original evidence and separately record a reviewed normalization rule, its source, validity period and failure behavior before assigning UTC event time. Receipt time or a moving raw tick alone is insufficient. Until then real observations, if later approved, must remain observation-only with unknown freshness and blocked AI/paper execution.
4. Verify GOLD instrument identity/quote currency/unit/contract metadata against the existing DEMO source and authoritative XM specification before mapping to canonical XAUUSD. A symbol string or price resemblance is insufficient. Mapping remains unknown here.
5. Separately approve production integration/activation after the secure observation handoff review. AI and execution require additional valid source-time/freshness/mapping evidence and existing model/budget gates. There is no reason to activate inference or purchase a VPS merely to complete this offline milestone.

No auth timeout changes or remembered-device implementation were included. This offline code can be reverted without data cleanup; no production rollback action is required.
