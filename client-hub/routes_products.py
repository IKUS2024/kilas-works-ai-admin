"""Customer product entry and independent Finance subscription UI."""
import io
import uuid
from functools import wraps
from flask import Blueprint, render_template, request, session, redirect, url_for, abort, flash, send_file
import db
import repo
import security
import product_flow
import finance_entitlements as entitlement
import finance_subscription as subscription
import finance_service as finance
import catalog_service
from pricing_config import BRAIN_PLAN,FINANCE_PLAN

products_bp=Blueprint('products',__name__)


@products_bp.after_request
def privacy(response):
    response.headers['Cache-Control']='private, no-store'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Robots-Tag']='noindex, noarchive'
    return response


@products_bp.errorhandler(finance.FinanceError)
def safe_error(error):
    return render_template('product_error.html'),400


@products_bp.errorhandler(Exception)
def unavailable(error):
    from werkzeug.exceptions import HTTPException
    if isinstance(error,HTTPException): return error
    # Fixed UI, no exception, query parameters, proof hash or credentials in logs.
    return render_template('product_error.html'),503


@products_bp.route('/products')
def index():
    return render_template('products.html',brain=BRAIN_PLAN,finance_plan=FINANCE_PLAN,items=catalog_service.list_active_catalog(),
        service_description=catalog_service.service_description,display_price=catalog_service.display_price,
        transport_policy=__import__('pricing_config').TRANSPORT_POLICY)


@products_bp.route('/products/select',methods=['POST'])
def select():
    key=product_flow.intent(request.form.get('product'))
    if not key:abort(400)
    session['product_intent']=key
    return redirect(url_for('products.continue_product') if security.current_user() else url_for('auth.login_page'),code=303)


@products_bp.route('/products/continue',methods=['GET','POST'])
@security.login_required
def continue_product():
    user=security.current_user();key=product_flow.intent(session.get('product_intent'))
    if not key:return redirect(url_for('products.index'))
    if request.method=='POST':
        if request.form.get('create')=='yes':
            try: business_id=product_flow.create_business(user['id'],request.form.get('business_name'),request.form.get('setup_identity'))
            except ValueError:abort(400)
        else:
            business_id=request.form.get('business_id',type=int)
            if business_id:security.require_business_access(business_id,user)
            elif key in ('brain','finance'):abort(400)
        if key=='finance':return redirect(url_for('products.finance_setup',business_id=business_id),code=303)
        if key=='brain':
            with db.app_purchase_transaction(business_id,None):
                security.require_business_access(business_id,user)
                if repo.get_business(business_id)['package']=='NONE':repo.upgrade_business_package(business_id,'AI_ADMIN',user['id'])
            return redirect(url_for('client.wizard_step',business_id=business_id,step='basics'),code=303)
        # Render explicit existing checkout/brief POST with the selected, authorized business.
        item=catalog_service.get_catalog_item(key)
        if not item or not item['is_active']:abort(404)
        return render_template('product_continue.html',item=item,chosen_business_id=business_id,ready=True)
    return render_template('product_continue.html',product=key,businesses=repo.list_businesses_for_user(user['id']),setup_identity=uuid.uuid4().hex,ready=False)


@products_bp.route('/business/<int:business_id>/finance-subscription',methods=['GET','POST'])
@security.login_required
def finance_setup(business_id):
    user=security.current_user();business=security.require_business_access(business_id,user)
    if request.method=='POST':
        action=request.form.get('action')
        if action=='setup':
            from routes_finance import whole_idr
            entitlement.setup(business_id,user['id'],request.form.get('name'),request.form.get('account_type'),whole_idr(request.form.get('opening_balance','0'),signed=True))
        elif action=='trial':
            if request.form.get('terms')!='yes':abort(400)
            entitlement.start_trial(business_id,user['id'])
        elif action=='subscribe':
            bill_id=subscription.create_bill(business_id,user['id'],request.form.get('request_key'))
            return redirect(url_for('products.bill_page',business_id=business_id,bill_id=bill_id),code=303)
        else:abort(400)
        return redirect(url_for('products.finance_setup',business_id=business_id),code=303)
    return render_template('finance_subscription.html',business=business,entitlement=entitlement.state(business_id),finance_plan=FINANCE_PLAN,bill_request_key=uuid.uuid4().hex,self_service_enabled=entitlement.self_service(),
        accounts=[a for a in finance.list_accounts(business_id,actor_user_id=user['id']) if a['currency']=='IDR'],bank=subscription.payment_details(),
        bills=db.query_all('SELECT id,status,amount_minor,created_at FROM finance_subscription_bills WHERE business_id=? ORDER BY id DESC LIMIT 50',(business_id,)))


@products_bp.route('/business/<int:business_id>/finance-bills/<int:bill_id>',methods=['GET','POST'])
@security.login_required
def bill_page(business_id,bill_id):
    user=security.current_user();business=security.require_business_access(business_id,user)
    bill=subscription.bill(business_id,bill_id,user['id'])
    if request.method=='POST':
        import file_utils
        upload=request.files.get('proof_file')
        if not upload:abort(400)
        try:subscription.upload_proof(business_id,bill_id,user['id'],upload.filename,upload.read(file_utils.MAX_IMAGE_UPLOAD_BYTES+1))
        except (ValueError,file_utils.UploadRejected):
            flash('Bukti belum dapat diterima. Gunakan gambar valid dalam batas ukuran; periksa status tagihan sebelum mencoba lagi.','error')
        return redirect(url_for('products.bill_page',business_id=business_id,bill_id=bill_id),code=303)
    return render_template('finance_bill.html',business=business,bill=bill,bank=subscription.payment_details(),admin=user['role']=='KILAS_ADMIN')


@products_bp.route('/business/<int:business_id>/finance-bills/<int:bill_id>/proof')
@security.login_required
def proof(business_id,bill_id):
    user=security.current_user();subscription.bill(business_id,bill_id,user['id'])
    row=db.query_one('SELECT proof_content,proof_mime FROM finance_subscription_bills WHERE business_id=? AND id=?',(business_id,bill_id))
    if not row or not row['proof_content']:abort(404)
    response=send_file(io.BytesIO(bytes(row['proof_content'])),mimetype=row['proof_mime'],download_name='bukti-pembayaran',as_attachment=True)
    response.headers['X-Content-Type-Options']='nosniff'
    return response


@products_bp.route('/admin/finance-subscription-bills')
@security.login_required
def admin_bills():
    if security.current_user()['role']!='KILAS_ADMIN':abort(403)
    rows=db.query_all("SELECT f.id,f.business_id,f.status,b.business_name FROM finance_subscription_bills f JOIN businesses b ON b.id=f.business_id WHERE f.status='REVIEW' ORDER BY f.id LIMIT 200")
    return render_template('finance_bill_queue.html',bills=rows)


@products_bp.route('/business/<int:business_id>/finance-bills/<int:bill_id>/review',methods=['POST'])
@security.login_required
def review(business_id,bill_id):
    if request.form.get('decision') not in ('approve','reject'):abort(400)
    subscription.review(business_id,bill_id,security.current_user()['id'],request.form['decision']=='approve')
    return redirect(url_for('products.bill_page',business_id=business_id,bill_id=bill_id),code=303)


@products_bp.route('/account/bills')
@security.login_required
def account_bills():
    user=security.current_user()
    return render_template('account_bills.html',businesses=repo.list_businesses_for_user(user['id']))


@products_bp.route('/products/dashboard-business',methods=['POST'])
@security.login_required
def dashboard_business():
    business_id=request.form.get('business_id',type=int)
    if not business_id:abort(400)
    security.require_business_access(business_id,security.current_user())
    session['dashboard_business_id']=business_id
    return redirect(url_for('client.dashboard'),code=303)
