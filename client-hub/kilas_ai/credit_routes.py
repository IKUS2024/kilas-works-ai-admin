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


def require_enabled():
    if not policy.enabled():abort(404)


def page():
    require_enabled()
    return render_template('kilas_ai/credit_wallet.html',balance=wallet.balance(session['user_id']),invoice=None,bank=BANK,subscription=usage.effective_plan(session['user_id']),request_key=secrets.token_hex(24)),200,{'Cache-Control':'private, no-store'}


@ai_bp.post('/credits/orders')
def purchase():
    require_enabled()
    if request.form.get('acknowledge')!='yes':return {'code':'purchase_confirmation_required'},400
    try:ident=wallet.create_purchase(session['user_id'],request.form.get('request_key'))
    except wallet.WalletError as error:return {'code':str(error)},400
    return redirect(url_for('kilas_ai.credit_order',ident=ident),code=303)


@ai_bp.get('/credits/orders/<ident>')
def credit_order(ident):
    require_enabled();invoice=wallet.order(session['user_id'],ident)
    if not invoice:abort(404)
    return render_template('kilas_ai/credit_wallet.html',balance=wallet.balance(session['user_id']),invoice=invoice,bank=BANK,subscription=usage.effective_plan(session['user_id'])),200,{'Cache-Control':'private, no-store'}


@ai_bp.post('/credits/orders/<ident>/proof')
def credit_proof_upload(ident):
    require_enabled()
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
    require_enabled()
    return _proof(ident,session['user_id'])


@admin_bp.get('/credits/payments')
def credit_payments():
    require_enabled()
    rows=db.query_all("SELECT o.id,o.user_id,o.amount_idr,o.status,o.proof_digest,(SELECT COUNT(*) FROM kilas_credit_orders d WHERE d.proof_digest=o.proof_digest AND d.id<>o.id) AS duplicate_proofs FROM kilas_credit_orders o WHERE o.status='UNDER_REVIEW' ORDER BY o.created_at LIMIT 100")
    pending=db.query_all("SELECT user_id,operation_key,feature,maximum_charge,created_at FROM kilas_credit_admissions WHERE status='RESERVED' ORDER BY created_at LIMIT 100")
    return render_template('kilas_ai/credit_reviews.html',payments=rows,pending=pending)


@admin_bp.get('/credits/orders/<ident>/proof')
def credit_review_proof(ident):
    require_enabled()
    return _proof(ident)


@admin_bp.post('/credits/orders/<ident>/review')
def credit_review(ident):
    require_enabled()
    try:wallet.review(ident,session['user_id'],request.form.get('decision'),request.form.get('note'),transfer_reference=request.form.get('transfer_reference'))
    except wallet.WalletError as error:return {'code':str(error)},400
    return redirect(url_for('kilas_ai_admin.credit_payments'),code=303)


@ai_bp.app_context_processor
def credit_context():
    return {'credit_wallet_enabled':policy.enabled()}


@ai_bp.errorhandler(policy.ConsentRequired)
def credit_consent_needed(error):
    token=policy.persist_consent(error)
    return {'code':'credit_consent_required','error':'credit_consent_required','credit_consent_url':url_for('kilas_ai.credit_consent',token=token)},402


@ai_bp.route('/credits/consent/<token>',methods=['GET','POST'])
def credit_consent(token):
    require_enabled()
    item=db.query_one('SELECT token,feature,maximum_units,free_units,maximum_charge,terms_json,status,expires_at FROM kilas_credit_consents WHERE token=? AND user_id=?',(token,session['user_id']))
    if not item:abort(404)
    state=None
    if request.method=='POST':
        decision=request.form.get('decision')
        if decision not in ('approve','decline'):abort(400)
        try:state=policy.consent(session['user_id'],token,decision=='approve')
        except wallet.WalletError as error:return {'code':str(error)},409
    return render_template('kilas_ai/credit_consent.html',quote=item,terms=json.loads(item['terms_json']),state=state,return_to=request.args.get('return_to') if re.fullmatch(r'/business/[0-9]+/finance/receipts/new',request.args.get('return_to','')) else None),200,{'Cache-Control':'private, no-store'}


@admin_bp.post('/credits/reconcile')
def credit_reconcile():
    require_enabled()
    try:
        policy.reconcile(int(request.form['user_id']),request.form['operation_key'],session['user_id'],request.form['outcome'],int(request.form['actual_units']),request.form['evidence'])
    except (KeyError,ValueError,wallet.WalletError) as error:return {'code':str(error)},400
    return redirect(url_for('kilas_ai_admin.credit_payments'),code=303)
