"""Tenant-scoped actionable attention history. Resolving never changes business truth."""
import json
import time
import uuid
from . import jobs, operation_access
from .operation_contracts import OperationError, REASONS


def audit(tx,bid,action,detail,actor=None):
    tx.execute('INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (?,?,?,?)',
               (actor,bid,action,json.dumps(dict(detail,origin='OWNER' if actor else 'WEB_AUTOMATION'))))


def references(tx,bid,customer_id=None,conversation_id=None,job_id=None):
    if job_id:
        job=jobs._row(jobs._get(tx,bid,job_id))
        if (customer_id is not None and customer_id!=job['customer_id']) or (conversation_id is not None and conversation_id!=job['conversation_id']):
            raise OperationError('not_found',404)
        customer_id,conversation_id=job['customer_id'],job['conversation_id']
    if conversation_id:
        link=tx.one('SELECT customer_id FROM kw_web_customer_links WHERE business_id=? AND conversation_id=?',(bid,conversation_id))
        if not link or (customer_id is not None and customer_id!=link['customer_id']):
            raise OperationError('not_found',404)
        customer_id=link['customer_id']
    if customer_id: jobs._references(tx,bid,customer_id,conversation_id)
    return customer_id,conversation_id,job_id


def ensure(tx,bid,source_key,reason,*,customer_id=None,conversation_id=None,job_id=None,now=None):
    if not isinstance(source_key,str) or not 1<=len(source_key)<=160 or reason not in REASONS:
        raise OperationError('invalid_attention')
    customer_id,conversation_id,job_id=references(tx,bid,customer_id,conversation_id,job_id)
    now=int(time.time()) if now is None else now
    priority='HIGH' if reason in ('HUMAN_REPLY_NEEDED','AUTOMATION_FAILED') else 'NORMAL'
    row=tx.one('INSERT INTO kw_core_attention(business_id,id,source_key,reason,priority,customer_id,conversation_id,job_id,created_at,updated_at) '
               'VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(business_id,source_key) DO NOTHING RETURNING id',
               (bid,uuid.uuid4().hex,source_key,reason,priority,customer_id,conversation_id,job_id,now,now))
    if row: audit(tx,bid,'ATTENTION_CREATED',{'attention_id':row['id'],'reason':reason})
    # A resolved condition never reopens just because the scheduler scans it again.
    return tx.one('SELECT * FROM kw_core_attention WHERE business_id=? AND source_key=?',(bid,source_key))


def resolve_source(tx,bid,source_key,now):
    rows=tx.execute("UPDATE kw_core_attention SET status='RESOLVED',resolved_at=?,updated_at=? WHERE business_id=? AND source_key=? AND status='OPEN' RETURNING id",(now,now,bid,source_key))
    for row in rows: audit(tx,bid,'ATTENTION_RESOLVED',{'attention_id':row['id']})


def resolve(bid,aid,actor_id):
    jobs._positive(actor_id)
    with jobs.transaction() as tx:
        jobs._lock(tx,bid);operation_access.require(tx,bid)
        row=tx.one('SELECT * FROM kw_core_attention WHERE business_id=? AND id=?',(bid,aid))
        if not row: raise OperationError('not_found',404)
        if row['status']=='OPEN':
            now=int(time.time())
            tx.execute("UPDATE kw_core_attention SET status='RESOLVED',resolved_at=?,updated_at=? WHERE business_id=? AND id=?",(now,now,bid,aid))
            audit(tx,bid,'ATTENTION_RESOLVED',{'attention_id':aid},actor_id)
        return aid


def listing(bid,*,page=1,status='OPEN',limit=10):
    if status not in ('OPEN','RESOLVED') or type(limit) is not int or not 1<=limit<=10:
        raise OperationError('invalid_filter')
    try: page=max(1,int(page))
    except (TypeError,ValueError): raise OperationError('invalid_page')
    with jobs.transaction() as tx:
        operation_access.require(tx,bid)
        total=tx.one('SELECT COUNT(*) AS n FROM kw_core_attention WHERE business_id=? AND status=?',(bid,status))['n']
        pages=max(1,(total+limit-1)//limit);page=min(page,pages)
        rows=tx.execute('SELECT a.*,c.display_name,j.title AS job_title FROM kw_core_attention a '
                        'LEFT JOIN kw_core_customers c ON c.business_id=a.business_id AND c.id=a.customer_id '
                        'LEFT JOIN kw_core_jobs j ON j.business_id=a.business_id AND j.id=a.job_id '
                        'WHERE a.business_id=? AND a.status=? ORDER BY a.priority,a.created_at,a.id LIMIT ? OFFSET ?',
                        (bid,status,limit,(page-1)*limit))
        for row in rows: row['reason_label']=REASONS[row['reason']]
        return {'rows':rows,'total':total,'page':page,'pages':pages,'status':status}
