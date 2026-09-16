"""Phase 1A: tenant-scoped cash ledger, integer minor units, no UI/integration/AI.

Internal service API, like the existing business repositories. Future authenticated entry points
must resolve business_id using require_business_access(), never trust a client-supplied tenant.
Optional actor_user_id is checked against existing admin/membership rules on reads and writes;
None is reserved for trusted internal jobs. It is not an anonymous/public access mechanism.
No operation hard-deletes a transaction. All monetary amounts are caller-supplied integers in
minor units of the stated currency (IDR defaults); there is no conversion or float calculation.
"""
from contextlib import contextmanager
from datetime import date
import re

import db
import repo

ACCOUNT_TYPES = ('CASH', 'BANK', 'EWALLET', 'OTHER')
DIRECTIONS = ('INCOME', 'EXPENSE')
FIELDS = ('direction', 'amount_minor', 'currency', 'account_id', 'category_id', 'occurred_on',
          'description', 'counterparty_name', 'project_id', 'source_type', 'source_ref')
DEFAULT_CATEGORIES = {
    'INCOME': ('Penjualan / Jasa', 'Subscription', 'Pendapatan Lain'),
    'EXPENSE': ('Produksi / Vendor', 'Gaji / Freelancer', 'Marketing / Ads', 'Transport',
                'Software / API', 'Operasional', 'Pengeluaran Lain'),
}


class FinanceError(ValueError):
    """Safe categories only: never includes supplied text or other tenant data."""


def _id(value):
    if type(value) is not int or value <= 0 or value > 2**63-1:
        raise FinanceError('invalid_id')
    return value


def _scope(business_id, actor_user_id=None):
    _id(business_id)
    if not db.query_one('SELECT id FROM businesses WHERE id=?', (business_id,)):
        raise FinanceError('business_unavailable')
    if actor_user_id is not None:
        _id(actor_user_id)
        actor = db.query_one('SELECT role FROM users WHERE id=?', (actor_user_id,))
        member = db.query_one('SELECT user_id FROM business_memberships WHERE business_id=? AND user_id=?',
                              (business_id, actor_user_id))
        if not actor or (actor['role'] != 'KILAS_ADMIN' and not member):
            raise FinanceError('business_unavailable')


@contextmanager
def _write(business_id, actor_user_id):
    _id(business_id)
    # Existing abstraction holds a business row lock and keeps nested DB/audit writes atomic.
    # No new transaction framework, no payment/project operation is called.
    with db.app_purchase_transaction(business_id, None):
        _scope(business_id, actor_user_id)
        yield


def _enum(value, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise FinanceError('invalid_enum')
    return value


def _text(value, limit, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise FinanceError('invalid_text')
    value = value.strip()
    if not value and required:
        raise FinanceError('missing_name')
    return value or None


def _money(value, positive=False):
    if type(value) is not int or not -(2**63) <= value <= 2**63-1 or (positive and value <= 0):
        raise FinanceError('invalid_money_minor')
    return value


def _currency(value):
    if not isinstance(value, str) or not re.fullmatch('[A-Za-z]{3}', value.strip()):
        raise FinanceError('invalid_currency')
    return value.strip().upper()


def _date(value):
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, str):
        try:
            if date.fromisoformat(value).isoformat() == value:
                return value
        except ValueError:
            pass
    raise FinanceError('invalid_date')


def _audit(business_id, actor_user_id, event, record_id):
    # Reuse existing audit storage; no descriptions, counterparties, bank details or source refs.
    repo.write_audit(actor_user_id, business_id, event, f'finance_record_id={record_id}')


def _create_account(business_id, name, account_type, currency, opening_balance_minor, actor_user_id):
    now = repo._now()
    record_id = db.insert_returning_id(
        'INSERT INTO finance_accounts (business_id,name,account_type,currency,opening_balance_minor,created_at,updated_at) '
        'VALUES (?,?,?,?,?,?,?)', (business_id, name, account_type, currency, opening_balance_minor, now, now))
    _audit(business_id, actor_user_id, 'FINANCE_ACCOUNT_CREATED', record_id)
    return record_id


def create_account(business_id, name, account_type='CASH', currency='IDR', opening_balance_minor=0, *, actor_user_id=None):
    name = _text(name, 160, True)
    account_type, currency = _enum(account_type, ACCOUNT_TYPES), _currency(currency)
    opening_balance_minor = _money(opening_balance_minor)
    with _write(business_id, actor_user_id):
        if db.query_one('SELECT id FROM finance_accounts WHERE business_id=? AND name=? AND account_type=? AND currency=?',
                        (business_id, name, account_type, currency)):
            raise FinanceError('account_exists')
        return _create_account(business_id, name, account_type, currency, opening_balance_minor, actor_user_id)


def list_accounts(business_id, include_inactive=False, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    return db.query_all('SELECT * FROM finance_accounts WHERE business_id=?' +
                        ('' if include_inactive else ' AND is_active=TRUE') + ' ORDER BY id', (business_id,))


def _create_category(business_id, direction, name, actor_user_id):
    now = repo._now()
    record_id = db.insert_returning_id(
        'INSERT INTO finance_categories (business_id,direction,name,created_at,updated_at) VALUES (?,?,?,?,?)',
        (business_id, direction, name, now, now))
    _audit(business_id, actor_user_id, 'FINANCE_CATEGORY_CREATED', record_id)
    return record_id


def create_category(business_id, direction, name, *, actor_user_id=None):
    direction, name = _enum(direction, DIRECTIONS), _text(name, 160, True)
    with _write(business_id, actor_user_id):
        if db.query_one('SELECT id FROM finance_categories WHERE business_id=? AND direction=? AND name=?',
                        (business_id, direction, name)):
            raise FinanceError('category_exists')
        return _create_category(business_id, direction, name, actor_user_id)


def list_categories(business_id, direction=None, include_inactive=False, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    sql, params = 'SELECT * FROM finance_categories WHERE business_id=?', [business_id]
    if direction is not None:
        sql += ' AND direction=?'; params.append(_enum(direction, DIRECTIONS))
    if not include_inactive:
        sql += ' AND is_active=TRUE'
    return db.query_all(sql + ' ORDER BY direction,id', params)


def ensure_finance_defaults(business_id, *, actor_user_id=None):
    """Explicit only, never called on boot. Existing names/balances/active flags are untouched."""
    with _write(business_id, actor_user_id):
        if not db.query_one("SELECT id FROM finance_accounts WHERE business_id=? AND name=? AND account_type='CASH' AND currency='IDR'",
                            (business_id, 'Kas')):
            _create_account(business_id, 'Kas', 'CASH', 'IDR', 0, actor_user_id)
        for direction, names in DEFAULT_CATEGORIES.items():
            for name in names:
                if not db.query_one('SELECT id FROM finance_categories WHERE business_id=? AND direction=? AND name=?',
                                    (business_id, direction, name)):
                    _create_category(business_id, direction, name, actor_user_id)


def _transaction_data(business_id, data):
    data = dict(data)
    data['direction'] = _enum(data['direction'], DIRECTIONS)
    data['amount_minor'] = _money(data['amount_minor'], positive=True)
    data['currency'] = _currency(data['currency'])
    data['occurred_on'] = _date(data['occurred_on'])
    account = db.query_one('SELECT currency,is_active FROM finance_accounts WHERE business_id=? AND id=?',
                           (business_id, _id(data['account_id'])))
    if not account or not account['is_active']:
        raise FinanceError('account_unavailable')
    if account['currency'] != data['currency']:
        raise FinanceError('account_currency_mismatch')
    category = db.query_one('SELECT direction,is_active FROM finance_categories WHERE business_id=? AND id=?',
                            (business_id, _id(data['category_id'])))
    if not category or not category['is_active']:
        raise FinanceError('category_unavailable')
    if category['direction'] != data['direction']:
        raise FinanceError('category_direction_mismatch')
    if data['project_id'] is not None and not db.query_one('SELECT id FROM projects WHERE business_id=? AND id=?',
                                                         (business_id, _id(data['project_id']))):
        raise FinanceError('project_unavailable')
    for key, limit in (('description', 4000), ('counterparty_name', 160), ('source_type', 64), ('source_ref', 256)):
        data[key] = _text(data[key], limit)
    return data


def create_transaction(business_id, direction, amount_minor, account_id, category_id, occurred_on, *,
                       currency='IDR', description=None, counterparty_name=None, project_id=None,
                       source_type=None, source_ref=None, actor_user_id=None):
    raw = {key: value for key, value in locals().items() if key in FIELDS}
    with _write(business_id, actor_user_id):
        data = _transaction_data(business_id, raw)
        now = repo._now()
        record_id = db.insert_returning_id(
            'INSERT INTO finance_transactions (business_id,' + ','.join(FIELDS) +
            ',created_by_user_id,created_at,updated_at) VALUES (' + ','.join(['?'] * (len(FIELDS)+4)) + ')',
            [business_id] + [data[key] for key in FIELDS] + [actor_user_id, now, now])
        _audit(business_id, actor_user_id, 'FINANCE_TRANSACTION_CREATED', record_id)
        return record_id


def get_transaction(business_id, transaction_id, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    return db.query_one('SELECT * FROM finance_transactions WHERE business_id=? AND id=?',
                        (business_id, _id(transaction_id)))


def _period(start_date, end_date):
    start, end = _date(start_date), _date(end_date)
    if start > end:
        raise FinanceError('invalid_period')
    return start, end


def list_transactions(business_id, *, start_date=None, end_date=None, direction=None, status=None,
                      account_id=None, limit=100, offset=0, actor_user_id=None):
    _scope(business_id, actor_user_id)
    if type(limit) is not int or not 1 <= limit <= 1000 or type(offset) is not int or offset < 0:
        raise FinanceError('invalid_pagination')
    sql, params = 'SELECT * FROM finance_transactions WHERE business_id=?', [business_id]
    if start_date is not None and end_date is not None:
        _period(start_date, end_date)
    for value, clause in ((start_date, ' AND occurred_on>=?'), (end_date, ' AND occurred_on<=?')):
        if value is not None:
            sql += clause; params.append(_date(value))
    if direction is not None:
        sql += ' AND direction=?'; params.append(_enum(direction, DIRECTIONS))
    if status is not None:
        sql += ' AND status=?'; params.append(_enum(status, ('POSTED', 'VOID')))
    if account_id is not None:
        sql += ' AND account_id=?'; params.append(_id(account_id))
    return db.query_all(sql + ' ORDER BY occurred_on DESC,id DESC LIMIT ? OFFSET ?', params + [limit, offset])


def update_transaction(business_id, transaction_id, *, actor_user_id=None, **changes):
    if set(changes) - set(FIELDS):
        raise FinanceError('unsupported_fields')
    with _write(business_id, actor_user_id):
        current = get_transaction(business_id, transaction_id, actor_user_id=actor_user_id)
        if current is None:
            raise FinanceError('transaction_unavailable')
        if current['status'] == 'VOID':
            raise FinanceError('transaction_void')
        original = {key: current[key] for key in FIELDS}
        data = _transaction_data(business_id, dict(original, **changes))
        if data != original:
            db.execute('UPDATE finance_transactions SET ' + ','.join(key+'=?' for key in FIELDS) +
                       ',updated_at=? WHERE business_id=? AND id=? AND status=\'POSTED\'',
                       [data[key] for key in FIELDS] + [repo._now(), business_id, transaction_id])
            _audit(business_id, actor_user_id, 'FINANCE_TRANSACTION_UPDATED', transaction_id)
        return get_transaction(business_id, transaction_id, actor_user_id=actor_user_id)


def void_transaction(business_id, transaction_id, actor_user_id=None):
    with _write(business_id, actor_user_id):
        current = get_transaction(business_id, transaction_id, actor_user_id=actor_user_id)
        if current is None:
            raise FinanceError('transaction_unavailable')
        if current['status'] != 'VOID':
            now = repo._now()
            db.execute("UPDATE finance_transactions SET status='VOID',voided_at=?,voided_by_user_id=?,updated_at=? "
                       "WHERE business_id=? AND id=? AND status='POSTED'", (now, actor_user_id, now, business_id, transaction_id))
            _audit(business_id, actor_user_id, 'FINANCE_TRANSACTION_VOIDED', transaction_id)
        return get_transaction(business_id, transaction_id, actor_user_id=actor_user_id)


def get_finance_summary(business_id, start_date, end_date, *, currency='IDR', actor_user_id=None):
    """Inclusive dates, POSTED only. Cash-based movement, NOT accrual profit.

    One currency at a time: never silently add IDR to USD. Python integer aggregation avoids
    SQLite SUM overflow/float promotion when totals exceed an individual signed BIGINT.
    """
    _scope(business_id, actor_user_id)
    start, end = _period(start_date, end_date)
    currency = _currency(currency)
    rows = db.query_all("SELECT direction,amount_minor FROM finance_transactions WHERE business_id=? "
                        "AND status='POSTED' AND currency=? AND occurred_on>=? AND occurred_on<=?",
                        (business_id, currency, start, end))
    income = sum(row['amount_minor'] for row in rows if row['direction'] == 'INCOME')
    expense = sum(row['amount_minor'] for row in rows if row['direction'] == 'EXPENSE')
    return {'currency': currency, 'total_income_minor': income, 'total_expense_minor': expense,
            'net_cashflow_minor': income-expense}
