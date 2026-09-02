-- White-screen bug fix — "Info Pembayaran -> Simpan & Lanjut -> white screen" (PostgreSQL side —
-- see the _sqlite.sql sibling file for the full root-cause explanation).
--
-- business_profiles.operating_hours was typed JSONB here but SQLite's own schema (and every
-- actual application code path — routes_client.py, business_settings.html, ai_onboarding.py,
-- provisioning.py, tenant_config_service.py) treats it as plain free text. Fix the type to match
-- actual usage.
--
-- WHY "USING (operating_hours #>> '{}')" AND NOT A PLAIN "::text" CAST:
-- A plain `operating_hours::text` cast on a JSONB column returns the JSON SOURCE TEXT, which for
-- a JSON string scalar INCLUDES the surrounding quote characters — e.g. the JSONB value
-- "Senin-Sabtu 09.00-18.00" (a JSON string) would become the 27-character TEXT value
-- '"Senin-Sabtu 09.00-18.00"' (with literal quote characters baked into the string), which is
-- wrong: every template/consumer in this app displays operating_hours as plain text and would
-- show those extra quote characters to a real user. The `#>> '{}'` operator ("get JSON value at
-- this path, as text", with an empty path meaning "the top-level value itself") correctly
-- UNWRAPS a JSON string scalar to its plain, unquoted text content instead. NULL stays NULL
-- either way. In the unlikely event a row somehow holds a non-scalar JSON value (an object/array
-- — never produced by this app's own code per the source audit backing this migration, since the
-- one code path that would json.dumps() a dict/list into this column is dead/never invoked in
-- practice), `#>> '{}'` falls back to that value's own JSON text representation, which is a
-- reasonable, non-destructive outcome for a case that shouldn't occur.
--
-- IDEMPOTENT / SAFE TO RE-RUN: wrapped in a DO block that only runs the ALTER when the column is
-- still 'jsonb' — the `#>>` operator only applies to a jsonb column, so re-running this migration
-- after the column has already been converted to text (e.g. if scripts/run_migrations.py is ever
-- run twice, or a future boot has RUN_MIGRATIONS_ON_BOOT=true) would otherwise fail with
-- "operator does not exist: text #>> unknown". This check makes it a true no-op on every run
-- after the first, matching the "safe to re-run" contract every other migration in this folder
-- already has (see db.py's own MIGRATIONS list comment).
--
-- LOSSLESS FOR EXISTING DATA: this ALTER COLUMN never drops, renames, or removes the column, and
-- the USING expression above preserves every existing row's actual text content (unwrapped, not
-- discarded) — the only rows affected are ones that hold a value at all; NULL/empty rows are
-- unaffected either way.
DO $$
BEGIN
    IF (
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'business_profiles' AND column_name = 'operating_hours'
    ) = 'jsonb' THEN
        ALTER TABLE business_profiles
            ALTER COLUMN operating_hours TYPE TEXT USING (operating_hours #>> '{}');
    END IF;
END $$;
