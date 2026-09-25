"""Explicit additive 0057 installer; never invoked on application boot."""
from pathlib import Path
import db
from kilas_core.customers import transaction


def apply_schema():
    sql = (Path(__file__).resolve().parents[1] / 'migrations' /
           f'0057_kilas_core_jobs_{db.BACKEND}.sql').read_text()
    with transaction() as tx:
        for statement in sql.split(';'):
            if statement.strip():
                tx.execute(statement)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    apply_schema()
