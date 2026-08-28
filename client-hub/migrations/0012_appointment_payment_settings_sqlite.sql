-- Business Hub V2, Pro tenant parity cycle (Tasks 3/4/5, SQLite dialect). ADDITIVE ONLY.
--
-- Adds the small set of columns a tenant needs to self-configure two Pro-only behaviors that were
-- previously only ever backed by KILAS WORKS' OWN hardcoded config (business hours/appointment
-- rules for appointments, PAYMENT_CONFIG's BCA account for payment): an explicit per-tenant
-- appointment-enabled toggle (a business can be on the Pro package, which unlocks the CAPABILITY
-- in feature_flags.FEATURE_MATRIX, but still not want the bot booking appointments for it), and
-- this tenant's OWN payment/bank details for its OWN customers to transfer to (never Kilas Works'
-- BCA account, which remains a completely separate concern handled entirely by the app/checkout
-- flow and untouched by this migration).
--
-- business_profiles already has operating_hours/closed_days/appointment_rules_raw (0001) — those
-- are reused as-is for appointment business hours/notes, so only the genuinely missing fields are
-- added here.
ALTER TABLE business_profiles ADD COLUMN appointment_enabled BOOLEAN NOT NULL DEFAULT 1;
ALTER TABLE business_profiles ADD COLUMN payment_bank_name TEXT;
ALTER TABLE business_profiles ADD COLUMN payment_account_number TEXT;
ALTER TABLE business_profiles ADD COLUMN payment_account_name TEXT;
ALTER TABLE business_profiles ADD COLUMN payment_instructions TEXT;
