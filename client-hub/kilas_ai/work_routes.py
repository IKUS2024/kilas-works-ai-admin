"""Authenticated Work preferences, notifications, push registration and bounded start."""
import json
import math
import secrets
from datetime import timedelta
from flask import request, session, abort
import db
from .routes import ai_bp, automation_enabled
from . import autonomous_store as store, usage, automation_store, work_push


@ai_bp.before_request
def require_work_flag():
    if request.endpoint and request.endpoint.startswith('kilas_ai.work_') and not automation_enabled():
        abort(404)


@ai_bp.post('/work/preferences')
def work_preferences():
    data=request.get_json(silent=True) or {}
    if not isinstance(data,dict):abort(400)
    try:
        zone=data.get('timezone')
        if zone and zone != automation_store.setting(session['user_id']):
            automation_store.set_timezone(session['user_id'],zone)
    except ValueError:return {'error':'Pilih zona waktu yang valid.'},400
    return {'timezone':automation_store.setting(session['user_id']),'push_available':work_push.configured(),'public_key':db_key()}


def db_key():
    import os
    return os.environ.get('KILAS_WEB_PUSH_PUBLIC_KEY','') if work_push.configured() else ''


@ai_bp.post('/work/push')
def work_push_register():
    if not request.is_secure:abort(400)
    try:return {'id':work_push.register(session['user_id'],request.get_json(silent=True) or {})}
    except (ValueError,TypeError):return {'error':'Notifikasi perangkat belum dapat diaktifkan.'},400


@ai_bp.delete('/work/push/<int:subscription>')
def work_push_remove(subscription):
    db.execute('DELETE FROM kilas_work_push_subscriptions WHERE id=? AND user_id=?',(subscription,session['user_id']))
    return {},204


@ai_bp.post('/work/notifications/read')
def work_notifications_read():
    db.execute('UPDATE kilas_agent_events SET unread=0 WHERE job_id IN (SELECT id FROM kilas_agent_jobs WHERE user_id=?)',(session['user_id'],))
    return {},204


@ai_bp.post('/work/jobs/<int:job_id>/start')
def work_start(job_id):
    from . import autonomous_runner
    if not autonomous_runner.enabled():abort(404)
    # One persisted, owner-scoped due claim; no process/thread or unpersisted work.
    with store.transaction() as conn:
        token=secrets.token_hex(24)
        row=usage._query(conn,"UPDATE kilas_agent_jobs SET lease_token=?,lease_until=? WHERE id=? AND user_id=? AND status IN ('PLANNING','RUNNING','WAITING') AND next_wake_at<=? AND (lease_until IS NULL OR lease_until<=?) RETURNING id",(token,store.stamp(store.now()+timedelta(seconds=180)),job_id,session['user_id'],store.stamp(),store.stamp()),one=True)
    if row:autonomous_runner.execute(job_id,token)
    return {'started':bool(row)}


def location_payload(raw):
    if not raw:return None
    try:
        data=json.loads(raw)
        if data.get('permission_granted') is not True:raise ValueError('permission')
        values={k:float(data[k]) for k in ('latitude','longitude','accuracy','timestamp')}
        if not all(math.isfinite(v) for v in values.values()) or not -90<=values['latitude']<=90 or not -180<=values['longitude']<=180 or not 0<=values['accuracy']<=100000:raise ValueError('invalid_location')
        age=store.now().timestamp()*1000-values['timestamp']
        if not -30000<=age<=300000:raise ValueError('stale_location')
        return values
    except (ValueError,TypeError,KeyError,AttributeError):raise ValueError('invalid_location') from None


@ai_bp.get('/work/service-worker.js')
def work_service_worker():
    from flask import send_from_directory, current_app
    response=send_from_directory(current_app.static_folder,'kilas_work_sw.js',mimetype='application/javascript')
    response.headers['Service-Worker-Allowed']='/kilas-ai/'
    response.headers['Cache-Control']='no-cache'
    return response
