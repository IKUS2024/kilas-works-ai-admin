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
