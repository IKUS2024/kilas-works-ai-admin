"""Small deterministic WEB-only runner. No model/network/legacy notification imports.

Run one bounded page explicitly. Repeated/concurrent runs are safe: business lock,
conversation lock, stable source key, durable message and terminal state in one tx.
No lease needed for a local-only atomic append; no worker holds a lock across IO.
"""
import hashlib
import time
from . import jobs, attention, operation_access
from .operation_contracts import DEFAULT_CONFIG, MESSAGES, OperationError, config as validate_config
from public_chat import store

FOLLOWUP='CUSTOMER_INACTIVE_FOLLOWUP'
REVIEW='JOB_COMPLETED_REVIEW_REQUEST'


def clock(now=None):
    now=int(time.time()) if now is None else now
    if type(now) is not int or now<0: raise OperationError('invalid_clock')
    return now


def _config(tx,bid):
    row=tx.one('SELECT * FROM kw_core_automation_config WHERE business_id=?',(bid,))
    if not row: return dict(DEFAULT_CONFIG,version=0)
    return {**{key:bool(row[key]) if key.endswith('_enabled') else row[key] for key in DEFAULT_CONFIG},'version':row['version']}


def get_config(bid):
    with jobs.transaction() as tx:
        operation_access.require(tx,bid)
        return _config(tx,bid)


def set_config(bid,payload,*,actor_id,expected_version):
    clean=validate_config(payload);jobs._positive(actor_id)
    if type(expected_version) is not int or expected_version<0: raise OperationError('invalid_version')
    with jobs.transaction() as tx:
        jobs._lock(tx,bid);operation_access.require(tx,bid)
        current=_config(tx,bid)
        if current['version']!=expected_version:
            if all(current[k]==v for k,v in clean.items()): return current
            raise OperationError('stale_version',409)
        tx.execute('INSERT INTO kw_core_automation_config(business_id,followup_enabled,delay_hours,max_attempts,review_enabled,updated_at) '
                   'VALUES (?,?,?,?,?,?) ON CONFLICT(business_id) DO UPDATE SET followup_enabled=excluded.followup_enabled,'
                   'delay_hours=excluded.delay_hours,max_attempts=excluded.max_attempts,review_enabled=excluded.review_enabled,'
                   'updated_at=excluded.updated_at,version=kw_core_automation_config.version+1',
                   (bid,int(clean['followup_enabled']),clean['delay_hours'],clean['max_attempts'],int(clean['review_enabled']),clock()))
        attention.audit(tx,bid,'WEB_AUTOMATION_CONFIG_CHANGED',{'config':clean},actor_id)
        return _config(tx,bid)


def _last_customer(tx,bid,cid):
    return tx.one("SELECT id,created_at FROM kw_web_messages WHERE business_id=? AND conversation_id=? AND role='user' ORDER BY id DESC LIMIT 1",(bid,cid))


def _enqueue(tx,bid,key,kind,customer,cid,jid,conv,last,attempt,now):
    attention.references(tx,bid,customer,cid,jid)
    tx.execute('INSERT INTO kw_core_automation_runs(business_id,source_key,kind,customer_id,conversation_id,job_id,conversation_version,'
               'customer_message_id,attempt,due_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) '
               'ON CONFLICT(business_id,source_key) DO NOTHING',
               (bid,key,kind,customer,cid,jid,conv['version'] if conv else None,last['id'] if last else None,attempt,now,now,now))


def observe_job(tx,row,now=None):
    """Called inside the existing Job write transaction, or by reconciliation scan."""
    bid=row['business_id']
    if not operation_access.enabled() or not operation_access.eligible(tx,bid): return
    now=clock(now);jid=row['id']
    if row['status']=='READY_FOR_QUOTE':
        attention.ensure(tx,bid,'ready:'+jid,'READY_FOR_QUOTE',job_id=jid,now=now)
    else:
        attention.resolve_source(tx,bid,'ready:'+jid,now)
    if row['status']!='COMPLETED': return
    attention.ensure(tx,bid,'review:'+jid,'REVIEW_REQUEST_DUE',job_id=jid,now=now)
    if _config(tx,bid)['review_enabled']:
        cid=row['conversation_id']
        conv=tx.one('SELECT * FROM kw_web_conversations WHERE business_id=? AND id=?',(bid,cid)) if cid else None
        last=_last_customer(tx,bid,cid) if cid else None
        _enqueue(tx,bid,'review:'+jid,REVIEW,row['customer_id'],cid,jid,conv,last,1,now)


def _followup_due(tx,bid,conv,cfg,now):
    if not cfg['followup_enabled'] or conv['mode']!='AI_ACTIVE' or conv['expires_at']<=now: return None
    last=_last_customer(tx,bid,conv['id'])
    if not last: return None
    response=tx.one("SELECT id,created_at FROM kw_web_messages WHERE business_id=? AND conversation_id=? AND role='assistant' ORDER BY id DESC LIMIT 1",(bid,conv['id']))
    if not response or response['id']<last['id']: return None
    # No follow-up for a conversation whose only linked work has finished/cancelled.
    counts=tx.one("SELECT COUNT(*) AS n,SUM(CASE WHEN status NOT IN ('COMPLETED','CANCELLED') THEN 1 ELSE 0 END) AS active FROM kw_core_jobs WHERE business_id=? AND conversation_id=?",(bid,conv['id']))
    if counts['n'] and not counts['active']: return None
    sent=tx.one("SELECT COUNT(*) AS n,MAX(delivered_at) AS last_at FROM kw_core_automation_runs WHERE business_id=? AND conversation_id=? AND kind=? AND customer_message_id=? AND status='DELIVERED'",(bid,conv['id'],FOLLOWUP,last['id']))
    due=max(last['created_at'],response['created_at'],sent['last_at'] or 0)+cfg['delay_hours']*3600
    if sent['n']>=cfg['max_attempts'] or now<due: return None
    return last,sent['n']+1


def scan(bid,*,now=None,conversation_after='',job_after=''):
    now=clock(now)
    conversation_after=jobs._text(conversation_after,128);job_after=jobs._text(job_after,128)
    with jobs.transaction() as tx:
        jobs._lock(tx,bid);operation_access.require(tx,bid)
        cfg=_config(tx,bid)
        rows=tx.execute('SELECT * FROM kw_core_jobs WHERE business_id=? AND id>? ORDER BY id LIMIT 100',(bid,job_after))
        for row in rows: observe_job(tx,row,now)
        conversations=tx.execute('SELECT c.*,l.customer_id FROM kw_web_conversations c JOIN kw_web_customer_links l '
            'ON l.business_id=c.business_id AND l.conversation_id=c.id WHERE c.business_id=? AND c.id>? ORDER BY c.id LIMIT 100',(bid,conversation_after))
        for conv in conversations:
            due=_followup_due(tx,bid,conv,cfg,now)
            if due:
                last,attempt=due
                key='followup:'+hashlib.sha256(f"{conv['id']}:{conv['version']}:{last['id']}:{attempt}".encode()).hexdigest()
                _enqueue(tx,bid,key,FOLLOWUP,conv['customer_id'],conv['id'],None,conv,last,attempt,now)
        return {'next_conversation':conversations[-1]['id'] if len(conversations)==100 else None,
                'next_job':rows[-1]['id'] if len(rows)==100 else None}


def _terminal(tx,row,status,now,error=None):
    tx.execute('UPDATE kw_core_automation_runs SET status=?,updated_at=?,error_code=?,delivered_at=? WHERE business_id=? AND source_key=?',
               (status,now,error,now if status=='DELIVERED' else None,row['business_id'],row['source_key']))
    attention.audit(tx,row['business_id'],'WEB_AUTOMATION_'+status,{'source_key':row['source_key'],'kind':row['kind']})
    if status=='SKIPPED' and row['kind']==REVIEW:
        attention.ensure(tx,row['business_id'],'review:'+row['job_id'],'REVIEW_REQUEST_DUE',job_id=row['job_id'],now=now)
    return status


def deliver(bid,key,*,now=None):
    now=clock(now)
    try:
        with jobs.transaction() as tx:
            jobs._lock(tx,bid);operation_access.require(tx,bid)
            row=tx.one('SELECT * FROM kw_core_automation_runs WHERE business_id=? AND source_key=?',(bid,key))
            if not row: raise OperationError('not_found',404)
            if row['status']!='PENDING' or row['due_at']>now: return row['status']
            cfg=_config(tx,bid)
            allowed=cfg['followup_enabled'] if row['kind']==FOLLOWUP else cfg['review_enabled']
            if not allowed: return _terminal(tx,row,'SKIPPED',now,'DISABLED')
            conv=store._locked(tx,bid,row['conversation_id']) if row['conversation_id'] else None
            channel=tx.one('SELECT enabled FROM kw_web_channels WHERE business_id=?',(bid,))
            if not conv or not channel or not channel['enabled'] or conv['expires_at']<=now:
                return _terminal(tx,row,'SKIPPED',now,'UNAVAILABLE')
            if conv['mode']!='AI_ACTIVE' or conv['version']!=row['conversation_version']:
                return _terminal(tx,row,'SKIPPED',now,'STALE')
            last=_last_customer(tx,bid,conv['id'])
            if (last['id'] if last else None)!=row['customer_message_id']:
                return _terminal(tx,row,'SKIPPED',now,'STALE')
            if tx.one("SELECT event_id FROM kw_web_events WHERE business_id=? AND conversation_id=? AND status='processing' LIMIT 1",(bid,conv['id'])):
                return 'PENDING'  # Retry only after the foreground conversation finishes.
            if row['kind']==FOLLOWUP:
                due=_followup_due(tx,bid,conv,cfg,now)
                if not due or due[1]!=row['attempt']:
                    return _terminal(tx,row,'SKIPPED',now,'STALE')
            elif jobs._row(jobs._get(tx,bid,row['job_id']))['status']!='COMPLETED':
                return _terminal(tx,row,'SKIPPED',now,'STALE')
            attention.references(tx,bid,row['customer_id'],conv['id'],row['job_id'])
            event='automation_'+hashlib.sha256(key.encode()).hexdigest()
            store._message(tx,bid,conv['id'],event,'assistant',MESSAGES[row['kind']])
            result=_terminal(tx,row,'DELIVERED',now)
            if row['kind']==REVIEW: attention.resolve_source(tx,bid,'review:'+row['job_id'],now)
            return result
    except OperationError:
        raise
    except Exception:
        # The message/status transaction has rolled back. Record failure separately,
        # never mark delivered and never loop a model/network retry.
        with jobs.transaction() as tx:
            jobs._lock(tx,bid);operation_access.require(tx,bid)
            row=tx.one('SELECT * FROM kw_core_automation_runs WHERE business_id=? AND source_key=?',(bid,key))
            if not row: raise OperationError('not_found',404)
            if row['status']=='PENDING':
                _terminal(tx,row,'FAILED',now,'WRITE_FAILED')
                attention.ensure(tx,bid,'failed:'+key,'AUTOMATION_FAILED',customer_id=row['customer_id'],
                                 conversation_id=row['conversation_id'],job_id=row['job_id'],now=now)
            return row['status'] if row['status']!='PENDING' else 'FAILED'


def run(bid,*,now=None,conversation_after='',job_after=''):
    now=clock(now)
    result=scan(bid,now=now,conversation_after=conversation_after,job_after=job_after)
    with jobs.transaction() as tx:
        operation_access.require(tx,bid)
        pending=tx.execute("SELECT source_key FROM kw_core_automation_runs WHERE business_id=? AND status='PENDING' AND due_at<=? ORDER BY due_at,source_key LIMIT 100",(bid,now))
    result['results']=[deliver(bid,row['source_key'],now=now) for row in pending]
    return result


if __name__=='__main__':
    import argparse
    import json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--business-id',type=int,required=True)
    parser.add_argument('--conversation-after',default='')
    parser.add_argument('--job-after',default='')
    args=parser.parse_args()
    print(json.dumps(run(args.business_id,conversation_after=args.conversation_after,job_after=args.job_after)))
