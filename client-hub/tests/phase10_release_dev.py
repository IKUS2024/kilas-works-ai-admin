"""Disposable loopback release harness; real auth/routes/CSRF/storage, synthetic AI IO."""
import os
if os.environ.get('KILAS_PHASE10_BROWSER_QA') != '1':
    raise SystemExit('Explicit Phase 10 disposable QA flag required')

from unittest.mock import Mock, patch
import json
from flask import jsonify
from test_kilas_finance_bridge import BridgeTests
from test_finance_phase2a import app
import repo, db, security, finance_entitlements
from kilas_core import operation_schema
import ai_onboarding
from playbook_qa_provider import reply

case = BridgeTests(); case.setUp()
operation_schema.apply_schema()
# Known synthetic fixture password only, never a production credential.
PASSWORD = 'Phase10-disposable-only!'
repo.update_user_password(case.actor, security.hash_password(PASSWORD))
repo.update_user_password(case.foreign_actor, security.hash_password(PASSWORD))
admin = repo.create_user('phase10-operator@example.test', security.hash_password(PASSWORD),
                         role='KILAS_ADMIN', full_name='Release QA Operator')
repo.upsert_business_profile(case.source, {'category':'Logistics'})
repo.save_ai_normalized_config(case.source, 'Synthetic approved logistics fixture',
                              {'business_name':'Release Logistics','hours':'09.00-17.00'}, [])
os.environ.update(KILAS_WEB_CHAT_ENABLED='true', KILAS_PLAYBOOKS_V2_ENABLED='true',
                  KILAS_OPERATIONS_V2_ENABLED='true', KILAS_FINANCE_ACCESS_MODE='self_service',
                  KILAS_FINANCE_UNLIMITED_TRIAL='false')
finance_entitlements.start_trial(case.target, case.actor)
finance_entitlements.start_trial(case.foreign, case.foreign_actor)
model = patch.object(ai_onboarding, '_call_claude', side_effect=reply); model.start()
# Stub only provider configuration/HTTP; retain semantic validation and draft engine.
def finance_provider(url, **kwargs):
    assert url == 'https://api.anthropic.com/v1/messages'
    request = json.loads(kwargs['json']['messages'][0]['content'])
    assert request['message'] == 'catat pengeluaran', request['message']
    response = Mock(status_code=200)
    response.json.return_value = {'stop_reason':'end_turn', 'content':[
        {'type':'text', 'text':json.dumps({'intent':'create_expense','slots':{}})}]}
    return response

finance_config = patch('finance_bank_extract.configuration', return_value=('synthetic-only','qa-model'))
finance_http = patch('requests.post', side_effect=finance_provider)
finance_config.start(); finance_http.start()
app.config.update(CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)


@app.get('/dev/health')
def release_health():
    # Fixture identifiers are not session entry shortcuts. Every browser logs in.
    return jsonify(source=case.source, target=case.target, branch=case.branch,
                   email=repo.get_user_by_id(case.actor)['email'],
                   foreign_email=repo.get_user_by_id(case.foreign_actor)['email'])


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8771, use_reloader=False, threaded=True)
