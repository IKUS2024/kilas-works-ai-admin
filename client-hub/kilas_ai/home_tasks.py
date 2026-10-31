"""Presentation-only Home task entry; existing transports and billing stay intact."""
from flask import abort, request
from .routes import ai_bp, automation_enabled


def context(owner):
    from . import agent_store, attachments, live_assist, live_qa_budget, store, usage,sidebar_history,copilot
    return {
        'automation_enabled': automation_enabled(),
        'limits': attachments.limits(usage.attachment_plan(owner)),
        'history_items': sidebar_history.recent(owner,include_conversations=automation_enabled(),copilot_only=copilot.visible(),exclude_copilot=not copilot.visible()),
        'threads': store.list_threads(owner, 6),
        'conversations': agent_store.recent_conversations(owner)[:6] if automation_enabled() else [],
        'live_available': live_qa_budget.enabled() and live_assist.ready(owner) and live_qa_budget.ready(owner,for_start=True),
    }


@ai_bp.app_context_processor
def audio_offering_context():
    from .audio_presentation import upload_translation_visible
    result = {'upload_translation_visible': upload_translation_visible(), 'live_translation_visible': False}
    if request.blueprint == 'finance':
        from flask import session
        if session.get('role') == 'CLIENT_OWNER' and session.get('user_id'):
            from . import live_translator
            result['kilas_live_translator_available'] = live_translator.ready(session['user_id'])
    return result


@ai_bp.app_context_processor
def chat_sidebar_context():
    """Owned, read-only sidebar projection on Kilas surfaces only."""
    from flask import session
    from .routes import enabled
    endpoint = request.endpoint or ''
    home_account = (endpoint == 'auth.account_page' and
                    (request.args.get('workspace') == 'home' or session.get('active_product') != 'finance'))
    surface = (endpoint in ('products.product_start', 'products.finance_entry') or home_account or
               request.blueprint in ('kilas_ai', 'kilas_audio', 'kilas_learning'))
    if request.endpoint in ('kilas_ai.shared','kilas_ai.share') or not (surface and enabled() and session.get('user_id') and session.get('role') == 'CLIENT_OWNER'):
        return {}

    def history():
        from . import agent_store, store,sidebar_history
        return {'history_items':sidebar_history.recent(session['user_id'],include_conversations=automation_enabled(),copilot_only=copilot.visible(),exclude_copilot=not copilot.visible()),'threads': store.list_threads(session['user_id'], 6),
                'conversations': agent_store.recent_conversations(session['user_id'])[:6] if automation_enabled() else [],
                'automation_enabled': automation_enabled()}
    import security
    from . import live_translator
    user = security.current_user()
    from . import copilot
    return {'chat_sidebar_enabled': request.blueprint not in ('kilas_audio', 'kilas_learning'),
            'copilot_primary': copilot.visible(),
            'kilas_revision_shell': True, 'kilas_live_translator_available': live_translator.ready(session['user_id']), 'kilas_profile_email': user.get('email','') if user else '',
            'chat_sidebar_history': history}


@ai_bp.app_context_processor
def account_workspace_context():
    """Share account navigation independently of the selected product's content."""
    from flask import session
    from .routes import enabled
    if (request.endpoint == 'auth.account_page' and session.get('user_id')
            and session.get('role') != 'KILAS_ADMIN'):
        result = {'account_navigation': True}
        # Exact, presentation-only entry hint; never changes product/access authority.
        home_entry = request.args.get('workspace') == 'home'
        if enabled() and (home_entry or session.get('active_product') != 'finance'):
            result['account_workspace'] = {'preferences': automation_enabled()}
        return result
    return {}


@ai_bp.post('/home-task', endpoint='home_task')
def open_task():
    task = request.form.get('task','chat')
    brief = request.form.get('brief','')
    limits = {'chat':12000,'video':2400,'translate':2400,'voiceover':4000}
    if task not in limits or len(brief) > limits[task]:
        abort(400)
    if task == 'chat':
        from .routes import home
        return home(initial_brief=brief)  # Non-JS fallback only; no provider request.
    if task == 'video':
        from .video_routes import home
        return home(initial_brief=brief,home_task=task)
    from .audio_routes import home
    return home(initial_brief=brief,home_task=task)


@ai_bp.get('/library')
def library():
    from flask import render_template, session
    from .library import collection
    return render_template('kilas_ai/library.html',**collection(session['user_id'],automation_enabled())),200,{'Cache-Control':'private, no-store','Vary':'Cookie'}


@ai_bp.get('/sidebar/history')
def sidebar_history():
    from flask import session
    from .sidebar_history import page
    from . import copilot
    return page(session['user_id'],request.args.get('cursor'),include_conversations=automation_enabled(),copilot_only=copilot.visible(),exclude_copilot=not copilot.visible()),200,{'Cache-Control':'private, no-store','Vary':'Cookie'}


@ai_bp.post('/video', endpoint='video_home_handoff')
def open_video_task():
    if request.form.get('task')!='video':abort(400)
    return open_task()
