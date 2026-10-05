# Audio result persistence incident — 2026-10-05

Production job 19: 45.696-second video dubbing. Provider output reached result settlement, but PostgreSQL backend was killed by signal 9 repeatedly during the large BYTEA UPDATE; database entered recovery and status GET returned 500. The database plan is basic_256mb. Memory exhaustion from psycopg2's expanded binary literal is the suspected mechanism, consistent with the repeated save-stage crashes; no provider resubmission occurred in investigation.

Read-only production accounting: PROCESSING, seconds_charged=0, reserved_seconds=0, no result. No Kilas Audio debit for this job. Any ElevenLabs credit charge is separate.

Narrow fix: PostgreSQL results larger than 512 KiB are saved in bounded statements inside the existing settlement transaction. Result, final status and debit commit atomically. No schema/config/provider/Finance changes. Regression test uses a 14 MiB synthetic result, checks bounded parameters, interrupted-save rollback, exact output bytes and idempotent settlement. Local focused Audio tests: 40 PASS. CI and same-job production recovery pending.
