"""Learning-only authenticated API; no provider secrets or transcripts in responses."""
from flask import Blueprint, request, g, session, jsonify, abort, redirect, url_for, Response
import security
import json
import re
from time import monotonic
from . import routes, learning, learning_store as store, audio_branded_voices as voices, audio_media
from .audio_transcription_budget import BudgetError
from .usage import UsageLimit

learning_bp=Blueprint('kilas_learning',__name__,url_prefix='/kilas-learning')

@learning_bp.before_request
def access():
    g.learning_started=monotonic()
    if not routes.enabled():
        abort(404)
    if not session.get('user_id'):
        if request.method=='GET' and request.path=='/kilas-learning':
            return redirect(url_for('auth.login_page'))
        abort(401)
    user=security.current_user()
    from . import free_test
    if not user or session.get('role')!=user['role'] or (user['role']!='CLIENT_OWNER' and not free_test.eligible(session['user_id'])):
        abort(403)
    if not learning.PRODUCT_ACTIVE:
        if request.endpoint not in ('kilas_learning.end','kilas_learning.cancel_start','kilas_learning.input_cancel'):
            if request.endpoint=='kilas_learning.home':
                abort(404)
            return jsonify(error='Learning telah dinonaktifkan.',code='learning_disabled',ended=True),410


@learning_bp.after_request
def private(response):
    response.headers['Cache-Control']='private, no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    # Safe control/status diagnostics: no identities, paths, prompts or audio.
    action=(request.endpoint or '').removeprefix('kilas_learning.')
    if action in ('current','status','turn_status','audio','start','input_start','cancel_start'):
        report={'action':action,'http_status':response.status_code,
                'duration_ms':round((monotonic()-g.get('learning_started',monotonic()))*1000)}
        if action in ('current','status','turn_status') and response.is_json:
            state=response.get_json(silent=True) or {}
            report.update(turn_status=state.get('status'),clips=len(state.get('clips') or []))
            code=state.get('error_code') or state.get('code')
            if code and re.fullmatch(r'[a-z_0-9]{1,80}',str(code)):report['error_code']=code
        print('KILAS_LEARNING_HTTP '+json.dumps(report,sort_keys=True),flush=True)
    return response


@learning_bp.errorhandler(store.Error)
@learning_bp.errorhandler(BudgetError)
@learning_bp.errorhandler(UsageLimit)
@learning_bp.errorhandler(audio_media.MediaError)
def invalid(error):
    return jsonify(error=str(error) if isinstance(error,store.Error) else 'Penggunaan belum tersedia. Periksa saldo atau coba nanti.',code=getattr(error,'code','unavailable')),getattr(error,'status',400)


@learning_bp.get('')
def home():
    # The cancelled product has no user-facing entry even under archived-code
    # tests that reactivate its internal pipeline. Historical rows stay internal.
    abort(404)


@learning_bp.get('/session')
def current():
    ident=store.current(session['user_id'])
    return jsonify(store.state(session['user_id'],ident) if ident else {'session_id':None})


@learning_bp.post('/sessions')
def start():
    owner=session['user_id'];learning.require_ready(owner)
    if request.form.get('consent')!='yes':
        raise store.Error('Setujui pemrosesan suara sebelum mulai.')
    if not voices.resolve(request.form.get('voice')):
        raise store.Error('Pilih suara yang tersedia.')
    ident,_=store.create(owner,request.form.get('start_key'),request.form.get('target'),request.form.get('native'),request.form.get('level'),request.form.get('voice'))
    # Fixed greeting operation survives a retried Start or reconnect without a second charge.
    try:
        learning.queue(owner,ident,'learn-'+ident+'-greeting')
    except store.Error as error:
        if error.code=='capacity':
            store.end(owner,ident)
        raise
    return jsonify(store.state(owner,ident)),201


@learning_bp.get('/sessions/<ident>')
def status(ident):
    return jsonify(store.state(session['user_id'],ident))


@learning_bp.get('/sessions/<ident>/turns/<turn>')
def turn_status(ident,turn):
    return jsonify(store.state(session['user_id'],ident,turn))


@learning_bp.get('/sessions/<ident>/turns/<turn>/clips/<int:index>')
def audio(ident,turn,index):
    return Response(store.clip(session['user_id'],ident,turn,index),mimetype='audio/mpeg')


@learning_bp.post('/sessions/<ident>/end')
def end(ident):
    store.end(session['user_id'],ident,retain_history=not learning.PRODUCT_ACTIVE)
    return jsonify(ended=True)


@learning_bp.post('/cancel-start')
def cancel_start():
    store.cancel_start(session['user_id'],request.form.get('start_key',''),request.form.get('session_id') or None,
                       retain_history=not learning.PRODUCT_ACTIVE)
    return jsonify(ended=True)


@learning_bp.post('/sessions/<ident>/input')
def input_start(ident):
    from . import learning_realtime
    turn=store.key(request.form.get('operation_key'))
    learning_realtime.begin(session['user_id'],ident,turn)
    return jsonify(store.state(session['user_id'],ident,turn)),202


@learning_bp.post('/sessions/<ident>/input/<turn>/chunks/<int:index>')
def input_chunk(ident,turn,index):
    from . import learning_realtime
    item=request.files.get('chunk')
    if not item:raise store.Error('Potongan audio tidak tersedia.')
    learning_realtime.append(session['user_id'],ident,turn,index,item.read(learning_realtime.MAX_CHUNK_BYTES+1))
    return jsonify(accepted=index)


@learning_bp.post('/sessions/<ident>/input/<turn>/commit')
def input_commit(ident,turn):
    from . import learning_realtime
    learning_realtime.commit(session['user_id'],ident,turn)
    return jsonify(store.state(session['user_id'],ident,turn)),202


@learning_bp.post('/sessions/<ident>/input/<turn>/cancel')
def input_cancel(ident,turn):
    from . import learning_realtime
    learning_realtime.cancel(session['user_id'],ident,turn)
    return jsonify(cancelled=True)
