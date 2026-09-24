"""Explicit additive 0058 only. Never invoked on boot or by the runner."""
from pathlib import Path
import db
from .customers import transaction


def apply_schema():
    sql = (Path(__file__).resolve().parents[1]/'migrations'/f'0058_kilas_operations_{db.BACKEND}.sql').read_text()
    with transaction() as tx:
        for statement in sql.split(';'):
            if statement.strip(): tx.execute(statement)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',required=True)
    parser.parse_args()
    apply_schema()
