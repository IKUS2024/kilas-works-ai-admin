"""Explicit optional Finance Bridge installer. Never runs on app boot."""
from pathlib import Path
import db
from public_chat.store import transaction

TABLES = ('kw_core_finance_connections', 'kw_core_finance_customer_links',
          'kw_core_finance_invoice_links', 'kw_core_finance_operations')


def apply_schema():
    sql = (Path(__file__).resolve().parents[1] / 'migrations' /
           f'0060_kilas_finance_bridge_{db.BACKEND}.sql').read_text()
    with transaction() as tx:
        for statement in sql.split(';'):
            if statement.strip():
                tx.execute(statement)
        # Every mapping revision, operation and resulting link is append-only.
        if db.BACKEND == 'postgres':
            tx.execute("""CREATE OR REPLACE FUNCTION kw_bridge_history_immutable()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'bridge history immutable'; END $$""")
        for table in TABLES:
            if db.BACKEND == 'postgres':
                tx.execute(f'DROP TRIGGER IF EXISTS immutable_history ON {table}')
                tx.execute(f'CREATE TRIGGER immutable_history BEFORE UPDATE OR DELETE ON {table} '
                           'FOR EACH ROW EXECUTE FUNCTION kw_bridge_history_immutable()')
            else:
                for action in ('UPDATE', 'DELETE'):
                    tx.execute(f'CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action.lower()} '
                               f'BEFORE {action} ON {table} '
                               "BEGIN SELECT RAISE(ABORT,'bridge history immutable'); END")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    apply_schema()
