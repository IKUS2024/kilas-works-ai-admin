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
WORKSPACE_TYPES = ('BUSINESS', 'PERSONAL')


def workspace(value):
    value = (value or 'BUSINESS').strip().upper() if isinstance(value, str) else value
    if value not in WORKSPACE_TYPES:
        error('workspace_unavailable')
    return value


def _workspace_row(business_id, branch_id):
    row = db.query_one(
        'SELECT workspace_type,owner_user_id FROM finance_branch_workspaces '
        'WHERE business_id=? AND branch_id=?',
        (business_id, branch_id))
    return row or {'workspace_type':'BUSINESS','owner_user_id':None}


def _enrich(row):
    if row is None:
        return None
    item = dict(row)
    meta = _workspace_row(item['business_id'], item['id'])
    item['workspace_type'] = meta['workspace_type']
    item['owner_user_id'] = meta['owner_user_id']
    item['stored_name'] = item['name']
    if item['workspace_type'] == 'PERSONAL':
        item['name'] = 'Pribadi'
    item['display_name'] = item['name']
    return item


def error(code):
    from finance_service import FinanceError
    raise FinanceError(code)


def get(business_id, branch_id, active=False, actor_user_id=None):
    from finance_service import _id
    row = db.query_one('SELECT * FROM finance_branches WHERE business_id=? AND id=?',
                       (business_id, _id(branch_id)))
    if not row or (active and not row['is_active']):
        error('branch_unavailable')
    row = _enrich(row)
    context = _current.get()
    actor = actor_user_id
    if actor is None and context and context[0] == business_id:
        actor = context[2]
    if row['workspace_type'] == 'PERSONAL' and (
            actor is None or int(row['owner_user_id']) != int(actor)):
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
        get(business_id, context[1], active=write, actor_user_id=context[2])


@contextmanager
def scope(business_id, branch_id, actor_user_id=None):
    from finance_service import _scope
    # Authorization before binding, without inheriting another tenant's context.
    previous = _current.set(None)
    try:
        _scope(business_id, actor_user_id)
        if branch_id is not None:
            get(business_id, branch_id, actor_user_id=actor_user_id)
        _current.set((business_id, branch_id, actor_user_id))
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


def list_branches(business_id, actor_user_id=None, workspace_type=None):
    from finance_service import _scope
    _scope(business_id, actor_user_id)
    context = _current.get()
    if workspace_type is None and context and context[0] == business_id and context[1] is not None:
        workspace_type = get(
            business_id, context[1], actor_user_id=context[2])['workspace_type']
    workspace_type = workspace(workspace_type or 'BUSINESS')
    if workspace_type == 'PERSONAL':
        if actor_user_id is None:
            error('branch_unavailable')
        rows = db.query_all(
            '''SELECT b.* FROM finance_branches b
               JOIN finance_branch_workspaces w
                 ON w.business_id=b.business_id AND w.branch_id=b.id
               WHERE b.business_id=? AND w.workspace_type='PERSONAL'
                 AND w.owner_user_id=? ORDER BY b.id''',
            (business_id, actor_user_id))
    else:
        rows = db.query_all(
            '''SELECT b.* FROM finance_branches b
               LEFT JOIN finance_branch_workspaces w
                 ON w.business_id=b.business_id AND w.branch_id=b.id
               WHERE b.business_id=?
                 AND COALESCE(w.workspace_type,'BUSINESS')='BUSINESS'
               ORDER BY b.id''',
            (business_id,))
    return [_enrich(row) for row in rows]


def default(business_id, actor_user_id=None):
    """Legacy/default Finance always belongs to the Business workspace."""
    rows = list_branches(business_id, actor_user_id, workspace_type='BUSINESS')
    row = next((item for item in rows if item['is_default']), None)
    if row:
        return row['id']
    now = repo._now()
    branch_id = db.insert_returning_id('INSERT INTO finance_branches '
        '(business_id,name,is_default,created_at,updated_at) VALUES (?,?,TRUE,?,?)',
        (business_id, 'Utama', now, now))
    db.execute(
        'INSERT INTO finance_branch_workspaces '
        '(business_id,branch_id,workspace_type,owner_user_id,created_at) VALUES (?,?,?,NULL,?)',
        (business_id, branch_id, 'BUSINESS', now))
    from finance_service import _audit
    _audit(business_id, actor_user_id, 'FINANCE_BRANCH_CREATED', branch_id)
    return branch_id


def ensure_personal(business_id, actor_user_id):
    """Create one owner-private Personal workspace on explicit entry."""
    from finance_service import _write, _audit, _create_account
    if actor_user_id is None:
        error('branch_unavailable')
    with _write(business_id, actor_user_id):
        rows = list_branches(
            business_id, actor_user_id, workspace_type='PERSONAL')
        if rows:
            row = next((item for item in rows if item['is_active']), rows[0])
            if not row['is_active']:
                db.execute(
                    'UPDATE finance_branches SET is_active=TRUE,updated_at=? '
                    'WHERE business_id=? AND id=?',
                    (repo._now(), business_id, row['id']))
            return row['id']
        now = repo._now()
        # Stored name is unique inside the business; UI always displays "Pribadi".
        stored_name = 'Pribadi · ' + str(actor_user_id)
        branch_id = db.insert_returning_id(
            'INSERT INTO finance_branches '
            '(business_id,name,is_default,created_at,updated_at) VALUES (?,?,FALSE,?,?)',
            (business_id, stored_name, now, now))
        db.execute(
            'INSERT INTO finance_branch_workspaces '
            '(business_id,branch_id,workspace_type,owner_user_id,created_at) VALUES (?,?,?,?,?)',
            (business_id, branch_id, 'PERSONAL', actor_user_id, now))
        _audit(business_id, actor_user_id, 'FINANCE_PERSONAL_WORKSPACE_CREATED', branch_id)
        _create_account(
            business_id, 'Kas', 'CASH', 'IDR', 0, actor_user_id,
            branch_id=branch_id)
        return branch_id


def write_branch(business_id, actor_user_id=None):
    validate(business_id, write=True)
    context = _current.get()
    branch_id = context[1] if context else default(business_id, actor_user_id)
    actor = context[2] if context else actor_user_id
    get(business_id, branch_id, active=True, actor_user_id=actor)
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
    actor = context[2] if context else None
    get(business_id, row['branch_id'], active=True, actor_user_id=actor)
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
    context = _current.get()
    workspace_type = (
        get(business_id, context[1], actor_user_id=context[2])['workspace_type']
        if context and context[1] is not None else 'BUSINESS')
    if workspace_type != 'BUSINESS':
        error('workspace_branch_locked')
    name = _text(name, 160, True)
    with _write(business_id, actor_user_id):
        existing = db.query_one(
            '''SELECT b.id,b.is_active FROM finance_branches b
               LEFT JOIN finance_branch_workspaces w
                 ON w.business_id=b.business_id AND w.branch_id=b.id
               WHERE b.business_id=? AND b.name=?
                 AND COALESCE(w.workspace_type,'BUSINESS')='BUSINESS' ''',
            (business_id, name))
        if existing:
            if not existing['is_active']:
                db.execute('UPDATE finance_branches SET is_active=TRUE,updated_at=? WHERE business_id=? AND id=?',
                           (repo._now(), business_id, existing['id']))
                _audit(business_id, actor_user_id, 'FINANCE_BRANCH_REACTIVATED', existing['id'])
            return existing['id']
        now = repo._now()
        branch_id = db.insert_returning_id(
            'INSERT INTO finance_branches (business_id,name,created_at,updated_at) VALUES (?,?,?,?)',
            (business_id, name, now, now))
        db.execute(
            'INSERT INTO finance_branch_workspaces '
            '(business_id,branch_id,workspace_type,owner_user_id,created_at) VALUES (?,?,?,NULL,?)',
            (business_id, branch_id, 'BUSINESS', now))
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
            # Truly remove a disposable branch that never carried Finance history.
            # Historical branches stay archived internally so ledger/audit references remain valid,
            # but the UI hides archived branches from normal selectors.
            history_tables = ('finance_transactions','finance_invoices','finance_recurring_expenses',
                              'finance_bank_imports','finance_fx_exchanges')
            has_history = any(db.query_one(
                'SELECT 1 FROM ' + table + ' WHERE business_id=? AND branch_id=? LIMIT 1',
                (business_id, row['id'])) for table in history_tables)
            opening = db.query_one(
                'SELECT 1 FROM finance_accounts WHERE business_id=? AND branch_id=? AND opening_balance_minor<>0 LIMIT 1',
                (business_id, row['id']))
            if not has_history and not opening and not row['is_default']:
                db.execute('DELETE FROM finance_accounts WHERE business_id=? AND branch_id=?',
                           (business_id, row['id']))
                db.execute('DELETE FROM finance_branches WHERE business_id=? AND id=?',
                           (business_id, row['id']))
                _audit(business_id, actor_user_id, 'FINANCE_BRANCH_DELETED', row['id'])
                return
        if kind == 'account':
            account_branch(business_id, record_id)
            if deactivate and row['is_active']:
                active = db.query_one(
                    'SELECT COUNT(*) AS n FROM finance_accounts WHERE business_id=? AND branch_id=? AND is_active=TRUE',
                    (business_id, row['branch_id']))
                if active['n'] <= 1:
                    error('account_last_active')
                # Never let deleting/hiding an account make money silently disappear from
                # "Saldo tersedia". Historical rows remain auditable, but an account may only
                # be deactivated after ITS OWN current balance is zero.
                from finance_service import business_today, get_account_balance_report
                balances = get_account_balance_report(
                    business_id, business_today(business_id).isoformat(), actor_user_id)
                target_balance = next(
                    (int(item['balance_minor']) for item in balances
                     if item['id'] == row['id']), None)
                if target_balance is None:
                    error('account_unavailable')
                if target_balance != 0:
                    error('account_balance_required')
                if db.query_one(
                    'SELECT 1 FROM finance_recurring_expenses WHERE business_id=? AND branch_id=? AND account_id=? AND is_active=TRUE LIMIT 1',
                    (business_id, row['branch_id'], row['id'])):
                    error('account_in_use')
        if kind == 'category' and deactivate and row['is_active']:
            active = db.query_one(
                'SELECT COUNT(*) AS n FROM finance_categories WHERE business_id=? AND direction=? AND is_active=TRUE',
                (business_id, row['direction']))
            if active['n'] <= 1:
                error('category_last_active')
            if db.query_one(
                'SELECT 1 FROM finance_recurring_expenses WHERE business_id=? AND category_id=? AND is_active=TRUE LIMIT 1',
                (business_id, row['id'])):
                error('category_in_use')
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
