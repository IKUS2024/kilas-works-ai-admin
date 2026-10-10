"""Default-off live assistance, separate from synthetic demo and project persistence."""
from flask import abort, render_template, request, session
from .routes import ai_bp
from . import live_assist as live


@ai_bp.before_request
def gate_live_assist():
    if (request.endpoint or '').startswith('kilas_ai.live_assist_') and not live.enabled(session.get('user_id')):abort(404)


@ai_bp.get('/live-assist',endpoint='live_assist_home')
def home():
    owner=session['user_id']
    provider_ready=live.qa.ready(owner,for_start=True) and live.stt.configured() if live.qa.enabled() else live.ready(owner)
    return render_template('kilas_content/live_assist.html',provider_ready=provider_ready,qa_only=live.qa.enabled()),200,{'Cache-Control':'private, no-store'}


@ai_bp.post('/live-assist/<operation>',endpoint='live_assist_action')
def action(operation):
    owner=session['user_id'];token=request.form.get('session_id','')
    try:
        if operation=='start':result={'session_id':live.create(owner,request.form.get('mode'),request.form.get('target'),request.form.get('consent')=='yes',request.form.get('sample_consent')=='yes')}
        elif operation=='stop':live.stop(owner,token);result={'stopped':True}
        elif operation=='chunk':result=live.chunk(owner,token,request.form.get('sequence',type=int),request.files.get('audio'))
        elif operation=='reply':result={'text':live.reply(owner,token,request.form.get('operation_key',''),request.form.get('facts',''))}
        else:abort(404)
        return result,200,{'Cache-Control':'private, no-store'}
    except LookupError:abort(404)
    except live.LiveError as error:
        code=str(error)
        return {'code':code,'error':'Pemrosesan provider belum aktif; persetujuan biaya belum tersedia.' if code=='budget_unavailable' else 'Pemrosesan berhenti. Tidak mencoba ulang otomatis; mulai sesi baru setelah memeriksa status.'},503 if code in ('budget_unavailable','chunk_failed','text_failed') else 409,{'Cache-Control':'private, no-store'}
