"""One expense ledger row, bounded category allocations and private receipt bytes."""
import hashlib
import json
import re
import db
import file_utils
import finance_service as finance


def allocations(business_id, transaction_id, actor_user_id):
    if not finance.get_transaction(business_id,transaction_id,actor_user_id=actor_user_id):
        raise finance.FinanceError('transaction_unavailable')
    return [dict(row) for row in db.query_all('SELECT category_id,amount_minor FROM finance_expense_allocations WHERE transaction_id=? ORDER BY sequence',(transaction_id,))]


def validate(business_id, amount, values, actor_user_id, *, retained=None):
    if not isinstance(values,list) or not 2<=len(values)<=20:raise finance.FinanceError('expense_split_invalid')
    if retained and values==retained and sum(v['amount_minor'] for v in retained)==amount:return [dict(v) for v in retained]
    seen=set();result=[]
    for value in values:
        if not isinstance(value,dict) or set(value)!={'category_id','amount_minor'}:raise finance.FinanceError('expense_split_invalid')
        category=finance._id(value['category_id']);money=finance._money(value['amount_minor'],positive=True)
        visible=next((c for c in finance.list_categories(business_id,'EXPENSE',include_children=True,actor_user_id=actor_user_id) if c['id']==category and c['is_active']),None)
        if not visible or category in seen:raise finance.FinanceError('expense_split_invalid')
        if not visible.get('parent_category_id') and finance.list_category_children(business_id,category,actor_user_id=actor_user_id):raise finance.FinanceError('subcategory_required')
        result.append(dict(category_id=category,amount_minor=money));seen.add(category)
    if sum(v['amount_minor'] for v in result)!=amount:raise finance.FinanceError('expense_split_total')
    return result


def replace(business_id, transaction_id, values, actor_user_id):
    if finance._finance_write.get()!=(business_id,actor_user_id):raise finance.FinanceError('business_unavailable')
    before=allocations(business_id,transaction_id,actor_user_id)
    if before==values:return
    db.execute('INSERT INTO finance_expense_revisions(transaction_id,before_json,after_json,actor_user_id,created_at) VALUES (?,?,?,?,?)',
               (transaction_id,json.dumps(before),json.dumps(values),actor_user_id,finance.repo._now()))
    db.execute('DELETE FROM finance_expense_allocations WHERE transaction_id=?',(transaction_id,))
    for sequence,value in enumerate(values):
        db.execute('INSERT INTO finance_expense_allocations(transaction_id,sequence,category_id,amount_minor) VALUES (?,?,?,?)',(transaction_id,sequence,value['category_id'],value['amount_minor']))
    db.execute('UPDATE finance_transactions SET updated_at=? WHERE id=?',(finance.repo._now(),transaction_id))
    finance._audit(business_id,actor_user_id,'FINANCE_EXPENSE_SPLIT_UPDATED',transaction_id)


def photo(upload):
    if not upload or not upload.filename:return None
    raw=upload.stream.read(file_utils.FINANCE_IMAGE_INPUT_BYTES+1)
    if upload.filename.rsplit('.',1)[-1].lower() not in ('jpg','jpeg','png','webp'):raise finance.FinanceError('expense_receipt_invalid')
    try:name,mime,_,raw=file_utils.prepare_finance_document(upload.filename,raw)
    except file_utils.UploadRejected:raise finance.FinanceError('expense_receipt_invalid') from None
    if len(raw)>4*1024*1024:raise finance.FinanceError('expense_receipt_invalid')
    extension={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}[mime]
    name=name.rsplit('.',1)[0]+'.'+extension
    return dict(name=name,mime=mime,raw=raw,digest=hashlib.sha256(raw).hexdigest())


def receipt_capacity(business_id,size,transaction_id=0):
    if db.BACKEND=='postgres':db.query_one('SELECT pg_advisory_xact_lock(74110701)')
    used=db.query_one('SELECT COALESCE(SUM(byte_size),0) AS n FROM finance_expense_receipts WHERE transaction_id<>?',(transaction_id,))['n']+db.query_one('SELECT COALESCE(SUM(byte_size),0) AS n FROM finance_installment_receipts')['n']
    owned=db.query_one('SELECT COALESCE(SUM(r.byte_size),0) AS n FROM finance_expense_receipts r JOIN finance_transactions t ON t.id=r.transaction_id WHERE t.business_id=? AND r.transaction_id<>?',(business_id,transaction_id))['n']+db.query_one('SELECT COALESCE(SUM(r.byte_size),0) AS n FROM finance_installment_receipts r JOIN finance_installment_plans p ON p.id=r.plan_id WHERE p.business_id=?',(business_id,))['n']
    if used+size>64*1024*1024 or owned+size>20*1024*1024:raise finance.FinanceError('expense_receipt_capacity')


def save(business_id, actor_user_id, *, amount_minor,account_id,category_id,occurred_on,currency,
         description=None,notes=None,counterparty_name=None,splits=None,receipt=None,submission_key=None,
         transaction_id=None,expected_updated_at=None,project_id=None,customer_id=None):
    with finance._write(business_id,actor_user_id):
        values=validate(business_id,amount_minor,splits,actor_user_id,retained=allocations(business_id,transaction_id,actor_user_id) if transaction_id else None) if splits else []
        if values:category_id=values[0]['category_id']
        data=dict(amount_minor=amount_minor,account_id=account_id,category_id=category_id,occurred_on=occurred_on,
                  description=description,notes=notes,counterparty_name=counterparty_name,project_id=project_id,customer_id=customer_id)
        if transaction_id:
            current=finance.get_transaction(business_id,transaction_id,actor_user_id=actor_user_id)
            if not current or current['direction']!='EXPENSE':raise finance.FinanceError('transaction_unavailable')
            if current['currency']!=currency:raise finance.FinanceError('account_currency_mismatch')
            finance.update_transaction(business_id,transaction_id,actor_user_id=actor_user_id,expected_updated_at=expected_updated_at,expense_splits=values,**data)
        else:
            if not isinstance(submission_key,str) or not re.fullmatch('[a-f0-9]{32}',submission_key):raise finance.FinanceError('expense_submission_invalid')
            if db.query_one('SELECT 1 FROM finance_installment_plans WHERE business_id=? AND submission_key=?',(business_id,submission_key)):raise finance.FinanceError('expense_submission_conflict')
            payload={**data,'currency':currency,'splits':values,'receipt_hash':receipt['digest'] if receipt else None}
            digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
            prior=db.query_one('SELECT transaction_id,payload_hash,actor_user_id FROM finance_expense_entries WHERE business_id=? AND submission_key=?',(business_id,submission_key))
            if prior:
                if prior['actor_user_id']!=actor_user_id or prior['payload_hash']!=digest or not finance.get_transaction(business_id,prior['transaction_id'],actor_user_id=actor_user_id):raise finance.FinanceError('expense_submission_conflict')
                return prior['transaction_id']
            transaction_id=finance.create_transaction(business_id,'EXPENSE',currency=currency,actor_user_id=actor_user_id,**data)
            db.execute('INSERT INTO finance_expense_entries(transaction_id,business_id,actor_user_id,submission_key,payload_hash) VALUES (?,?,?,?,?)',(transaction_id,business_id,actor_user_id,submission_key,digest))
            replace(business_id,transaction_id,values,actor_user_id)
        if receipt:
            receipt_capacity(business_id,len(receipt['raw']),transaction_id)
            db.execute('INSERT INTO finance_expense_receipts(transaction_id,filename,mime_type,content,byte_size,digest) VALUES (?,?,?,?,?,?) ON CONFLICT(transaction_id) DO UPDATE SET filename=excluded.filename,mime_type=excluded.mime_type,content=excluded.content,byte_size=excluded.byte_size,digest=excluded.digest',
                       (transaction_id,receipt['name'],receipt['mime'],receipt['raw'],len(receipt['raw']),receipt['digest']))
            db.execute('UPDATE finance_transactions SET updated_at=? WHERE id=?',(finance.repo._now(),transaction_id))
            finance._audit(business_id,actor_user_id,'FINANCE_EXPENSE_RECEIPT_SAVED',transaction_id)
        return transaction_id


def edit_categories(business_id,transaction_id,actor):
    transaction=finance.get_transaction(business_id,transaction_id,actor_user_id=actor)
    if not transaction:raise finance.FinanceError('transaction_unavailable')
    # A direct legacy Edit link may precede the first dashboard visit. Apply the
    # same reversible Personal catalog retirement before offering new choices;
    # retain this transaction's historical IDs below rather than deleting them.
    if finance._category_scope(business_id,actor)['workspace_type']=='PERSONAL':
        try:finance.sync_business_category_catalog(business_id,actor_user_id=actor)
        except finance.FinanceError as error:
            if str(error)!='finance_read_only':raise
    retained={transaction['category_id']}|{v['category_id'] for v in allocations(business_id,transaction_id,actor)}
    rows=finance.list_categories(business_id,'EXPENSE',include_inactive=True,include_children=True,actor_user_id=actor)
    retained|={v['parent_category_id'] for v in rows if v['id'] in retained and v.get('parent_category_id')}
    result=[]
    for row in rows:
        if row['is_active'] or row['id'] in retained:
            row['retained']=row['id'] in retained;result.append(row)
    return result
