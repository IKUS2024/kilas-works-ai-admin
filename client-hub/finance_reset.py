"""Explicit owner-scoped Finance reset requests. Preparing a request never resets ledger data."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import uuid
import db
import repo
import finance_service as finance
import finance_branches as branches

TTL = timedelta(minutes=10)
DIRECT_TABLES = ('finance_accounts','finance_transactions','finance_invoices','finance_recurring_expenses',
                 'finance_bank_imports','finance_budgets','finance_internal_transfers','finance_fx_exchanges')
CHILD_TABLES = (
    ('finance_invoice_items','finance_invoices','invoice_id'),
    ('finance_invoice_payments','finance_invoices','invoice_id'),
    ('finance_recurring_postings','finance_recurring_expenses','recurring_expense_id'),
    ('finance_bank_rows','finance_bank_imports','import_id'),
    ('finance_bank_extraction_reviews','finance_bank_imports','import_id'),
)


def _now():
    return datetime.now(timezone.utc)


def require_owner(business_id, branch_id, actor_user_id):
    """A real Personal owner or Business OWNER, including direct-service callers."""
    finance._id(actor_user_id)
    context = branches._current.get()
    if not context or context != (business_id, branch_id, actor_user_id):
        raise finance.FinanceError('branch_unavailable')
    finance._scope(business_id, actor_user_id)
    branch = branches.get(business_id, branch_id, active=True, actor_user_id=actor_user_id)
    if branch['workspace_type'] == 'PERSONAL':
        if branch['owner_user_id'] != actor_user_id:
            raise finance.FinanceError('branch_unavailable')
    else:
        finance._workspace_move_owner(business_id, actor_user_id)
    return branch


def target(business_id, branch_id, actor_user_id):
    branch = require_owner(business_id, branch_id, actor_user_id)
    business = repo.get_business(business_id)
    # Approved scope: exactly the selected Personal workspace or selected Business branch.
    rows=[branch]
    owner=repo.get_user_by_id(actor_user_id)
    owner_name=(owner.get('full_name') or owner['email'].split('@')[0]) if branch['workspace_type']=='PERSONAL' else None
    return dict(business_id=business_id, origin_branch_id=branch_id, branch_ids=[row['id'] for row in rows],
                workspace_type=branch['workspace_type'], business_name=business['business_name'],owner_name=owner_name,
                branch_names=[row['name'] for row in rows])


def _state(business_id, selected):
    ids=selected['branch_ids']
    placeholders=','.join('?' for _ in ids)
    records={}
    for table in DIRECT_TABLES:
        records[table]=db.query_all('SELECT * FROM '+table+' WHERE business_id=? AND branch_id IN ('+placeholders+') ORDER BY id',
                                    [business_id]+ids)
    for table,parent,key in CHILD_TABLES:
        records[table]=db.query_all('SELECT c.* FROM '+table+' c JOIN '+parent+' p '
            'ON p.business_id=c.business_id AND p.id=c.'+key+
            ' WHERE p.business_id=? AND p.branch_id IN ('+placeholders+')',[business_id]+ids)
    records={key:sorted(rows,key=lambda row:json.dumps(row,sort_keys=True)) for key,rows in records.items()}
    digest=hashlib.sha256(json.dumps(dict(target=selected,records=records),sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return records,digest


def _preview(selected, records):
    count=lambda table,field=None,values=None:sum(1 for row in records[table] if field is None or row[field] in values)
    return dict(target=selected,
        accounts=count('finance_accounts'),
        transactions=count('finance_transactions','status',('POSTED',)),
        invoices=count('finance_invoices','status',('DRAFT','ISSUED','PARTIALLY_PAID','PAID','OVERDUE')),
        recurring=count('finance_recurring_expenses','is_active',(True,1)),
        imports=count('finance_bank_imports','status',('REVIEW','OPEN')),
        budgets=count('finance_budgets'),
        transfers=count('finance_internal_transfers','status',('POSTED',)),
        exchanges=count('finance_fx_exchanges','status',('POSTED',)))


def prepare(business_id, branch_id, *, actor_user_id):
    with finance._write(business_id,actor_user_id):
        selected=target(business_id,branch_id,actor_user_id)
        records,digest=_state(business_id,selected)
        preview=_preview(selected,records)
        key=uuid.uuid4().hex
        now=_now()
        db.execute('INSERT INTO finance_reset_requests '
            '(request_key,business_id,origin_branch_id,actor_user_id,workspace_type,target_json,preview_json,'
            'state_digest,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (key,business_id,branch_id,actor_user_id,selected['workspace_type'],json.dumps(selected,sort_keys=True),
             json.dumps(preview,sort_keys=True),digest,now.isoformat(),(now+TTL).isoformat()))
        return key


def _request(business_id, branch_id, key, actor_user_id):
    require_owner(business_id,branch_id,actor_user_id)
    if not isinstance(key,str) or not re.fullmatch('[a-f0-9]{32}',key):
        raise finance.FinanceError('reset_unavailable')
    row=db.query_one('SELECT * FROM finance_reset_requests WHERE request_key=? AND business_id=? '
                     'AND origin_branch_id=? AND actor_user_id=?',(key,business_id,branch_id,actor_user_id))
    if not row:
        raise finance.FinanceError('reset_unavailable')
    return row


def preview(business_id, branch_id, key, *, actor_user_id):
    row=_request(business_id,branch_id,key,actor_user_id)
    result=json.loads(row['preview_json'])
    changed=False
    if not row['processed_at']:
        selected=target(business_id,branch_id,actor_user_id)
        _,digest=_state(business_id,selected)
        changed=json.loads(row['target_json'])!=selected or digest!=row['state_digest']
    result.update(request_key=key,processed=bool(row['processed_at']),changed=changed,expired=_now()>=datetime.fromisoformat(row['expires_at']))
    return result


def complete(business_id, branch_id, key, *, actor_user_id, confirmation, acknowledged):
    if confirmation != 'RESET' or acknowledged != 'yes':
        raise finance.FinanceError('reset_confirmation_required')
    with finance._write(business_id,actor_user_id):
        row=_request(business_id,branch_id,key,actor_user_id)
        if row['processed_at']:
            return key  # A repeated submission must never clear later new activity.
        if _now()>=datetime.fromisoformat(row['expires_at']):
            raise finance.FinanceError('reset_expired')
        selected=target(business_id,branch_id,actor_user_id)
        if json.loads(row['target_json'])!=selected:
            raise finance.FinanceError('reset_target_changed')
        _,digest=_state(business_id,selected)
        if digest!=row['state_digest']:
            raise finance.FinanceError('reset_data_changed')
        finance._reset_branch_records(business_id,branch_id,actor_user_id)
        db.execute('UPDATE finance_reset_requests SET processed_at=? WHERE request_key=?',(_now().isoformat(),key))
        finance._audit(business_id,actor_user_id,'FINANCE_RESET_CONFIRMED',branch_id)
        return key
