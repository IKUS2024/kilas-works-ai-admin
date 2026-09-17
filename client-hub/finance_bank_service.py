"""Tenant-scoped staging and human decisions. Every mutation holds one Finance lock."""
from collections import defaultdict,Counter
from datetime import date,timedelta
import hashlib
import json

import db
import repo
import finance_service as f
import finance_bank_extract as extraction

MAX_LEDGER = 5000
PAGE_SIZE = 50


def account(business_id,account_id,user_id):
    f._id(user_id)
    f._scope(business_id,user_id)
    row=db.query_one("SELECT * FROM finance_accounts WHERE business_id=? AND id=? AND currency='IDR' AND is_active=TRUE",
                     (business_id,f._id(account_id)))
    if not row:raise f.FinanceError('account_unavailable')
    return row


def get_import(business_id,import_id,user_id):
    f._id(user_id)
    f._scope(business_id,user_id)
    row=db.query_one('SELECT * FROM finance_bank_imports WHERE business_id=? AND id=?',(business_id,f._id(import_id)))
    if not row:raise f.FinanceError('bank_unavailable')
    return row


def get_rows(business_id,import_id,user_id):
    imp=get_import(business_id,import_id,user_id)
    rows=db.query_all('SELECT r.*,t.status AS linked_status,t.amount_minor AS linked_amount,t.direction AS linked_direction,'
        't.account_id AS linked_account,t.occurred_on AS linked_date FROM finance_bank_rows r '
        'LEFT JOIN finance_transactions t ON t.business_id=r.business_id AND t.id=COALESCE(r.matched_transaction_id,r.created_transaction_id) '
        'WHERE r.business_id=? AND r.import_id=? ORDER BY r.row_index LIMIT 1001',(business_id,import_id))
    if len(rows)>1000:raise f.FinanceError('bank_volume_limit')
    counts=Counter((r['occurred_on'],r['direction'],r['amount_minor'],r['description'],r['reference']) for r in rows)
    for row in rows:
        row['possible_overlap']=counts[(row['occurred_on'],row['direction'],row['amount_minor'],row['description'],row['reference'])]>1
        linked=row['matched_transaction_id'] or row['created_transaction_id']
        row['needs_attention']=bool(linked and (row['linked_status']!='POSTED' or row['linked_amount']!=row['amount_minor']
            or row['linked_direction']!=row['direction'] or row['linked_account']!=imp['account_id']
            or (row['reconciliation_status']=='MATCHED' and abs((date.fromisoformat(row['linked_date'])-date.fromisoformat(row['occurred_on'])).days)>3)))
    return rows


def list_imports(business_id,user_id,page=1):
    f._id(user_id)
    f._scope(business_id,user_id)
    if type(page) is not int or not 1<=page<=100000:raise f.FinanceError('invalid_page')
    return db.query_all('SELECT i.*,a.name AS account_name FROM finance_bank_imports i JOIN finance_accounts a '
        'ON a.business_id=i.business_id AND a.id=i.account_id WHERE i.business_id=? ORDER BY i.id DESC LIMIT 51 OFFSET ?',
        (business_id,(page-1)*50))


def find_import(business_id,account_id,identity,user_id):
    account(business_id,account_id,user_id)
    return db.query_one('SELECT id FROM finance_bank_imports WHERE business_id=? AND account_id=? AND file_hash=?',
                        (business_id,account_id,identity))


def row_hash(imp,index,row):
    return hashlib.sha256(json.dumps(dict(version=1,business_id=imp['business_id'],account_id=imp['account_id'],
        source_hash=imp['file_hash'],index=index,row=row),sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def insert_row(imp,index,row):
    now=repo._now()
    return db.insert_returning_id('INSERT INTO finance_bank_rows '
        '(business_id,import_id,row_index,row_hash,occurred_on,direction,amount_minor,description,reference,created_at,updated_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?)',(imp['business_id'],imp['id'],index,row_hash(imp,index,row),row['transaction_date'],
        row['direction'],row['amount_minor'],row['description'],row['reference'],now,now))


def stage(business_id,account_id,source,rows,user_id):
    if len(rows)>1000:raise f.FinanceError('bank_volume_limit')
    rows=[extraction.normalize(row) for row in rows]
    with f._write(business_id,user_id):
        account(business_id,account_id,user_id)
        existing=find_import(business_id,account_id,source['identity'],user_id)
        if existing:return existing['id']
        now=repo._now()
        import_id=db.insert_returning_id('INSERT INTO finance_bank_imports '
            '(business_id,account_id,source_kind,display_label,file_hash,source_count,imported_by_user_id,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?)',(business_id,account_id,source['kind'],source['label'],source['identity'],source['count'],user_id,now,now))
        imp=get_import(business_id,import_id,user_id)
        for index,row in enumerate(rows,1):insert_row(imp,index,row)
        f._audit(business_id,user_id,'FINANCE_BANK_IMPORT_CREATED',import_id)
        return import_id


def analyze(business_id,account_id,files,user_id):
    account(business_id,account_id,user_id)
    source=extraction.validate_sources(files)
    existing=find_import(business_id,account_id,source['identity'],user_id)
    if existing:return existing['id'],False
    rows,fallback=extraction.extract(source,user_id,business_id)
    return stage(business_id,account_id,source,rows,user_id),fallback


def _revision(imp,revision):
    if type(revision) is not int or imp['revision']!=revision:raise f.FinanceError('bank_stale_review')


def _row(business_id,import_id,row_id):
    row=db.query_one('SELECT * FROM finance_bank_rows WHERE business_id=? AND import_id=? AND id=?',
                     (business_id,import_id,f._id(row_id)))
    if not row:raise f.FinanceError('bank_row_unavailable')
    return row


def edit_row(business_id,import_id,row_id,revision,values,user_id):
    row=extraction.normalize(values)
    with f._write(business_id,user_id):
        imp=get_import(business_id,import_id,user_id);_revision(imp,revision)
        if imp['status']!='REVIEW':raise f.FinanceError('bank_not_review')
        if row_id is None:
            count=db.query_one('SELECT COUNT(*) AS n FROM finance_bank_rows WHERE business_id=? AND import_id=?',
                               (business_id,import_id))['n']
            if count>=1000:raise f.FinanceError('bank_volume_limit')
            insert_row(imp,count+1,row)
        else:
            original=_row(business_id,import_id,row_id)
            if original['reconciliation_status']!='UNMATCHED':raise f.FinanceError('bank_decided')
            db.execute('UPDATE finance_bank_rows SET occurred_on=?,direction=?,amount_minor=?,description=?,reference=?,row_hash=?,updated_at=? '
                'WHERE business_id=? AND import_id=? AND id=?',(row['transaction_date'],row['direction'],row['amount_minor'],row['description'],
                row['reference'],row_hash(imp,original['row_index'],row),repo._now(),business_id,import_id,row_id))
        db.execute('UPDATE finance_bank_imports SET revision=revision+1,updated_at=? WHERE business_id=? AND id=?',(repo._now(),business_id,import_id))
        f._audit(business_id,user_id,'FINANCE_BANK_IMPORT_REVIEWED',import_id)


def open_import(business_id,import_id,revision,user_id):
    with f._write(business_id,user_id):
        imp=get_import(business_id,import_id,user_id);_revision(imp,revision)
        if imp['status']!='REVIEW':raise f.FinanceError('bank_not_review')
        account(business_id,imp['account_id'],user_id)
        rows=get_rows(business_id,import_id,user_id)
        if not rows:raise f.FinanceError('bank_empty')
        for row in rows:
            extraction.normalize(dict(transaction_date=row['occurred_on'],direction=row['direction'],amount_minor=row['amount_minor'],description=row['description'],reference=row['reference']))
        db.execute("UPDATE finance_bank_imports SET status='OPEN',updated_at=? WHERE business_id=? AND id=?",(repo._now(),business_id,import_id))
        f._audit(business_id,user_id,'FINANCE_BANK_IMPORT_OPENED',import_id)


def cancel(business_id,import_id,user_id):
    with f._write(business_id,user_id):
        imp=get_import(business_id,import_id,user_id)
        if imp['status']=='CANCELLED':return
        if imp['status'] not in ('REVIEW','OPEN'):raise f.FinanceError('bank_cannot_cancel')
        if db.query_one("SELECT id FROM finance_bank_rows WHERE business_id=? AND import_id=? AND reconciliation_status<>'UNMATCHED' LIMIT 1",(business_id,import_id)):
            raise f.FinanceError('bank_cannot_cancel')
        db.execute("UPDATE finance_bank_imports SET status='CANCELLED',updated_at=? WHERE business_id=? AND id=?",(repo._now(),business_id,import_id))
        f._audit(business_id,user_id,'FINANCE_BANK_IMPORT_CANCELLED',import_id)


def date_gap(row,tx):
    return abs((date.fromisoformat(row['occurred_on'])-date.fromisoformat(tx['occurred_on'])).days)


def match_valid(imp,row,tx):
    return bool(tx and tx['business_id']==imp['business_id'] and tx['account_id']==imp['account_id'] and tx['currency']=='IDR'
        and tx['status']=='POSTED' and tx['direction']==row['direction'] and tx['amount_minor']==row['amount_minor'] and date_gap(row,tx)<=3)


def candidates(business_id,import_id,user_id):
    imp=get_import(business_id,import_id,user_id)
    if imp['status']!='OPEN':return {}
    rows=[row for row in get_rows(business_id,import_id,user_id) if row['reconciliation_status']=='UNMATCHED']
    if not rows:return {}
    days=[date.fromisoformat(row['occurred_on']).toordinal() for row in rows]
    start=date.fromordinal(max(date.min.toordinal(),min(days)-3)).isoformat()
    end=date.fromordinal(min(date.max.toordinal(),max(days)+3)).isoformat()
    ledger=db.query_all("SELECT t.* FROM finance_transactions t WHERE t.business_id=? AND t.account_id=? AND t.status='POSTED' AND t.currency='IDR' "
        'AND t.occurred_on>=? AND t.occurred_on<=? AND NOT EXISTS (SELECT 1 FROM finance_bank_rows r WHERE r.business_id=t.business_id '
        'AND (r.matched_transaction_id=t.id OR r.created_transaction_id=t.id)) ORDER BY t.occurred_on,t.id LIMIT ?',
        (business_id,imp['account_id'],start,end,MAX_LEDGER+1))
    if len(ledger)>MAX_LEDGER:raise f.FinanceError('bank_candidate_limit')
    groups=defaultdict(list)
    for tx in ledger:groups[(tx['direction'],tx['amount_minor'])].append(tx)
    output={}
    for row in rows:
        found=[tx for tx in groups[(row['direction'],row['amount_minor'])] if date_gap(row,tx)<=3]
        found.sort(key=lambda tx:(date_gap(row,tx),tx['occurred_on'],tx['id']))
        output[row['id']]=[dict(tx,explanation=('Nominal, arah, akun, dan tanggal sama' if date_gap(row,tx)==0 else
            f"Nominal, arah, dan akun sama; tanggal berbeda {date_gap(row,tx)} hari")) for tx in found[:10]]
    return output


def _complete(imp,user_id):
    pending=db.query_one("SELECT id FROM finance_bank_rows WHERE business_id=? AND import_id=? AND reconciliation_status='UNMATCHED' LIMIT 1",(imp['business_id'],imp['id']))
    if not pending:
        db.execute("UPDATE finance_bank_imports SET status='COMPLETED',updated_at=? WHERE business_id=? AND id=?",(repo._now(),imp['business_id'],imp['id']))
        f._audit(imp['business_id'],user_id,'FINANCE_BANK_IMPORT_COMPLETED',imp['id'])


def decide(business_id,import_id,row_id,action,user_id,*,transaction_id=None,fields=None):
    """No nested transaction: validation + link/origin + ledger + row + audits commit together."""
    if action not in ('match','post','ignore'):raise f.FinanceError('bank_invalid_action')
    with f._write(business_id,user_id):
        imp=get_import(business_id,import_id,user_id);row=_row(business_id,import_id,row_id)
        if imp['status'] not in ('OPEN','COMPLETED'):raise f.FinanceError('bank_not_open')
        state=row['reconciliation_status']
        data=None;tx=None
        if action=='post':
            if not isinstance(fields,dict) or set(fields)!={'category_id','occurred_on','description','counterparty_name'}:
                raise f.FinanceError('bank_invalid_fields')
            data=dict(direction=row['direction'],amount_minor=row['amount_minor'],currency='IDR',
                account_id=imp['account_id'],category_id=f._id(fields['category_id']),occurred_on=f._date(fields['occurred_on']),
                description=extraction.privacy_text(fields['description'],500) or None,
                counterparty_name=extraction.privacy_text(fields['counterparty_name'],160,True),
                project_id=None,customer_id=None,source_type='FINANCE_BANK_IMPORT',source_ref=row['row_hash'])
            tx=db.query_one('SELECT * FROM finance_transactions WHERE business_id=? AND source_type=? AND source_ref=?',
                            (business_id,'FINANCE_BANK_IMPORT',row['row_hash']))
            if state=='POSTED' and tx and row['created_transaction_id']==tx['id'] and tx['status']=='POSTED' and tx['created_by_user_id']==user_id and all(tx[k]==data[k] for k in f.FIELDS):
                return tx['id']
        elif action=='match':
            tx=f.get_transaction(business_id,f._id(transaction_id),actor_user_id=user_id)
            if not match_valid(imp,row,tx):raise f.FinanceError('bank_invalid_match')
            if state=='MATCHED' and row['matched_transaction_id']==tx['id']:return tx['id']
        elif state=='IGNORED':return row['id']
        if state!='UNMATCHED' or imp['status']!='OPEN':raise f.FinanceError('bank_decision_conflict')
        if action=='post':
            if tx:raise f.FinanceError('bank_origin_conflict')
            # Replay above makes no new decision, even if a category/account was later
            # archived. New writes always validate current active account/category here.
            data=f._transaction_data(business_id,data)
            tx_id=f._insert_transaction(business_id,data,user_id)
            db.execute("UPDATE finance_bank_rows SET reconciliation_status='POSTED',created_transaction_id=?,updated_at=? WHERE business_id=? AND import_id=? AND id=?",(tx_id,repo._now(),business_id,import_id,row_id))
            event='FINANCE_BANK_ROW_POSTED'
        elif action=='match':
            if db.query_one('SELECT id FROM finance_bank_rows WHERE business_id=? AND (matched_transaction_id=? OR created_transaction_id=?) LIMIT 1',(business_id,tx['id'],tx['id'])):
                raise f.FinanceError('bank_transaction_already_linked')
            tx_id=tx['id']
            db.execute("UPDATE finance_bank_rows SET reconciliation_status='MATCHED',matched_transaction_id=?,updated_at=? WHERE business_id=? AND import_id=? AND id=?",(tx_id,repo._now(),business_id,import_id,row_id))
            event='FINANCE_BANK_ROW_MATCHED'
        else:
            tx_id=row['id']
            db.execute("UPDATE finance_bank_rows SET reconciliation_status='IGNORED',updated_at=? WHERE business_id=? AND import_id=? AND id=?",(repo._now(),business_id,import_id,row_id))
            event='FINANCE_BANK_ROW_IGNORED'
        f._audit(business_id,user_id,event,row_id)
        _complete(imp,user_id)
        return tx_id
