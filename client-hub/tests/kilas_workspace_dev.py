"""Phase 9 disposable UI fixture. Never imported by production; all HTTP IO blocked."""
import os
if os.environ.get('KILAS_PHASE9_BROWSER_QA') != '1':
    raise SystemExit('Explicit synthetic Phase 9 QA flag required')
from test_kilas_finance_bridge import BridgeTests
from test_finance_phase2a import app
from flask import session, redirect, jsonify, request, abort
import repo, db, finance_service as finance, subscription_service
from kilas_core import operation_schema
case = BridgeTests(); case.setUp()
operation_schema.apply_schema()
ai_owner = repo.create_user('ai-only@example.test', 'unused', full_name='Rani')
ai_business = repo.create_business(ai_owner, 'Studio Rani', package='AI_ADMIN')
subscription_service.create_subscription(ai_business, 'ai_admin', ai_owner)
new_ai_owner = repo.create_user('new-ai@example.test', 'unused', full_name='Laras')
new_owner = repo.create_user('new-owner@example.test', 'unused', full_name='Nadia')
admin = repo.create_user('operator@example.test', 'unused', role='KILAS_ADMIN', full_name='Operator')
repo.update_business_identity(case.source, 'Studio Sore', actor_user_id=case.actor)
repo.update_business_identity(case.target, 'Studio Sore Finance', actor_user_id=case.actor)
repo.update_business_identity(case.b, 'Toko Senja', actor_user_id=case.uid)
db.execute("UPDATE businesses SET package='NONE' WHERE id=?", (case.b,))
os.environ.update(KILAS_CORE_V2_TEST_BUSINESS_IDS=f'{case.source},{ai_business}',
                  KILAS_WEB_CHAT_ENABLED='true', KILAS_OPERATIONS_V2_ENABLED='true')
# Populate finance using authoritative services, never UI fake values.
customer = finance.create_customer(case.target, 'PT Cahaya', actor_user_id=case.actor)
invoice = finance.create_finance_invoice(case.target, customer, '2026-09-01', '2026-09-30',
    [dict(description='Produksi konten', quantity=1, unit_price_minor=250000000)], actor_user_id=case.actor)
finance.issue_finance_invoice(case.target, invoice, actor_user_id=case.actor)
account = finance.list_accounts(case.target, actor_user_id=case.actor)[0]['id']
category = finance.list_categories(case.target, 'INCOME', actor_user_id=case.actor)[0]['id']
finance.create_transaction(case.target, 'INCOME', 850000000, account, category, '2026-09-10', actor_user_id=case.actor)
app.config.update(CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)


def persona_entry():
    if request.endpoint in ('persona','health','owner_evidence','finance_onboarding'):
        session.pop('active_product', None)
app.before_request_funcs[None].insert(0, persona_entry)


@app.get('/dev/health')
def health():
    return jsonify(source=case.source, target=case.target, branch=case.branch,
                   customer=case.cid, job=case.jid, standalone=case.b, ai=ai_business)


@app.get('/dev/persona/<name>')
def persona(name):
    actors = {'full':case.actor, 'finance':case.uid, 'ai':ai_owner, 'new':new_owner, 'admin':admin, 'new-ai':new_ai_owner}
    if name not in actors: abort(404)
    session.clear()
    session.update(user_id=actors[name], role='KILAS_ADMIN' if name=='admin' else 'CLIENT_OWNER',
                   _csrf_token='phase9-browser')
    return redirect('/admin' if name=='admin' else '/workspace')



@app.get('/dev/finance-onboarding')
def finance_onboarding():
    os.environ.update(KILAS_FINANCE_ACCESS_MODE='self_service', KILAS_FINANCE_UNLIMITED_TRIAL='false')
    session.clear();session.update(user_id=new_owner, role='CLIENT_OWNER', _csrf_token='phase9-browser')
    return redirect('/products/start')


@app.get('/dev/owner-evidence')
def owner_evidence():
    actor=session.get('user_id')
    if actor not in (new_owner, new_ai_owner): abort(404)
    rows=repo.list_businesses_for_user(actor)
    return jsonify(packages=[row['package'] for row in rows],
                   finance_accounts=sum(len(finance.list_accounts(row['id'],actor_user_id=actor)) for row in rows))

if __name__ == '__main__': app.run(host='127.0.0.1', port=8770, use_reloader=False)
