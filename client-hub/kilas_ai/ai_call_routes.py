"""AI Call shares authenticated AI access, never Translator endpoints."""
import re
from flask import abort, render_template, request, session
import security
import ui_i18n
from .routes import ai_bp
from . import ai_call as calls, ai_call_budget as budget

HEADERS={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}


@ai_bp.get('/call/audio-check')
def ai_call_audio_check():
    """Explicit local-only hardware check; no Call admission or provider IO."""
    return render_template('kilas_ai/call_audio_check.html'),200,{
        **HEADERS,
        'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        'Permissions-Policy':'microphone=(self), camera=(), geolocation=()',
        'Referrer-Policy':'no-referrer',
    }


def csrf():
    if not security.validate_csrf_token(request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')):abort(403)


def failure(error):
    code=getattr(error,'code','call_unavailable')
    known={'call_unavailable','call_ended','call_input_invalid','call_limit','call_backlog',
           'call_cursor_invalid','call_transport','not_owned','invalid_operation','already_processing',
           'service_busy','budget_limit','account_credit_limit','attempt_limit','duplicate_turn','reservation_expired'}
    return {'code':code if code in known else 'call_unavailable'},getattr(error,'status',503),HEADERS


@ai_bp.get('/call/readiness')
def ai_call_readiness():
    try:
        if not calls.ready(session['user_id']):return {'available':False,'reason':'call_unavailable'},200,HEADERS
        return budget.status(session['user_id']),200,HEADERS
    except Exception:return {'available':False,'reason':'call_unavailable'},200,HEADERS


@ai_bp.route('/call/<ident>',methods=['GET','POST'])
def ai_call_session(ident):
    if not re.fullmatch(r'[a-f0-9]{32}',ident):abort(404)
    try:
        if request.method=='POST':
            csrf()
            call=calls.start(session['user_id'],ident)
            return {'call_id':ident,'state':call.state},202,HEADERS
        call=calls.get(session['user_id'],ident)
        if call is None:return {'state':'CLOSED','code':'call_ended','frames':[],'next_index':0,'total_frames':0},200,HEADERS
        try:after=int(request.args.get('after','0'))
        except ValueError:abort(400)
        return call.snapshot(after),200,HEADERS
    except (calls.CallError,budget.ledger.BudgetError) as error:return failure(error)


@ai_bp.post('/call/<ident>/chunks/<int:index>')
def ai_call_chunk(ident,index):
    csrf()
    if request.content_length is None or not 2<=request.content_length<=16000:abort(400)
    try:
        call=calls.get(session['user_id'],ident)
        if call is None:raise calls.CallError('call_ended',409)
        try:call.accept(index,request.get_data(cache=False))
        except Exception:
            call.stop('call_input_invalid',erase=True)
            raise
        return {'accepted_index':index},200,HEADERS
    except (calls.CallError,budget.ledger.BudgetError) as error:return failure(error)


@ai_bp.post('/call/<ident>/ready')
def ai_call_client_ready(ident):
    """Browser audio readiness only; never a new provider/session admission."""
    csrf()
    try:
        value=request.get_json(silent=True) if request.is_json else None
        if (not isinstance(value,dict) or set(value)!={'language','user_started_speaking'}
                or not isinstance(value['language'],str) or value['language'] not in ui_i18n.LANGUAGES
                or type(value['user_started_speaking']) is not bool):
            raise calls.CallError('call_input_invalid',400)
        call=calls.get(session['user_id'],ident)
        if call is None:raise calls.CallError('call_ended',409)
        # Use the same explicit UI cookie as the rendered page, never browser
        # language guessing or arbitrary text in a client-generated prompt.
        selected=ui_i18n.language()
        call.client_ready(selected,user_started_speaking=value['user_started_speaking'])
        return {'ready':True,'language':selected},200,HEADERS
    except (calls.CallError,budget.ledger.BudgetError) as error:return failure(error)


@ai_bp.post('/call/<ident>/end')
def ai_call_end(ident):
    csrf()
    try:
        calls.end(session['user_id'],ident)
        return {'state':'CLOSED'},200,HEADERS
    except (calls.CallError,budget.ledger.BudgetError) as error:return failure(error)
