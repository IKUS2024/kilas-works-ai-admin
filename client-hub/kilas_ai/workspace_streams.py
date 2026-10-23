"""Durable chat event replay. Disconnect never retries a paid provider request."""
import json
import secrets
import threading
import time
from datetime import timedelta
import db
from flask import Response,abort,current_app,request,session,stream_with_context
from . import autonomous_store as store,usage,agent_store
from .routes import ai_bp

_slots=threading.BoundedSemaphore(2)
_HeartbeatThread=threading.Thread
HEARTBEAT_SECONDS=15
TERMINAL=('COMPLETED','FAILED','CANCELLED','INTERRUPTED')


def owned(ident):
    row=db.query_one('SELECT * FROM kilas_workspace_streams WHERE id=? AND user_id=?',(ident,session['user_id']))
    if not row or not agent_store.conversation(session['user_id'],row['conversation_id']):abort(404)
    return dict(row)


def emit(ident,payload):
    with store.transaction() as conn:
        usage._query(conn,'INSERT INTO kilas_workspace_stream_events(stream_id,payload,created_at) VALUES (?,?,?)',(ident,json.dumps(payload,ensure_ascii=False),store.stamp()))
        usage._query(conn,'UPDATE kilas_workspace_streams SET updated_at=? WHERE id=?',(store.stamp(),ident))


def _recover(conn,owner):
    # An expired process is an uncertain terminal outcome, never permission to regenerate.
    cutoff=store.stamp(store.now()-timedelta(minutes=5))
    usage._query(conn,"UPDATE kilas_workspace_streams SET state='INTERRUPTED' WHERE user_id=? AND state='RUNNING' AND updated_at<?",(owner,cutoff))


def recover(owner,conversation):
    if not agent_store.conversation(owner,conversation):return
    with store.transaction() as conn:
        if db.BACKEND=='postgres':usage._query(conn,'SELECT id FROM users WHERE id=? FOR UPDATE',(owner,),one=True)
        _recover(conn,owner)


def start(owner,conversation,key,factory):
    prior=db.query_one('SELECT id FROM kilas_workspace_streams WHERE user_id=? AND operation_key=?',(owner,key))
    if prior:return response(prior['id'])
    if not _slots.acquire(blocking=False):
        # No provider dispatched and no usage reservation is repeated here.
        factory.close() if hasattr(factory,'close') else None
        abort(429)
    try:
        with store.transaction() as conn:
            # One active generation per owner across processes/tabs.
            if db.BACKEND=='postgres':usage._query(conn,'SELECT id FROM users WHERE id=? FOR UPDATE',(owner,),one=True)
            if not usage._query(conn,'SELECT id FROM kilas_ai_conversations WHERE id=? AND user_id=? AND archived_at IS NULL',(conversation,owner),one=True):abort(404)
            _recover(conn,owner)
            active=usage._query(conn,"SELECT id FROM kilas_workspace_streams WHERE user_id=? AND state='RUNNING'",(owner,),one=True)
            if active:abort(429)
            ident=usage._query(conn,"INSERT INTO kilas_workspace_streams(user_id,conversation_id,operation_key,created_at,updated_at) VALUES (?,?,?,?,?) RETURNING id",(owner,conversation,key,store.stamp(),store.stamp()),one=True)[0]
        app=current_app._get_current_object()
        threading.Thread(target=_run,args=(app,ident,factory),name='workspace-chat-'+str(ident),daemon=True).start()
        return response(ident)
    except Exception:
        _slots.release();raise


def _run(app,ident,factory):
    stopped=threading.Event()
    def heartbeat():
        with app.app_context():
            while not stopped.wait(HEARTBEAT_SECONDS):
                try:db.execute("UPDATE kilas_workspace_streams SET updated_at=? WHERE id=? AND state='RUNNING'",(store.stamp(),ident))
                except Exception:pass  # A failed DB heartbeat must not start another provider call.
    pulse=_HeartbeatThread(target=heartbeat,name='workspace-heartbeat-'+str(ident),daemon=True)
    pulse.start()
    with app.app_context():
        outcome='COMPLETED';buffer='';last=time.monotonic();started=last;had_error=False;count=0;first_delta=True
        try:
            emit(ident,{'type':'activity','label':'Berpikir…'})
            for update in factory:
                row=db.query_one('SELECT state,cancel_requested FROM kilas_workspace_streams WHERE id=?',(ident,))
                if not row or row['cancel_requested'] or row['state']!='RUNNING':outcome='CANCELLED';break
                count+=1
                if count>20000 or time.monotonic()-started>240:raise ValueError('stream_limit')
                if update['type']=='delta':
                    buffer+=update['text']
                    if len(buffer)<240 and time.monotonic()-last<.1 and not first_delta:continue
                    first_delta=False
                if buffer:emit(ident,{'type':'delta','text':buffer});buffer='';last=time.monotonic()
                if update['type']=='delta' or update['type']=='done':continue
                if update['type']=='error':had_error=True
                emit(ident,update)
            if buffer:emit(ident,{'type':'delta','text':buffer})
            if had_error:outcome='FAILED'
        except Exception:
            outcome='FAILED';emit(ident,{'type':'error','message':'Jawaban terhenti. Buka riwayat; permintaan tidak diulang otomatis.'})
        finally:
            try:
                factory.close() if hasattr(factory,'close') else None
                if outcome=='CANCELLED':
                    row=db.query_one('SELECT user_id,conversation_id FROM kilas_workspace_streams WHERE id=?',(ident,))
                    if row:agent_store.append(row['user_id'],'assistant','Pembuatan jawaban dihentikan. Hasil parsial tersimpan; permintaan tidak diulang otomatis.',row['conversation_id'])
                db.execute('UPDATE kilas_workspace_streams SET state=?,updated_at=? WHERE id=?',(outcome,store.stamp(),ident))
                emit(ident,{'type':'done','state':outcome})
            finally:
                stopped.set();pulse.join(timeout=1);_slots.release()


def response(ident):
    owner=session['user_id'];row=owned(ident)
    try:after=max(0,int(request.args.get('after') or request.headers.get('Last-Event-ID') or 0))
    except ValueError:abort(400)
    def events():
        nonlocal after
        deadline=time.monotonic()+20
        yield ': workspace stream\n\n'
        while time.monotonic()<deadline:
            rows=db.query_all('SELECT id,payload FROM kilas_workspace_stream_events WHERE stream_id=? AND id>? ORDER BY id LIMIT 100',(ident,after))
            for item in rows:after=item['id'];yield 'id: '+str(after)+'\ndata: '+item['payload']+'\n\n'
            current=db.query_one('SELECT state FROM kilas_workspace_streams WHERE id=? AND user_id=?',(ident,owner))
            if not current:return
            if current['state'] in TERMINAL and not rows:
                yield 'data: '+json.dumps({'type':'done','state':current['state']})+'\n\n';return
            if not rows:yield ': heartbeat\n\n';time.sleep(.2)
    return Response(stream_with_context(events()),mimetype='text/event-stream',headers={'Cache-Control':'private, no-store','X-Accel-Buffering':'no','X-Workspace-Stream':str(ident)})


@ai_bp.get('/work/streams/<int:ident>')
def workspace_stream(ident):
    owned(ident);return response(ident)


@ai_bp.post('/work/streams/<int:ident>/cancel')
def workspace_stream_cancel(ident):
    owned(ident)
    db.execute("UPDATE kilas_workspace_streams SET cancel_requested=1 WHERE id=? AND user_id=? AND state='RUNNING'",(ident,session['user_id']))
    return {'cancel_requested':True,'provider_billing_may_continue':True},200,{'Cache-Control':'private, no-store'}


@ai_bp.get('/work/streams')
def workspace_stream_active():
    conversation=request.args.get('conversation_id',type=int)
    if not agent_store.conversation(session['user_id'],conversation):abort(404)
    recover(session['user_id'],conversation)
    rows=db.query_all("SELECT id,state FROM kilas_workspace_streams WHERE user_id=? AND conversation_id=? AND state='RUNNING' ORDER BY id DESC LIMIT 1",(session['user_id'],conversation))
    return {'streams':[dict(row) for row in rows]},200,{'Cache-Control':'private, no-store'}
