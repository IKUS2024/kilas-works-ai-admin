"""Explicit Finance branch context shared by routes and existing services.

None context is reserved for existing internal business-wide readers/jobs. HTTP routes
always bind (business, branch), with branch=None meaning read-only Semua Cabang.
No session fallback: an old form cannot silently move to a newly selected branch.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import db
import repo

_current = ContextVar('finance_branch', default=None)


def error(code):
    from finance_service import FinanceError
    raise FinanceError(code)


def get(business_id, branch_id, active=False):
    from finance_service import _id
    row = db.query_one('SELECT * FROM finance_branches WHERE business_id=? AND id=?',
                       (business_id, _id(branch_id)))
    if not row or (active and not row['is_active']):
        error('branch_unavailable')
    return row


def validate(business_id, write=False):
    context = _current.get()
    if context is None:
        return
    if context[0] != business_id:
        error('branch_unavailable')
    if context[1] is None:
        if write:
            error('all_branches_read_only')
    else:
        get(business_id, context[1], active=write)


@contextmanager
def scope(business_id, branch_id, actor_user_id=None):
    from finance_service import _scope
    # Authorization before binding, without inheriting another tenant's context.
    previous = _current.set(None)
    try:
        _scope(business_id, actor_user_id)
        if branch_id is not None:
            get(business_id, branch_id)
        _current.set((business_id, branch_id))
        yield
    finally:
        _current.reset(previous)


def predicate(alias=''):
    """SQL suffix at explicitly scoped SELECT sites; only validated integer IDs.

    Business predicates remain mandatory at each call site. No SQL parsing/rewrite.
    """
    context = _current.get()
    if context is None or context[1] is None:
        return ''
    from finance_service import _id
    if alias not in ('', 'a', 't', 'i', 'r'):
        raise ValueError('invalid SQL alias')
    column = (alias + '.' if alias else '') + 'branch_id'
    return ' AND ' + column + '=' + str(_id(context[1])) + ' '


def list_branches(business_id, actor_user_id=None):
    from finance_service import _scope
    _scope(business_id, actor_user_id)
    return db.query_all('SELECT * FROM finance_branches WHERE business_id=? ORDER BY id', (business_id,))


def default(business_id, actor_user_id=None):
    """Called only inside the existing business write lock; deterministic legacy branch."""
    row = db.query_one('SELECT * FROM finance_branches WHERE business_id=? AND is_default=TRUE', (business_id,))
    if row:
        return row['id']
    now = repo._now()
    branch_id = db.insert_returning_id('INSERT INTO finance_branches '
        '(business_id,name,is_default,created_at,updated_at) VALUES (?,?,TRUE,?,?)',
        (business_id, 'Utama', now, now))
    from finance_service import _audit
    _audit(business_id, actor_user_id, 'FINANCE_BRANCH_CREATED', branch_id)
    return branch_id


def write_branch(business_id, actor_user_id=None):
    validate(business_id, write=True)
    context = _current.get()
    branch_id = context[1] if context else default(business_id, actor_user_id)
    get(business_id, branch_id, active=True)
    return branch_id


def account_branch(business_id, account_id):
    from finance_service import _id
    validate(business_id, write=True)
    row = db.query_one('SELECT branch_id FROM finance_accounts WHERE business_id=? AND id=?',
                       (business_id, _id(account_id)))
    if not row:
        error('account_unavailable')
    context = _current.get()
    if context and context[1] != row['branch_id']:
        error('account_unavailable')
    get(business_id, row['branch_id'], active=True)
    return row['branch_id']


def token_branch(business_id):
    """Signed reviews always bind a single branch, including legacy internal callers."""
    validate(business_id, write=True)
    context = _current.get()
    if context:
        return context[1]
    rows = list_branches(business_id)
    if len(rows) != 1 or not rows[0]['is_active']:
        error('branch_required')
    return rows[0]['id']


def check_token(business_id, branch_id):
    if type(branch_id) is not int or branch_id != token_branch(business_id):
        error('branch_confirmation_mismatch')


def create_branch(business_id, name, actor_user_id=None):
    from finance_service import _write, _text, _audit, _create_account
    name = _text(name, 160, True)
    with _write(business_id, actor_user_id):
        if db.query_one('SELECT id FROM finance_branches WHERE business_id=? AND name=?', (business_id, name)):
            error('branch_exists')
        now = repo._now()
        branch_id = db.insert_returning_id('INSERT INTO finance_branches (business_id,name,created_at,updated_at) VALUES (?,?,?,?)',
                                          (business_id, name, now, now))
        _audit(business_id, actor_user_id, 'FINANCE_BRANCH_CREATED', branch_id)
        _create_account(business_id, 'Kas', 'CASH', 'IDR', 0, actor_user_id, branch_id=branch_id)
        return branch_id


def update_record(business_id, kind, record_id, name=None, deactivate=False, actor_user_id=None):
    from finance_service import _write, _text, _id, _audit
    tables = {'branch': 'finance_branches', 'account': 'finance_accounts', 'category': 'finance_categories'}
    if kind not in tables or type(deactivate) is not bool:
        error('invalid_enum')
    table = tables[kind]
    with _write(business_id, actor_user_id):
        row = db.query_one('SELECT * FROM ' + table + ' WHERE business_id=? AND id=?', (business_id, _id(record_id)))
        if not row:
            error(kind + '_unavailable')
        if kind == 'branch' and deactivate and row['is_active']:
            active = db.query_one('SELECT COUNT(*) AS n FROM finance_branches WHERE business_id=? AND is_active=TRUE', (business_id,))
            if active['n'] <= 1:
                error('branch_last_active')
        if kind == 'account':
            account_branch(business_id, record_id)
        clean = _text(name, 160, True) if name is not None else row['name']
        sql, params = 'SELECT id FROM ' + table + ' WHERE business_id=? AND name=? AND id<>?', [business_id, clean, record_id]
        if kind == 'account':
            sql += ' AND branch_id=? AND account_type=? AND currency=?'
            params += [row['branch_id'], row['account_type'], row['currency']]
        elif kind == 'category':
            sql += ' AND direction=?'; params.append(row['direction'])
        if db.query_one(sql, params):
            error(kind + '_exists')
        db.execute('UPDATE ' + table + ' SET name=?,is_active=?,updated_at=? WHERE business_id=? AND id=?',
                   (clean, False if deactivate else row['is_active'], repo._now(), business_id, record_id))
        _audit(business_id, actor_user_id, 'FINANCE_' + kind.upper() + ('_DEACTIVATED' if deactivate else '_UPDATED'), record_id)
