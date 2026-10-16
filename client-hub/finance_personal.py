"""One canonical Personal ledger per owner. Existing ledger rows are never moved or merged."""
import db
import repo


def _error(code):
    from finance_service import FinanceError
    raise FinanceError(code)


def lock_owner(user_id):
    from finance_service import _id
    _id(user_id)
    # Creation and writes in different businesses serialize on the same owner.
    suffix=' FOR UPDATE' if db.BACKEND=='postgres' else ''
    if not db.query_one('SELECT id FROM users WHERE id=?'+suffix,(user_id,)):
        _error('business_unavailable')


def _contexts(user_id):
    return db.query_all(
        "SELECT w.business_id,w.branch_id,w.owner_user_id,b.business_name,f.is_active,f.created_at,"
        "EXISTS(SELECT 1 FROM business_memberships m WHERE m.business_id=w.business_id AND m.user_id=?) AS has_access "
        "FROM finance_branch_workspaces w JOIN finance_branches f "
        "ON f.business_id=w.business_id AND f.id=w.branch_id JOIN businesses b ON b.id=w.business_id "
        "WHERE w.workspace_type='PERSONAL' AND w.owner_user_id=? ORDER BY f.created_at,f.id",(user_id,user_id))


def has_data(row):
    bid,branch=row['business_id'],row['branch_id']
    # A pristine auto-seeded zero Kas is not a second populated financial dataset.
    if db.query_one("SELECT 1 FROM finance_accounts WHERE business_id=? AND branch_id=? "
        "AND (name<>? OR account_type<>? OR currency<>? OR opening_balance_minor<>0) LIMIT 1",
        (bid,branch,'Kas','CASH','IDR')):
        return True
    for table in ('finance_transactions','finance_invoices','finance_recurring_expenses','finance_budgets',
                  'finance_bank_imports','finance_internal_transfers','finance_fx_exchanges','finance_invoice_settings','finance_payees'):
        if db.query_one('SELECT 1 FROM '+table+' WHERE business_id=? AND branch_id=? LIMIT 1',(bid,branch)):
            return True
    import finance_service as finance
    default_names=set(name for values in finance.PERSONAL_DEFAULT_CATEGORIES.values() for name in values)
    for groups in finance.PERSONAL_DEFAULT_CATEGORY_CHILDREN.values():
        for values in groups.values():default_names.update(values)
    default_names.update(('Pendapatan Lain','Pengeluaran Lain','Lainnya'))
    settings=db.query_all('SELECT display_name FROM finance_category_workspace_settings WHERE business_id=? AND scope_key=?',
                          (bid,'PERSONAL:'+str(row['owner_user_id'])))
    if any(setting['display_name'] not in default_names for setting in settings):
        return True
    return False


def resolve_home(user_id):
    """Read-only: reuse the unique populated dataset; otherwise the oldest existing empty one.

    An established home is immutable here. Any populated secondary needs an explicit migration,
    never an automatic merge, move, copy or arbitrary choice between populated ledgers.
    """
    from finance_service import _id
    _id(user_id)
    rows=_contexts(user_id)
    stored=db.query_one('SELECT * FROM finance_personal_homes WHERE user_id=?',(user_id,))
    if stored:
        selected=next((row for row in rows if row['business_id']==stored['business_id'] and row['branch_id']==stored['branch_id']),None)
        if selected is None or not selected['has_access']:
            _error('personal_home_unavailable')
        if any(row['branch_id']!=selected['branch_id'] and has_data(row) for row in rows):
            _error('personal_context_conflict')
        return selected
    populated=[row for row in rows if has_data(row)]
    if len(populated)>1:
        _error('personal_context_conflict')
    selected=populated[0] if populated else (rows[0] if rows else None)
    if selected and not selected['has_access']:
        _error('personal_home_unavailable')
    return selected


def bind_home(user_id,business_id,branch_id):
    import finance_service as finance
    if finance._finance_write.get()!=(business_id,user_id):
        _error('business_unavailable')
    owned=db.query_one("SELECT 1 FROM finance_branch_workspaces w JOIN business_memberships m "
        "ON m.business_id=w.business_id AND m.user_id=? WHERE w.business_id=? AND w.branch_id=? "
        "AND w.workspace_type='PERSONAL' AND w.owner_user_id=?",(user_id,business_id,branch_id,user_id))
    if not owned:
        _error('branch_unavailable')
    current=db.query_one('SELECT * FROM finance_personal_homes WHERE user_id=?',(user_id,))
    if current:
        if (current['business_id'],current['branch_id'])!=(business_id,branch_id):
            _error('personal_home_elsewhere')
        return branch_id
    db.execute('INSERT INTO finance_personal_homes(user_id,business_id,branch_id,created_at) VALUES (?,?,?,?)',
               (user_id,business_id,branch_id,repo._now()))
    return branch_id
