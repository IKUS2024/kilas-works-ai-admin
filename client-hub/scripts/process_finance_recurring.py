"""Future daily cron: cd client-hub && python scripts/process_finance_recurring.py

No migrations, app import, background thread, network or automatic boot invocation.
Each business is processed independently. Configure a cron job separately after review.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db
import finance_service as finance


def run(as_of=None):
    """Trusted CLI entry only; no route exposes this cross-business dispatcher.

    Logs only fixed labels and counts. Configuration attention/catch-up is not an execution
    failure; DB/setup/processing exceptions produce nonzero exit while other businesses continue.
    """
    try:
        as_of = finance._date(as_of or datetime.now(timezone.utc).date())
        businesses = db.query_all('SELECT DISTINCT business_id FROM finance_recurring_expenses '
            'WHERE is_active=TRUE AND next_due_on<=? ORDER BY business_id',(as_of,))
    except Exception:
        print('FINANCE_RECURRING status=setup_failed',file=sys.stderr)
        return 1
    failed = posted = attention = pending = 0
    for row in businesses:
        try:
            result = finance.process_due_recurring_expenses(row['business_id'],as_of)
            posted += result['posted_count']; attention += result['needs_attention_count']; pending += int(result['has_more'])
        except Exception:
            failed += 1
            print('FINANCE_RECURRING status=business_processing_failed',file=sys.stderr)
    print(f'FINANCE_RECURRING processed_businesses={len(businesses)} posted={posted} needs_attention={attention} pending_businesses={pending} failed={failed}')
    return 1 if failed else 0


if __name__=='__main__':
    raise SystemExit(run())
