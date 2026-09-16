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
import uuid

import db
import repo

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
        if data['source_type'] == 'FINANCE_INVOICE_PAYMENT':
            raise FinanceError('invoice_ledger_managed')
        return _insert_transaction(business_id, data, actor_user_id)


def _insert_transaction(business_id, data, actor_user_id):
    """Caller already holds the business lock; used by atomic Finance payment posting."""
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
        if current['source_type'] == 'FINANCE_INVOICE_PAYMENT' or changes.get('source_type') == 'FINANCE_INVOICE_PAYMENT':
            raise FinanceError('invoice_ledger_managed')
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
        if current['source_type'] == 'FINANCE_INVOICE_PAYMENT':
            raise FinanceError('invoice_ledger_managed')
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
            '(business_id,customer_id,invoice_number,issue_date,due_date,notes,created_by_user_id,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?)', (business_id, customer_id, 'KFIN-PENDING-'+uuid.uuid4().hex,
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
    return db.query_one('SELECT * FROM finance_invoices WHERE business_id=? AND id=?',
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
    row = db.query_one('''SELECT i.status,i.due_date,
        COALESCE((SELECT SUM(x.quantity*x.unit_price_minor) FROM finance_invoice_items x
                  WHERE x.business_id=i.business_id AND x.invoice_id=i.id),0) AS total_minor,
        COALESCE((SELECT SUM(p.amount_minor) FROM finance_invoice_payments p
                  WHERE p.business_id=i.business_id AND p.invoice_id=i.id),0) AS paid_minor
        FROM finance_invoices i WHERE i.business_id=? AND i.id=?''', (business_id, _id(invoice_id)))
    if not row:
        raise FinanceError('invoice_unavailable')
    total, paid = int(row['total_minor']), int(row['paid_minor'])
    outstanding = total-paid
    return dict(total_minor=total, paid_minor=paid, outstanding_minor=outstanding,
        overdue=row['status'] in ('ISSUED','PARTIALLY_PAID') and outstanding > 0 and
                row['due_date'] < _date(today or date.today()))


def list_finance_invoices(business_id, status=None, customer_id=None, actor_user_id=None):
    _scope(business_id, actor_user_id)
    sql, params = 'SELECT * FROM finance_invoices WHERE business_id=?', [business_id]
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
        existing = db.query_one('SELECT * FROM finance_invoice_payments WHERE business_id=? AND idempotency_key=?',
                                 (business_id, idempotency_key))
        if existing:
            expected = dict(invoice_id=invoice_id, amount_minor=amount_minor, paid_on=paid_on,
                            account_id=account_id, category_id=income_category_id, note=note, created_by_user_id=actor_user_id)
            if any(existing[k] != v for k,v in expected.items()) or existing['ledger_transaction_id'] is None:
                raise FinanceError('payment_key_conflict')
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
    rows = db.query_all('''SELECT i.due_date,
        (SELECT SUM(x.quantity*x.unit_price_minor) FROM finance_invoice_items x
         WHERE x.business_id=i.business_id AND x.invoice_id=i.id) AS total_minor,
        COALESCE((SELECT SUM(p.amount_minor) FROM finance_invoice_payments p
         WHERE p.business_id=i.business_id AND p.invoice_id=i.id),0) AS paid_minor
        FROM finance_invoices i WHERE i.business_id=? AND i.status IN ('ISSUED','PARTIALLY_PAID')''', (business_id,))
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
    rows = db.query_all("SELECT customer_id,direction,amount_minor FROM finance_transactions WHERE business_id=? "
        "AND customer_id IS NOT NULL AND status='POSTED' AND currency='IDR' AND occurred_on>=? AND occurred_on<=?", (business_id,start,end))
    result = {}
    for row in rows:
        item = result.setdefault(row['customer_id'], dict(customer_id=row['customer_id'],income_minor=0,expense_minor=0,net_cash_contribution_minor=0))
        key = 'income_minor' if row['direction'] == 'INCOME' else 'expense_minor'
        item[key] += row['amount_minor']
        item['net_cash_contribution_minor'] = item['income_minor']-item['expense_minor']
    return [result[k] for k in sorted(result)]
