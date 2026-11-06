"""Disabled-until-activation manual credit purchase and private proof routes."""
import io
import json
import re
import secrets
from flask import abort, render_template, request, session, redirect, url_for, send_file
import db
from .routes import ai_bp
from .billing_routes import admin_bp
from . import credit_policy as policy, credit_wallet as wallet, usage

# Authoritative user instruction for this credit product only.
BANK={'bank_name':'Bank Mega','account_number':'10180016000684','account_holder':'KILAS TEKNOLOGI KREATIF'}


def require_enabled(*,accepted=False):
    if policy.enabled():return
    if not accepted:abort(404)
    conn=usage._connect()
    try:
        if not policy.installed(conn):abort(404)
        existing=usage._query(conn,'SELECT 1 FROM kilas_credit_orders LIMIT 1',one=True) or usage._query(conn,'SELECT 1 FROM kilas_credit_admissions LIMIT 1',one=True)
        if not existing:abort(404)
    finally:conn.close()


def page():
    require_enabled()
    return render_template('kilas_ai/credit_wallet.html',balance=wallet.balance(session['user_id']),invoice=None,bank=BANK,subscription=usage.effective_plan(session['user_id']),request_key=secrets.token_hex(24)),200,{'Cache-Control':'private, no-store'}


@ai_bp.post('/credits/orders')
def purchase():
    require_enabled()
    from . import credit_activation
    credit_activation.gate(session['user_id'])
    if request.form.get('acknowledge')!='yes':return {'code':'purchase_confirmation_required'},400
    try:ident=wallet.create_purchase(session['user_id'],request.form.get('request_key'))
    except wallet.WalletError as error:return {'code':str(error)},400
    return redirect(url_for('kilas_ai.credit_order',ident=ident),code=303)


@ai_bp.get('/credits/orders/<ident>')
def credit_order(ident):
    require_enabled(accepted=True);invoice=wallet.order(session['user_id'],ident)
    if not invoice:abort(404)
    return render_template('kilas_ai/credit_wallet.html',balance=wallet.balance(session['user_id']),invoice=invoice,bank=BANK,subscription=usage.effective_plan(session['user_id'])),200,{'Cache-Control':'private, no-store'}


@ai_bp.post('/credits/orders/<ident>/proof')
def credit_proof_upload(ident):
    require_enabled(accepted=True)
    if not wallet.order(session['user_id'],ident):abort(404)
    try:wallet.submit_proof(session['user_id'],ident,request.files.get('proof'))
    except wallet.WalletError as error:return {'code':str(error)},400
    return redirect(url_for('kilas_ai.credit_order',ident=ident),code=303)


def _proof(ident,user=None):
    row=db.query_one('SELECT proof_name,proof_mime,proof_content FROM kilas_credit_orders WHERE id=?'+(' AND user_id=?' if user is not None else ''),(ident,user) if user is not None else (ident,))
    if not row or not row['proof_content']:abort(404)
    response=send_file(io.BytesIO(bytes(row['proof_content'])),mimetype=row['proof_mime'],as_attachment=True,download_name=row['proof_name'])
    response.headers.update({'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"})
    return response


@ai_bp.get('/credits/orders/<ident>/proof')
def credit_proof(ident):
    require_enabled(accepted=True)
    return _proof(ident,session['user_id'])


@admin_bp.get('/credits/payments')
def credit_payments():
    require_enabled(accepted=True)
    rows=db.query_all("SELECT o.id,o.user_id,o.amount_idr,o.status,o.proof_digest,(SELECT COUNT(*) FROM kilas_credit_orders d WHERE d.proof_digest=o.proof_digest AND d.id<>o.id) AS duplicate_proofs FROM kilas_credit_orders o WHERE o.status='UNDER_REVIEW' ORDER BY o.created_at LIMIT 100")
    pending=db.query_all("SELECT user_id,operation_key,feature,maximum_charge,created_at FROM kilas_credit_admissions WHERE status='RESERVED' ORDER BY created_at LIMIT 100")
    return render_template('kilas_ai/credit_reviews.html',payments=rows,pending=pending)


@admin_bp.get('/credits/orders/<ident>/proof')
def credit_review_proof(ident):
    require_enabled(accepted=True)
    return _proof(ident)


@admin_bp.post('/credits/orders/<ident>/review')
def credit_review(ident):
    require_enabled(accepted=True)
    try:wallet.review(ident,session['user_id'],request.form.get('decision'),request.form.get('note'),transfer_reference=request.form.get('transfer_reference'))
    except wallet.WalletError as error:return {'code':str(error)},400
    return redirect(url_for('kilas_ai_admin.credit_payments'),code=303)


@ai_bp.app_context_processor
def credit_context():
    return {'credit_wallet_enabled':policy.enabled()}


@ai_bp.errorhandler(wallet.WalletError)
def credit_contract_error(error):
    code=str(error)
    return {'code':code,'error':code},402 if code=='insufficient_credit' else 409


@ai_bp.errorhandler(policy.ConsentRequired)
def credit_consent_needed(error):
    token=policy.persist_consent(error)
    return {'code':'credit_consent_required','error':'credit_consent_required','credit_consent_url':url_for('kilas_ai.credit_consent',token=token)},402


@ai_bp.before_app_request
def credit_retry_account_fence():
    token=request.headers.get('X-Kilas-Credit-Consent')
    if not token or request.method!='POST' or not re.match(r'^/kilas-(ai|translator)/',request.path):return
    if not policy.enabled():return {'code':'credit_policy_disabled'},409
    if not re.fullmatch(r'[a-f0-9]{64}',token):return {'code':'credit_consent_invalid'},409
    item=db.query_one('SELECT user_id,operation_key,status,expires_at FROM kilas_credit_consents WHERE token=?',(token,))
    key=(request.view_args or {}).get('key') or request.form.get('operation_key') or (request.get_json(silent=True) or {}).get('operation_key')
    if request.endpoint in ('kilas_audio.interpreter_session','kilas_audio.interpreter_turn'):
        from .credit_interpreter import operation
        try:key=operation(request.view_args['ident'],0 if request.endpoint.endswith('interpreter_session') else int(request.form['turn_index']))
        except (ValueError,KeyError):return {'code':'credit_consent_invalid'},409
    if (not item or item['user_id']!=session.get('user_id') or item['operation_key']!=key
            or item['status'] not in ('APPROVED','CONSUMED') or usage._as_utc(item['expires_at'])<=usage._now()):
        return {'code':'credit_consent_account_or_request_changed'},409


@ai_bp.route('/credits/consent/<token>',methods=['GET','POST'])
def credit_consent(token):
    require_enabled()
    item=db.query_one('SELECT token,feature,maximum_units,free_units,maximum_charge,terms_json,status,expires_at FROM kilas_credit_consents WHERE token=? AND user_id=?',(token,session['user_id']))
    if not item:abort(404)
    state=None
    if request.method=='POST':
        decision=request.form.get('decision')
        if decision not in ('approve','decline'):abort(400)
        try:
            from . import credit_work
            state=credit_work.decide(session['user_id'],token,decision=='approve')
        except wallet.WalletError as error:return {'code':str(error)},409
    work=db.query_one('SELECT job_id FROM kilas_credit_work_waits WHERE token=? AND user_id=?',(token,session['user_id']))
    return render_template('kilas_ai/credit_consent.html',work=work,quote=item,terms=json.loads(item['terms_json']),state=state,return_to=request.args.get('return_to') if re.fullmatch(r'/business/[0-9]+/finance/receipts/new',request.args.get('return_to','')) else None),200,{'Cache-Control':'private, no-store'}


@admin_bp.post('/credits/reconcile')
def credit_reconcile():
    require_enabled(accepted=True)
    try:
        policy.reconcile(int(request.form['user_id']),request.form['operation_key'],session['user_id'],request.form['outcome'],int(request.form['actual_units']),request.form['evidence'])
    except (KeyError,ValueError,wallet.WalletError) as error:return {'code':str(error)},400
    return redirect(url_for('kilas_ai_admin.credit_payments'),code=303)
