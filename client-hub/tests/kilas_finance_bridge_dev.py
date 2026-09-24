"""Synthetic loopback-only Phase 7 browser harness; never imported by the app."""
import os
if os.environ.get('KILAS_PHASE7_BROWSER_QA') != '1':
    raise SystemExit('Explicit synthetic Phase 7 browser QA flag required')
# The fixture clears DATABASE_URL, creates a new temporary SQLite database and
# blocks requests.Session network IO. It never reads customer/production databases.
from test_kilas_finance_bridge import BridgeTests
from test_finance_phase2a import app
from flask import jsonify,session,redirect,abort
import db,finance_service as f,finance_branches as branches
from kilas_core import finance_bridge as bridge
case=BridgeTests();case.setUp()
app.config.update(CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
base=f'/business/{case.source}/finance-bridge'

@app.get('/dev/health')
def health():
    return jsonify(source=case.source,target=case.target,branch=case.branch,cid=case.cid,jid=case.jid)

@app.get('/dev/owner')
def owner():
    session.clear();session['user_id']=case.actor;session['active_product']='brain'
    return redirect(f'/business/{case.source}/jobs/{case.jid}')

@app.get('/dev/standalone')
def standalone():
    session.clear();session['user_id']=case.actor;session['active_product']='finance'
    return redirect(f'/business/{case.target}/finance')

@app.get('/dev/foreign')
def foreign():
    session.clear();session['user_id']=case.foreign_actor;session['active_product']='brain'
    return jsonify(synthetic=True)

@app.post('/dev/payment')
def payment():
    if session.get('user_id')!=case.actor:abort(404)
    result=bridge.read_invoice(case.source,case.actor,case.jid)
    iid=result['invoice']['id']
    with branches.scope(case.target,case.branch,case.actor):
        if result['invoice']['status']=='DRAFT':f.issue_finance_invoice(case.target,iid,actor_user_id=case.actor)
        account=f.list_accounts(case.target,actor_user_id=case.actor)[0]['id']
        category=f.list_categories(case.target,'INCOME',actor_user_id=case.actor)[0]['id']
        f.record_invoice_payment(case.target,iid,50000,'2026-09-10',account,category,
                                 actor_user_id=case.actor,idempotency_key='synthetic-browser-payment')
    return jsonify(ok=True)

@app.post('/dev/expire')
def expire():
    if session.get('user_id')!=case.actor:abort(404)
    os.environ.update(KILAS_FINANCE_ACCESS_MODE='self_service',KILAS_FINANCE_UNLIMITED_TRIAL='false')
    return jsonify(ok=True)

if __name__=='__main__':app.run(host='127.0.0.1',port=8768,use_reloader=False)
