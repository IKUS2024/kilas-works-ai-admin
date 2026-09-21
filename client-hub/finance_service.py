"""Phase 1A: tenant-scoped cash ledger, integer minor units, no UI/integration/AI.

Internal service API, like the existing business repositories. Future authenticated entry points
must resolve business_id using require_business_access(), never trust a client-supplied tenant.
Optional actor_user_id is checked against existing admin/membership rules on reads and writes;
None is reserved for trusted internal jobs. It is not an anonymous/public access mechanism.
No operation hard-deletes a transaction. All monetary amounts are caller-supplied integers in
minor units of the stated currency (IDR defaults); there is no conversion or float calculation.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import calendar
import hashlib
import json
import re
import uuid

import db
import repo
import finance_ai_safety
import finance_branches as branches

ACCOUNT_TYPES = ('CASH', 'BANK', 'EWALLET', 'OTHER')
LEGACY_ACCOUNT_TYPE_LABELS = {'CASH':'Tunai','BANK':'Rekening Bank','EWALLET':'E-Wallet','OTHER':'Lainnya'}
DEFAULT_ACCOUNT_TYPE_OPTIONS = (
    ('Credit', 'OTHER'),
    ('Debit', 'BANK'),
    ('Piutang', 'OTHER'),
    ('Tabungan', 'BANK'),
    ('E-wallet', 'EWALLET'),
    ('Wallet', 'CASH'),
)

def _account_type_display_name(name):
    text = (name or '').strip()
    return 'E-wallet' if text.casefold() == 'e-wallet' else text
DIRECTIONS = ('INCOME', 'EXPENSE')
SUPPORTED_CURRENCIES = ('IDR', 'USD', 'SGD', 'MYR', 'EUR', 'GBP', 'AUD', 'JPY', 'CNY', 'HKD', 'THB')
FIELDS = ('direction', 'amount_minor', 'currency', 'account_id', 'category_id', 'occurred_on',
          'description', 'counterparty_name', 'project_id', 'source_type', 'source_ref', 'customer_id')
DEFAULT_CATEGORIES = {
    'INCOME': ('Penjualan / Jasa', 'Subscription', 'Pendapatan Lain'),
    'EXPENSE': ('Biaya Sewa', 'Utilitas', 'Makanan & Belanja Harian', 'Perlengkapan',
                'Transportasi', 'Asuransi', 'Biaya Tak Terduga'),
}
DEFAULT_CATEGORY_CHILDREN = {
    'EXPENSE': {
        'Utilitas': ('Listrik', 'Air', 'Internet', 'Telepon', 'Gas', 'Laundry', 'Sampah / Kebersihan'),
    },
}


class FinanceError(ValueError):
    """Safe categories only: never includes supplied text or other tenant data."""


def business_today(business_id=None):
    """Business-local calendar date; falls back to the legacy server date safely."""
    if business_id is None:
        current=branches._current.get()
        business_id=current[0] if current else None
    if business_id is None:return date.today()
    profile=repo.get_business_profile(business_id) or {}
    name=(profile.get('timezone') or '').strip()
    if not name and str(profile.get('country') or '').strip().casefold()=='indonesia':name='Asia/Jakarta'
    if not name:return date.today()
    try:return datetime.now(ZoneInfo(name)).date()
    except (ZoneInfoNotFoundError,ValueError,TypeError):return date.today()

_finance_write = ContextVar('finance_write_owner', default=None)


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
    # A reviewed compound command may reuse Finance services under ONE existing
    # business lock. Never adopt an unrelated commerce transaction or another actor.
    if _finance_write.get() == (business_id, actor_user_id):
        _scope(business_id, actor_user_id)
        import finance_entitlements
        finance_entitlements.require_write(business_id, actor_user_id)
        branches.validate(business_id, write=True)
        yield
        return
    # Existing abstraction holds a business row lock and keeps nested DB/audit writes atomic.
    # No new transaction framework, no payment/project operation is called.
    with db.app_purchase_transaction(business_id, None):
        _scope(business_id, actor_user_id)
        import finance_entitlements
        finance_entitlements.require_write(business_id, actor_user_id)
        branches.validate(business_id, write=True)
        token = _finance_write.set((business_id, actor_user_id))
        try:
            yield
        finally:
            _finance_write.reset(token)


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
    value = value.strip().upper()
    if value not in SUPPORTED_CURRENCIES:
        raise FinanceError('unsupported_currency')
    return value


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


def _materialize_account_type_options(business_id):
    rows = db.query_all(
        'SELECT id,name,is_active FROM finance_account_type_options WHERE business_id=? ORDER BY id',
        (business_id,))
    known = {(row['name'] or '').strip().casefold() for row in rows}
    now = repo._now()
    for name, legacy_type in DEFAULT_ACCOUNT_TYPE_OPTIONS:
        if name.casefold() in known:
            continue
        db.insert_returning_id(
            'INSERT INTO finance_account_type_options '
            '(business_id,name,legacy_type,is_default,is_active,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?)',
            (business_id, name, legacy_type, True, True, now, now))
        known.add(name.casefold())


def _account_type_option_by_name(business_id, name, include_inactive=False):
    key = (name or '').strip().casefold()
    if not key:
        return None
    rows = db.query_all(
        'SELECT * FROM finance_account_type_options WHERE business_id=? ORDER BY id',
        (business_id,))
    return next((row for row in rows
                 if (row['name'] or '').strip().casefold() == key
                 and (include_inactive or row['is_active'])), None)


def list_account_type_options(business_id, include_inactive=False, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    rows = db.query_all(
        'SELECT * FROM finance_account_type_options WHERE business_id=? ORDER BY id',
        (business_id,))
    if not rows:
        return [
            dict(id=None, business_id=business_id, name=name, legacy_type=legacy_type,
                 is_default=True, is_active=True)
            for name, legacy_type in DEFAULT_ACCOUNT_TYPE_OPTIONS
        ]
    if not include_inactive:
        rows = [row for row in rows if row['is_active']]
    result = []
    for raw in rows:
        row = dict(raw)
        row['name'] = _account_type_display_name(row.get('name'))
        result.append(row)
    return result


def create_account_type_option(business_id, name, *, actor_user_id=None):
    name = _text(name, 80, True)
    with _write(business_id, actor_user_id):
        _materialize_account_type_options(business_id)
        existing = _account_type_option_by_name(business_id, name, include_inactive=True)
        if existing:
            if not existing['is_active']:
                db.execute(
                    'UPDATE finance_account_type_options SET is_active=TRUE,updated_at=? '
                    'WHERE business_id=? AND id=?',
                    (repo._now(), business_id, existing['id']))
                _audit(business_id, actor_user_id, 'FINANCE_ACCOUNT_TYPE_REACTIVATED', existing['id'])
            return existing['id']
        now = repo._now()
        record_id = db.insert_returning_id(
            'INSERT INTO finance_account_type_options '
            '(business_id,name,legacy_type,is_default,is_active,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?)',
            (business_id, name, 'OTHER', False, True, now, now))
        _audit(business_id, actor_user_id, 'FINANCE_ACCOUNT_TYPE_CREATED', record_id)
        return record_id


def delete_account_type_option(business_id, name, *, actor_user_id=None):
    name = _text(name, 80, True)
    with _write(business_id, actor_user_id):
        _materialize_account_type_options(business_id)
        existing = _account_type_option_by_name(business_id, name)
        if not existing:
            raise FinanceError('account_type_unavailable')
        db.execute(
            'UPDATE finance_account_type_options SET is_active=FALSE,updated_at=? '
            'WHERE business_id=? AND id=?',
            (repo._now(), business_id, existing['id']))
        _audit(business_id, actor_user_id, 'FINANCE_ACCOUNT_TYPE_DEACTIVATED', existing['id'])


def _assign_account_type_option(business_id, account_id, option_id):
    now = repo._now()
    db.execute(
        'INSERT INTO finance_account_type_assignments '
        '(business_id,account_id,option_id,created_at,updated_at) VALUES (?,?,?,?,?) '
        'ON CONFLICT(business_id,account_id) DO UPDATE SET '
        'option_id=excluded.option_id,updated_at=excluded.updated_at',
        (business_id, account_id, option_id, now, now))


def account_type_label_map(business_id, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    rows = db.query_all(
        'SELECT a.account_id,o.name FROM finance_account_type_assignments a '
        'JOIN finance_account_type_options o '
        'ON o.business_id=a.business_id AND o.id=a.option_id '
        'WHERE a.business_id=?',
        (business_id,))
    return {row['account_id']: _account_type_display_name(row['name']) for row in rows}


def _label_accounts(business_id, rows, actor_user_id=None):
    labels = account_type_label_map(business_id, actor_user_id=actor_user_id)
    result = []
    for raw in rows:
        row = dict(raw)
        row['account_type_label'] = labels.get(
            row['id'], LEGACY_ACCOUNT_TYPE_LABELS.get(row['account_type'], 'Lainnya'))
        result.append(row)
    return result


def create_account(business_id, name, account_type='CASH', currency='IDR', opening_balance_minor=0,
                   *, account_type_label=None, actor_user_id=None):
    name = _text(name, 160, True)
    currency = _currency(currency)
    opening_balance_minor = _money(opening_balance_minor)
    label = _text(account_type_label, 80, True) if account_type_label is not None else None
    legacy_type = None if label is not None else _enum(account_type, ACCOUNT_TYPES)
    with _write(business_id, actor_user_id):
        option = None
        if label is not None:
            _materialize_account_type_options(business_id)
            option = _account_type_option_by_name(business_id, label)
            if not option:
                raise FinanceError('account_type_unavailable')
            legacy_type = _enum(option['legacy_type'], ACCOUNT_TYPES)
        branch_id = branches.write_branch(business_id, actor_user_id)
        existing = db.query_one(
            ('SELECT id,is_active FROM finance_accounts WHERE business_id=?' +
             branches.predicate('') +
             ' AND branch_id=? AND name=? AND account_type=? AND currency=?'),
            (business_id, branch_id, name, legacy_type, currency))
        if existing:
            if not existing['is_active']:
                db.execute(
                    'UPDATE finance_accounts SET is_active=TRUE,updated_at=? WHERE business_id=? AND id=?',
                    (repo._now(), business_id, existing['id']))
                _audit(business_id, actor_user_id, 'FINANCE_ACCOUNT_REACTIVATED', existing['id'])
            if option:
                _assign_account_type_option(business_id, existing['id'], option['id'])
            return existing['id']
        account_id = _create_account(
            business_id, name, legacy_type, currency, opening_balance_minor, actor_user_id)
        if option:
            _assign_account_type_option(business_id, account_id, option['id'])
        return account_id


def list_accounts(business_id, include_inactive=False, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    rows = db.query_all(
        ('SELECT * FROM finance_accounts WHERE business_id=?' + branches.predicate()) +
        ('' if include_inactive else ' AND is_active=TRUE') + ' ORDER BY id',
        (business_id,))
    return _label_accounts(business_id, rows, actor_user_id)


def get_account(business_id, account_id, *, actor_user_id=None, active=False):
    _scope(business_id,actor_user_id)
    row=db.query_one(('SELECT * FROM finance_accounts WHERE business_id=?' + branches.predicate('') + ' AND id=?'),
                     (business_id,_id(account_id)))
    if not row or (active and not row['is_active']):raise FinanceError('account_unavailable')
    _currency(row['currency'])
    return _label_accounts(business_id, [row], actor_user_id)[0]


def update_account_opening_balance(business_id, account_id, opening_balance_minor, *, actor_user_id=None):
    opening_balance_minor=_money(opening_balance_minor)
    with _write(business_id,actor_user_id):
        branches.account_branch(business_id,account_id)
        row=db.query_one(
            'SELECT id FROM finance_accounts WHERE business_id=? AND id=? AND is_active=TRUE',
            (business_id,_id(account_id)))
        if not row:raise FinanceError('account_unavailable')
        db.execute(
            'UPDATE finance_accounts SET opening_balance_minor=?,updated_at=? WHERE business_id=? AND id=?',
            (opening_balance_minor,repo._now(),business_id,account_id))
        _audit(business_id,actor_user_id,'FINANCE_ACCOUNT_OPENING_BALANCE_UPDATED',account_id)
    return opening_balance_minor


def set_account_current_balance(business_id, account_id, target_balance_minor, *, actor_user_id=None):
    target_balance_minor=_money(target_balance_minor)
    with _write(business_id,actor_user_id):
        branches.account_branch(business_id,account_id)
        account=get_account(business_id,account_id,actor_user_id=actor_user_id,active=True)
        balances=get_account_balance_report(
            business_id,business_today(business_id).isoformat(),actor_user_id)
        current=next((row for row in balances if row['id']==account_id),None)
        if not current:raise FinanceError('account_unavailable')
        delta=_money(target_balance_minor-int(current['balance_minor']))
        new_opening=_money(int(account['opening_balance_minor'])+delta)
        db.execute(
            'UPDATE finance_accounts SET opening_balance_minor=?,updated_at=? WHERE business_id=? AND id=?',
            (new_opening,repo._now(),business_id,account_id))
        _audit(business_id,actor_user_id,'FINANCE_ACCOUNT_BALANCE_ADJUSTED',account_id)
    return new_opening


def _create_category(business_id, direction, name, actor_user_id):
    now = repo._now()
    record_id = db.insert_returning_id(
        'INSERT INTO finance_categories (business_id,direction,name,created_at,updated_at) VALUES (?,?,?,?,?)',
        (business_id, direction, name, now, now))
    _audit(business_id, actor_user_id, 'FINANCE_CATEGORY_CREATED', record_id)
    return record_id


def _link_category_parent(business_id, child_category_id, parent_category_id):
    child = db.query_one(
        'SELECT id,direction FROM finance_categories WHERE business_id=? AND id=?',
        (business_id, _id(child_category_id)))
    parent = db.query_one(
        'SELECT id,direction,is_active FROM finance_categories WHERE business_id=? AND id=?',
        (business_id, _id(parent_category_id)))
    if not child or not parent or not parent['is_active']:
        raise FinanceError('category_unavailable')
    if child['id'] == parent['id'] or child['direction'] != parent['direction']:
        raise FinanceError('category_parent_mismatch')
    if db.query_one(
        'SELECT 1 FROM finance_category_hierarchy WHERE business_id=? AND child_category_id=?',
        (business_id, parent['id'])):
        raise FinanceError('category_parent_mismatch')
    db.execute(
        'INSERT INTO finance_category_hierarchy '
        '(business_id,child_category_id,parent_category_id,created_at) VALUES (?,?,?,?) '
        'ON CONFLICT(business_id,child_category_id) DO UPDATE SET parent_category_id=excluded.parent_category_id',
        (business_id, child['id'], parent['id'], repo._now()))


def create_category(business_id, direction, name, *, parent_category_id=None, actor_user_id=None):
    direction, name = _enum(direction, DIRECTIONS), _text(name, 160, True)
    with _write(business_id, actor_user_id):
        existing = db.query_one(
            'SELECT id,is_active FROM finance_categories WHERE business_id=? AND direction=? AND name=?',
            (business_id, direction, name))
        if existing:
            if not existing['is_active']:
                db.execute(
                    'UPDATE finance_categories SET is_active=TRUE,updated_at=? WHERE business_id=? AND id=?',
                    (repo._now(), business_id, existing['id']))
                _audit(business_id, actor_user_id, 'FINANCE_CATEGORY_REACTIVATED', existing['id'])
            category_id = existing['id']
        else:
            category_id = _create_category(business_id, direction, name, actor_user_id)
        if parent_category_id is not None:
            _link_category_parent(business_id, category_id, parent_category_id)
        return category_id


def list_categories(business_id, direction=None, include_inactive=False, include_children=False, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    sql = (
        'SELECT c.*,h.parent_category_id,p.name AS parent_name '
        'FROM finance_categories c '
        'LEFT JOIN finance_category_hierarchy h '
        'ON h.business_id=c.business_id AND h.child_category_id=c.id '
        'LEFT JOIN finance_categories p '
        'ON p.business_id=c.business_id AND p.id=h.parent_category_id '
        'WHERE c.business_id=?'
    )
    params = [business_id]
    if direction is not None:
        sql += ' AND c.direction=?'; params.append(_enum(direction, DIRECTIONS))
    if not include_inactive:
        sql += ' AND c.is_active=TRUE'
    if not include_children:
        sql += ' AND h.child_category_id IS NULL'
    rows = [dict(row) for row in db.query_all(sql + ' ORDER BY c.direction,c.id', params)]
    return rows


def list_category_children(business_id, parent_category_id, include_inactive=False, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    parent_id = _id(parent_category_id)
    sql = (
        'SELECT c.*,h.parent_category_id,p.name AS parent_name '
        'FROM finance_category_hierarchy h '
        'JOIN finance_categories c '
        'ON c.business_id=h.business_id AND c.id=h.child_category_id '
        'JOIN finance_categories p '
        'ON p.business_id=h.business_id AND p.id=h.parent_category_id '
        'WHERE h.business_id=? AND h.parent_category_id=?'
    )
    if not include_inactive:
        sql += ' AND c.is_active=TRUE'
    return [dict(row) for row in db.query_all(sql + ' ORDER BY c.id', (business_id, parent_id))]


def resolve_category_selection(business_id, direction, category_id, subcategory_id=None, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    direction = _enum(direction, DIRECTIONS)
    category_id = _id(category_id)
    parent = db.query_one(
        'SELECT id,direction,is_active FROM finance_categories WHERE business_id=? AND id=?',
        (business_id, category_id))
    if not parent or not parent['is_active'] or parent['direction'] != direction:
        raise FinanceError('category_unavailable')
    if db.query_one(
        'SELECT 1 FROM finance_category_hierarchy WHERE business_id=? AND child_category_id=?',
        (business_id, category_id)):
        raise FinanceError('category_parent_mismatch')
    children = list_category_children(
        business_id, category_id, actor_user_id=actor_user_id)
    if not children:
        if subcategory_id not in (None, ''):
            raise FinanceError('subcategory_unavailable')
        return category_id
    if subcategory_id in (None, ''):
        raise FinanceError('subcategory_required')
    child_id = _id(subcategory_id)
    if not any(row['id'] == child_id and row['direction'] == direction for row in children):
        raise FinanceError('subcategory_unavailable')
    return child_id


def ensure_finance_defaults(business_id, *, actor_user_id=None):
    """Explicit only, never called on boot. Existing names/balances/active flags are untouched."""
    with _write(business_id, actor_user_id):
        branch_id = branches.write_branch(business_id, actor_user_id)
        if not db.query_one(('SELECT id FROM finance_accounts WHERE business_id=?' + branches.predicate('') + " AND branch_id=? AND name=? AND account_type='CASH' AND currency='IDR'"),
                            (business_id, branch_id, 'Kas')):
            _create_account(business_id, 'Kas', 'CASH', 'IDR', 0, actor_user_id)
        category_ids = {}
        for direction, names in DEFAULT_CATEGORIES.items():
            for name in names:
                row = db.query_one(
                    'SELECT id,is_active FROM finance_categories WHERE business_id=? AND direction=? AND name=?',
                    (business_id, direction, name))
                if not row:
                    category_id = _create_category(business_id, direction, name, actor_user_id)
                else:
                    category_id = row['id']
                category_ids[(direction, name)] = category_id
        for direction, parents in DEFAULT_CATEGORY_CHILDREN.items():
            for parent_name, child_names in parents.items():
                parent_id = category_ids.get((direction, parent_name))
                if parent_id is None:
                    continue
                for child_name in child_names:
                    row = db.query_one(
                        'SELECT id,is_active FROM finance_categories WHERE business_id=? AND direction=? AND name=?',
                        (business_id, direction, child_name))
                    if row:
                        child_id = row['id']
                        if not row['is_active']:
                            db.execute(
                                'UPDATE finance_categories SET is_active=TRUE,updated_at=? WHERE business_id=? AND id=?',
                                (repo._now(), business_id, child_id))
                    else:
                        child_id = _create_category(
                            business_id, direction, child_name, actor_user_id)
                    _link_category_parent(business_id, child_id, parent_id)


def _transaction_data(business_id, data, *, scheduled=False):
    data = dict(data)
    data['direction'] = _enum(data['direction'], DIRECTIONS)
    data['amount_minor'] = _money(data['amount_minor'], positive=True)
    data['currency'] = _currency(data['currency'])
    data['occurred_on'] = _date(data['occurred_on'])
    if not scheduled and data['occurred_on'] > business_today(business_id).isoformat():
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
    if data['direction'] == 'EXPENSE' and data.get('counterparty_name'):
        _ensure_payee(business_id, data['branch_id'], data['counterparty_name'], actor_user_id)
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
                      account_id=None, customer_id=None, project_id=None, category_id=None, currency=None,
                      limit=100, offset=0, actor_user_id=None):
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
    for key,value in (('customer_id',customer_id),('project_id',project_id),('category_id',category_id)):
        if value is not None:sql+=' AND '+key+'=?';params.append(_id(value))
    if currency is not None:sql+=' AND currency=?';params.append(_currency(currency))
    return db.query_all(sql + ' ORDER BY occurred_on DESC,id DESC LIMIT ? OFFSET ?', params + [limit, offset])


def count_transactions(business_id, *, start_date=None, end_date=None, direction=None, status=None,
                       account_id=None, customer_id=None, project_id=None, category_id=None, currency=None,actor_user_id=None):
    """Count the same scoped transaction set used by list_transactions without materializing rows."""
    _scope(business_id, actor_user_id)
    sql, params = ('SELECT COUNT(*) AS n FROM finance_transactions WHERE business_id=?' + branches.predicate()), [business_id]
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
    for key,value in (('customer_id',customer_id),('project_id',project_id),('category_id',category_id)):
        if value is not None:sql+=' AND '+key+'=?';params.append(_id(value))
    if currency is not None:sql+=' AND currency=?';params.append(_currency(currency))
    row = db.query_one(sql, params)
    return int(row['n']) if row else 0


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
        db.execute("UPDATE finance_fx_exchanges SET status='VOID',voided_at=COALESCE(voided_at,?),voided_by_user_id=COALESCE(voided_by_user_id,?),updated_at=? WHERE business_id=? AND branch_id=? AND status='POSTED'",
                   (now,actor_user_id,now,business_id,branch_id))
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


def get_finance_summaries(business_id, start_date, end_date, *, actor_user_id=None):
    """Cash movement grouped by original currency; currencies are never silently mixed."""
    return get_cash_totals(business_id,start_date,end_date,actor_user_id=actor_user_id)


def _money_sum():
    """Exact aggregation even when multiple int64 entries exceed int64 in total.

    Postgres SUM(bigint) returns numeric. SQLite SUM overflows and TOTAL loses
    precision, so its aggregate returns decimal text, converted to Python int.
    """
    if db.BACKEND!='sqlite':return 'SUM'
    class IntegerSum:
        def __init__(self):self.total=0
        def step(self,value):self.total+=int(value or 0)
        def finalize(self):return str(self.total)
    db.get_connection().create_aggregate('finance_integer_sum',1,IntegerSum)
    return 'finance_integer_sum'


def _ensure_payee(business_id, branch_id, name, actor_user_id):
    """Create/reactivate one branch-scoped payee while the caller already holds Finance's write lock."""
    name = _text(name, 160, True)
    branches.get(business_id, branch_id, active=True)
    row = db.query_one(
        'SELECT id,is_active FROM finance_payees WHERE business_id=? AND branch_id=? AND name=?',
        (business_id, branch_id, name))
    if row:
        if not row['is_active']:
            db.execute(
                'UPDATE finance_payees SET is_active=TRUE,updated_at=? WHERE business_id=? AND id=?',
                (repo._now(), business_id, row['id']))
            _audit(business_id, actor_user_id, 'FINANCE_PAYEE_REACTIVATED', row['id'])
        return row['id']
    now = repo._now()
    payee_id = db.insert_returning_id(
        'INSERT INTO finance_payees '
        '(business_id,branch_id,name,is_active,created_by_user_id,created_at,updated_at) '
        'VALUES (?,?,?,TRUE,?,?,?)',
        (business_id, branch_id, name, actor_user_id, now, now))
    _audit(business_id, actor_user_id, 'FINANCE_PAYEE_CREATED', payee_id)
    return payee_id


def create_payee(business_id, name, *, actor_user_id=None):
    """HomeBudget-style manual Payee creation; no ledger transaction is posted."""
    name = _text(name, 160, True)
    with _write(business_id, actor_user_id):
        branch_id = branches.write_branch(business_id, actor_user_id)
        return _ensure_payee(business_id, branch_id, name, actor_user_id)


def update_payee(business_id, payee_id, name, *, actor_user_id=None):
    """Rename active payee master data and its descriptive references without changing money."""
    name = _text(name, 160, True)
    with _write(business_id, actor_user_id):
        branch_id = branches.write_branch(business_id, actor_user_id)
        payee = db.query_one(
            'SELECT * FROM finance_payees WHERE business_id=? AND branch_id=? AND id=?',
            (business_id, branch_id, _id(payee_id)))
        if not payee or not payee['is_active']:
            raise FinanceError('payee_unavailable')
        duplicate = db.query_one(
            'SELECT id FROM finance_payees WHERE business_id=? AND branch_id=? AND name=? AND id<>?',
            (business_id, branch_id, name, payee['id']))
        if duplicate:
            raise FinanceError('payee_exists')
        old_name = payee['name']
        now = repo._now()
        db.execute(
            'UPDATE finance_payees SET name=?,updated_at=? WHERE business_id=? AND branch_id=? AND id=?',
            (name, now, business_id, branch_id, payee['id']))
        if old_name != name:
            db.execute(
                "UPDATE finance_transactions SET counterparty_name=?,updated_at=? "
                "WHERE business_id=? AND branch_id=? AND direction='EXPENSE' AND counterparty_name=?",
                (name, now, business_id, branch_id, old_name))
            db.execute(
                'UPDATE finance_recurring_expenses SET counterparty_name=?,updated_at=? '
                'WHERE business_id=? AND branch_id=? AND counterparty_name=?',
                (name, now, business_id, branch_id, old_name))
        _audit(business_id, actor_user_id, 'FINANCE_PAYEE_UPDATED', payee['id'])
        return payee['id']


def deactivate_payee(business_id, payee_id, *, actor_user_id=None):
    """Hide a payee from active master data; historical ledger descriptions stay intact."""
    with _write(business_id, actor_user_id):
        branch_id = branches.write_branch(business_id, actor_user_id)
        payee = db.query_one(
            'SELECT * FROM finance_payees WHERE business_id=? AND branch_id=? AND id=?',
            (business_id, branch_id, _id(payee_id)))
        if not payee:
            raise FinanceError('payee_unavailable')
        if payee['is_active'] and db.query_one(
                'SELECT 1 FROM finance_recurring_expenses '
                'WHERE business_id=? AND branch_id=? AND counterparty_name=? '
                'AND is_active=TRUE LIMIT 1',
                (business_id, branch_id, payee['name'])):
            raise FinanceError('payee_in_use')
        if payee['is_active']:
            db.execute(
                'UPDATE finance_payees SET is_active=FALSE,updated_at=? '
                'WHERE business_id=? AND branch_id=? AND id=?',
                (repo._now(), business_id, branch_id, payee['id']))
            _audit(business_id, actor_user_id, 'FINANCE_PAYEE_DEACTIVATED', payee['id'])
        return payee['id']


def list_payees(business_id, include_inactive=False, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    sql = ('SELECT * FROM finance_payees WHERE business_id=?' + branches.predicate(''))
    if not include_inactive:
        sql += ' AND is_active=TRUE'
    return db.query_all(sql + ' ORDER BY name,id', (business_id,))


def list_payee_summaries(business_id, start_date=None, end_date=None, *, actor_user_id=None):
    """HomeBudget-style Payees plus their expense totals; manual payees can exist before first payment."""
    _scope(business_id, actor_user_id)
    where = ("business_id=?" + branches.predicate("") +
             " AND status='POSTED' AND direction='EXPENSE' " +
             "AND counterparty_name IS NOT NULL AND TRIM(counterparty_name)<>''")
    params = [business_id]
    if start_date is not None and end_date is not None:
        _period(start_date, end_date)
    for value, clause in ((start_date, 'occurred_on>=?'), (end_date, 'occurred_on<=?')):
        if value is not None:
            where += ' AND ' + clause
            params.append(_date(value))
    money_sum = _money_sum()
    rows = db.query_all(
        ("SELECT counterparty_name AS name,currency," + money_sum +
         "(amount_minor) AS total_minor,COUNT(*) AS transaction_count," +
         "MAX(occurred_on) AS last_paid_on FROM finance_transactions WHERE " +
         where + " GROUP BY counterparty_name,currency " +
         "ORDER BY MAX(occurred_on) DESC,counterparty_name,currency"),
        params)
    all_payees = list_payees(
        business_id, include_inactive=True, actor_user_id=actor_user_id)
    active_by_name = {payee['name']: payee for payee in all_payees if payee['is_active']}
    inactive_names = {payee['name'] for payee in all_payees if not payee['is_active']}
    visible_rows = []
    for row in rows:
        row['total_minor'] = int(row['total_minor'])
        row['transaction_count'] = int(row['transaction_count'])
        _currency(row['currency'])
        # Deleting a payee hides it from the Payee master list only. The source
        # transactions remain untouched and continue to count in Finance reports.
        if row['name'] in inactive_names:
            continue
        row['payee_id'] = active_by_name.get(row['name'], {}).get('id')
        visible_rows.append(row)
    rows = visible_rows

    # A Payee is master data, not a fake Rp0 ledger entry. For presentation only,
    # emit a zero-total IDR summary when it has never been used yet.
    active_payees = [payee for payee in all_payees if payee['is_active']]
    names_with_transactions = {row['name'] for row in rows}
    for payee in active_payees:
        if payee['name'] not in names_with_transactions:
            rows.append(dict(
                payee_id=payee['id'], name=payee['name'], currency='IDR',
                total_minor=0, transaction_count=0, last_paid_on=None))
    return rows


def get_cash_totals(business_id, start_date=None, end_date=None, *, actor_user_id=None,
                    account_id=None, customer_id=None, project_id=None, category_id=None,
                    currency=None, direction=None, group_by=None):
    """Complete native-currency totals, including all time, without exporting ledger rows.

    Shared by manual summaries and conversation. The export's 366-day/row bounds
    must not truncate totals. Opening balances and FX are separate records.
    """
    _scope(business_id,actor_user_id)
    where='t.business_id=?'+branches.predicate('t')+" AND t.status='POSTED'"
    params=[business_id]
    if start_date is not None and end_date is not None:_period(start_date,end_date)
    for value,clause in ((start_date,'t.occurred_on>=?'),(end_date,'t.occurred_on<=?')):
        if value is not None:where+=' AND '+clause;params.append(_date(value))
    for key,value in (('account_id',account_id),('customer_id',customer_id),('project_id',project_id),('category_id',category_id)):
        if value is not None:where+=' AND t.'+key+'=?';params.append(_id(value))
    if currency:where+=' AND t.currency=?';params.append(_currency(currency))
    if direction:where+=' AND t.direction=?';params.append(_enum(direction,DIRECTIONS))
    dimensions={
        'account':('t.account_id','a.name'), 'category':('t.category_id','c.name'),
        'customer':('t.customer_id','u.name'), 'project':('t.project_id','p.title'),
        'branch':('t.branch_id','b.name')}
    if group_by is not None and group_by not in dimensions:raise FinanceError('invalid_enum')
    extra='';group='t.currency'
    if group_by:
        ident,label=dimensions[group_by];extra=f', {ident} AS entity_id, {label} AS name';group+=f', {ident}, {label}'
    money_sum=_money_sum()
    sql='''SELECT t.currency,
        COALESCE(SUM(CASE WHEN t.direction='INCOME' THEN t.amount_minor ELSE 0 END),0) AS total_income_minor,
        COALESCE(SUM(CASE WHEN t.direction='EXPENSE' THEN t.amount_minor ELSE 0 END),0) AS total_expense_minor,
        COUNT(*) AS transaction_count'''+extra+''' FROM finance_transactions t
        LEFT JOIN finance_accounts a ON a.business_id=t.business_id AND a.id=t.account_id
        LEFT JOIN finance_categories c ON c.business_id=t.business_id AND c.id=t.category_id
        LEFT JOIN finance_customers u ON u.business_id=t.business_id AND u.id=t.customer_id
        LEFT JOIN projects p ON p.business_id=t.business_id AND p.id=t.project_id
        LEFT JOIN finance_branches b ON b.business_id=t.business_id AND b.id=t.branch_id
        WHERE '''+where+' GROUP BY '+group+' ORDER BY t.currency'
    rows=db.query_all(sql.replace('SUM(',money_sum+'('),params)
    for row in rows:
        _currency(row['currency'])
        for key in ('total_income_minor','total_expense_minor','transaction_count'):row[key]=int(row[key])
        row['net_cashflow_minor']=row['total_income_minor']-row['total_expense_minor']
    return sorted(rows,key=lambda r:SUPPORTED_CURRENCIES.index(r['currency']))


def get_transaction_date_bounds(business_id, *, actor_user_id=None):
    """First/last active ledger dates in the current business/branch scope."""
    _scope(business_id, actor_user_id)
    row = db.query_one(('SELECT MIN(occurred_on) AS first_on,MAX(occurred_on) AS last_on '
                        'FROM finance_transactions WHERE business_id=?' + branches.predicate('') +
                        " AND status='POSTED'"), (business_id,))
    return {'first_on': row['first_on'] if row else None, 'last_on': row['last_on'] if row else None}


# Finance receivables: deliberately never reads platform invoices/payments/payment_service.
def create_customer(business_id, name, phone=None, email=None, notes=None, actor_user_id=None, *, idempotency_key=None):
    from finance_draft_fields import customer_values
    values = customer_values(dict(name=name,phone=phone,email=email,notes=notes))
    with _write(business_id, actor_user_id):
        if idempotency_key is not None:
            if not isinstance(idempotency_key,str) or not re.fullmatch('[a-f0-9]{32}',idempotency_key):
                raise FinanceError('invalid_customer_key')
            marker='draft='+idempotency_key+';id='
            previous=db.query_one('SELECT detail FROM audit_log WHERE business_id=? AND actor_user_id=? AND action=? AND detail LIKE ?',
                (business_id,actor_user_id,'FINANCE_ASSISTANT_CUSTOMER_CONFIRMED',marker+'%'))
            if previous:
                existing=get_customer(business_id,int(previous['detail'].removeprefix(marker)),actor_user_id)
                if not existing or tuple(existing[k] for k in ('name','phone','email','notes'))!=values:
                    raise FinanceError('customer_key_conflict')
                return existing['id']
        now = repo._now()
        customer_id = db.insert_returning_id('INSERT INTO finance_customers '
            '(business_id,name,phone,email,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?)',
            (business_id, *values, now, now))
        _audit(business_id, actor_user_id, 'FINANCE_CUSTOMER_CREATED', customer_id)
        if idempotency_key is not None:
            repo.write_audit(actor_user_id,business_id,'FINANCE_ASSISTANT_CUSTOMER_CONFIRMED',marker+str(customer_id))
        return customer_id


def get_customer(business_id, customer_id, actor_user_id=None):
    _scope(business_id, actor_user_id)
    return db.query_one('SELECT * FROM finance_customers WHERE business_id=? AND id=?',
                        (business_id, _id(customer_id)))


def list_customers(business_id, include_inactive=False, actor_user_id=None):
    _scope(business_id, actor_user_id)
    return db.query_all('SELECT * FROM finance_customers WHERE business_id=?' +
        ('' if include_inactive else ' AND is_active=TRUE') + ' ORDER BY name,id', (business_id,))


def update_customer(business_id, customer_id, name, phone=None, email=None, notes=None, *, actor_user_id=None):
    from finance_draft_fields import customer_values
    values = customer_values(dict(name=name, phone=phone, email=email, notes=notes))
    with _write(business_id, actor_user_id):
        row = get_customer(business_id, customer_id, actor_user_id)
        if not row or not row['is_active']:
            raise FinanceError('customer_unavailable')
        db.execute('UPDATE finance_customers SET name=?,phone=?,email=?,notes=?,updated_at=? WHERE business_id=? AND id=?',
                   (*values, repo._now(), business_id, row['id']))
        _audit(business_id, actor_user_id, 'FINANCE_CUSTOMER_UPDATED', row['id'])
        return row['id']


def delete_customer(business_id, customer_id, *, actor_user_id=None):
    with _write(business_id, actor_user_id):
        row = get_customer(business_id, customer_id, actor_user_id)
        if not row:
            raise FinanceError('customer_unavailable')
        if row['is_active']:
            db.execute('UPDATE finance_customers SET is_active=FALSE,updated_at=? WHERE business_id=? AND id=?',
                       (repo._now(), business_id, row['id']))
            _audit(business_id, actor_user_id, 'FINANCE_CUSTOMER_DELETED', row['id'])
        return row['id']


def create_finance_invoice(business_id, customer_id, issue_date, due_date, items, notes=None, currency='IDR', actor_user_id=None, *, idempotency_key=None):
    issue_date, due_date = _period(issue_date, due_date)
    currency=_currency(currency)
    if issue_date > business_today(business_id).isoformat():
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
        marker=None
        if idempotency_key is not None:
            if not isinstance(idempotency_key,str) or not re.fullmatch('[a-f0-9]{32}',idempotency_key):
                raise FinanceError('invalid_invoice_key')
            marker='draft='+idempotency_key+';id='
            previous=db.query_one('SELECT detail FROM audit_log WHERE business_id=? AND actor_user_id=? AND action=? AND detail LIKE ?',
                (business_id,actor_user_id,'FINANCE_ASSISTANT_INVOICE_CONFIRMED',marker+'%'))
            if previous:
                existing=get_finance_invoice(business_id,int(previous['detail'].removeprefix(marker)),actor_user_id)
                old_items=list_invoice_items(business_id,existing['id'],actor_user_id) if existing else []
                if (not existing or tuple(existing[k] for k in ('customer_id','issue_date','due_date','currency','notes')) !=
                        (customer_id,issue_date,due_date,currency,notes) or
                        [(r['description'],r['quantity'],r['unit_price_minor']) for r in old_items] != clean):
                    raise FinanceError('invoice_key_conflict')
                return existing['id']
        customer = get_customer(business_id, customer_id, actor_user_id)
        if not customer or not customer['is_active']:
            raise FinanceError('customer_unavailable')
        now = repo._now()
        invoice_id = db.insert_returning_id('INSERT INTO finance_invoices '
            '(business_id,branch_id,customer_id,invoice_number,issue_date,due_date,currency,notes,created_by_user_id,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?)', (business_id, branches.write_branch(business_id, actor_user_id), customer_id, 'KFIN-PENDING-'+uuid.uuid4().hex,
            issue_date, due_date, currency, notes, actor_user_id, now, now))
        number = f'KFIN-{issue_date[:4]}-{invoice_id:06d}'
        db.execute('UPDATE finance_invoices SET invoice_number=? WHERE business_id=? AND id=?', (number, business_id, invoice_id))
        for description, quantity, price in clean:
            db.execute('INSERT INTO finance_invoice_items '
                '(business_id,invoice_id,description,quantity,unit_price_minor,created_at) VALUES (?,?,?,?,?,?)',
                (business_id, invoice_id, description, quantity, price, now))
        _audit(business_id, actor_user_id, 'FINANCE_INVOICE_CREATED', invoice_id)
        if marker is not None:
            repo.write_audit(actor_user_id,business_id,'FINANCE_ASSISTANT_INVOICE_CONFIRMED',marker+str(invoice_id))
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
                row['due_date'] < _date(today or business_today(business_id)))


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


def _invoice_archive_states(business_id, actor_user_id=None):
    """UI-only invoice archive state from the audit log.

    Archiving never changes invoice/payment/ledger accounting state. The latest
    archive/restore event wins, so paid history remains available and reversible.
    """
    _scope(business_id, actor_user_id)
    rows=db.query_all("""SELECT action,detail FROM audit_log
        WHERE business_id=? AND action IN ('FINANCE_INVOICE_ARCHIVED','FINANCE_INVOICE_RESTORED')
        ORDER BY id""",(business_id,))
    archived=set()
    for row in rows:
        match=re.fullmatch(r'finance_record_id=(\d+)',row['detail'] or '')
        if not match:continue
        ident=int(match[1])
        if row['action']=='FINANCE_INVOICE_ARCHIVED':archived.add(ident)
        else:archived.discard(ident)
    return archived


def archived_invoice_ids(business_id, actor_user_id=None):
    return _invoice_archive_states(business_id,actor_user_id)


def archive_finance_invoice(business_id, invoice_id, actor_user_id=None):
    """Hide a fully paid invoice from the working list without touching accounting."""
    with _write(business_id,actor_user_id):
        invoice=_invoice(business_id,invoice_id,actor_user_id)
        totals=get_invoice_totals(business_id,invoice_id,actor_user_id)
        if invoice['status']!='PAID' or totals['outstanding_minor']!=0:
            raise FinanceError('invoice_archive_requires_paid')
        if invoice['id'] not in _invoice_archive_states(business_id,actor_user_id):
            _audit(business_id,actor_user_id,'FINANCE_INVOICE_ARCHIVED',invoice['id'])
        return invoice['id']


def restore_finance_invoice(business_id, invoice_id, actor_user_id=None):
    """Restore a UI-archived invoice. Accounting was never changed."""
    with _write(business_id,actor_user_id):
        invoice=_invoice(business_id,invoice_id,actor_user_id)
        if invoice['status']!='PAID':raise FinanceError('invoice_archive_requires_paid')
        if invoice['id'] in _invoice_archive_states(business_id,actor_user_id):
            _audit(business_id,actor_user_id,'FINANCE_INVOICE_RESTORED',invoice['id'])
        return invoice['id']


def update_finance_invoice_notes(business_id, invoice_id, notes=None, actor_user_id=None):
    """Edit non-financial invoice notes in any non-void state.

    Totals, items, payment history, status and linked income stay immutable.
    """
    notes=_text(notes,4000)
    with _write(business_id,actor_user_id):
        invoice=_invoice(business_id,invoice_id,actor_user_id)
        if invoice['status']=='VOID':raise FinanceError('invoice_unavailable')
        db.execute('UPDATE finance_invoices SET notes=?,updated_at=? WHERE business_id=? AND id=?',
                   (notes,repo._now(),business_id,invoice['id']))
        _audit(business_id,actor_user_id,'FINANCE_INVOICE_NOTES_UPDATED',invoice['id'])
        return invoice['id']


def invoice_fingerprint(business_id, invoice, actor_user_id=None):
    fields={k:invoice[k] for k in ('id','customer_id','issue_date','due_date','currency','notes')}
    fields['items']=[{k:r[k] for k in ('description','quantity','unit_price_minor')} for r in list_invoice_items(business_id,invoice['id'],actor_user_id)]
    return hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()


def issue_finance_invoice(business_id, invoice_id, actor_user_id=None, *, idempotency_key=None, expected_fingerprint=None):
    with _write(business_id, actor_user_id):
        invoice = _invoice(business_id, invoice_id, actor_user_id)
        marker=None
        if expected_fingerprint is not None and invoice_fingerprint(business_id,invoice,actor_user_id)!=expected_fingerprint:
            raise FinanceError('invalid_draft')
        if idempotency_key is not None:
            if not isinstance(idempotency_key,str) or not re.fullmatch('[a-f0-9]{32}',idempotency_key):raise FinanceError('invalid_invoice_key')
            marker='draft='+idempotency_key+';id='+str(invoice_id)
            if db.query_one('SELECT id FROM audit_log WHERE business_id=? AND actor_user_id=? AND action=? AND detail=?',
                            (business_id,actor_user_id,'FINANCE_ASSISTANT_ISSUE_CONFIRMED',marker)):
                return invoice_id
        if invoice['status'] != 'DRAFT':
            raise FinanceError('invalid_invoice_state')
        # Zero-priced drafts are allowed but cannot create a permanently open zero receivable.
        if get_invoice_totals(business_id, invoice_id)['total_minor'] <= 0:
            raise FinanceError('empty_invoice_total')
        db.execute("UPDATE finance_invoices SET status='ISSUED',updated_at=? WHERE business_id=? AND id=?",
                   (repo._now(), business_id, invoice_id))
        _audit(business_id, actor_user_id, 'FINANCE_INVOICE_ISSUED', invoice_id)
        if marker is not None:repo.write_audit(actor_user_id,business_id,'FINANCE_ASSISTANT_ISSUE_CONFIRMED',marker)


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
    if paid_on > business_today(business_id).isoformat():
        raise FinanceError('future_date')
    note = _text(note, 1000)
    _id(invoice_id); _id(account_id); _id(income_category_id)
    with _write(business_id, actor_user_id):
        invoice = _invoice(business_id, invoice_id, actor_user_id)
        if branches.account_branch(business_id, account_id) != invoice['branch_id']:
            raise FinanceError('branch_mismatch')
        account=get_account(business_id,account_id,actor_user_id=actor_user_id,active=True)
        if account['currency']!=invoice['currency']:raise FinanceError('account_currency_mismatch')
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
        data = _transaction_data(business_id, dict(direction='INCOME', amount_minor=amount_minor, currency=invoice['currency'],
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
    rows = db.query_all(('''SELECT i.currency,i.due_date,
        (SELECT SUM(x.quantity*x.unit_price_minor) FROM finance_invoice_items x
         WHERE x.business_id=i.business_id AND x.invoice_id=i.id) AS total_minor,
        COALESCE((SELECT SUM(p.amount_minor) FROM finance_invoice_payments p
         WHERE p.business_id=i.business_id AND p.invoice_id=i.id),0) AS paid_minor
        FROM finance_invoices i WHERE i.business_id=?''' + branches.predicate('i') +
        " AND i.status IN ('ISSUED','PARTIALLY_PAID')"), (business_id,))
    today = _date(today or business_today(business_id))
    groups={}
    open_count=overdue_count=0
    for row in rows:
        currency=_currency(row['currency'])
        remaining=int(row['total_minor'] or 0)-int(row['paid_minor'] or 0)
        if remaining<=0: continue
        item=groups.setdefault(currency,dict(currency=currency,total_outstanding_minor=0,
            overdue_outstanding_minor=0,open_invoice_count=0,overdue_invoice_count=0))
        item['total_outstanding_minor']+=remaining;item['open_invoice_count']+=1;open_count+=1
        if row['due_date']<today:
            item['overdue_outstanding_minor']+=remaining;item['overdue_invoice_count']+=1;overdue_count+=1
    by_currency=[groups[c] for c in SUPPORTED_CURRENCIES if c in groups]
    idr=groups.get('IDR',dict(currency='IDR',total_outstanding_minor=0,overdue_outstanding_minor=0,
        open_invoice_count=0,overdue_invoice_count=0))
    return dict(idr,by_currency=by_currency,open_invoice_count=open_count,overdue_invoice_count=overdue_count)

def get_customer_cash_contribution(business_id, start_date, end_date, actor_user_id=None):
    _scope(business_id, actor_user_id)
    start,end=_period(start_date,end_date)
    rows=db.query_all(('SELECT customer_id,currency,direction,amount_minor FROM finance_transactions WHERE business_id=?' +
        branches.predicate('') + " AND customer_id IS NOT NULL AND status='POSTED' AND occurred_on>=? AND occurred_on<=?"),
        (business_id,start,end))
    result={}
    for row in rows:
        currency=_currency(row['currency']);key=(row['customer_id'],currency)
        item=result.setdefault(key,dict(customer_id=row['customer_id'],currency=currency,income_minor=0,
            expense_minor=0,net_cash_contribution_minor=0))
        item['income_minor' if row['direction']=='INCOME' else 'expense_minor']+=row['amount_minor']
        item['net_cash_contribution_minor']=item['income_minor']-item['expense_minor']
    return [result[k] for k in sorted(result,key=lambda x:(x[0],SUPPORTED_CURRENCIES.index(x[1])))]

# Phase 2B: no GET/boot scheduler, no platform commerce amounts, no automatic external actions.
MAX_RECURRING_OCCURRENCES = 100


def _recurring_data(business_id, rule, *, scheduled=False):
    return _transaction_data(business_id, dict(branch_id=rule.get('branch_id'), direction='EXPENSE', amount_minor=rule['amount_minor'],
        currency=rule['currency'], account_id=rule['account_id'], category_id=rule['category_id'],
        occurred_on=rule['next_due_on'], project_id=rule['project_id'], customer_id=None,
        counterparty_name=rule['counterparty_name'], description=rule['description'] or rule['name'],
        source_type='FINANCE_RECURRING_EXPENSE', source_ref=None), scheduled=scheduled)


def create_recurring_expense(business_id, name, amount_minor, account_id, category_id, cadence,
                             next_due_on, end_on=None, project_id=None, counterparty_name=None,
                             description=None, actor_user_id=None, *, idempotency_key=None, expected_currency=None):
    if idempotency_key is not None and (not isinstance(idempotency_key,str) or not re.fullmatch('[a-f0-9]{64}',idempotency_key)):
        raise FinanceError('invalid_recurring_key')
    name, cadence = _text(name,160,True), _enum(cadence,('WEEKLY','MONTHLY'))
    next_due_on = _date(next_due_on)
    end_on = _period(next_due_on,end_on)[1] if end_on is not None else None
    anchor = date.fromisoformat(next_due_on).day if cadence=='MONTHLY' else None
    with _write(business_id,actor_user_id):
        account=get_account(business_id,_id(account_id),actor_user_id=actor_user_id,active=True)
        if expected_currency is not None and account['currency']!=_currency(expected_currency):
            raise FinanceError('account_currency_mismatch')
        rule = dict(name=name,amount_minor=amount_minor,currency=account['currency'],account_id=account_id,category_id=category_id,
                    next_due_on=next_due_on,project_id=project_id,counterparty_name=counterparty_name,description=description)
        data = _recurring_data(business_id,rule,scheduled=True)
        if idempotency_key:
            marker='draft_digest='+idempotency_key+';id='
            previous=db.query_one('SELECT detail FROM audit_log WHERE business_id=? AND actor_user_id=? AND action=? AND detail LIKE ?',
                (business_id,actor_user_id,'FINANCE_ASSISTANT_RECURRING_CONFIRMED',marker+'%'))
            if previous:
                existing=get_recurring_expense(business_id,int(previous['detail'].removeprefix(marker)),actor_user_id)
                if not existing:raise FinanceError('recurring_unavailable')
                return existing['id']
        now = repo._now()
        recurring_id = db.insert_returning_id('INSERT INTO finance_recurring_expenses '
            '(business_id,branch_id,name,amount_minor,currency,account_id,category_id,project_id,counterparty_name,description,cadence,anchor_day,next_due_on,end_on,created_by_user_id,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (business_id,data['branch_id'],name,data['amount_minor'],data['currency'],account_id,category_id,
            data['project_id'],data['counterparty_name'],_text(description,4000),cadence,anchor,next_due_on,end_on,actor_user_id,now,now))
        _audit(business_id,actor_user_id,'FINANCE_RECURRING_CREATED',recurring_id)
        if idempotency_key:
            repo.write_audit(actor_user_id,business_id,'FINANCE_ASSISTANT_RECURRING_CONFIRMED',marker+str(recurring_id))
        return recurring_id


def update_recurring_expense(business_id, recurring_id, name, amount_minor, account_id,
                             category_id, cadence, next_due_on, end_on=None,
                             project_id=None, counterparty_name=None, description=None,
                             actor_user_id=None, *, expected_currency=None):
    """Edit only the future recurring rule; already-posted ledger history is immutable."""
    name, cadence = _text(name,160,True), _enum(cadence,('WEEKLY','MONTHLY'))
    next_due_on = _date(next_due_on)
    end_on = _period(next_due_on,end_on)[1] if end_on is not None else None
    anchor = date.fromisoformat(next_due_on).day if cadence=='MONTHLY' else None
    with _write(business_id,actor_user_id):
        existing = get_recurring_expense(
            business_id, _id(recurring_id), actor_user_id)
        if not existing or not existing['is_active']:
            raise FinanceError('recurring_unavailable')
        account = get_account(
            business_id, _id(account_id), actor_user_id=actor_user_id, active=True)
        if not account:
            raise FinanceError('account_unavailable')
        if expected_currency is not None and account['currency'] != _currency(expected_currency):
            raise FinanceError('account_currency_mismatch')
        rule = dict(
            branch_id=existing['branch_id'], name=name, amount_minor=amount_minor,
            currency=account['currency'], account_id=account_id,
            category_id=category_id, next_due_on=next_due_on,
            project_id=project_id, counterparty_name=counterparty_name,
            description=description)
        data = _recurring_data(business_id, rule, scheduled=True)
        now = repo._now()
        db.execute(
            'UPDATE finance_recurring_expenses SET '
            'name=?,amount_minor=?,currency=?,account_id=?,category_id=?,project_id=?,'
            'counterparty_name=?,description=?,cadence=?,anchor_day=?,next_due_on=?,end_on=?,updated_at=? '
            'WHERE business_id=? AND branch_id=? AND id=?',
            (name, data['amount_minor'], data['currency'], account_id, category_id,
             data['project_id'], data['counterparty_name'], _text(description,4000),
             cadence, anchor, next_due_on, end_on, now,
             business_id, existing['branch_id'], existing['id']))
        _audit(business_id,actor_user_id,'FINANCE_RECURRING_UPDATED',existing['id'])
        return existing['id']


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
        _recurring_data(business_id,rule,scheduled=True)
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
    rows=db.query_all(('''SELECT r.*,a.name AS account_name,c.name AS category_name,
        pc.name AS parent_category_name
        FROM finance_recurring_expenses r
        JOIN finance_accounts a ON a.business_id=r.business_id AND a.id=r.account_id
        JOIN finance_categories c ON c.business_id=r.business_id AND c.id=r.category_id
        LEFT JOIN finance_category_hierarchy h ON h.business_id=c.business_id AND h.child_category_id=c.id
        LEFT JOIN finance_categories pc ON pc.business_id=h.business_id AND pc.id=h.parent_category_id
        WHERE r.business_id=?''' + branches.predicate('r') +
        ' AND r.is_active=TRUE AND r.next_due_on<=? ORDER BY r.next_due_on,r.id LIMIT 100'),(business_id,as_of))
    result=[]
    for row in rows:
        row=dict(row)
        if row.get('parent_category_name'):
            row['category_name']=row['parent_category_name']+' / '+row['category_name']
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
    start,end=_period(start_date,end_date)
    rows=db.query_all(('SELECT t.project_id,p.title,p.status,t.currency,t.direction,t.amount_minor FROM finance_transactions t '
        'JOIN projects p ON p.business_id=t.business_id AND p.id=t.project_id WHERE t.business_id=?' +
        branches.predicate('t') + " AND t.status='POSTED' AND t.occurred_on>=? AND t.occurred_on<=? ORDER BY p.title,p.id,t.id"),
        (business_id,start,end))
    result={}
    for row in rows:
        currency=_currency(row['currency']);key=(row['project_id'],currency)
        item=result.setdefault(key,dict(project_id=row['project_id'],title=row['title'],status=row['status'],currency=currency,
            income_minor=0,expense_minor=0,net_cash_contribution_minor=0,transaction_count=0))
        item['income_minor' if row['direction']=='INCOME' else 'expense_minor']+=row['amount_minor']
        item['net_cash_contribution_minor']=item['income_minor']-item['expense_minor'];item['transaction_count']+=1
    return list(result.values())


# Phase 3 reporting: read-only multi-currency. Monetary totals are never combined across currencies.

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
    start,end=report_period(start_date,end_date)
    return _report_query(('''SELECT t.branch_id,(SELECT name FROM finance_branches b WHERE b.id=t.branch_id AND b.business_id=t.business_id) AS branch_name,
        t.occurred_on,t.direction,t.amount_minor,t.currency,t.status,t.source_type,t.counterparty_name,t.description,
        t.category_id,t.customer_id,t.project_id,a.name AS account_name,c.name AS category_name,
        pc.name AS parent_category_name,u.name AS customer_name,p.title AS project_name
        FROM finance_transactions t
        LEFT JOIN finance_accounts a ON a.business_id=t.business_id AND a.id=t.account_id
        LEFT JOIN finance_categories c ON c.business_id=t.business_id AND c.id=t.category_id
        LEFT JOIN finance_category_hierarchy h ON h.business_id=c.business_id AND h.child_category_id=c.id
        LEFT JOIN finance_categories pc ON pc.business_id=h.business_id AND pc.id=h.parent_category_id
        LEFT JOIN finance_customers u ON u.business_id=t.business_id AND u.id=t.customer_id
        LEFT JOIN projects p ON p.business_id=t.business_id AND p.id=t.project_id
        WHERE t.business_id=?''' + branches.predicate('t') + " AND t.occurred_on>=? AND t.occurred_on<=?")+
        ('' if include_void else " AND t.status='POSTED'")+' ORDER BY t.occurred_on,t.id',(business_id,start,end))


def get_cashflow_reports(business_id,start_date,end_date,actor_user_id=None):
    rows=get_report_transactions(business_id,start_date,end_date,actor_user_id)
    groups={}
    for row in rows:
        code=_currency(row['currency'])
        item=groups.setdefault(code,dict(currency=code,total_income_minor=0,total_expense_minor=0,
            net_cashflow_minor=0,transaction_count=0))
        item['total_income_minor' if row['direction']=='INCOME' else 'total_expense_minor']+=row['amount_minor']
        item['net_cashflow_minor']=item['total_income_minor']-item['total_expense_minor'];item['transaction_count']+=1
    if not groups:groups['IDR']=dict(currency='IDR',total_income_minor=0,total_expense_minor=0,net_cashflow_minor=0,transaction_count=0)
    return [groups[c] for c in SUPPORTED_CURRENCIES if c in groups]


def get_cashflow_report(business_id,start_date,end_date,actor_user_id=None):
    rows=get_cashflow_reports(business_id,start_date,end_date,actor_user_id)
    return next((r for r in rows if r['currency']=='IDR'),
        dict(currency='IDR',total_income_minor=0,total_expense_minor=0,net_cashflow_minor=0,transaction_count=0))


def get_category_breakdown(business_id,start_date,end_date,actor_user_id=None):
    rows=get_report_transactions(business_id,start_date,end_date,actor_user_id)
    totals={};groups={}
    for r in rows:
        code=_currency(r['currency']);total_key=(code,r['direction'])
        totals[total_key]=totals.get(total_key,0)+r['amount_minor']
        key=(code,r['direction'],r['category_id'])
        category_name=r['category_name'] or 'Kategori tidak tersedia'
        if r.get('parent_category_name'):
            category_name=r['parent_category_name']+' / '+category_name
        item=groups.setdefault(key,dict(currency=code,direction=r['direction'],category_id=r['category_id'],
            name=category_name,amount_minor=0,transaction_count=0))
        item['amount_minor']+=r['amount_minor'];item['transaction_count']+=1
    for item in groups.values():
        denominator=totals.get((item['currency'],item['direction']),0)
        points=(item['amount_minor']*10000+denominator//2)//denominator if denominator else 0
        item['percentage']=f'{points//100}.{points%100:02d}'
    return sorted(groups.values(),key=lambda r:(SUPPORTED_CURRENCIES.index(r['currency']),r['direction'],
        -r['amount_minor'],r['name'],r['category_id']))

def get_account_balance_report(business_id, as_of, actor_user_id=None):
    _scope(business_id,actor_user_id);as_of=_date(as_of)
    accounts=_report_query(('SELECT branch_id,id,name,account_type,currency,opening_balance_minor,is_active,(SELECT name FROM finance_branches b WHERE b.business_id=finance_accounts.business_id AND b.id=finance_accounts.branch_id) AS branch_name FROM finance_accounts WHERE business_id=?' + branches.predicate('') + ' ORDER BY currency,name,id'),(business_id,))
    accounts=_label_accounts(business_id,accounts,actor_user_id)
    rows=db.query_all(('SELECT account_id,currency,direction,'+_money_sum()+'(amount_minor) AS amount_minor FROM finance_transactions WHERE business_id=?' + branches.predicate('') + " AND status='POSTED' AND occurred_on<=? GROUP BY account_id,currency,direction"),(business_id,as_of))
    groups={a['id']:dict(a,income_minor=0,expense_minor=0,exchange_in_minor=0,exchange_out_minor=0,balance_minor=a['opening_balance_minor']) for a in accounts}
    for row in rows:
        if row['account_id'] in groups and groups[row['account_id']]['currency']==row['currency']:
            item=groups[row['account_id']];item['income_minor' if row['direction']=='INCOME' else 'expense_minor']+=int(row['amount_minor'])
    exchanges=db.query_all(('SELECT from_account_id,to_account_id,from_amount_minor,to_amount_minor FROM finance_fx_exchanges WHERE business_id=?' +
        branches.predicate('') + " AND status='POSTED' AND occurred_on<=? ORDER BY id"),(business_id,as_of))
    for row in exchanges:
        if row['from_account_id'] in groups:groups[row['from_account_id']]['exchange_out_minor']+=row['from_amount_minor']
        if row['to_account_id'] in groups:groups[row['to_account_id']]['exchange_in_minor']+=row['to_amount_minor']
    for item in groups.values():
        item['balance_minor']=item['opening_balance_minor']+item['income_minor']-item['expense_minor']+item['exchange_in_minor']-item['exchange_out_minor']
    return list(groups.values())


def aggregate_account_balances_by_currency(accounts):
    """Aggregate one already-read account snapshot without re-reading the ledger."""
    fields = ('opening_balance_minor','income_minor','expense_minor','exchange_in_minor',
              'exchange_out_minor','balance_minor')
    totals = {}
    for account in accounts:
        currency = _currency(account['currency'])
        item = totals.setdefault(currency, dict(currency=currency, **{field:0 for field in fields}))
        for field in fields:
            item[field] += int(account.get(field, 0))
    return [totals[code] for code in SUPPORTED_CURRENCIES if code in totals]


def get_balance_totals_by_currency(business_id, as_of, actor_user_id=None):
    return aggregate_account_balances_by_currency(
        get_account_balance_report(business_id, as_of, actor_user_id))


def list_currency_exchanges(business_id,actor_user_id=None,limit=100):
    _scope(business_id,actor_user_id)
    if type(limit) is not int or not 1<=limit<=500:raise FinanceError('invalid_pagination')
    return db.query_all(('''SELECT finance_fx_exchanges.*,
        (SELECT name FROM finance_accounts a WHERE a.business_id=finance_fx_exchanges.business_id AND a.id=finance_fx_exchanges.from_account_id) AS from_account_name,
        (SELECT name FROM finance_accounts a WHERE a.business_id=finance_fx_exchanges.business_id AND a.id=finance_fx_exchanges.to_account_id) AS to_account_name
        FROM finance_fx_exchanges WHERE business_id=?''' + branches.predicate('') +
        ' ORDER BY occurred_on DESC,id DESC LIMIT ?'),(business_id,limit))


def record_currency_exchange(business_id,from_account_id,to_account_id,from_amount_minor,to_amount_minor,occurred_on,
                             *,note=None,reference_rate=None,rate_source=None,rate_as_of=None,actor_user_id=None):
    occurred_on=_date(occurred_on)
    if occurred_on>business_today(business_id).isoformat():raise FinanceError('future_date')
    note=_text(note,500)
    with _write(business_id,actor_user_id):
        source=get_account(business_id,_id(from_account_id),actor_user_id=actor_user_id,active=True)
        target=get_account(business_id,_id(to_account_id),actor_user_id=actor_user_id,active=True)
        if source['id']==target['id'] or source['currency']==target['currency']:raise FinanceError('fx_same_currency')
        if source['branch_id']!=target['branch_id']:raise FinanceError('branch_mismatch')
        from_amount_minor=_money(from_amount_minor,positive=True);to_amount_minor=_money(to_amount_minor,positive=True)
        import finance_fx
        actual=finance_fx.major(to_amount_minor,target['currency'])/finance_fx.major(from_amount_minor,source['currency'])
        now=repo._now()
        record_id=db.insert_returning_id('''INSERT INTO finance_fx_exchanges
            (business_id,branch_id,from_account_id,to_account_id,from_currency,to_currency,from_amount_minor,to_amount_minor,
             occurred_on,actual_rate,reference_rate,rate_source,rate_as_of,note,status,created_by_user_id,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'POSTED',?,?,?)''',
            (business_id,source['branch_id'],source['id'],target['id'],source['currency'],target['currency'],
             from_amount_minor,to_amount_minor,occurred_on,str(actual),str(reference_rate) if reference_rate is not None else None,
             _text(rate_source,120),_text(rate_as_of,40),note,actor_user_id,now,now))
        _audit(business_id,actor_user_id,'FINANCE_FX_EXCHANGE_CREATED',record_id);return record_id


def void_currency_exchange(business_id,exchange_id,actor_user_id=None):
    with _write(business_id,actor_user_id):
        row=db.query_one(('SELECT id,status FROM finance_fx_exchanges WHERE business_id=?' + branches.predicate('') + ' AND id=?'),
                         (business_id,_id(exchange_id)))
        if not row:raise FinanceError('fx_exchange_unavailable')
        if row['status']=='POSTED':
            now=repo._now();db.execute("UPDATE finance_fx_exchanges SET status='VOID',voided_at=?,voided_by_user_id=?,updated_at=? WHERE business_id=? AND id=?",
                       (now,actor_user_id,now,business_id,exchange_id));_audit(business_id,actor_user_id,'FINANCE_FX_EXCHANGE_VOIDED',exchange_id)
        return exchange_id


def get_customer_contribution_report(business_id,start_date,end_date,actor_user_id=None):
    rows=get_report_transactions(business_id,start_date,end_date,actor_user_id)
    groups={}
    for r in rows:
        if not r['customer_id'] or r['customer_name'] is None:continue
        code=_currency(r['currency']);key=(r['customer_id'],code)
        item=groups.setdefault(key,dict(customer_id=r['customer_id'],name=r['customer_name'],currency=code,
            income_minor=0,expense_minor=0,net_cash_contribution_minor=0,transaction_count=0))
        item['income_minor' if r['direction']=='INCOME' else 'expense_minor']+=r['amount_minor']
        item['net_cash_contribution_minor']=item['income_minor']-item['expense_minor'];item['transaction_count']+=1
    return list(groups.values())


def get_project_contribution_report(business_id,start_date,end_date,actor_user_id=None):
    get_report_transactions(business_id,start_date,end_date,actor_user_id)
    return get_project_cash_contribution(business_id,start_date,end_date,actor_user_id)

def get_report_invoices(business_id, as_of, start_date=None, end_date=None, actor_user_id=None,
                        customer_id=None, open_only=False):
    _scope(business_id,actor_user_id);as_of=_date(as_of)
    sql=('''SELECT i.branch_id,(SELECT name FROM finance_branches b WHERE b.id=i.branch_id AND b.business_id=i.business_id) AS branch_name,
        i.id,i.customer_id,i.invoice_number,i.issue_date,i.due_date,i.currency,i.status,c.name AS customer_name,
        COALESCE((SELECT SUM(x.quantity*x.unit_price_minor) FROM finance_invoice_items x
            WHERE x.business_id=i.business_id AND x.invoice_id=i.id),0) AS total_minor,
        COALESCE((SELECT SUM(p.amount_minor) FROM finance_invoice_payments p
            WHERE p.business_id=i.business_id AND p.invoice_id=i.id AND p.paid_on<=?),0) AS paid_minor
        FROM finance_invoices i LEFT JOIN finance_customers c ON c.business_id=i.business_id AND c.id=i.customer_id
        WHERE i.business_id=?''' + branches.predicate('i') + " AND i.issue_date<=?")
    params=[as_of,business_id,as_of]
    if customer_id is not None:
        if not get_customer(business_id,customer_id,actor_user_id):raise FinanceError('customer_unavailable')
        sql+=' AND i.customer_id=?';params.append(customer_id)
    if open_only:sql+=" AND i.status IN ('ISSUED','PARTIALLY_PAID','PAID')"
    if start_date is not None or end_date is not None:
        start,end=report_period(start_date,end_date);sql+=' AND i.issue_date>=? AND i.issue_date<=?';params.extend([start,end])
    rows=_report_query(sql+' ORDER BY i.issue_date,i.id',params)
    for r in rows:
        r['currency']=_currency(r['currency']);r['total_minor'],r['paid_minor']=int(r['total_minor']),int(r['paid_minor'])
        r['outstanding_minor']=r['total_minor']-r['paid_minor']
        # A payment after as_of cannot erase a historical receivable. Derive
        # payment status from this dated projection, not the invoice's live status.
        if r['status'] in ('ISSUED','PARTIALLY_PAID','PAID'):
            r['status']='PAID' if r['outstanding_minor']<=0 else 'PARTIALLY_PAID' if r['paid_minor'] else 'ISSUED'
        r['days_late']=max(0,(date.fromisoformat(as_of)-date.fromisoformat(r['due_date'])).days)
        r['overdue']=r['status'] in ('ISSUED','PARTIALLY_PAID') and r['outstanding_minor']>0 and r['days_late']>0
    return [r for r in rows if r['outstanding_minor']>0] if open_only else rows

def get_receivables_aging(business_id, as_of, actor_user_id=None):
    return receivables_aging_rows(get_report_invoices(business_id,as_of,actor_user_id=actor_user_id))


def receivables_aging_rows(rows):
    """Deterministic aging grouped by native currency; never mixes monetary amounts."""
    labels=('Belum jatuh tempo','Terlambat 1–30 hari','Terlambat 31–60 hari',
            'Terlambat 61–90 hari','Terlambat >90 hari')
    groups={}
    for r in rows:
        if r['status'] not in ('ISSUED','PARTIALLY_PAID') or r['outstanding_minor']<=0:continue
        code=_currency(r.get('currency','IDR'))
        item=groups.setdefault(code,dict(currency=code,buckets=[dict(label=x,amount_minor=0,invoice_count=0) for x in labels]))
        days=r['days_late'];index=0 if days==0 else 1 if days<=30 else 2 if days<=60 else 3 if days<=90 else 4
        item['buckets'][index]['amount_minor']+=r['outstanding_minor'];item['buckets'][index]['invoice_count']+=1
    by_currency=[]
    for code in SUPPORTED_CURRENCIES:
        if code not in groups:continue
        item=groups[code];item['total_outstanding_minor']=sum(b['amount_minor'] for b in item['buckets'])
        item['total_overdue_minor']=sum(b['amount_minor'] for b in item['buckets'][1:])
        item['open_invoice_count']=sum(b['invoice_count'] for b in item['buckets'])
        item['overdue_invoice_count']=sum(b['invoice_count'] for b in item['buckets'][1:]);by_currency.append(item)
    idr=next((x for x in by_currency if x['currency']=='IDR'),None)
    if idr is None:
        idr=dict(currency='IDR',buckets=[dict(label=x,amount_minor=0,invoice_count=0) for x in labels],
            total_outstanding_minor=0,total_overdue_minor=0,open_invoice_count=0,overdue_invoice_count=0)
    return dict(buckets=idr['buckets'],total_outstanding_minor=idr['total_outstanding_minor'],
        total_overdue_minor=idr['total_overdue_minor'],by_currency=by_currency,
        open_invoice_count=sum(x['open_invoice_count'] for x in by_currency),
        overdue_invoice_count=sum(x['overdue_invoice_count'] for x in by_currency))

def get_upcoming_recurring_commitments(business_id,start_date,end_date,actor_user_id=None):
    _scope(business_id,actor_user_id);start,end=report_period(start_date,end_date)
    rules=_report_query(('''SELECT r.*,(SELECT name FROM finance_branches b WHERE b.business_id=r.business_id AND b.id=r.branch_id) AS branch_name,
        p.title AS project_name,a.name AS account_name,c.name AS category_name,
        pc.name AS parent_category_name
        FROM finance_recurring_expenses r
        LEFT JOIN projects p ON p.business_id=r.business_id AND p.id=r.project_id
        LEFT JOIN finance_accounts a ON a.business_id=r.business_id AND a.id=r.account_id
        LEFT JOIN finance_categories c ON c.business_id=r.business_id AND c.id=r.category_id
        LEFT JOIN finance_category_hierarchy h ON h.business_id=c.business_id AND h.child_category_id=c.id
        LEFT JOIN finance_categories pc ON pc.business_id=h.business_id AND pc.id=h.parent_category_id
        WHERE r.business_id=?''' + branches.predicate('r') + " AND r.is_active=TRUE AND r.next_due_on<=? ORDER BY r.next_due_on,r.id"),
        (business_id,end))
    result=[];start_day=date.fromisoformat(start)
    for rule in rules:
        rule['currency']=_currency(rule['currency']);current=date.fromisoformat(rule['next_due_on'])
        if current<start_day:
            if rule['cadence']=='WEEKLY':current+=timedelta(days=((start_day-current).days//7)*7)
            else:current=date(start_day.year,start_day.month,min(rule['anchor_day'],calendar.monthrange(start_day.year,start_day.month)[1]))
            rule['next_due_on']=current.isoformat()
            if current<start_day:rule['next_due_on']=_next_recurring_date(rule)
        last=min(end,rule['end_on']) if rule['end_on'] else end
        while rule['next_due_on']<=last:
            if len(result)>=MAX_COMMITMENT_OCCURRENCES:raise FinanceError('forecast_limit')
            result.append(dict(recurring_id=rule['id'],branch_name=rule['branch_name'],name=rule['name'],currency=rule['currency'],
                scheduled_on=rule['next_due_on'],amount_minor=rule['amount_minor'],project_name=rule['project_name'],
                account_name=rule['account_name'],category_name=(
                    (rule['parent_category_name']+' / ') if rule.get('parent_category_name') else ''
                )+(rule['category_name'] or 'Kategori tidak tersedia'),
                counterparty_name=rule['counterparty_name'],description=rule['description'],
                cadence=rule['cadence'],end_on=rule['end_on']))
            if rule['next_due_on']==last:break
            try:rule['next_due_on']=_next_recurring_date(rule)
            except FinanceError:
                if last.startswith('9999-12'):break
                raise
    return sorted(result,key=lambda r:(r['scheduled_on'],SUPPORTED_CURRENCIES.index(r['currency']),r['name']))

def get_monthly_cashflow_trends(business_id,start_month,end_month,actor_user_id=None,start_date=None,end_date=None):
    months=report_months(start_month,end_month);year,month=map(int,end_month.split('-'))
    first=start_date or start_month+'-01';last=end_date or date(year,month,calendar.monthrange(year,month)[1]).isoformat()
    if first[:7]!=start_month or last[:7]!=end_month:raise FinanceError('report_range')
    rows=get_report_transactions(business_id,first,last,actor_user_id)
    currencies=[c for c in SUPPORTED_CURRENCIES if any(r['currency']==c for r in rows)] or ['IDR']
    trend={(m,c):dict(month=m,currency=c,income_minor=0,expense_minor=0,net_cashflow_minor=0) for c in currencies for m in months}
    for r in rows:
        item=trend[(r['occurred_on'][:7],r['currency'])]
        item['income_minor' if r['direction']=='INCOME' else 'expense_minor']+=r['amount_minor']
        item['net_cashflow_minor']=item['income_minor']-item['expense_minor']
    return [trend[(m,c)] for c in currencies for m in months]


def get_monthly_cashflow_trend(business_id,start_month,end_month,actor_user_id=None,start_date=None,end_date=None):
    rows=get_monthly_cashflow_trends(business_id,start_month,end_month,actor_user_id,start_date,end_date)
    idr=[r for r in rows if r['currency']=='IDR']
    if idr:return idr
    return [dict(month=m,currency='IDR',income_minor=0,expense_minor=0,net_cashflow_minor=0)
            for m in report_months(start_month,end_month)]

def operator_invoice_choices(business_id, actor_user_id=None):
    """Bounded picker only; does not load invoice notes or the whole history."""
    _scope(business_id,actor_user_id)
    return db.query_all(('SELECT id,invoice_number,currency FROM finance_invoices WHERE business_id=?' + branches.predicate('') + " AND status IN ('ISSUED','PARTIALLY_PAID') ORDER BY issue_date DESC,id DESC LIMIT 100"),(business_id,))


def find_receipt_transaction(business_id, receipt_hash, *, actor_user_id):
    """Read-only exact-file lookup. VOID origins remain reserved, within this tenant."""
    _scope(business_id, actor_user_id)
    if not isinstance(receipt_hash, str) or not re.fullmatch('[a-f0-9]{64}', receipt_hash):
        raise FinanceError('invalid_receipt_hash')
    return db.query_one(('SELECT *, (SELECT name FROM finance_branches b WHERE b.id=finance_transactions.branch_id AND b.business_id=finance_transactions.business_id) AS branch_name FROM finance_transactions WHERE business_id=?' + branches.predicate('') + ' AND source_type=? AND source_ref=? ORDER BY id LIMIT 1'),
                        (business_id, 'FINANCE_RECEIPT', receipt_hash))


def create_receipt_expense(business_id, receipt_hash, amount_minor, account_id, category_id,
                           occurred_on, *, currency='IDR', description=None, counterparty_name=None, actor_user_id):
    """Explicit reviewed confirmation only. One existing business lock, one ledger + audit.

    Exact replay requires POSTED state, all accounting fields and original actor.
    A voided or edited receipt cannot silently create a replacement.
    """
    _id(actor_user_id)
    with _write(business_id, actor_user_id):
        data = _transaction_data(business_id, dict(direction='EXPENSE', currency=_currency(currency),
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


# Monthly expense budgets. Planning metadata only; never posts ledger transactions.
def _budget_month(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}', value):
        raise FinanceError('invalid_period')
    try:
        year, month = map(int, value.split('-'))
        date(year, month, 1)
    except (ValueError, TypeError):
        raise FinanceError('invalid_period') from None
    return value


def list_monthly_budgets(business_id, month, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    month = _budget_month(month)
    return db.query_all(
        ('SELECT b.*,c.name AS category_name FROM finance_budgets b '
         'JOIN finance_categories c ON c.business_id=b.business_id AND c.id=b.category_id '
         'WHERE b.business_id=?' + branches.predicate('') +
         ' AND b.month=? ORDER BY c.name,b.id'),
        (business_id, month))


def set_monthly_budget(business_id, month, category_id, amount_minor, currency='IDR', *,
                       actor_user_id=None):
    month = _budget_month(month)
    category_id = _id(category_id)
    amount_minor = _money(amount_minor, positive=True)
    currency = _currency(currency)
    with _write(business_id, actor_user_id):
        branch_id = branches.write_branch(business_id, actor_user_id)
        category = db.query_one(
            'SELECT id,direction,is_active FROM finance_categories WHERE business_id=? AND id=?',
            (business_id, category_id))
        if not category or not category['is_active']:
            raise FinanceError('category_unavailable')
        if category['direction'] != 'EXPENSE':
            raise FinanceError('category_direction_mismatch')
        existing = db.query_one(
            'SELECT id FROM finance_budgets WHERE business_id=? AND branch_id=? AND month=? AND category_id=?',
            (business_id, branch_id, month, category_id))
        now = repo._now()
        if existing:
            db.execute(
                'UPDATE finance_budgets SET amount_minor=?,currency=?,updated_at=? '
                'WHERE business_id=? AND branch_id=? AND id=?',
                (amount_minor, currency, now, business_id, branch_id, existing['id']))
            _audit(business_id, actor_user_id, 'FINANCE_BUDGET_UPDATED', existing['id'])
            return existing['id']
        record_id = db.insert_returning_id(
            'INSERT INTO finance_budgets '
            '(business_id,branch_id,month,category_id,amount_minor,currency,created_by_user_id,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?)',
            (business_id, branch_id, month, category_id, amount_minor, currency,
             actor_user_id, now, now))
        _audit(business_id, actor_user_id, 'FINANCE_BUDGET_CREATED', record_id)
        return record_id


def delete_monthly_budget(business_id, budget_id, *, actor_user_id=None):
    with _write(business_id, actor_user_id):
        budget_id = _id(budget_id)
        row = db.query_one(
            ('SELECT id FROM finance_budgets WHERE business_id=?' + branches.predicate('') + ' AND id=?'),
            (business_id, budget_id))
        if not row:
            raise FinanceError('budget_unavailable')
        db.execute('DELETE FROM finance_budgets WHERE business_id=? AND id=?',
                   (business_id, budget_id))
        _audit(business_id, actor_user_id, 'FINANCE_BUDGET_DELETED', budget_id)
        return budget_id


def get_expense_category_totals(business_id, start_date, end_date, *, actor_user_id=None):
    _scope(business_id, actor_user_id)
    start_date, end_date = _period(start_date, end_date)
    return db.query_all(
        ('SELECT category_id,currency,SUM(amount_minor) AS amount_minor,COUNT(*) AS transaction_count '
         'FROM finance_transactions WHERE business_id=?' + branches.predicate('') +
         " AND status='POSTED' AND direction='EXPENSE' AND occurred_on>=? AND occurred_on<=? "
         'GROUP BY category_id,currency ORDER BY category_id,currency'),
        (business_id, start_date, end_date))
