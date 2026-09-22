"""Read-only recurring-bill checker.

A due date is a commitment, not proof that cash moved. This script intentionally never
posts ledger transactions. Actual expenses are created only by an explicit paid action
that supplies the real payment date.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db
import finance_service as finance


def run(as_of=None):
    """Report due recurring rules without changing balances, expenses, budgets, or reports."""
    try:
        as_of = finance._date(as_of or datetime.now(timezone.utc).date())
        row = db.query_one(
            'SELECT COUNT(*) AS due_rules,COUNT(DISTINCT business_id) AS businesses '
            'FROM finance_recurring_expenses WHERE is_active=TRUE AND next_due_on<=?',
            (as_of,))
        due_rules = int(row['due_rules'] or 0) if row else 0
        businesses = int(row['businesses'] or 0) if row else 0
    except Exception:
        print('FINANCE_RECURRING status=read_failed',file=sys.stderr)
        return 1
    print(
        f'FINANCE_RECURRING auto_post=disabled due_businesses={businesses} '
        f'due_rules={due_rules}')
    return 0


if __name__=='__main__':
    raise SystemExit(run())
