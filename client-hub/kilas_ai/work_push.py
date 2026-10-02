"""Owned Web Push subscriptions and at-most-once transport attempts from durable events."""
import base64
import json
import os
from urllib.parse import urlsplit
import db
from . import autonomous_store as store, usage


def configured():
    return all(os.environ.get(k,'').strip() for k in ('KILAS_WEB_PUSH_PUBLIC_KEY','KILAS_WEB_PUSH_PRIVATE_KEY','KILAS_WEB_PUSH_SUBJECT'))


def register(owner, data):
    if not isinstance(data,dict):raise ValueError('invalid_subscription')
    endpoint=data.get('endpoint',''); parsed=urlsplit(endpoint)
    allowed=parsed.hostname in ('fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com') or bool(parsed.hostname and parsed.hostname.endswith('.notify.windows.com'))
    if parsed.scheme!='https' or not allowed or parsed.username or parsed.password or parsed.port not in (None,443) or len(endpoint)>2048 or parsed.fragment:raise ValueError('invalid_push_endpoint')
    keys=data.get('keys',{})
    if not isinstance(keys,dict):raise ValueError('invalid_push_keys')
    if set(keys)!= {'p256dh','auth'}:raise ValueError('invalid_push_keys')
    if any(not isinstance(v,str) or len(v)>150 for v in keys.values()):raise ValueError('invalid_push_keys')
    try:
        public=base64.urlsafe_b64decode(keys['p256dh']+'='*(-len(keys['p256dh'])%4))
        auth=base64.urlsafe_b64decode(keys['auth']+'='*(-len(keys['auth'])%4))
        from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey, SECP256R1
        EllipticCurvePublicKey.from_encoded_point(SECP256R1(),public)
        if len(auth)!=16 or any(len(v)>150 for v in keys.values()):raise ValueError('invalid_push_keys')
    except Exception:raise ValueError('invalid_push_keys') from None
    with store.transaction() as conn:
        # Owner lock serializes per-account subscription caps on PostgreSQL.
        if db.BACKEND=='postgres':usage._query(conn,'SELECT id FROM users WHERE id=? FOR UPDATE',(owner,),one=True)
        row=usage._query(conn,'SELECT id,user_id FROM kilas_work_push_subscriptions WHERE endpoint=?',(endpoint,),one=True)
        if row and row[1]!=owner:raise ValueError('subscription_not_owned')
        if not row and usage._query(conn,'SELECT COUNT(*) FROM kilas_work_push_subscriptions WHERE user_id=?',(owner,),one=True)[0]>=5:raise ValueError('subscription_limit')
        result=usage._query(conn,'INSERT INTO kilas_work_push_subscriptions(user_id,endpoint,keys_json) VALUES (?,?,?) ON CONFLICT(endpoint) DO UPDATE SET keys_json=excluded.keys_json,enabled=1 WHERE kilas_work_push_subscriptions.user_id=excluded.user_id RETURNING id',(owner,endpoint,json.dumps(keys)),one=True)
        if not result:raise ValueError('subscription_not_owned')
        return result[0]


def queue(conn,event_id,owner):
    if configured():usage._query(conn,"INSERT INTO kilas_work_push_deliveries(event_id,subscription_id) SELECT ?,id FROM kilas_work_push_subscriptions WHERE user_id=? AND enabled=1 ON CONFLICT(event_id,subscription_id) DO NOTHING",(event_id,owner))


def deliver(limit=10):
    if not configured():return 0
    from pywebpush import webpush, WebPushException
    sent=0
    rows=db.query_all("SELECT d.event_id,d.subscription_id,s.endpoint,s.keys_json,e.summary,j.origin_conversation_id FROM kilas_work_push_deliveries d JOIN kilas_work_push_subscriptions s ON s.id=d.subscription_id JOIN kilas_agent_events e ON e.id=d.event_id JOIN kilas_agent_jobs j ON j.id=e.job_id WHERE d.state='PENDING' AND s.enabled=1 AND s.user_id=j.user_id ORDER BY d.event_id LIMIT ?",(min(10,limit),))
    for row in rows:
        with store.transaction() as conn:
            claimed=usage._query(conn,"UPDATE kilas_work_push_deliveries SET state='ATTEMPTED',attempted_at=? WHERE event_id=? AND subscription_id=? AND state='PENDING' RETURNING event_id",(store.stamp(),row['event_id'],row['subscription_id']),one=True)
        if not claimed:continue
        # Commit before external delivery: ambiguous failures are never blindly resent.
        state='UNCERTAIN'
        try:
            webpush({'endpoint':row['endpoint'],'keys':json.loads(row['keys_json'])},json.dumps({'title':'Kilas AI','body':row['summary'][:240],'tag':'work-'+str(row['event_id']),'url':'/kilas-ai/agent?conversation='+str(row['origin_conversation_id'])}),vapid_private_key=os.environ['KILAS_WEB_PUSH_PRIVATE_KEY'],vapid_claims={'sub':os.environ['KILAS_WEB_PUSH_SUBJECT']},timeout=5,ttl=3600)
            state='SENT';sent+=1
        except WebPushException as error:
            if error.response is not None and error.response.status_code in (404,410):
                db.execute('UPDATE kilas_work_push_subscriptions SET enabled=0 WHERE id=?',(row['subscription_id'],));state='INVALID'
        except Exception:pass
        db.execute('UPDATE kilas_work_push_deliveries SET state=? WHERE event_id=? AND subscription_id=?',(state,row['event_id'],row['subscription_id']))
    return sent
