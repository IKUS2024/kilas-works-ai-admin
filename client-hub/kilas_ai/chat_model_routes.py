"""Private model selection on the existing Chat authorization and CSRF boundary."""
import os
from flask import abort, request, session
from .routes import ai_bp, enabled
from . import chat_models,model_preferences


@ai_bp.record_once
def prepare_chat_models(state):
    if enabled():
        from .chat_models_schema import apply_release
        apply_release()
        apply_release('0103_kilas_image_models')
        apply_release('0105_kilas_workspace_streams')
        apply_release('0106_kilas_workspace_execution')
        from .workspace_execution_proof import maybe_start
        maybe_start(state.app)  # No work without separate proof-specific approval.
        from .workspace_execution_access import log_readiness
        log_readiness()  # Read-only gate evidence; never creates a sandbox.
        if os.environ.get('RENDER_SERVICE_ID') and not state.app.testing:
            chat_models.warmup()  # Read-only Models APIs; never inference.
            from . import image_models
            image_models.warmup()


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
    selected=chat_models.preference(session['user_id'],surface,ident) if surface else model_preferences.get(session['user_id'],'chat')
    return {**result,'selected':selected or result['default']},200,{'Cache-Control':'private, no-store'}


@ai_bp.get('/chat/capabilities')
def workspace_capabilities():
    from .workspace_registry import registry
    return registry(),200,{'Cache-Control':'private, no-store'}


@ai_bp.post('/chat/model')
def select_model():
    body=request.get_json(silent=True) or {}
    surface=body.get('surface');ident=body.get('conversation_id')
    if not isinstance(body.get('model'),str) or body['model'] not in chat_models.CATALOG:
        return {'error':'Model tidak valid. Pilih model dari daftar.'},400
    if ident is not None:
        try:chat_models.owned(session['user_id'],surface,ident)
        except chat_models.SelectionError:abort(404)
    elif surface not in (None,'thread','conversation'):abort(400)
    try:
        model=body['model']
        if ident is not None:model=chat_models.choose(session['user_id'],surface,ident,model)
        elif not chat_models.check(model)['available']:raise chat_models.SelectionError('Model pilihan tidak tersedia. Pilih model lain; permintaan tidak dialihkan.')
        model_preferences.remember(session['user_id'],'chat',model)
    except chat_models.SelectionError as error:return {'error':str(error)},400
    return {'selected':model,'name':chat_models.spec(model)['name']}


@ai_bp.app_context_processor
def selector_context():
    def name(model):
        from . import image_models
        return (chat_models.CATALOG.get(model) or image_models.CATALOG.get(model) or ('',model or ''))[1]
    def preview(kind,surface,ident):
        # Resolve the same ownership scope as the catalog endpoint without IO.
        from . import image_models
        module=image_models if kind=='image' else chat_models
        selected=module.preference(session['user_id'],surface,ident) if ident is not None else model_preferences.get(session['user_id'],kind)
        if selected:
            try:return module.cached_metadata(selected) or module.spec(selected)
            except chat_models.SelectionError:return None
        cached=module.catalog(cache_only=True)
        return next((item for item in cached['models'] if item['id']==cached['default']),None) if cached else None
    common={'chat_model_name':name,'chat_model_preview':preview}
    if request.endpoint == 'kilas_ai.agent_home' and request.args.get('view','chat')=='chat':
        return {**common,'ui_model_surface':{'surface':'conversation','id':session.get('agent_conversation_id')}}
    if request.endpoint in ('kilas_ai.home','kilas_ai.thread_page','products.product_start') or (request.endpoint=='auth.account_page' and (request.args.get('workspace')=='home' or session.get('active_product')!='finance')):
        return {**common,'ui_model_surface':{'surface':'thread','id':(request.view_args or {}).get('thread_id')}}
    return common


@ai_bp.get('/chat/image-models')
def image_catalog():
    from . import image_models
    surface,ident=_surface();result=image_models.catalog()
    selected=image_models.preference(session['user_id'],surface,ident) if surface else model_preferences.get(session['user_id'],'image')
    selected=selected or result['default']
    return {**result,'selected':selected,'selected_info':image_models.check(selected) if selected else None},200,{'Cache-Control':'private, no-store'}


@ai_bp.post('/chat/image-model')
def select_image_model():
    from . import image_models
    body=request.get_json(silent=True) or {};surface=body.get('surface');ident=body.get('conversation_id')
    try:
        image_models.spec(body.get('model'))
        if ident is not None:chat_models.owned(session['user_id'],surface,ident)
        elif surface not in (None,'thread','conversation'):raise chat_models.SelectionError('invalid_surface')
    except chat_models.SelectionError:return {'error':'Model atau percakapan tidak valid.'},400
    try:
        model=body['model']
        if ident is not None:model=image_models.choose(session['user_id'],surface,ident,model)
        elif not image_models.check(model)['available']:raise chat_models.SelectionError('Model gambar pilihan tidak tersedia. Pilih model lain; permintaan tidak dialihkan.')
        model_preferences.remember(session['user_id'],'image',model)
    except chat_models.SelectionError as error:return {'error':str(error)},400
    return {'selected':model,'name':image_models.spec(model)['name']}
