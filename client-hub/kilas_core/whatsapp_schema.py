"""Explicit additive Phase 8 installer; never run on app boot."""
from pathlib import Path
import db
from public_chat.store import transaction


def apply_schema():
    path = Path(__file__).resolve().parents[1]/'migrations'/f'0061_kilas_whatsapp_{db.BACKEND}.sql'
    with transaction() as tx:
        for statement in path.read_text().split(';'):
            if statement.strip(): tx.execute(statement)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    apply_schema()
