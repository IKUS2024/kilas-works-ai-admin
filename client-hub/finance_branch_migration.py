"""SQLite 0033 adapter: atomic, repeatable additions and account unique-key change."""
import sqlite3


def migrate_sqlite(conn, script):
    conn.commit()
    enabled = conn.execute('PRAGMA foreign_keys').fetchone()[0]
    conn.execute('PRAGMA foreign_keys=OFF')
    try:
        conn.execute('BEGIN IMMEDIATE')
        statement = ''
        for line in script.splitlines(True):
            statement += line
            if sqlite3.complete_statement(statement):
                try:
                    conn.execute(statement)
                except sqlite3.OperationalError as exc:
                    if not ('duplicate column name' in str(exc) and statement.lstrip().startswith('ALTER TABLE')):
                        raise
                statement = ''
        # SQLite cannot drop the old inline UNIQUE constraint. Rebuild only that table,
        # preserving every ID/column and all child FK names. Never rename the old table.
        schema = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='finance_accounts'").fetchone()[0]
        old = 'UNIQUE(business_id,name,account_type,currency)'
        if old in schema:
            schema = schema.replace('CREATE TABLE finance_accounts', 'CREATE TABLE finance_accounts_branch_new', 1)
            schema = schema.replace(old, 'UNIQUE(business_id,branch_id,name,account_type,currency)')
            conn.execute(schema)
            columns = ','.join(row[1] for row in conn.execute('PRAGMA table_info(finance_accounts)'))
            conn.execute('INSERT INTO finance_accounts_branch_new (' + columns + ') SELECT ' + columns + ' FROM finance_accounts')
            conn.execute('DROP TABLE finance_accounts')
            conn.execute('ALTER TABLE finance_accounts_branch_new RENAME TO finance_accounts')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_finance_accounts_business ON finance_accounts(business_id)')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_finance_accounts_branch_id ON finance_accounts(business_id,branch_id,id)')
        # Financial identities are immutable. Parent guards also protect raw SQL callers.
        for table in ('finance_accounts', 'finance_transactions', 'finance_invoices', 'finance_recurring_expenses', 'finance_bank_imports'):
            for event in ('INSERT', 'UPDATE'):
                conditions = ['NOT EXISTS (SELECT 1 FROM finance_branches b WHERE b.business_id=NEW.business_id AND b.id=NEW.branch_id)']
                if table in ('finance_transactions', 'finance_recurring_expenses', 'finance_bank_imports'):
                    conditions.append('NOT EXISTS (SELECT 1 FROM finance_accounts a WHERE a.business_id=NEW.business_id AND a.branch_id=NEW.branch_id AND a.id=NEW.account_id)')
                if event == 'UPDATE':
                    conditions.append('NEW.branch_id IS NOT OLD.branch_id OR NEW.business_id IS NOT OLD.business_id')
                conn.execute('CREATE TRIGGER IF NOT EXISTS guard_' + table + '_' + event.lower() + ' BEFORE ' + event + ' ON ' + table +
                    ' WHEN ' + ' OR '.join('(' + c + ')' for c in conditions) + " BEGIN SELECT RAISE(ABORT,'finance branch mismatch'); END")
        for event in ('INSERT', 'UPDATE'):
            conn.execute('CREATE TRIGGER IF NOT EXISTS guard_finance_payment_branch_' + event.lower() + ' BEFORE ' + event +
                " ON finance_invoice_payments WHEN NOT EXISTS (SELECT 1 FROM finance_invoices i JOIN finance_accounts a ON a.business_id=i.business_id AND a.branch_id=i.branch_id WHERE i.business_id=NEW.business_id AND i.id=NEW.invoice_id AND a.id=NEW.account_id) BEGIN SELECT RAISE(ABORT,'finance payment branch mismatch'); END")
        if conn.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Finance branch migration: foreign key check failed')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute('PRAGMA foreign_keys=' + ('ON' if enabled else 'OFF'))
