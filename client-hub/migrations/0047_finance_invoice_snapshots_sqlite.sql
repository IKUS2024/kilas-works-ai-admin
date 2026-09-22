-- Invoice-only identity snapshots, branch defaults and private revision history.
ALTER TABLE finance_invoices ADD COLUMN document_snapshot TEXT;
ALTER TABLE finance_invoices ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
CREATE TABLE finance_invoice_settings (
 business_id INTEGER NOT NULL, branch_id INTEGER NOT NULL, defaults_json TEXT NOT NULL,
 updated_at TEXT NOT NULL, PRIMARY KEY(business_id,branch_id),
 FOREIGN KEY(business_id,branch_id) REFERENCES finance_branches(business_id,id) ON DELETE CASCADE
);
CREATE TABLE finance_invoice_revisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, invoice_id INTEGER NOT NULL,
 revision INTEGER NOT NULL, actor_user_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL,
 fields_changed TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
 UNIQUE(business_id,invoice_id,revision),
 FOREIGN KEY(business_id,invoice_id) REFERENCES finance_invoices(business_id,id)
);

-- Freeze the available legacy identity once; older unsaved contact details cannot be recovered.
UPDATE finance_invoices SET document_snapshot=(SELECT json_object(
 'sender',json_object('name',b.business_name,'address',COALESCE(p.address,''),'phone',COALESCE(p.business_phone,''),'email','','tax_id','','website',''),
 'recipient',json_object('name',c.name,'pic','','address','','phone',COALESCE(c.phone,''),'email',COALESCE(c.email,''),'tax_id',''),
 'payment',json_object('method',CASE WHEN COALESCE(p.payment_bank_name,'')<>'' THEN 'Transfer Bank' ELSE '' END,'bank',COALESCE(p.payment_bank_name,''),'account_number',COALESCE(p.payment_account_number,''),'account_holder',COALESCE(p.payment_account_name,''),'instructions',COALESCE(p.payment_instructions,'')),
 'reference','')
 FROM businesses b JOIN finance_customers c ON c.business_id=b.id
 LEFT JOIN business_profiles p ON p.business_id=b.id
 WHERE b.id=finance_invoices.business_id AND c.id=finance_invoices.customer_id)
 WHERE document_snapshot IS NULL;
