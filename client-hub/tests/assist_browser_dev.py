"""Disposable synthetic Assist browser QA. Never imported by production.

KILAS_MASTER_BROWSER_QA=true is required. Refuses production service names, database URLs
and provider credentials. The only fake boundary is external AI/WhatsApp/network transport.
Authentication/tenant scoping is exercised by integration tests; /qa entries select fake users.
"""
import os

if __name__ != '__main__' or os.environ.get('KILAS_MASTER_BROWSER_QA') != 'true':
    raise RuntimeError('explicit_synthetic_qa_required')
if os.environ.get('RENDER_SERVICE_NAME','').startswith('kilas-works-') or any(os.environ.get(key) for key in (
        'DATABASE_URL','OPENAI_API_KEY','ANTHROPIC_API_KEY','WHATSAPP_ACCESS_TOKEN','INTERNAL_SERVICE_SECRET')):
    raise RuntimeError('production_configuration_forbidden')

import json
import secrets
import re
import tempfile
from pathlib import Path

os.environ.update(CLIENT_HUB_DB_PATH=str(Path(tempfile.mkdtemp(prefix='assist-browser-'))/'synthetic.db'),
    SECRET_KEY=secrets.token_hex(32),RUN_MIGRATIONS_ON_BOOT='true',KILAS_CORE_V2_ENABLED='true',
    KILAS_ASSIST_RUNTIME_ENABLED='true',KILAS_CUSTOMERS_V2_ENABLED='true',KILAS_JOBS_V2_ENABLED='true',
    KILAS_FINANCE_ACCESS_MODE='self_service',KILAS_PLAYBOOKS_V2_ENABLED='true',KILAS_OPERATIONS_V2_ENABLED='true',KILAS_FINANCE_BRIDGE_ENABLED='true')

import requests
def no_network(*args,**kwargs):raise RuntimeError('external_network_disabled_in_synthetic_qa')
requests.sessions.Session.request=no_network

import db,repo,app,ai_router,ai_onboarding,assist_training
from public_chat import schema
from kilas_core import customer_schema,job_schema,operation_schema,finance_bridge_schema,whatsapp_schema
for installer in (schema,customer_schema,job_schema,operation_schema,finance_bridge_schema,whatsapp_schema):installer.apply_schema()
db.execute('CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,number TEXT,mode TEXT,role TEXT,content TEXT,created_at TEXT)')

owner=repo.create_user('owner@synthetic.invalid','not-a-login-password')
other=repo.create_user('other@synthetic.invalid','not-a-login-password')
admin=repo.create_user('admin@synthetic.invalid','not-a-login-password',role='KILAS_ADMIN')
bid=repo.create_business(owner,'Studio Uji Kilas','AI_ADMIN')
other_bid=repo.create_business(other,'Bisnis Pembanding QA','AI_ADMIN')

def deterministic_model(system,messages,maximum=1500,**kwargs):
    if 'owner_teaches' in str(messages):
        value=json.loads(messages[-1]['content'])
        text=json.dumps({'reply':'Baik, saya memahami aturan tersebut dan akan meminta bantuan pemilik jika ragu.',
            'knowledge':(value['previous_knowledge']+'\n'+value['owner_teaches']).strip()},ensure_ascii=False)
    else:text='Harga layanan mengikuti informasi bisnis. Untuk diskon atau kepastian jadwal, saya akan meminta persetujuan pemilik.'
    return text,'end_turn',None
ai_router.complete=deterministic_model

def normalize(business,profile,services,faqs,files,**kwargs):
    return dict(business_name=business['business_name'],description=profile.get('short_description'),
        category=profile.get('category'),services=[],faqs=[],languages={'primary':'id','additional':[]},
        tone='ramah',missing_fields=[]),None
ai_onboarding.normalize_business_data=normalize

from flask import abort,redirect,session,url_for
web=app.app
web.config.update(TESTING=False)

@web.get('/qa/<actor>')
def enter(actor):
    identities={'owner':(owner,bid),'other':(other,other_bid),'admin':(admin,None)}
    if actor not in identities:abort(404)
    uid,business_id=identities[actor]
    session.clear();session.update(user_id=uid,role='KILAS_ADMIN' if actor=='admin' else 'CLIENT_OWNER')
    if business_id:session.update(active_product='ai',workspace_ai_business=business_id)
    return redirect(url_for('platform_control.page') if actor=='admin' else url_for('workspace.ai_home'))

@web.after_request
def synthetic_notice(response):
    if response.mimetype=='text/html':
        notice='<aside style="padding:8px;background:#fff3b0;color:#222">QA: data sintetis, AI uji, pengiriman WhatsApp dinonaktifkan.</aside>'
        response.set_data(re.sub(r'(<body[^>]*>)',lambda m:m[1]+notice,response.get_data(as_text=True),count=1))
    return response

web.run(host='0.0.0.0',port=int(os.environ.get('PORT','5000')),debug=False,use_reloader=False)
