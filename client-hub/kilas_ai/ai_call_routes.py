"""AI Call shares authenticated AI access, never Translator endpoints."""
import re
from flask import abort, request, session
import security
from .routes import ai_bp
from . import ai_call as calls, ai_call_budget as budget

HEADERS={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}


def csrf():
    if not security.validate_csrf_token(request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')):abort(403)


def failure(error):
    code=getattr(error,'code','call_unavailable')
    known={'call_unavailable','call_ended','call_input_invalid','call_limit','call_backlog',
           'call_cursor_invalid','call_transport','not_owned','invalid_operation','already_processing',
           'service_busy','budget_limit','attempt_limit','duplicate_turn','reservation_expired'}
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


@ai_bp.post('/call/<ident>/end')
def ai_call_end(ident):
    csrf()
    try:
        calls.end(session['user_id'],ident)
        return {'state':'CLOSED'},200,HEADERS
    except (calls.CallError,budget.ledger.BudgetError) as error:return failure(error)
