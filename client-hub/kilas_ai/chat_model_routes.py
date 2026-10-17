"""Private model selection on the existing Chat authorization and CSRF boundary."""
import os
from flask import abort, request, session
from .routes import ai_bp, enabled
from . import chat_models


@ai_bp.record_once
def prepare_chat_models(state):
    if enabled():
        from .chat_models_schema import apply_release
        apply_release()
        if os.environ.get('RENDER_SERVICE_ID') and not state.app.testing:
            chat_models.warmup()  # Read-only Models APIs; never inference.


def _surface():
    surface=request.args.get('surface')
    ident=request.args.get('conversation_id',type=int)
    if surface is None:return None,None
    try:chat_models.owned(session['user_id'],surface,ident)
    except chat_models.SelectionError:abort(404)
    return surface,ident


@ai_bp.get('/chat/models')
def model_catalog():
    surface,ident=_surface()
    result=chat_models.catalog()
    selected=chat_models.preference(session['user_id'],surface,ident) if surface else None
    return {**result,'selected':selected or result['default']},200,{'Cache-Control':'private, no-store'}


@ai_bp.post('/chat/model')
def select_model():
    body=request.get_json(silent=True) or {}
    surface=body.get('surface');ident=body.get('conversation_id')
    if not isinstance(body.get('model'),str) or body['model'] not in chat_models.CATALOG:
        return {'error':'Model tidak valid. Pilih model dari daftar.'},400
    try:
        chat_models.owned(session['user_id'],surface,ident)
    except chat_models.SelectionError:abort(404)
    try:model=chat_models.choose(session['user_id'],surface,ident,body.get('model'))
    except chat_models.SelectionError as error:return {'error':str(error)},400
    return {'selected':model,'name':chat_models.spec(model)['name']}


@ai_bp.app_context_processor
def selector_context():
    def name(model):return chat_models.CATALOG.get(model,('',model or ''))[1]
    common={'chat_model_name':name}
    if request.endpoint == 'kilas_ai.agent_home' and request.args.get('view','chat')=='chat':
        return {**common,'ui_model_surface':{'surface':'conversation','id':session.get('agent_conversation_id')}}
    if request.endpoint in ('kilas_ai.home','kilas_ai.thread_page','products.product_start') or (request.endpoint=='auth.account_page' and (request.args.get('workspace')=='home' or session.get('active_product')!='finance')):
        return {**common,'ui_model_surface':{'surface':'thread','id':(request.view_args or {}).get('thread_id')}}
    return common
