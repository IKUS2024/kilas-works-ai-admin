"""SELECT-only release evidence. This never opens a provider connection."""
import db
from . import ai_call as calls, ai_call_budget as budget, routes


def report():
    result={'model':budget.MODEL,'configured_ready':False,'paid_qa':False,
            'model_access_verified':False,'audio_persisted':False,'lease_seconds':90}
    value=budget.config()
    if not value:return {**result,'reason':'feature_or_policy_unavailable'}
    other=db.query_one('SELECT id FROM users WHERE id<>? ORDER BY id LIMIT 1',(value['allowed_owner'],))

    def account(owner):
        if not routes.enabled() or not calls.ready(owner):return {'configured_ready':False,'reason':'call_unavailable'}
        snapshot=budget.status(owner)
        return {'configured_ready':bool(snapshot['available']), 'reason':snapshot.get('reason'),
                'remaining_micro_usd':snapshot.get('remaining_micro_usd'),
                'reserve_micro_usd':snapshot.get('reserve_micro_usd')}

    owner=account(value['allowed_owner'])
    return {**result,'configured_ready':owner['configured_ready'],'owner':owner,
            'nonowner':account(other['id']) if other else None,'audience':value['audience']}
