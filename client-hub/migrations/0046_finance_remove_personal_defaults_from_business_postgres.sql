-- Remove Personal-only default categories that were accidentally mapped into Business.
-- Historical Business usage wins: any category already used by Business remains active.
UPDATE finance_category_workspace_settings s
SET is_active=FALSE,updated_at=CURRENT_TIMESTAMP
WHERE s.scope_key='BUSINESS'
  AND s.is_active=TRUE
  AND (
    s.category_id IN (
      SELECT c.id
      FROM finance_categories c
      WHERE c.direction='INCOME'
        AND c.name IN (
          'Gaji','Bonus','Freelance / Side Job','Investasi','Hadiah / Transfer Masuk'
        )
    )
    OR s.category_id IN (
      SELECT c.id
      FROM finance_categories c
      WHERE c.direction='EXPENSE'
        AND c.name IN (
          'Tempat Tinggal / Sewa','Kesehatan','Belanja Pribadi','Hiburan',
          'Pendidikan','Cicilan / Utang','Keluarga','Donasi'
        )
    )
  )
  AND EXISTS (
    SELECT 1
    FROM finance_category_workspace_settings p
    WHERE p.business_id=s.business_id
      AND p.category_id=s.category_id
      AND p.workspace_type='PERSONAL'
  )
  AND NOT EXISTS (
    SELECT 1 FROM finance_transactions t
    JOIN finance_branch_workspaces w
      ON w.business_id=t.business_id AND w.branch_id=t.branch_id
     AND w.workspace_type='BUSINESS'
    WHERE t.business_id=s.business_id AND t.category_id=s.category_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM finance_budgets b
    JOIN finance_branch_workspaces w
      ON w.business_id=b.business_id AND w.branch_id=b.branch_id
     AND w.workspace_type='BUSINESS'
    WHERE b.business_id=s.business_id AND b.category_id=s.category_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM finance_recurring_expenses r
    JOIN finance_branch_workspaces w
      ON w.business_id=r.business_id AND w.branch_id=r.branch_id
     AND w.workspace_type='BUSINESS'
    WHERE r.business_id=s.business_id AND r.category_id=s.category_id
  );
