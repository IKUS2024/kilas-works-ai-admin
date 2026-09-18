"""Phase 1A: tenant-scoped cash ledger, integer minor units, no UI/integration/AI.

Internal service API, like the existing business repositories. Future authenticated entry points
must resolve business_id using require_business_access(), never trust a client-supplied tenant.
Optional actor_user_id is checked against existing admin/membership rules on reads and writes;
None is reserved for trusted internal jobs. It is not an anonymous/public access mechanism.
No operation hard-deletes a transaction. All monetary amounts are caller-supplied integers in
minor units of the stated currency (IDR defaults); there is no conversion or float calculation.
"""
from contextlib import contextmanager
from datetime import date, timedelta
import calendar
import json
import re
import uuid

import db
import repo
import finance_ai_safety
import finance_branches as branches

ACCOUNT_TYPES = ('CASH', 'BANK', 'EWALLET', 'OTHER')
DIRECTIONS = ('INCOME', 'EXPENSE')
FIELDS = ('direction', 'amount_minor', 'currency', 'account_id', 'category_id', 'occurred_on',
          'description', 'counterparty_name', 'project_id', 'source_type', 'source_ref', 'customer_id')
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
    branches.validate(business_id)
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
        import finance_entitlements
        finance_entitlements.require_write(business_id, actor_user_id)
        branches.validate(business_id, write=True)
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


def _create_account(business_id, name, account_type, currency, opening_balance_minor, actor_user_id, branch_id=None):
    branch_id = branch_id or branches.write_branch(business_id, actor_user_id)
    branches.get(business_id, branch_id, active=True)
    now = repo._now()
    record_id = db.insert_returning_id(
        'INSERT INTO finance_accounts (business_id,branch_id,name,account_type,currency,opening_balance_minor,created_at,updated_at) '
        'VALUES (?,?,?,?,?,?,?,?)', (business_id, branch_id, name, account_type, currency, opening_balance_minor, now, now))
    _audit(business_id, actor_user_id, 'FINANCE_ACCOUNT_CREATED', record_id)
    return record_id


def create_account(business_id, name, account_type='CASH', currency='IDR', opening_balance_minor=0, *, actor_user_id=None):
    name = _text(name, 160, True)
    account_type, currency = _enum(account_type, ACCOUNT_TYPES), _currency(currency)
    opening_balance_minor = _money(opening_balance_minor)
    with _write(business_id, actor_user_id):
        branch_id = branches.write_branch(business_id, actor_user_id)
        if db.query_one(('SELECT id FROM finance_accounts WHERE business_id=?' + branches.predicate('') + ' AND branch_id=? AND name=? AND account_type=? AND currency=?'),
                        (business_id, branch_id, name, account_type, currency)):
            raise FinanceError('account_exists')
        return _create_account(business_id, name, account_type, currency, opening_balance_minor, actor_user_id)


def list_accounts(business_id, include_inactive=False, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    return db.query_all(('SELECT * FROM finance_accounts WHERE business_id=?' + branches.predicate()) +
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
        branch_id = branches.write_branch(business_id, actor_user_id)
        if not db.query_one(('SELECT id FROM finance_accounts WHERE business_id=?' + branches.predicate('') + " AND branch_id=? AND name=? AND account_type='CASH' AND currency='IDR'"),
                            (business_id, branch_id, 'Kas')):
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
    if data['occurred_on'] > date.today().isoformat():
        raise FinanceError('future_date')
    branch_id = branches.account_branch(business_id, data['account_id'])
    if data.get('branch_id') is not None and data['branch_id'] != branch_id:
        raise FinanceError('branch_mismatch')
    data['branch_id'] = branch_id
    account = db.query_one(('SELECT currency,is_active FROM finance_accounts WHERE business_id=?' + branches.predicate('') + ' AND id=?'),
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
    if data['customer_id'] is not None:
        customer = get_customer(business_id, _id(data['customer_id']))
        if not customer or not customer['is_active']:
            raise FinanceError('customer_unavailable')
    for key, limit in (('description', 4000), ('counterparty_name', 160), ('source_type', 64), ('source_ref', 256)):
        data[key] = _text(data[key], limit)
    return data


def create_transaction(business_id, direction, amount_minor, account_id, category_id, occurred_on, *,
                       currency='IDR', description=None, counterparty_name=None, project_id=None,
                       source_type=None, source_ref=None, customer_id=None, actor_user_id=None):
    raw = {key: value for key, value in locals().items() if key in FIELDS}
    with _write(business_id, actor_user_id):
        data = _transaction_data(business_id, raw)
        if data['source_type'] == 'FINANCE_BANK_IMPORT':
            raise FinanceError('bank_origin_managed')
        if data['source_type'] == 'FINANCE_RECEIPT':
            raise FinanceError('receipt_origin_managed')
        if data['source_type'] == 'FINANCE_OPERATOR':
            # One signed draft = one persistent ledger row, across workers/restarts.
            # The existing business lock is held until ledger + audit commit together.
            if not data['source_ref'] or not re.fullmatch('[a-f0-9]{32}', data['source_ref']):
                raise FinanceError('invalid_operator_key')
            existing = db.query_one(('SELECT *, (SELECT name FROM finance_branches b WHERE b.id=finance_transactions.branch_id AND b.business_id=finance_transactions.business_id) AS branch_name FROM finance_transactions WHERE business_id=?' + branches.predicate('') + ' AND source_type=? AND source_ref=?'), (business_id, 'FINANCE_OPERATOR', data['source_ref']))
            if existing:
                if existing['created_by_user_id'] != actor_user_id or any(existing[key] != data[key] for key in FIELDS):
                    raise FinanceError('operator_key_conflict')
                finance_ai_safety.event('operator_replay')
                return existing['id']
        if data['source_type'] == 'FINANCE_RECURRING_EXPENSE':
            raise FinanceError('recurring_ledger_managed')
        if data['source_type'] == 'FINANCE_INVOICE_PAYMENT':
            raise FinanceError('invoice_ledger_managed')
        return _insert_transaction(business_id, data, actor_user_id)


def _insert_transaction(business_id, data, actor_user_id):
    """Caller already holds the business lock; used by atomic Finance payment posting."""
    now = repo._now()
    record_id = db.insert_returning_id(
        'INSERT INTO finance_transactions (business_id,branch_id,' + ','.join(FIELDS) +
        ',created_by_user_id,created_at,updated_at) VALUES (' + ','.join(['?'] * (len(FIELDS)+5)) + ')',
        [business_id, data['branch_id']] + [data[key] for key in FIELDS] + [actor_user_id, now, now])
    _audit(business_id, actor_user_id, 'FINANCE_TRANSACTION_CREATED', record_id)
    return record_id


def get_transaction(business_id, transaction_id, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    return db.query_one(('SELECT *, (SELECT name FROM finance_branches b WHERE b.id=finance_transactions.branch_id AND b.business_id=finance_transactions.business_id) AS branch_name FROM finance_transactions WHERE business_id=?' + branches.predicate('') + ' AND id=?'),
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
    sql, params = ('SELECT *, (SELECT name FROM finance_branches b WHERE b.id=finance_transactions.branch_id AND b.business_id=finance_transactions.business_id) AS branch_name FROM finance_transactions WHERE business_id=?' + branches.predicate()), [business_id]
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
        if current['source_type'] == 'FINANCE_OPERATOR':
            if any(key in changes and changes[key] != current[key] for key in ('source_type','source_ref')):
                raise FinanceError('operator_origin_immutable')
        elif changes.get('source_type') == 'FINANCE_OPERATOR':
            raise FinanceError('operator_origin_immutable')
        if current['source_type'] == 'FINANCE_INVOICE_PAYMENT' or changes.get('source_type') == 'FINANCE_INVOICE_PAYMENT':
            raise FinanceError('invoice_ledger_managed')
        if current['source_type'] == 'FINANCE_RECURRING_EXPENSE':
            raise FinanceError('recurring_ledger_managed')
        if current['status'] == 'VOID':
            raise FinanceError('transaction_void')
        original = {key: current[key] for key in FIELDS}
        data = _transaction_data(business_id, dict(original, branch_id=current['branch_id'], **changes))
        # Check canonical source names after _text strips whitespace. Raw-input
        # guards above alone allow padded managed origins on unrelated records.
        if data['source_type'] == 'FINANCE_INVOICE_PAYMENT':
            raise FinanceError('invoice_ledger_managed')
        if data['source_type'] == 'FINANCE_OPERATOR' and current['source_type'] != 'FINANCE_OPERATOR':
            raise FinanceError('operator_origin_immutable')
        if data['source_type'] == 'FINANCE_RECURRING_EXPENSE':
            raise FinanceError('recurring_ledger_managed')
        if current['source_type'] == 'FINANCE_BANK_IMPORT':
            if any(data[key] != current[key] for key in ('source_type', 'source_ref')):
                raise FinanceError('bank_origin_immutable')
        elif data['source_type'] == 'FINANCE_BANK_IMPORT':
            raise FinanceError('bank_origin_immutable')
        if current['source_type'] == 'FINANCE_RECEIPT':
            if (any(data[key] != current[key] for key in ('source_type', 'source_ref'))
                    or data['direction'] != 'EXPENSE' or data['currency'] != 'IDR'):
                raise FinanceError('receipt_origin_immutable')
        elif data['source_type'] == 'FINANCE_RECEIPT':
            raise FinanceError('receipt_origin_immutable')
        if any(data[key] != original[key] for key in FIELDS):
            db.execute('INSERT INTO finance_transaction_revisions '
                '(business_id,transaction_id,before_json,after_json,actor_user_id,created_at) VALUES (?,?,?,?,?,?)',
                (business_id, transaction_id, json.dumps(dict(original, branch_id=current['branch_id']), sort_keys=True),
                 json.dumps(data, sort_keys=True), actor_user_id, repo._now()))
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
        if current['source_type'] == 'FINANCE_INVOICE_PAYMENT':
            raise FinanceError('invoice_ledger_managed')
        if current['status'] != 'VOID':
            now = repo._now()
            db.execute("UPDATE finance_transactions SET status='VOID',voided_at=?,voided_by_user_id=?,updated_at=? "
                       "WHERE business_id=? AND id=? AND status='POSTED'", (now, actor_user_id, now, business_id, transaction_id))
            _audit(business_id, actor_user_id, 'FINANCE_TRANSACTION_VOIDED', transaction_id)
        return get_transaction(business_id, transaction_id, actor_user_id=actor_user_id)


def reset_branch_finance(business_id, actor_user_id=None):
    """Reset the selected active branch to a clean Rp0 starting point without hard-deleting history.

    Financial rows remain available for audit/export history, but no longer affect current balances
    or receivables. Branches, accounts, categories, customers and projects remain configured.
    """
    with _write(business_id, actor_user_id):
        branch_id = branches.write_branch(business_id, actor_user_id)
        now = repo._now()
        # Include every source (manual, receipt, bank, recurring, invoice payment). Reset is the
        # explicit branch-level escape hatch; ordinary source-specific void restrictions remain.
        db.execute(
            "UPDATE finance_transactions SET status='VOID',voided_at=COALESCE(voided_at,?),"
            "voided_by_user_id=COALESCE(voided_by_user_id,?),updated_at=? "
            "WHERE business_id=? AND branch_id=? AND status='POSTED'",
            (now, actor_user_id, now, business_id, branch_id))
        db.execute(
            "UPDATE finance_accounts SET opening_balance_minor=0,updated_at=? "
            "WHERE business_id=? AND branch_id=?",
            (now, business_id, branch_id))
        # A reset intentionally closes even paid/part-paid invoices. Payment rows remain immutable
        # history, while VOID invoices are excluded from current receivables and aging.
        db.execute(
            "UPDATE finance_invoices SET status='VOID',voided_at=COALESCE(voided_at,?),"
            "voided_by_user_id=COALESCE(voided_by_user_id,?),updated_at=? "
            "WHERE business_id=? AND branch_id=? AND status<>'VOID'",
            (now, actor_user_id, now, business_id, branch_id))
        db.execute(
            "UPDATE finance_recurring_expenses SET is_active=FALSE,updated_at=? "
            "WHERE business_id=? AND branch_id=? AND is_active=TRUE",
            (now, business_id, branch_id))
        # In-progress bank work is closed; completed imports stay as historical reconciliation.
        db.execute(
            "UPDATE finance_bank_imports SET status='CANCELLED',updated_at=? "
            "WHERE business_id=? AND branch_id=? AND status IN ('REVIEW','OPEN')",
            (now, business_id, branch_id))
        _audit(business_id, actor_user_id, 'FINANCE_BRANCH_RESET', branch_id)
        return branch_id


def get_finance_summary(business_id, start_date, end_date, *, currency='IDR', actor_user_id=None):
    """Inclusive dates, POSTED only. Cash-based movement, NOT accrual profit.

    One currency at a time: never silently add IDR to USD. Python integer aggregation avoids
    SQLite SUM overflow/float promotion when totals exceed an individual signed BIGINT.
    """
    _scope(business_id, actor_user_id)
    start, end = _period(start_date, end_date)
    currency = _currency(currency)
    rows = db.query_all(('SELECT direction,amount_minor FROM finance_transactions WHERE business_id=?' + branches.predicate('') + " AND status='POSTED' AND currency=? AND occurred_on>=? AND occurred_on<=?"),
                        (business_id, currency, start, end))
    income = sum(row['amount_minor'] for row in rows if row['direction'] == 'INCOME')
    expense = sum(row['amount_minor'] for row in rows if row['direction'] == 'EXPENSE')
    return {'currency': currency, 'total_income_minor': income, 'total_expense_minor': expense,
            'net_cashflow_minor': income-expense}


# Finance receivables: deliberately never reads platform invoices/payments/payment_service.
def create_customer(business_id, name, phone=None, email=None, notes=None, actor_user_id=None):
    values = (_text(name, 160, True), _text(phone, 64), _text(email, 254), _text(notes, 4000))
    with _write(business_id, actor_user_id):
        now = repo._now()
        customer_id = db.insert_returning_id('INSERT INTO finance_customers '
            '(business_id,name,phone,email,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
            (business_id, *values, now, now))
        _audit(business_id, actor_user_id, 'FINANCE_CUSTOMER_CREATED', customer_id)
        return customer_id


def get_customer(business_id, customer_id, actor_user_id=None):
    _scope(business_id, actor_user_id)
    return db.query_one('SELECT * FROM finance_customers WHERE business_id=? AND id=?',
                        (business_id, _id(customer_id)))


def list_customers(business_id, include_inactive=False, actor_user_id=None):
    _scope(business_id, actor_user_id)
    return db.query_all('SELECT * FROM finance_customers WHERE business_id=?' +
        ('' if include_inactive else ' AND is_active=TRUE') + ' ORDER BY name,id', (business_id,))


def create_finance_invoice(business_id, customer_id, issue_date, due_date, items, notes=None, actor_user_id=None):
    issue_date, due_date = _period(issue_date, due_date)
    if issue_date > date.today().isoformat():
        raise FinanceError('future_date')
    notes = _text(notes, 4000)
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise FinanceError('invalid_items')
    clean, total = [], 0
    for item in items:
        if not isinstance(item, dict) or set(item) != {'description', 'quantity', 'unit_price_minor'}:
            raise FinanceError('invalid_items')
        description = _text(item['description'], 500, True)
        quantity, price = _money(item['quantity'], positive=True), _money(item['unit_price_minor'])
        if price < 0:
            raise FinanceError('invalid_money_minor')
        total = _money(total + quantity * price)
        clean.append((description, quantity, price))
    with _write(business_id, actor_user_id):
        customer = get_customer(business_id, customer_id, actor_user_id)
        if not customer or not customer['is_active']:
            raise FinanceError('customer_unavailable')
        now = repo._now()
        invoice_id = db.insert_returning_id('INSERT INTO finance_invoices '
            '(business_id,branch_id,customer_id,invoice_number,issue_date,due_date,notes,created_by_user_id,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)', (business_id, branches.write_branch(business_id, actor_user_id), customer_id, 'KFIN-PENDING-'+uuid.uuid4().hex,
            issue_date, due_date, notes, actor_user_id, now, now))
        number = f'KFIN-{issue_date[:4]}-{invoice_id:06d}'
        db.execute('UPDATE finance_invoices SET invoice_number=? WHERE business_id=? AND id=?', (number, business_id, invoice_id))
        for description, quantity, price in clean:
            db.execute('INSERT INTO finance_invoice_items '
                '(business_id,invoice_id,description,quantity,unit_price_minor,created_at) VALUES (?,?,?,?,?,?)',
                (business_id, invoice_id, description, quantity, price, now))
        _audit(business_id, actor_user_id, 'FINANCE_INVOICE_CREATED', invoice_id)
        return invoice_id


def get_finance_invoice(business_id, invoice_id, actor_user_id=None):
    _scope(business_id, actor_user_id)
    return db.query_one(('SELECT *, (SELECT name FROM finance_branches b WHERE b.business_id=finance_invoices.business_id AND b.id=finance_invoices.branch_id) AS branch_name FROM finance_invoices WHERE business_id=?' + branches.predicate('') + ' AND id=?'),
                        (business_id, _id(invoice_id)))


def _invoice(business_id, invoice_id, actor_user_id=None):
    invoice = get_finance_invoice(business_id, invoice_id, actor_user_id)
    if not invoice:
        raise FinanceError('invoice_unavailable')
    return invoice


def list_invoice_items(business_id, invoice_id, actor_user_id=None):
    _invoice(business_id, invoice_id, actor_user_id)
    return db.query_all('SELECT * FROM finance_invoice_items WHERE business_id=? AND invoice_id=? ORDER BY id',
                        (business_id, invoice_id))


def list_invoice_payments(business_id, invoice_id, actor_user_id=None):
    _invoice(business_id, invoice_id, actor_user_id)
    return db.query_all('SELECT * FROM finance_invoice_payments WHERE business_id=? AND invoice_id=? ORDER BY paid_on,id',
                        (business_id, invoice_id))


def get_invoice_totals(business_id, invoice_id, actor_user_id=None, today=None):
    # One statement gives a consistent read snapshot while another request posts a payment.
    _scope(business_id, actor_user_id)
    row = db.query_one(('''SELECT i.status,i.due_date,
        COALESCE((SELECT SUM(x.quantity*x.unit_price_minor) FROM finance_invoice_items x
                  WHERE x.business_id=i.business_id AND x.invoice_id=i.id),0) AS total_minor,
        COALESCE((SELECT SUM(p.amount_minor) FROM finance_invoice_payments p
                  WHERE p.business_id=i.business_id AND p.invoice_id=i.id),0) AS paid_minor
        FROM finance_invoices i WHERE i.business_id=?''' + branches.predicate('i') + ' AND i.id=?'), (business_id, _id(invoice_id)))
    if not row:
        raise FinanceError('invoice_unavailable')
    total, paid = int(row['total_minor']), int(row['paid_minor'])
    outstanding = total-paid
    return dict(total_minor=total, paid_minor=paid, outstanding_minor=outstanding,
        overdue=row['status'] in ('ISSUED','PARTIALLY_PAID') and outstanding > 0 and
                row['due_date'] < _date(today or date.today()))


def list_finance_invoices(business_id, status=None, customer_id=None, actor_user_id=None):
    _scope(business_id, actor_user_id)
    sql, params = ('SELECT *, (SELECT name FROM finance_branches b WHERE b.business_id=finance_invoices.business_id AND b.id=finance_invoices.branch_id) AS branch_name FROM finance_invoices WHERE business_id=?' + branches.predicate()), [business_id]
    if status is not None:
        sql += ' AND status=?'; params.append(_enum(status, ('DRAFT','ISSUED','PARTIALLY_PAID','PAID','VOID')))
    if customer_id is not None:
        if not get_customer(business_id, customer_id, actor_user_id):
            raise FinanceError('customer_unavailable')
        sql += ' AND customer_id=?'; params.append(customer_id)
    return db.query_all(sql + ' ORDER BY issue_date DESC,id DESC', params)


def issue_finance_invoice(business_id, invoice_id, actor_user_id=None):
    with _write(business_id, actor_user_id):
        invoice = _invoice(business_id, invoice_id, actor_user_id)
        if invoice['status'] != 'DRAFT':
            raise FinanceError('invalid_invoice_state')
        # Zero-priced drafts are allowed but cannot create a permanently open zero receivable.
        if get_invoice_totals(business_id, invoice_id)['total_minor'] <= 0:
            raise FinanceError('empty_invoice_total')
        db.execute("UPDATE finance_invoices SET status='ISSUED',updated_at=? WHERE business_id=? AND id=?",
                   (repo._now(), business_id, invoice_id))
        _audit(business_id, actor_user_id, 'FINANCE_INVOICE_ISSUED', invoice_id)


def void_finance_invoice(business_id, invoice_id, actor_user_id=None):
    with _write(business_id, actor_user_id):
        invoice = _invoice(business_id, invoice_id, actor_user_id)
        if invoice['status'] not in ('DRAFT','ISSUED') or list_invoice_payments(business_id, invoice_id):
            raise FinanceError('invoice_cannot_void')
        now = repo._now()
        db.execute("UPDATE finance_invoices SET status='VOID',updated_at=?,voided_at=?,voided_by_user_id=? WHERE business_id=? AND id=?",
                   (now, now, actor_user_id, business_id, invoice_id))
        _audit(business_id, actor_user_id, 'FINANCE_INVOICE_VOIDED', invoice_id)


def record_invoice_payment(business_id, invoice_id, amount_minor, paid_on, account_id, income_category_id,
                           note=None, actor_user_id=None, *, idempotency_key):
    """One explicit submission key, one payment, one ledger income. Reuse key on transport retry.

    Shared business lock serializes all Finance writers; helpers below never nest transactions.
    The unique key and all writes/audits commit together, including invoice state.
    """
    if not isinstance(idempotency_key, str) or not re.fullmatch('[a-zA-Z0-9_-]{16,80}', idempotency_key):
        raise FinanceError('invalid_payment_key')
    amount_minor, paid_on = _money(amount_minor, positive=True), _date(paid_on)
    note = _text(note, 1000)
    _id(invoice_id); _id(account_id); _id(income_category_id)
    with _write(business_id, actor_user_id):
        invoice = _invoice(business_id, invoice_id, actor_user_id)
        if branches.account_branch(business_id, account_id) != invoice['branch_id']:
            raise FinanceError('branch_mismatch')
        existing = db.query_one('SELECT * FROM finance_invoice_payments WHERE business_id=? AND idempotency_key=?',
                                 (business_id, idempotency_key))
        if existing:
            expected = dict(invoice_id=invoice_id, amount_minor=amount_minor, paid_on=paid_on,
                            account_id=account_id, category_id=income_category_id, note=note, created_by_user_id=actor_user_id)
            if any(existing[k] != v for k,v in expected.items()) or existing['ledger_transaction_id'] is None:
                raise FinanceError('payment_key_conflict')
            if idempotency_key.startswith('operator_'):
                finance_ai_safety.event('operator_replay')
            return existing['id']
        if invoice['status'] not in ('ISSUED','PARTIALLY_PAID'):
            raise FinanceError('invalid_invoice_state')
        totals = get_invoice_totals(business_id, invoice_id)
        if amount_minor > totals['outstanding_minor']:
            raise FinanceError('overpayment')
        data = _transaction_data(business_id, dict(direction='INCOME', amount_minor=amount_minor, currency='IDR',
            account_id=account_id, category_id=income_category_id, occurred_on=paid_on, description=None,
            counterparty_name=None, project_id=None, customer_id=invoice['customer_id'],
            source_type='FINANCE_INVOICE_PAYMENT', source_ref=None))
        now = repo._now()
        payment_id = db.insert_returning_id('INSERT INTO finance_invoice_payments '
            '(business_id,invoice_id,amount_minor,paid_on,account_id,category_id,note,idempotency_key,created_by_user_id,created_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?)', (business_id,invoice_id,amount_minor,paid_on,account_id,income_category_id,note,idempotency_key,actor_user_id,now))
        data['source_ref'] = str(payment_id)
        ledger_id = _insert_transaction(business_id, data, actor_user_id)
        db.execute('UPDATE finance_invoice_payments SET ledger_transaction_id=? WHERE business_id=? AND id=?',
                   (ledger_id,business_id,payment_id))
        remaining = get_invoice_totals(business_id, invoice_id)['outstanding_minor']
        db.execute('UPDATE finance_invoices SET status=?,updated_at=? WHERE business_id=? AND id=?',
                   ('PAID' if remaining == 0 else 'PARTIALLY_PAID', now, business_id, invoice_id))
        _audit(business_id, actor_user_id, 'FINANCE_INVOICE_PAYMENT_RECORDED', payment_id)
        return payment_id


def get_receivables_summary(business_id, actor_user_id=None, today=None):
    _scope(business_id, actor_user_id)
    # All monetary rows read in one statement; aggregate with Python integers, never floats.
    rows = db.query_all(('''SELECT i.due_date,
        (SELECT SUM(x.quantity*x.unit_price_minor) FROM finance_invoice_items x
         WHERE x.business_id=i.business_id AND x.invoice_id=i.id) AS total_minor,
        COALESCE((SELECT SUM(p.amount_minor) FROM finance_invoice_payments p
         WHERE p.business_id=i.business_id AND p.invoice_id=i.id),0) AS paid_minor
        FROM finance_invoices i WHERE i.business_id=?''' + branches.predicate('i') + " AND i.status IN ('ISSUED','PARTIALLY_PAID')"), (business_id,))
    result = dict(total_outstanding_minor=0, overdue_outstanding_minor=0, open_invoice_count=0, overdue_invoice_count=0)
    today = _date(today or date.today())
    for row in rows:
        remaining = int(row['total_minor'] or 0)-int(row['paid_minor'])
        if remaining > 0:
            result['total_outstanding_minor'] += remaining; result['open_invoice_count'] += 1
            if row['due_date'] < today:
                result['overdue_outstanding_minor'] += remaining; result['overdue_invoice_count'] += 1
    return result


def get_customer_cash_contribution(business_id, start_date, end_date, actor_user_id=None):
    _scope(business_id, actor_user_id)
    start, end = _period(start_date, end_date)
    rows = db.query_all(('SELECT customer_id,direction,amount_minor FROM finance_transactions WHERE business_id=?' + branches.predicate('') + " AND customer_id IS NOT NULL AND status='POSTED' AND currency='IDR' AND occurred_on>=? AND occurred_on<=?"), (business_id,start,end))
    result = {}
    for row in rows:
        item = result.setdefault(row['customer_id'], dict(customer_id=row['customer_id'],income_minor=0,expense_minor=0,net_cash_contribution_minor=0))
        key = 'income_minor' if row['direction'] == 'INCOME' else 'expense_minor'
        item[key] += row['amount_minor']
        item['net_cash_contribution_minor'] = item['income_minor']-item['expense_minor']
    return [result[k] for k in sorted(result)]


# Phase 2B: no GET/boot scheduler, no platform commerce amounts, no automatic external actions.
MAX_RECURRING_OCCURRENCES = 100


def _recurring_data(business_id, rule):
    return _transaction_data(business_id, dict(branch_id=rule.get('branch_id'), direction='EXPENSE', amount_minor=rule['amount_minor'],
        currency=rule['currency'], account_id=rule['account_id'], category_id=rule['category_id'],
        occurred_on=rule['next_due_on'], project_id=rule['project_id'], customer_id=None,
        counterparty_name=rule['counterparty_name'], description=rule['description'] or rule['name'],
        source_type='FINANCE_RECURRING_EXPENSE', source_ref=None))


def create_recurring_expense(business_id, name, amount_minor, account_id, category_id, cadence,
                             next_due_on, end_on=None, project_id=None, counterparty_name=None,
                             description=None, actor_user_id=None):
    name, cadence = _text(name,160,True), _enum(cadence,('WEEKLY','MONTHLY'))
    next_due_on = _date(next_due_on)
    end_on = _period(next_due_on,end_on)[1] if end_on is not None else None
    anchor = date.fromisoformat(next_due_on).day if cadence=='MONTHLY' else None
    rule = dict(name=name,amount_minor=amount_minor,currency='IDR',account_id=account_id,category_id=category_id,
                next_due_on=next_due_on,project_id=project_id,counterparty_name=counterparty_name,description=description)
    with _write(business_id,actor_user_id):
        data = _recurring_data(business_id,rule)
        now = repo._now()
        recurring_id = db.insert_returning_id('INSERT INTO finance_recurring_expenses '
            '(business_id,branch_id,name,amount_minor,account_id,category_id,project_id,counterparty_name,description,cadence,anchor_day,next_due_on,end_on,created_by_user_id,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (business_id,data['branch_id'],name,data['amount_minor'],account_id,category_id,
            data['project_id'],data['counterparty_name'],_text(description,4000),cadence,anchor,next_due_on,end_on,actor_user_id,now,now))
        _audit(business_id,actor_user_id,'FINANCE_RECURRING_CREATED',recurring_id)
        return recurring_id


def get_recurring_expense(business_id, recurring_id, actor_user_id=None):
    _scope(business_id,actor_user_id)
    return db.query_one(('SELECT *, (SELECT name FROM finance_branches b WHERE b.business_id=finance_recurring_expenses.business_id AND b.id=finance_recurring_expenses.branch_id) AS branch_name FROM finance_recurring_expenses WHERE business_id=?' + branches.predicate('') + ' AND id=?'),
                        (business_id,_id(recurring_id)))


def list_recurring_expenses(business_id, include_inactive=False, actor_user_id=None):
    _scope(business_id,actor_user_id)
    return db.query_all(('SELECT *, (SELECT name FROM finance_branches b WHERE b.business_id=finance_recurring_expenses.business_id AND b.id=finance_recurring_expenses.branch_id) AS branch_name FROM finance_recurring_expenses WHERE business_id=?' + branches.predicate()) +
        ('' if include_inactive else ' AND is_active=TRUE') + ' ORDER BY next_due_on,id',(business_id,))


def recurring_needs_attention(business_id, recurring_id, actor_user_id=None):
    """Read-only configuration check; safe category, never counterparty/account data in errors."""
    rule = get_recurring_expense(business_id,recurring_id,actor_user_id)
    if not rule:
        raise FinanceError('recurring_unavailable')
    try:
        _recurring_data(business_id,rule)
    except FinanceError:
        return True
    return False


def deactivate_recurring_expense(business_id, recurring_id, actor_user_id=None):
    with _write(business_id,actor_user_id):
        rule = get_recurring_expense(business_id,recurring_id,actor_user_id)
        if not rule:
            raise FinanceError('recurring_unavailable')
        if rule['is_active']:
            db.execute('UPDATE finance_recurring_expenses SET is_active=FALSE,updated_at=? WHERE business_id=? AND id=?',
                       (repo._now(),business_id,recurring_id))
            _audit(business_id,actor_user_id,'FINANCE_RECURRING_DEACTIVATED',recurring_id)


def list_recurring_postings(business_id, recurring_id, actor_user_id=None):
    if not get_recurring_expense(business_id,recurring_id,actor_user_id):
        raise FinanceError('recurring_unavailable')
    return db.query_all('SELECT * FROM finance_recurring_postings WHERE business_id=? AND recurring_expense_id=? ORDER BY scheduled_on,id',
                        (business_id,recurring_id))


def _next_recurring_date(rule):
    scheduled = date.fromisoformat(rule['next_due_on'])
    try:
        if rule['cadence']=='WEEKLY':
            return (scheduled+timedelta(days=7)).isoformat()
        month = scheduled.month % 12 + 1
        year = scheduled.year + (scheduled.month == 12)
        return date(year,month,min(rule['anchor_day'],calendar.monthrange(year,month)[1])).isoformat()
    except (ValueError,OverflowError):
        raise FinanceError('invalid_date') from None


def preview_due_recurring_expenses(business_id, as_of, actor_user_id=None):
    """Read-only next occurrence per rule; no future schedule is skipped."""
    _scope(business_id,actor_user_id);as_of=_date(as_of)
    rows=db.query_all(('SELECT r.*,a.name AS account_name,c.name AS category_name FROM finance_recurring_expenses r JOIN finance_accounts a ON a.business_id=r.business_id AND a.id=r.account_id JOIN finance_categories c ON c.business_id=r.business_id AND c.id=r.category_id WHERE r.business_id=?' + branches.predicate('r') + ' AND r.is_active=TRUE AND r.next_due_on<=? ORDER BY r.next_due_on,r.id LIMIT 100'),(business_id,as_of))
    result=[]
    for row in rows:
        if row['end_on'] and row['next_due_on']>row['end_on']:continue
        try:_recurring_data(business_id,row)
        except FinanceError:continue
        if not db.query_one('SELECT id FROM finance_recurring_postings WHERE business_id=? AND recurring_expense_id=? AND scheduled_on=?',(business_id,row['id'],row['next_due_on'])):
            result.append(dict(row,selection=f"{row['id']}:{row['next_due_on']}"))
    return result


def process_due_recurring_expenses(business_id, as_of, actor_user_id=None, max_occurrences=MAX_RECURRING_OCCURRENCES, selected=None):
    """At most 100 occurrences per call, including already-posted recovery checks.

    One business transaction: any SQL/audit failure rolls back all writes in this call. Invalid
    configuration stays due and is reported; other valid rules can progress. A shared business
    lock serializes UI/cron and the occurrence UNIQUE constraint adds duplicate protection.
    VOID is not a missing occurrence: its posting stays recorded and is never regenerated.
    """
    as_of = _date(as_of)
    if type(max_occurrences) is not int or not 1 <= max_occurrences <= MAX_RECURRING_OCCURRENCES:
        raise FinanceError('invalid_recurring_limit')
    if selected is not None:
        if not isinstance(selected,list) or not 1<=len(selected)<=100 or any(not isinstance(x,str) or not re.fullmatch(r'[1-9][0-9]{0,18}:[0-9]{4}-[0-9]{2}-[0-9]{2}',x) for x in selected):
            raise FinanceError('invalid_recurring_selection')
        selected=set(selected)
    posted, handled, attention = 0, 0, 0
    with _write(business_id,actor_user_id):
        rules = db.query_all(('SELECT *, (SELECT name FROM finance_branches b WHERE b.business_id=finance_recurring_expenses.business_id AND b.id=finance_recurring_expenses.branch_id) AS branch_name FROM finance_recurring_expenses WHERE business_id=?' + branches.predicate('') + ' AND is_active=TRUE AND next_due_on<=? ORDER BY next_due_on,id'), (business_id,as_of))
        for rule in rules:
            while rule['is_active'] and rule['next_due_on']<=as_of and handled<max_occurrences:
                if selected is not None and f"{rule['id']}:{rule['next_due_on']}" not in selected: break
                if rule['end_on'] and rule['next_due_on']>rule['end_on']:
                    deactivate_sql = 'UPDATE finance_recurring_expenses SET is_active=FALSE,updated_at=? WHERE business_id=? AND id=?'
                    db.execute(deactivate_sql,(repo._now(),business_id,rule['id']))
                    _audit(business_id,actor_user_id,'FINANCE_RECURRING_DEACTIVATED',rule['id'])
                    break
                try:
                    data = _recurring_data(business_id,rule)
                    next_due = _next_recurring_date(rule)
                except FinanceError:
                    attention += 1
                    break
                existing = db.query_one('SELECT ledger_transaction_id FROM finance_recurring_postings WHERE business_id=? AND recurring_expense_id=? AND scheduled_on=?',
                                         (business_id,rule['id'],rule['next_due_on']))
                if existing and existing['ledger_transaction_id'] is None:
                    attention += 1
                    break  # fail closed; never duplicate an unresolved occurrence
                if not existing:
                    posting_id = db.insert_returning_id('INSERT INTO finance_recurring_postings '
                        '(business_id,recurring_expense_id,scheduled_on,created_at) VALUES (?,?,?,?)',
                        (business_id,rule['id'],rule['next_due_on'],repo._now()))
                    data['source_ref'] = str(posting_id)
                    ledger_id = _insert_transaction(business_id,data,actor_user_id)
                    db.execute('UPDATE finance_recurring_postings SET ledger_transaction_id=? WHERE business_id=? AND id=?',
                               (ledger_id,business_id,posting_id))
                    _audit(business_id,actor_user_id,'FINANCE_RECURRING_POSTED',posting_id)
                    posted += 1
                handled += 1
                active = not rule['end_on'] or next_due<=rule['end_on']
                db.execute('UPDATE finance_recurring_expenses SET next_due_on=?,is_active=?,updated_at=? WHERE business_id=? AND id=?',
                           (next_due,active,repo._now(),business_id,rule['id']))
                if not active:
                    _audit(business_id,actor_user_id,'FINANCE_RECURRING_DEACTIVATED',rule['id'])
                rule.update(next_due_on=next_due,is_active=active)
        remaining = db.query_one(('SELECT id FROM finance_recurring_expenses WHERE business_id=?' + branches.predicate('') + ' AND is_active=TRUE AND next_due_on<=? LIMIT 1'),(business_id,as_of))
    return dict(posted_count=posted,needs_attention_count=attention,has_more=bool(remaining),limit_reached=handled>=max_occurrences and bool(remaining))


def list_finance_projects(business_id, actor_user_id=None):
    """Existing Client Hub project identity only, never platform billing amounts."""
    _scope(business_id,actor_user_id)
    return db.query_all('SELECT id,title,status FROM projects WHERE business_id=? ORDER BY title,id',(business_id,))


def get_project_cash_contribution(business_id, start_date, end_date, actor_user_id=None):
    _scope(business_id,actor_user_id)
    start,end = _period(start_date,end_date)
    rows = db.query_all(('SELECT t.project_id,p.title,p.status,t.direction,t.amount_minor FROM finance_transactions t JOIN projects p ON p.business_id=t.business_id AND p.id=t.project_id WHERE t.business_id=?' + branches.predicate('t') + " AND t.status='POSTED' AND t.currency='IDR' AND t.occurred_on>=? AND t.occurred_on<=? ORDER BY p.title,p.id,t.id"),(business_id,start,end))
    result = {}
    for row in rows:
        item = result.setdefault(row['project_id'],dict(project_id=row['project_id'],title=row['title'],status=row['status'],
            income_minor=0,expense_minor=0,net_cash_contribution_minor=0,transaction_count=0))
        item['income_minor' if row['direction']=='INCOME' else 'expense_minor'] += row['amount_minor']
        item['net_cash_contribution_minor'] = item['income_minor']-item['expense_minor']
        item['transaction_count'] += 1
    return list(result.values())


# Phase 3 reporting: read-only, IDR only. Limits apply before materializing large exports.
MAX_REPORT_ROWS = 50_000
MAX_COMMITMENT_OCCURRENCES = 1000


def report_period(start_date, end_date):
    start,end = _period(start_date,end_date)
    if (date.fromisoformat(end)-date.fromisoformat(start)).days+1 > 366:
        raise FinanceError('report_range')
    return start,end


def report_months(start_month, end_month):
    if not all(isinstance(m,str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}',m) for m in (start_month,end_month)):
        raise FinanceError('report_range')
    start,end = _period(start_month+'-01',end_month+'-01')
    a,b = date.fromisoformat(start),date.fromisoformat(end)
    count = (b.year-a.year)*12+b.month-a.month+1
    if count>12:
        raise FinanceError('report_range')
    return [f'{(a.year*12+a.month-1+n)//12:04d}-{(a.month-1+n)%12+1:02d}' for n in range(count)]


def _report_query(sql, params):
    rows = db.query_all(sql+' LIMIT ?',list(params)+[MAX_REPORT_ROWS+1])
    if len(rows)>MAX_REPORT_ROWS:
        raise FinanceError('report_limit')
    return rows


def get_report_transactions(business_id, start_date, end_date, actor_user_id=None, include_void=False):
    _scope(business_id,actor_user_id)
    start,end = report_period(start_date,end_date)
    return _report_query(('''SELECT t.branch_id,(SELECT name FROM finance_branches b WHERE b.id=t.branch_id AND b.business_id=t.business_id) AS branch_name,t.occurred_on,t.direction,t.amount_minor,t.status,t.source_type,
        t.counterparty_name,t.description,t.category_id,t.customer_id,t.project_id,
        a.name AS account_name,c.name AS category_name,u.name AS customer_name,p.title AS project_name
        FROM finance_transactions t
        LEFT JOIN finance_accounts a ON a.business_id=t.business_id AND a.id=t.account_id
        LEFT JOIN finance_categories c ON c.business_id=t.business_id AND c.id=t.category_id
        LEFT JOIN finance_customers u ON u.business_id=t.business_id AND u.id=t.customer_id
        LEFT JOIN projects p ON p.business_id=t.business_id AND p.id=t.project_id
        WHERE t.business_id=?''' + branches.predicate('t') + " AND t.currency='IDR' AND t.occurred_on>=? AND t.occurred_on<=?")+
        ('' if include_void else " AND t.status='POSTED'")+' ORDER BY t.occurred_on,t.id',(business_id,start,end))


def get_cashflow_report(business_id, start_date, end_date, actor_user_id=None):
    rows = get_report_transactions(business_id,start_date,end_date,actor_user_id)
    # Same integer-only cash calculation as the original Finance summary; adds count.
    income=sum(r['amount_minor'] for r in rows if r['direction']=='INCOME')
    expense=sum(r['amount_minor'] for r in rows if r['direction']=='EXPENSE')
    return dict(total_income_minor=income,total_expense_minor=expense,net_cashflow_minor=income-expense,transaction_count=len(rows))


def get_category_breakdown(business_id, start_date, end_date, actor_user_id=None):
    rows=get_report_transactions(business_id,start_date,end_date,actor_user_id)
    totals={'INCOME':0,'EXPENSE':0};groups={}
    for r in rows:
        item=groups.setdefault((r['direction'],r['category_id']),dict(direction=r['direction'],category_id=r['category_id'],
            name=r['category_name'] or 'Kategori tidak tersedia',amount_minor=0,transaction_count=0))
        item['amount_minor']+=r['amount_minor'];item['transaction_count']+=1;totals[r['direction']]+=r['amount_minor']
    for item in groups.values():
        denominator=totals[item['direction']]
        # Rounded basis points with arbitrary-precision integers. No float money or ratios.
        points=(item['amount_minor']*10000+denominator//2)//denominator if denominator else 0
        item['percentage']=f'{points//100}.{points%100:02d}'
    return sorted(groups.values(),key=lambda r:(r['direction'],-r['amount_minor'],r['name'],r['category_id']))


def get_account_balance_report(business_id, as_of, actor_user_id=None):
    _scope(business_id,actor_user_id);as_of=_date(as_of)
    accounts=_report_query(('SELECT branch_id,id,name,account_type,opening_balance_minor,is_active,(SELECT name FROM finance_branches b WHERE b.business_id=finance_accounts.business_id AND b.id=finance_accounts.branch_id) AS branch_name FROM finance_accounts WHERE business_id=?' + branches.predicate('') + " AND currency='IDR' ORDER BY name,id"),(business_id,))
    rows=_report_query(('SELECT account_id,direction,amount_minor FROM finance_transactions WHERE business_id=?' + branches.predicate('') + " AND status='POSTED' AND currency='IDR' AND occurred_on<=? ORDER BY id"),(business_id,as_of))
    groups={a['id']:dict(a,income_minor=0,expense_minor=0,balance_minor=a['opening_balance_minor']) for a in accounts}
    for r in rows:
        if r['account_id'] in groups:
            item=groups[r['account_id']];item['income_minor' if r['direction']=='INCOME' else 'expense_minor']+=r['amount_minor']
            item['balance_minor']=item['opening_balance_minor']+item['income_minor']-item['expense_minor']
    return list(groups.values())


def get_customer_contribution_report(business_id, start_date, end_date, actor_user_id=None):
    rows=get_report_transactions(business_id,start_date,end_date,actor_user_id)
    names={r['customer_id']:r['customer_name'] for r in rows if r['customer_id'] and r['customer_name'] is not None}
    counts={}
    for r in rows:
        if r['customer_id'] in names:counts[r['customer_id']]=counts.get(r['customer_id'],0)+1
    # Reuse Phase 2A cash contribution, decorating only with business-scoped display data.
    return [dict(r,name=names[r['customer_id']],transaction_count=counts[r['customer_id']])
        for r in get_customer_cash_contribution(business_id,start_date,end_date,actor_user_id) if r['customer_id'] in names]


def get_project_contribution_report(business_id, start_date, end_date, actor_user_id=None):
    get_report_transactions(business_id,start_date,end_date,actor_user_id)  # validates range/volume
    return get_project_cash_contribution(business_id,start_date,end_date,actor_user_id)


def get_report_invoices(business_id, as_of, start_date=None, end_date=None, actor_user_id=None,
                        customer_id=None, open_only=False):
    _scope(business_id,actor_user_id);as_of=_date(as_of)
    sql=('''SELECT i.branch_id,(SELECT name FROM finance_branches b WHERE b.id=i.branch_id AND b.business_id=i.business_id) AS branch_name,i.id,i.customer_id,i.invoice_number,i.issue_date,i.due_date,i.status,c.name AS customer_name,
        COALESCE((SELECT SUM(x.quantity*x.unit_price_minor) FROM finance_invoice_items x
            WHERE x.business_id=i.business_id AND x.invoice_id=i.id),0) AS total_minor,
        COALESCE((SELECT SUM(p.amount_minor) FROM finance_invoice_payments p
            WHERE p.business_id=i.business_id AND p.invoice_id=i.id AND p.paid_on<=?),0) AS paid_minor
        FROM finance_invoices i LEFT JOIN finance_customers c ON c.business_id=i.business_id AND c.id=i.customer_id
        WHERE i.business_id=?''' + branches.predicate('i') + " AND i.currency='IDR' AND i.issue_date<=?")
    params=[as_of,business_id,as_of]
    if customer_id is not None:
        if not get_customer(business_id, customer_id, actor_user_id):
            raise FinanceError('customer_unavailable')
        sql+=' AND i.customer_id=?';params.append(customer_id)
    if open_only:
        sql+=" AND i.status IN ('ISSUED','PARTIALLY_PAID')"
    if start_date is not None or end_date is not None:
        start,end=report_period(start_date,end_date)
        sql+=' AND i.issue_date>=? AND i.issue_date<=?';params.extend([start,end])
    rows=_report_query(sql+' ORDER BY i.issue_date,i.id',params)
    for r in rows:
        r['total_minor'],r['paid_minor']=int(r['total_minor']),int(r['paid_minor'])
        r['outstanding_minor']=r['total_minor']-r['paid_minor']
        r['days_late']=max(0,(date.fromisoformat(as_of)-date.fromisoformat(r['due_date'])).days)
        r['overdue']=r['status'] in ('ISSUED','PARTIALLY_PAID') and r['outstanding_minor']>0 and r['days_late']>0
    return rows


def get_receivables_aging(business_id, as_of, actor_user_id=None):
    return receivables_aging_rows(get_report_invoices(business_id,as_of,actor_user_id=actor_user_id))


def receivables_aging_rows(rows):
    """Shared deterministic aging for Phase 3 reports and the collection workspace."""
    labels=('Belum jatuh tempo','Telat Dibayar 1–30 Hari','Telat Dibayar 31–60 Hari','Telat Dibayar 61–90 Hari','>90 hari terlambat')
    buckets=[dict(label=label,amount_minor=0,invoice_count=0) for label in labels]
    for r in rows:
        # Current invoice state is authoritative; no historical issue/void status reconstruction.
        if r['status'] not in ('ISSUED','PARTIALLY_PAID') or r['outstanding_minor']<=0:continue
        days=r['days_late'];index=0 if days==0 else 1 if days<=30 else 2 if days<=60 else 3 if days<=90 else 4
        buckets[index]['amount_minor']+=r['outstanding_minor'];buckets[index]['invoice_count']+=1
    return dict(buckets=buckets,total_outstanding_minor=sum(b['amount_minor'] for b in buckets),
                total_overdue_minor=sum(b['amount_minor'] for b in buckets[1:]))


def get_upcoming_recurring_commitments(business_id, start_date, end_date, actor_user_id=None):
    _scope(business_id,actor_user_id);start,end=report_period(start_date,end_date)
    rules=_report_query(('''SELECT r.*,(SELECT name FROM finance_branches b WHERE b.business_id=r.business_id AND b.id=r.branch_id) AS branch_name,p.title AS project_name,a.name AS account_name,c.name AS category_name
        FROM finance_recurring_expenses r
        LEFT JOIN projects p ON p.business_id=r.business_id AND p.id=r.project_id
        LEFT JOIN finance_accounts a ON a.business_id=r.business_id AND a.id=r.account_id
        LEFT JOIN finance_categories c ON c.business_id=r.business_id AND c.id=r.category_id
        WHERE r.business_id=?''' + branches.predicate('r') + " AND r.is_active=TRUE AND r.currency='IDR' AND r.next_due_on<=?\n        ORDER BY r.next_due_on,r.id"),(business_id,end))
    result=[];start_day=date.fromisoformat(start)
    for rule in rules:
        current=date.fromisoformat(rule['next_due_on'])
        if current<start_day:
            if rule['cadence']=='WEEKLY':
                current+=timedelta(days=((start_day-current).days//7)*7)
            else:
                current=date(start_day.year,start_day.month,min(rule['anchor_day'],calendar.monthrange(start_day.year,start_day.month)[1]))
            rule['next_due_on']=current.isoformat()
            if current<start_day:rule['next_due_on']=_next_recurring_date(rule)
        last=min(end,rule['end_on']) if rule['end_on'] else end
        while rule['next_due_on']<=last:
            if len(result)>=MAX_COMMITMENT_OCCURRENCES:raise FinanceError('forecast_limit')
            result.append(dict(branch_name=rule['branch_name'],name=rule['name'],scheduled_on=rule['next_due_on'],amount_minor=rule['amount_minor'],
                project_name=rule['project_name'],account_name=rule['account_name'],category_name=rule['category_name']))
            if rule['next_due_on']==last:break
            try:rule['next_due_on']=_next_recurring_date(rule)
            except FinanceError:
                if last.startswith('9999-12'):break
                raise
    return sorted(result,key=lambda r:(r['scheduled_on'],r['name']))


def get_monthly_cashflow_trend(business_id, start_month, end_month, actor_user_id=None, start_date=None, end_date=None):
    months=report_months(start_month,end_month)
    year,month=map(int,end_month.split('-'))
    first=start_date or start_month+'-01'
    last=end_date or date(year,month,calendar.monthrange(year,month)[1]).isoformat()
    if first[:7]!=start_month or last[:7]!=end_month:raise FinanceError('report_range')
    rows=get_report_transactions(business_id,first,last,actor_user_id)
    trend={m:dict(month=m,income_minor=0,expense_minor=0,net_cashflow_minor=0) for m in months}
    for r in rows:
        item=trend[r['occurred_on'][:7]];item['income_minor' if r['direction']=='INCOME' else 'expense_minor']+=r['amount_minor']
        item['net_cashflow_minor']=item['income_minor']-item['expense_minor']
    return list(trend.values())


def operator_invoice_choices(business_id, actor_user_id=None):
    """Bounded picker only; does not load invoice notes or the whole history."""
    _scope(business_id,actor_user_id)
    return db.query_all(('SELECT id,invoice_number FROM finance_invoices WHERE business_id=?' + branches.predicate('') + " AND currency='IDR' AND status IN ('ISSUED','PARTIALLY_PAID') ORDER BY issue_date DESC,id DESC LIMIT 100"),(business_id,))


def find_receipt_transaction(business_id, receipt_hash, *, actor_user_id):
    """Read-only exact-file lookup. VOID origins remain reserved, within this tenant."""
    _scope(business_id, actor_user_id)
    if not isinstance(receipt_hash, str) or not re.fullmatch('[a-f0-9]{64}', receipt_hash):
        raise FinanceError('invalid_receipt_hash')
    return db.query_one(('SELECT *, (SELECT name FROM finance_branches b WHERE b.id=finance_transactions.branch_id AND b.business_id=finance_transactions.business_id) AS branch_name FROM finance_transactions WHERE business_id=?' + branches.predicate('') + ' AND source_type=? AND source_ref=? ORDER BY id LIMIT 1'),
                        (business_id, 'FINANCE_RECEIPT', receipt_hash))


def create_receipt_expense(business_id, receipt_hash, amount_minor, account_id, category_id,
                           occurred_on, *, description=None, counterparty_name=None, actor_user_id):
    """Explicit reviewed confirmation only. One existing business lock, one ledger + audit.

    Exact replay requires POSTED state, all accounting fields and original actor.
    A voided or edited receipt cannot silently create a replacement.
    """
    _id(actor_user_id)
    with _write(business_id, actor_user_id):
        data = _transaction_data(business_id, dict(direction='EXPENSE', currency='IDR',
            amount_minor=amount_minor, account_id=account_id, category_id=category_id,
            occurred_on=occurred_on, description=description, counterparty_name=counterparty_name,
            project_id=None, customer_id=None, source_type='FINANCE_RECEIPT', source_ref=receipt_hash))
        existing = find_receipt_transaction(business_id, receipt_hash, actor_user_id=actor_user_id)
        if existing:
            if (existing['status'] != 'POSTED' or existing['created_by_user_id'] != actor_user_id
                    or any(existing[key] != data[key] for key in FIELDS)):
                raise FinanceError('receipt_duplicate_conflict')
            return existing['id']
        return _insert_transaction(business_id, data, actor_user_id)
