"""Authoritative demo bindings on Kilas's shared WhatsApp transport.

Message membership is explicit; phone strings and open-ended message ranges cannot
grant access to another session. The platform Inbox keeps the original message rows.
"""
import hashlib
import json
import re
import secrets
import time
import uuid

import assist_journey
import db
import repo
from kilas_core.customers import transaction

MARKER = re.compile(r'\bKWDEMO-([0-9a-f]{24})\b', re.I)


def latest(bid):
    return db.query_one('SELECT * FROM kw_assist_demo_sessions WHERE business_id=? '
                        'ORDER BY active DESC,created_at DESC,id DESC LIMIT 1', (bid,))


def begin(bid, actor):
    business = repo.get_business(bid)
    state = assist_journey.state(business)
    if not state['ready'] or state['connected'] or not (state['demo_active'] or state['paid']):
        raise ValueError('demo_unavailable')
    if not db.query_one('SELECT 1 FROM business_memberships WHERE business_id=? AND user_id=?', (bid, actor)):
        raise ValueError('not_found')
    token, sid, now = secrets.token_hex(12), uuid.uuid4().hex, int(time.time())
    expiry = int(state['demo_expires_at'].timestamp()) if state['demo_active'] else now + 7 * 86400
    with transaction() as tx:
        tx.execute('UPDATE businesses SET id=id WHERE id=?', (bid,))
        tx.execute('UPDATE kw_assist_demo_sessions SET active=FALSE WHERE business_id=? AND active=TRUE', (bid,))
        tx.execute('INSERT INTO kw_assist_demo_sessions(id,business_id,actor_id,token_hash,created_at,expires_at) '
                   'VALUES (?,?,?,?,?,?)', (sid,bid,actor,hashlib.sha256(token.encode()).hexdigest(),now,expiry))
    return sid, 'KWDEMO-' + token


def resolve(phone, text, *, now=None):
    """Called only after the webhook verified the platform Phone Number ID and signature."""
    if not isinstance(phone, str) or not re.fullmatch(r'[1-9][0-9]{7,14}', phone):
        return None
    now = int(time.time()) if now is None else now
    match = MARKER.search(text or '')
    if match:
        token_hash = hashlib.sha256(match[1].lower().encode()).hexdigest()
        candidate = db.query_one('SELECT * FROM kw_assist_demo_sessions WHERE token_hash=?', (token_hash,))
        if not candidate or not candidate['active'] or candidate['expires_at'] <= now:
            raise ValueError('invalid_demo_binding')
        if candidate['sender_phone'] and candidate['sender_phone'] != phone:
            raise ValueError('demo_already_bound')
        with transaction() as tx:
            # Serialize binding claims on the shared platform identity, including concurrent
            # attempts to bind one sender to separate business sessions.
            suffix = ' FOR UPDATE' if db.BACKEND == 'postgres' else ''
            tx.one('SELECT id FROM users WHERE id=?'+suffix, (candidate['actor_id'],))
            current = tx.one('SELECT * FROM kw_assist_demo_sessions WHERE id=?'+suffix, (candidate['id'],))
            if (not current['active'] or current['expires_at'] <= now or
                    current['sender_phone'] not in (None, phone)):
                raise ValueError('invalid_demo_binding')
            # A new explicit binding ends the previous sender's session; old messages remain
            # associated only with the old session. Unique index is the final concurrency guard.
            tx.execute('UPDATE kw_assist_demo_sessions SET active=FALSE '
                       'WHERE sender_phone=? AND id<>? AND active=TRUE', (phone, current['id']))
            tx.execute('UPDATE kw_assist_demo_sessions SET sender_phone=? WHERE id=?', (phone,current['id']))
            if current['sender_phone'] is None:
                # The explicit new invitation starts a new Demo. Do not inherit a human
                # takeover from a previous tenant/legacy conversation on this shared phone.
                tx.execute("INSERT INTO platform_wa_conversation_state(customer_phone,mode) VALUES (?,'AI_ACTIVE') "
                           "ON CONFLICT(customer_phone) DO UPDATE SET mode='AI_ACTIVE',updated_by_user_id=NULL",
                           (phone,))
            current['sender_phone'] = phone
        return current
    # Keep the expired sender recognizable so it cannot fall through to platform knowledge.
    return db.query_one('SELECT * FROM kw_assist_demo_sessions WHERE sender_phone=? '
                        'AND active=TRUE', (phone,))


def binding(bid, phone=None):
    row = latest(bid)
    if not row or not row['sender_phone'] or phone and row['sender_phone'] != phone:
        return None
    return dict(row, phone=row['sender_phone'], session_id=row['id'])


def rows(bid, phone, *, after=0, limit=160):
    bound = binding(bid, phone)
    if not bound:
        return []
    return db.query_all('SELECT m.id,m.role,m.content,m.created_at FROM messages m '
        'JOIN kw_assist_demo_events e ON (e.inbound_message_id=m.id OR e.reply_message_id=m.id) '
        'WHERE e.business_id=? AND e.session_id=? AND m.number=? AND m.id>? '
        'ORDER BY m.id LIMIT ?', (bid,bound['id'],phone,after,max(1,min(limit,160))))


def message_allowed(bid, phone, message_id):
    bound = binding(bid, phone)
    return bool(bound and db.query_one('SELECT 1 FROM kw_assist_demo_events WHERE business_id=? '
        'AND session_id=? AND (inbound_message_id=? OR reply_message_id=?)',
        (bid,bound['id'],message_id,message_id)))


def require_outgoing_scope(scope, phone):
    if not isinstance(scope, dict) or type(scope.get('business_id')) is not int:
        raise ValueError('invalid_demo_scope')
    bound = binding(scope['business_id'], phone)
    if (not bound or not bound['active'] or bound['expires_at'] <= int(time.time())
            or bound['id'] != scope.get('session_id')):
        raise ValueError('invalid_demo_scope')
    return bound


def record_sent(bound, text):
    """A trusted sender supplies the exact session checked before its send, never a phone scan."""
    now = int(time.time())
    with transaction() as tx:
        mid = tx.one("INSERT INTO messages(number,mode,role,content) VALUES (?,'customer','assistant',?) RETURNING id",
                     (bound['phone'],text))['id']
        tx.execute('INSERT INTO kw_assist_demo_events(provider_id,session_id,business_id,payload_hash,'
                   'reply_message_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                   ('manual_'+uuid.uuid4().hex,bound['id'],bound['business_id'],
                    hashlib.sha256(text.encode()).hexdigest(),mid,'sent',now,now))
    return mid


def record_sent_media(bound, provider_id):
    """Attach the exact media message row; never infer membership from a sender/date range."""
    import inbox_media_service
    row=db.query_one('SELECT * FROM inbox_media WHERE scope_key=? AND event_id=?',
                     (inbox_media_service.scope(None),provider_id))
    if not row or not row.get('message_row_id'):return False
    message=db.query_one("SELECT id FROM messages WHERE id=? AND number=? AND role='assistant'",
                         (row['message_row_id'],bound['phone']))
    if not message:return False
    now=int(time.time())
    db.execute('INSERT INTO kw_assist_demo_events(provider_id,session_id,business_id,payload_hash,'
        'reply_message_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(provider_id) DO NOTHING',
        ('manual_media_'+provider_id,bound['id'],bound['business_id'],hashlib.sha256(provider_id.encode()).hexdigest(),
         message['id'],'sent',now,now))
    return True


def process(event, *, profile_name=None, media_message_id=None, send, media_channel=None):
    """Platform webhook only, after signature + Phone Number ID verification.

    Returns False only when this sender is not a demo. Claims are durable before inference
    or send. Ambiguous delivery is never retried automatically. Tenant membership is explicit.
    """
    import assist_reply
    import platform_inbox_service
    from kilas_core import customers, customer_action_jobs, customer_insights

    phone, provider_id = event.get('from'), event.get('id')
    content = (event.get('text') or {}).get('body') or (event.get(event.get('type')) or {}).get('caption') or ''
    if not isinstance(provider_id, str) or not provider_id or len(provider_id) > 512:
        raise ValueError('invalid_event')
    digest = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    prior = db.query_one('SELECT * FROM kw_assist_demo_events WHERE provider_id=?', (provider_id,))
    if prior:
        if prior['payload_hash'] != digest:
            raise ValueError('event_conflict')
        return True
    bound = resolve(phone, content)
    if not bound:
        return False
    bid, now = bound['business_id'], int(time.time())
    state = assist_journey.state(repo.get_business(bid))
    if bound['expires_at'] <= now or state['connected'] or not (state['demo_active'] or state['paid']):
        return False  # Webhook sends only the fixed workspace instruction, never legacy AI.
    if not content:
        content = '[Lampiran '+str(event.get('type') or 'pesan')+']'
    with transaction() as tx:
        tx.execute('UPDATE kw_assist_demo_sessions SET id=id WHERE id=?', (bound['id'],))
        prior = tx.one('SELECT provider_id FROM kw_assist_demo_events WHERE provider_id=?', (provider_id,))
        if prior:
            return True
        if media_message_id:
            original = tx.one('SELECT id FROM messages WHERE id=? AND number=? AND role=?',
                              (media_message_id, phone, 'user'))
            if not original:
                raise ValueError('invalid_media_scope')
            mid = media_message_id
        else:
            mid = tx.one("INSERT INTO messages(number,mode,role,content) VALUES (?,'customer','user',?) RETURNING id",
                         (phone, content))['id']
        tx.execute('INSERT INTO kw_assist_demo_events(provider_id,session_id,business_id,payload_hash,'
                   'inbound_message_id,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                   (provider_id,bound['id'],bid,digest,mid,'processing',now,now))
    customer = customers.ensure_whatsapp_lead(bid, phone, profile_name)
    if platform_inbox_service.get_state(phone) != 'AI_ACTIVE':
        db.execute("UPDATE kw_assist_demo_events SET status='human' WHERE provider_id=?", (provider_id,))
        return True
    try:
        if MARKER.search(content):
            reply = 'Demo aktif ✅ Sekarang chat seperti customer bisnis kamu.'
            insight, trace = None, {'title':'Demo terhubung','intent':'Aktivasi demo',
                'summary':'Kode demo menghubungkan percakapan ini ke workspace Anda.', 'confidence':100}
        else:
            history = rows(bid, phone)
            previous = customer_insights._stored(bid, customer['id']) if customer else None
            reply, insight, trace = assist_reply.generate(bid, content,
                [{'role':r['role'], 'content':r['content'][:1200]} for r in history[-13:] if r['id'] != mid],
                customer_insights.for_inference(bid, customer['id'], previous) if customer else None)
        # Owner takeover or a new binding wins over a response generated in flight.
        current = db.query_one('SELECT active FROM kw_assist_demo_sessions WHERE id=?', (bound['id'],))
        if not current['active'] or platform_inbox_service.get_state(phone) != 'AI_ACTIVE':
            db.execute("UPDATE kw_assist_demo_events SET status='human' WHERE provider_id=?", (provider_id,))
            return True
        if insight and insight.get('_handoff_requested'):
            # The customer gets this acknowledgement, then only the owner's explicit
            # return-to-AI action may resume automated replies, just as in production.
            platform_inbox_service.start_human_takeover(phone)
        import assist_business_media
        with transaction() as tx:
            assist_business_media.schedule(tx, bid, 'demo:' + provider_id, bound['id'], trace.pop('_media', None))
        db.execute("UPDATE kw_assist_demo_events SET reply_text=?,explanation_json=?,status='sending' WHERE provider_id=?",
                   (reply,json.dumps(trace,ensure_ascii=False),provider_id))
        ok, _ = send(phone, reply)
        with transaction() as tx:
            reply_mid = None
            if ok:
                reply_mid = tx.one("INSERT INTO messages(number,mode,role,content) VALUES (?,'customer','assistant',?) RETURNING id",
                                  (phone, reply))['id']
            tx.execute('UPDATE kw_assist_demo_events SET reply_message_id=?,status=?,updated_at=? WHERE provider_id=?',
                       (reply_mid,'sent' if ok else 'delivery_unknown',int(time.time()),provider_id))
        if insight and customer:
            persist_insight(bid, customer, insight, max(mid,reply_mid or 0))
        if ok and media_channel:
            assist_business_media.deliver_demo(bound, provider_id, media_channel)
        return True
    except Exception:
        # A claimed event remains inspectable; no hidden replay can duplicate a send or Job.
        db.execute("UPDATE kw_assist_demo_events SET status=CASE WHEN status='sending' THEN 'delivery_unknown' "
                   "WHEN status='processing' THEN 'needs_review' ELSE status END WHERE provider_id=?", (provider_id,))
        raise


def persist_insight(bid, customer, insight, cursor):
    from kilas_core import customers, customer_action_jobs, customer_insights
    now = int(time.time())
    with transaction() as tx:
        tx.execute('UPDATE businesses SET id=id WHERE id=?', (bid,))
        previous = tx.one('SELECT * FROM kw_core_customer_insights WHERE business_id=? AND customer_id=?',
                          (bid,customer['id']))
        if previous and previous['demo_message_cursor'] >= cursor:
            return
        tx.execute('INSERT INTO kw_core_customer_insights(business_id,customer_id,insight_json,core_message_cursor,'
                   'demo_message_cursor,analyzed_message_count,updated_at) VALUES (?,?,?,?,?,?,?) '
                   'ON CONFLICT(business_id,customer_id) DO UPDATE SET insight_json=excluded.insight_json,'
                   'demo_message_cursor=excluded.demo_message_cursor,analyzed_message_count=excluded.analyzed_message_count,'
                   'updated_at=excluded.updated_at',
                   (bid,customer['id'],json.dumps(insight,ensure_ascii=False),
                    (previous or {}).get('core_message_cursor',0),cursor,
                    (previous or {}).get('analyzed_message_count',0)+1,now))
    insight = dict(insight, _meta={'has_history':True,'fresh':True})
    business = repo.get_business(bid)
    customer = customer_action_jobs.promote_lead_if_actionable(business,customer,insight)
    customer_action_jobs.sync_from_insight(business,customer,insight)
