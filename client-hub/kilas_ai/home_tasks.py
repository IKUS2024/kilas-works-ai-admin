"""Presentation-only Home task entry; existing transports and billing stay intact."""
from flask import abort, request
from .routes import ai_bp, automation_enabled


def context(owner):
    from . import agent_store, attachments, live_assist, live_qa_budget, store, usage
    return {
        'automation_enabled': automation_enabled(),
        'limits': attachments.limits(usage.attachment_plan(owner)),
        'threads': store.list_threads(owner, 6),
        'conversations': agent_store.recent_conversations(owner)[:6] if automation_enabled() else [],
        'live_available': live_qa_budget.enabled() and live_assist.ready(owner) and live_qa_budget.ready(owner,for_start=True),
    }


@ai_bp.app_context_processor
def audio_offering_context():
    from .audio_presentation import upload_translation_visible
    return {'upload_translation_visible': upload_translation_visible()}


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
    brief = request.form.get('brief','').strip()
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


@ai_bp.post('/video', endpoint='video_home_handoff')
def open_video_task():
    if request.form.get('task')!='video':abort(400)
    return open_task()
