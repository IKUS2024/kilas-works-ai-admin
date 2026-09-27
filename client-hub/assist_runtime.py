"""One inference for production reply + incremental insight; fenced, atomic Core writes."""
import json
import time
import assist_reply
import assist_business_media
import ai_reply_explanation
from public_chat import store
from kilas_core import customers,jobs,customer_insights,customer_action_jobs


def process(business,message,event,history,*,eligibility,fence=None):
    bid,cid=business['id'],message.conversation_id
    customer=customers.customer_for_conversation(bid,cid)
    if not customer:return store.finish(event,error='provider_error')
    previous=customer_insights._stored(bid,customer['id'])
    with store.transaction() as snapshot:
        before=snapshot.execute('SELECT id,version FROM kw_core_jobs WHERE business_id=? AND customer_id=? ORDER BY updated_at DESC,id LIMIT 100',(bid,customer['id']))
    versions={j['id']:j['version'] for j in before}
    reply,insight,trace=assist_reply.generate(bid,message.text,history,
        customer_insights.for_inference(bid,customer['id'],previous),feature='tenant_customer')
    if not eligibility(bid):return store.finish(event,error='provider_error')
    with store.transaction() as tx:
        jobs._lock(tx,bid)
        def commit(transaction):
            if fence is not None and not fence(transaction):return None
            current=transaction.one('''SELECT c.*,s.stage FROM kw_core_customers c
                JOIN kw_core_customer_stages s ON s.business_id=c.business_id AND s.customer_id=c.id
                WHERE c.business_id=? AND c.id=?''',(bid,customer['id']))
            if not current:return None
            latest=transaction.execute('SELECT id,version FROM kw_core_jobs WHERE business_id=? AND customer_id=? ORDER BY updated_at DESC,id LIMIT 100',(bid,customer['id']))
            if {j['id']:j['version'] for j in latest} != versions:
                # Human changes made during inference win. Do not overwrite operational facts.
                ai_reply_explanation.save_core(transaction,bid,cid,message.external_message_id,ai_reply_explanation.stale_update())
                return 'Tim baru memperbarui permintaan Anda. Saya minta tim memeriksa detail terbaru terlebih dahulu.'
            now=int(time.time())
            cursor=transaction.one('SELECT MAX(id) AS n FROM kw_web_messages WHERE business_id=? AND conversation_id=?',(bid,cid))['n'] or 0
            stored=transaction.one('SELECT * FROM kw_core_customer_insights WHERE business_id=? AND customer_id=?',(bid,current['id']))
            if not stored or stored['core_message_cursor']<cursor:
                transaction.execute('''INSERT INTO kw_core_customer_insights
                    (business_id,customer_id,insight_json,core_message_cursor,demo_message_cursor,analyzed_message_count,updated_at)
                    VALUES (?,?,?,?,?,?,?) ON CONFLICT(business_id,customer_id) DO UPDATE SET
                    insight_json=excluded.insight_json,core_message_cursor=excluded.core_message_cursor,
                    analyzed_message_count=excluded.analyzed_message_count,updated_at=excluded.updated_at''',
                    (bid,current['id'],json.dumps(insight,ensure_ascii=False),cursor,
                     (stored or {}).get('demo_message_cursor',0),(stored or {}).get('analyzed_message_count',0)+1,now))
                if (current['stage']=='LEAD' and insight.get('action')
                        and insight.get('job_status') in ('PERLU_TINDAKAN','DIKERJAKAN')):
                    transaction.execute("UPDATE kw_core_customer_stages SET stage='CUSTOMER',updated_at=? WHERE business_id=? AND customer_id=?",(now,bid,current['id']))
                    transaction.execute('INSERT INTO audit_log(business_id,action,detail) VALUES (?,?,?)',
                        (bid,'ASSIST_CUSTOMER_PROMOTED',current['id']))
                    current['stage']='CUSTOMER'
                customer_action_jobs.sync_from_insight(business,current,
                    dict(insight,_meta={'fresh':True,'has_history':True}),transaction=transaction)
            assist_business_media.schedule(transaction, bid, 'core:' + message.external_message_id,
                                           cid, trace.pop('_media', None))
            ai_reply_explanation.save_core(transaction,bid,cid,message.external_message_id,trace)
            if insight.get('_handoff_requested'):
                from kilas_core import operation_access, handover
                if operation_access.eligible(transaction,bid):
                    handover.request_human(transaction,bid,cid,'HUMAN')
                else:
                    # Human requests remain effective even with optional attention UI disabled.
                    from kilas_core.adapters.whatsapp import binding
                    import wa_takeover_service
                    store._set_mode(transaction,bid,cid,'HUMAN_TAKEOVER',None,origin='ASSIST_HANDOFF')
                    link=binding(transaction,bid,cid)
                    if link:
                        wa_takeover_service.set_state_in_transaction(transaction,bid,link['customer_phone'],'HUMAN_TAKEOVER',None)
            return reply
        result=store._finish(tx,event,before_reply=commit)
        reply_row=tx.one("SELECT id FROM kw_web_messages WHERE business_id=? AND conversation_id=? AND event_id=? AND role='assistant'",(bid,cid,message.external_message_id))
        if reply_row:
            tx.execute('UPDATE kw_core_customer_insights SET core_message_cursor=? WHERE business_id=? AND customer_id=? AND core_message_cursor<?',
                (reply_row['id'],bid,customer['id'],reply_row['id']))
        return result
