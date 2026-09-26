"""Explicit owner forms only; chat/AI cannot call financial actions here."""
import uuid
from werkzeug.exceptions import NotFound
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
import db, security
import finance_service as finance
import finance_branches as branches
from . import finance_bridge as bridge

bridge_bp = Blueprint('core_finance_bridge', __name__)


@bridge_bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def available(business):
    if not bridge.enabled():
        return False
    user = security.current_user()
    if not user or not business:
        return False
    try:
        bridge._source(business['id'], user['id'])
        return True
    except bridge.BridgeError:
        return False


def _context(bid):
    business = security.require_business_access(bid)
    actor = security.current_user()['id']
    if not available(business):
        abort(404)
    return business, actor


@bridge_bp.before_app_request
def limit_body():
    if (request.endpoint or '').startswith('core_finance_bridge.'):
        request.max_content_length = 24 * 1024


@bridge_bp.errorhandler(bridge.BridgeError)
@bridge_bp.errorhandler(finance.FinanceError)
def error_response(error):
    status = getattr(error, 'status', 400)
    if status == 404:
        return NotFound().get_response()
    return render_template('finance_bridge_error.html', bid=request.view_args['bid'],
        message=('Data koneksi berubah atau aksi sudah digunakan. Muat ulang dan periksa riwayat.' if status == 409 else
                 'Belum tersimpan. Periksa konfirmasi, isian, akses Finance, dan cabang aktif.')), status


def _form(fields):
    if request.is_json or set(request.form) - set(fields) - {'csrf_token','operation_key','confirmed','version'}:
        raise bridge.BridgeError('invalid_form')
    if any(len(request.form.getlist(k)) != 1 for k in request.form):
        raise bridge.BridgeError('invalid_form')
    return request.form


def _int(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        raise bridge.BridgeError('invalid_form') from None


def _command(form):
    return dict(expected_version=_int(form.get('version')), operation_key=form.get('operation_key'),
                confirmed=form.get('confirmed') == 'yes')


def _render(business, actor, **extra):
    mapping = bridge.connection(business['id'], actor)
    return render_template('finance_bridge.html', business=business, mapping=mapping,
                           operation_key=uuid.uuid4().hex, **extra)


@bridge_bp.get('/business/<int:bid>/finance-bridge')
@security.login_required
def settings(bid):
    business, actor = _context(bid)
    owned = db.query_all("SELECT b.id,b.business_name FROM businesses b JOIN business_memberships m "
                         "ON m.business_id=b.id WHERE m.user_id=? AND m.role_in_business='OWNER' ORDER BY b.id", (actor,))
    choices = []
    for row in owned:
        for branch in branches.list_branches(row['id'], actor):
            if branch['is_active']:
                choices.append(dict(business=row, branch=branch))
    return _render(business, actor, mode='settings', choices=choices)


@bridge_bp.post('/business/<int:bid>/finance-bridge')
@security.login_required
def configure(bid):
    _, actor = _context(bid)
    form = _form(['destination','enabled'])
    try:
        target, branch = form.get('destination','').split(':')
    except ValueError:
        raise bridge.BridgeError('invalid_form') from None
    if form.get('enabled') not in ('yes','no'):
        raise bridge.BridgeError('invalid_form')
    bridge.configure(bid,actor,finance_business_id=_int(target),finance_branch_id=_int(branch),
                     enabled_value=form['enabled']=='yes',**_command(form))
    return redirect(url_for('core_finance_bridge.settings',bid=bid),code=303)


@bridge_bp.get('/business/<int:bid>/finance-bridge/customers/<cid>')
@security.login_required
def customer_page(bid,cid):
    business, actor = _context(bid)
    customer = bridge._customer(bid,cid)
    mapping = bridge.connection(bid,actor)
    choices = []
    if mapping and mapping['enabled']:
        bridge._finance_owner(mapping['finance_business_id'],actor)
        with branches.scope(mapping['finance_business_id'],mapping['finance_branch_id'],actor):
            choices = finance.list_customers(mapping['finance_business_id'],actor_user_id=actor)
    return _render(business,actor,mode='customer',customer=customer,choices=choices,
                   links=bridge.customer_links(bid,actor,cid))


@bridge_bp.post('/business/<int:bid>/finance-bridge/customers/<cid>')
@security.login_required
def customer_link(bid,cid):
    _, actor = _context(bid)
    form = _form(['customer_choice','name','phone','email'])
    choice = form.get('customer_choice')
    args = (dict(new_customer={k:form.get(k,'') for k in ('name','phone','email')}) if choice=='new'
            else dict(existing_customer_id=_int(choice)))
    bridge.link_customer(bid,actor,cid,**args,**_command(form))
    return redirect(url_for('core_finance_bridge.customer_page',bid=bid,cid=cid),code=303)


@bridge_bp.get('/business/<int:bid>/finance-bridge/jobs/<jid>')
@security.login_required
def job_page(bid,jid):
    business, actor = _context(bid)
    job = bridge._job(bid,jid)
    return _render(business,actor,mode='job',job=job,result=bridge.read_invoice(bid,actor,jid),
                   links=bridge.customer_links(bid,actor,job['customer_id']))


@bridge_bp.post('/business/<int:bid>/finance-bridge/jobs/<jid>/invoice/start')
@security.login_required
def invoice_start(bid,jid):
    _, actor = _context(bid)
    mapping = bridge.connection(bid,actor)
    if not mapping or not mapping['enabled']:
        raise bridge.BridgeError('not_connected',409)
    bridge.ensure_job_customer_link(
        bid,actor,jid,expected_version=mapping['version'],operation_key=uuid.uuid4().hex)
    ctx=bridge.invoice_editor_context(
        bid,actor,jid,expected_version=mapping['version'],
        finance_business_id=mapping['finance_business_id'],finance_branch_id=mapping['finance_branch_id'])
    return redirect(url_for('finance.new_invoice',
        business_id=ctx['mapping']['finance_business_id'],branch_id=ctx['mapping']['finance_branch_id'],
        core_bid=bid,core_job=jid,core_version=ctx['mapping']['version']),code=303)


@bridge_bp.post('/business/<int:bid>/finance-bridge/jobs/<jid>/invoice/publish')
@security.login_required
def invoice_publish(bid,jid):
    _, actor = _context(bid)
    result=bridge.publish_and_send_invoice(bid,actor,jid,uuid.uuid4().hex)
    status=(result.get('delivery') or {}).get('status') or 'unknown'
    if status not in ('accepted','sent','delivered','read'):
        flash('Invoice sudah terbit. Pengiriman WhatsApp belum berhasil atau belum dapat dipastikan ('+status+').', 'error')
    return redirect(url_for('core_jobs.detail_page',bid=bid,job_id=jid,invoice_delivery=status),code=303)


@bridge_bp.post('/business/<int:bid>/finance-bridge/jobs/<jid>/invoice/paid')
@security.login_required
def invoice_paid(bid,jid):
    _, actor = _context(bid)
    allowed={'csrf_token','paid_on','account_id','category_id','note','payment_key'}
    if set(request.form)-allowed or any(len(request.form.getlist(k))!=1 for k in request.form):
        raise bridge.BridgeError('invalid_form')
    bridge.record_full_payment(
        bid,actor,jid,paid_on=request.form.get('paid_on'),
        account_id=_int(request.form.get('account_id')),category_id=_int(request.form.get('category_id')),
        note=request.form.get('note'),payment_key=request.form.get('payment_key'))
    return redirect(url_for('core_jobs.detail_page',bid=bid,job_id=jid,invoice_paid=1),code=303)


@bridge_bp.post('/business/<int:bid>/finance-bridge/jobs/<jid>')
@security.login_required
def draft(bid,jid):
    _, actor = _context(bid)
    form = _form(['currency','issue_date','due_date','notes']+
                 [f'{field}_{i}' for i in range(5) for field in ('description','quantity','price')])
    from routes_finance import currency_amount
    items=[]
    for i in range(5):
        description,quantity,price=(form.get(f'{key}_{i}','').strip() for key in ('description','quantity','price'))
        if description or quantity or price:
            items.append(dict(description=description,quantity=_int(quantity),
                              unit_price_minor=currency_amount(price,form.get('currency'),signed=True)))
    invoice={k:form.get(k,'') for k in ('currency','issue_date','due_date','notes')}
    invoice['items']=items
    bridge.create_draft(bid,actor,jid,invoice=invoice,**_command(form))
    return redirect(url_for('core_finance_bridge.job_page',bid=bid,jid=jid),code=303)


def panel(business, customer_id=None, job_id=None):
    if not available(business):
        return None
    actor=security.current_user()['id']
    try:
        mapping=bridge.connection(business['id'],actor)
        result=bridge.read_invoice(business['id'],actor,job_id) if job_id else None
        data=dict(mapping=mapping,result=result,
                  links=bridge.customer_links(business['id'],actor,customer_id) if customer_id else [],
                  operation_key=uuid.uuid4().hex,payment_key=uuid.uuid4().hex)
        if result:
            data['delivery']=bridge.invoice_delivery_status(business['id'],result['link']['finance_invoice_id'])
            if result['invoice']['status'] in ('ISSUED','PARTIALLY_PAID'):
                data['payment_options']=bridge.payment_options(business['id'],actor,job_id)
        return data
    except (bridge.BridgeError, finance.FinanceError):
        # Lost Finance access must neither leak its data nor break the Core Job.
        return dict(unavailable=True,mapping=None,result=None,links=[])
