"""Read-only startup evidence; never opens a provider connection."""
import db
from . import interpreter as calls, interpreter_budget as budget
from .interpreter_settings import LANGUAGES


def report():
    value=budget.config()
    if not value:return {'configured_ready':False,'reason':'policy_unavailable','paid_qa':False}
    def account(owner):
        if not calls.ready(owner):return {'available':False,'reason':'call_unavailable'}
        return budget.status(owner)
    other=db.query_one('SELECT id FROM users WHERE id<>? ORDER BY id LIMIT 1',(value['allowed_owner'],))
    return {'model':budget.MODEL,'audience':value['audience'],'owner':account(value['allowed_owner']),
            'nonowner':account(other['id']) if other else None,'paid_qa':False,
            'provider_verified':False,'language_count':len(LANGUAGES),'single_socket':True}
