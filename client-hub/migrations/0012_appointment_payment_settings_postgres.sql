-- Business Hub V2, Pro tenant parity cycle (Tasks 3/4/5, PostgreSQL dialect). ADDITIVE ONLY.
-- See 0012_appointment_payment_settings_sqlite.sql for the full rationale.
ALTER TABLE business_profiles ADD COLUMN IF NOT EXISTS appointment_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE business_profiles ADD COLUMN IF NOT EXISTS payment_bank_name TEXT;
ALTER TABLE business_profiles ADD COLUMN IF NOT EXISTS payment_account_number TEXT;
ALTER TABLE business_profiles ADD COLUMN IF NOT EXISTS payment_account_name TEXT;
ALTER TABLE business_profiles ADD COLUMN IF NOT EXISTS payment_instructions TEXT;
