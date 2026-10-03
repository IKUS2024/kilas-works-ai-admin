"""Conversational Agent front end over the existing account-owned task engine."""
import json
import logging
import re
import time
import secrets
from datetime import datetime, timezone

import db
from flask import abort, redirect, render_template, request, session, url_for

from . import agent_planner, agent_store, automation_schedule as schedule, automation_store as store, usage
from . import connectors, google_connection, connector_flow, connector_planner
from .routes import ai_bp, automation_enabled
from . import work_routes  # Register the scoped Work endpoints on the existing blueprint.


@ai_bp.before_request
def require_agent_flag():
    if request.endpoint and request.endpoint.startswith("kilas_ai.agent_") and not automation_enabled():
        abort(404)


def _owner():
    return session["user_id"]


def _clear_chat_context():
    for key in ('autonomous_job_id', 'agent_connector_context', 'agent_connector_context_at',
                'agent_work_clarification', 'agent_pending_action', 'automation_preview',
                'automation_preview_origin', 'connector_pending_intent', 'work_reminder_pending', 'work_location_request', 'work_document_pending'):
        session.pop(key, None)


@ai_bp.post('/agent/conversations', endpoint='agent_new_chat')
def new_chat():
    conversation_id = agent_store.new_conversation(_owner())
    _clear_chat_context()
    session['agent_conversation_id'] = conversation_id
    return redirect(url_for('kilas_ai.agent_home', conversation=conversation_id), code=303)


@ai_bp.post('/agent/conversations/<int:conversation_id>/rename', endpoint='agent_rename_chat')
def rename_chat(conversation_id):
    title = ' '.join(request.form.get('title', '').split())
    if not agent_store.conversation(_owner(), conversation_id):
        abort(404)
    if not 1 <= len(title) <= 60:
        abort(400)
    db.execute('UPDATE kilas_ai_conversations SET title=? WHERE id=? AND user_id=?', (title, conversation_id, _owner()))
    return redirect(url_for('kilas_ai.agent_home', conversation=conversation_id), code=303)


def _tasks():
    tasks = []
    for status in ("ACTIVE", "PAUSED"):
        rows, _ = store.list_for_owner(_owner(), status, 1)
        tasks.extend(dict(row) for row in rows)
    return tasks


def _reply(message):
    agent_store.append(_owner(), "assistant", message[:2400])


def _preview(item_id, spec):
    session["automation_preview"] = {"automation_id": item_id, "created": int(time.time()),
                                     "spec": {**spec, "next_run_at": spec["next_run_at"].isoformat()}}
    session["automation_preview_origin"] = "agent"
    session.modified = True


@ai_bp.get("/agent", endpoint="agent_home")
def agent_home():
    view = request.args.get("view", "chat")
    if view == 'connections':
        return redirect(url_for('kilas_ai.agent_home'), code=303)
    if view not in ("chat", "tasks", "activity", "connections", "history", "notifications", "settings"):
        view = "chat"
    owner = _owner()
    selected = request.args.get('conversation', type=int)
    if selected is not None:
        if not agent_store.conversation(owner, selected):
            abort(404)
        if selected != session.get('agent_conversation_id'):
            _clear_chat_context()
        session['agent_conversation_id'] = selected
    conversation_id = agent_store.current_conversation(owner)
    conversation = agent_store.conversation(owner, conversation_id)
    from . import autonomous_runner, autonomous_store, work_push
    from .agent_presentation import job_card, time_label
    if view == 'activity':
        return redirect(url_for('kilas_ai.agent_home', view='notifications'), code=303)
    raw_autonomous_jobs = autonomous_store.list_jobs(owner, active_only=True) if autonomous_runner.enabled() and view=='tasks' else []
    autonomous_jobs = [job_card(j) for j in raw_autonomous_jobs]
    active_count = db.query_one("SELECT COUNT(*) AS n FROM kilas_agent_jobs WHERE user_id=? AND status NOT IN ('COMPLETED','FAILED','STOPPED')", (owner,))['n'] if autonomous_runner.enabled() else 0
    autonomous_unread = db.query_one('SELECT COUNT(*) AS n FROM kilas_agent_events e JOIN kilas_agent_jobs j ON j.id=e.job_id WHERE j.user_id=? AND e.unread=1 AND e.kind IN (\'REMINDER\',\'CONDITION_MET\',\'COMPLETED\',\'FAILED\',\'WAITING_INPUT\',\'WAITING_CAPABILITY\',\'NEEDS_APPROVAL\',\'BLOCKED\')', (owner,))['n'] if autonomous_runner.enabled() else 0
    messages = agent_store.messages(owner, conversation_id=conversation_id, before=request.args.get('before',type=int)) if view=='chat' else []
    from . import agent_attachments
    message_attachments = agent_attachments.listing(owner, conversation_id, [m['id'] for m in messages])
    older = db.query_one('SELECT id FROM kilas_ai_agent_messages WHERE user_id=? AND conversation_id=? AND id<? LIMIT 1',(owner,conversation_id,messages[0]['id'])) if messages else None
    inline_jobs = {}
    if view == 'chat' and autonomous_runner.enabled():
        for job in autonomous_store.conversation_jobs(owner, conversation_id, [m['id'] for m in messages], include_unanchored=not older):
            inline_jobs.setdefault(job['origin_message_id'], []).append(job_card(job))
    page = max(1,min(request.args.get('page',1,type=int),10000))
    if view=='history' and autonomous_runner.enabled():
        history_jobs=db.query_all('SELECT * FROM kilas_agent_jobs WHERE user_id=? ORDER BY id DESC LIMIT 21 OFFSET ?',(owner,(page-1)*20))
        autonomous_jobs=[job_card(dict(row)) for row in history_jobs[:20]]
    history_chats, more_chats = agent_store.conversation_page(owner,page) if view=='history' else ([],False)
    from . import store as legacy_store
    legacy_chats=legacy_store.list_threads(owner) if view=='history' else []
    more_chats=more_chats or (view=='history' and autonomous_runner.enabled() and len(history_jobs)>20)
    from .work_runtime import LABELS
    notifications = [{**dict(e),'label':e['summary'] if e['kind']=='REMINDER' else LABELS.get(e['kind'],'Pekerjaan diperbarui'),'time_label':time_label(e['created_at'],store.setting(owner))} for e in db.query_all('SELECT e.*,j.origin_conversation_id FROM kilas_agent_events e JOIN kilas_agent_jobs j ON j.id=e.job_id WHERE j.user_id=? AND e.unread=1 AND e.kind IN (\'REMINDER\',\'CONDITION_MET\',\'COMPLETED\',\'FAILED\',\'WAITING_INPUT\',\'WAITING_CAPABILITY\',\'NEEDS_APPROVAL\',\'BLOCKED\') ORDER BY e.id DESC LIMIT 30',(owner,))] if view=='notifications' else []
    location = session.get('work_location_request')
    return render_template('kilas_ai/agent.html', view=view, messages=messages, message_attachments=message_attachments, conversation=conversation, inline_jobs=inline_jobs,
        recent_chats=agent_store.recent_conversations(owner), older=bool(older), operation_key=secrets.token_urlsafe(24),
        history_chats=history_chats, legacy_chats=legacy_chats, history_page=page, more_chats=more_chats, autonomous_jobs=autonomous_jobs,
        autonomous_enabled=autonomous_runner.enabled(), active_count=active_count, autonomous_unread=autonomous_unread,
        notifications=notifications, timezone=store.setting(owner), push_available=work_push.configured(),
        location_request=location if location and location['conversation']==conversation_id else None,
        error=request.args.get('error'), prefill=request.args.get('message','')[:1200])


@ai_bp.post("/agent/chat", endpoint="agent_chat")
def agent_chat():
    text = str(request.form.get("message") or "").strip()
    if not 1 <= len(text) <= 1200:
        return redirect(url_for("kilas_ai.agent_home", error="message"), code=303)
    owner = _owner()
    files=[f for f in request.files.getlist('source_files') if f.filename]
    if files:
        from . import attachments,work_attachments
        try:
            prepared=work_attachments.prepare_many(files,usage.effective_plan(owner)['plan'])
            request.work_attachments=prepared
            request.work_source_materials=[{'filename':item['filename'],'text':item['extracted_text'][:4000]} for item in prepared if item.get('extracted_text')]
        except attachments.AttachmentError as error:
            return {'error':str(error)},400
    selected = request.form.get('conversation_id', type=int)
    if selected is not None:
        if not agent_store.conversation(owner, selected):
            abort(404)
        if selected != session.get('agent_conversation_id'):
            _clear_chat_context()
        session['agent_conversation_id'] = selected
    conversation_id = agent_store.current_conversation(owner)
    key = request.form.get('operation_key') or secrets.token_urlsafe(24)
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,96}', key):
        abort(400)
    if not agent_store.claim_request(owner, conversation_id, key):
        return {'error': 'Pesan ini sudah diterima. Buka kembali chat untuk melihat hasilnya.'}, 409
    from . import work_runtime, work_routes
    zone=request.form.get('browser_timezone')
    if zone and not store.has_setting(owner):
        try:store.set_timezone(owner,zone)
        except ValueError:pass
    try:request.work_location=work_routes.location_payload(request.form.get('work_location'))
    except ValueError:return {'error':'Lokasi tidak valid. Berikan lokasi lagi atau sebutkan daerahnya.'},400
    # Acknowledgment clears event unread state only; durable inline results stay
    # attached to their original message, independently of this flag.
    db.execute(
        "UPDATE kilas_agent_events SET unread=0 WHERE job_id IN ("
        "SELECT id FROM kilas_agent_jobs WHERE user_id=? AND origin_conversation_id=? "
        "AND status IN ('COMPLETED','FAILED','STOPPED'))",
        (owner, conversation_id))
    request.work_origin_message_id = agent_store.append(owner, 'user', text, conversation_id,
                                                     attachments=getattr(request, 'work_attachments', ()))
    from .unified_runtime import dispatch
    return dispatch(owner,text,key,conversation_id)


@ai_bp.post("/agent/action", endpoint="agent_action")
def agent_action():
    pending = session.pop("agent_pending_action", None)
    if not pending or int(time.time()) - pending.get("created", 0) > 900:
        return redirect(url_for("kilas_ai.agent_home", error="expired"), code=303)
    item = store.get(_owner(), pending["id"])
    if not item or pending["action"] not in ("pause", "resume"):
        abort(404)
    try:
        store.set_status(_owner(), item["id"], pending["action"])
    except store.AutomationError:
        return redirect(url_for("kilas_ai.agent_home", error="action"), code=303)
    _reply(f"{item['title']} sudah {'dijeda' if pending['action'] == 'pause' else 'diaktifkan kembali'}.")
    return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)
