ALTER TABLE kilas_ai_usage ADD COLUMN customer_charge_exempt INTEGER NOT NULL DEFAULT 0 CHECK (customer_charge_exempt IN (0,1));
