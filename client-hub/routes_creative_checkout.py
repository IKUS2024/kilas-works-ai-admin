"""Scoped Creative Services checkout; existing account and admin roles are unchanged."""
import io
from urllib.parse import urlencode
from flask import Blueprint, abort, current_app, make_response, redirect, render_template, request, url_for
from itsdangerous import BadSignature
import creative_orders as orders
import db
import payment_service
import projects_repo
import security

creative_checkout_bp = Blueprint('creative_checkout', __name__, url_prefix='/creative-services')


def current_offer(key, addon='none'):
    # Retired influencer links still resolve to the current package, without an add-on.
    if addon in ('micro', 'macro', 'mega') and addon not in orders.CATALOG['addons']:
        addon = 'none'
    return orders.offer(key, addon)


@creative_checkout_bp.before_app_request
def limit_upload():
    if request.endpoint == 'creative_checkout.payment' and request.method == 'POST':
        request.max_content_length = orders.MAX_PROOF_BYTES + 128 * 1024


@creative_checkout_bp.before_app_request
def resume_after_login():
    # Login (including OAuth/register) already lands here. A separate signed, bounded
    # selection cookie survives the existing login session rotation; it grants no access.
    if request.endpoint != 'products.product_start' or not request.cookies.get('creative_selection') or not security.current_user():
        return
    try:
        choice = orders.signer().loads(request.cookies['creative_selection'], max_age=1800)
        key, addon = choice['key'], choice['addon']
        selected = current_offer(key, addon)
        addon = selected['addon']
    except (BadSignature, ValueError, TypeError, KeyError):
        return
    response = redirect(url_for('creative_checkout.checkout', key=key, addon=addon), code=303)
    response.delete_cookie('creative_selection', path='/')
    return response


@creative_checkout_bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def preserve_selection(response):
    # Called after invalid identity is cleared. This cookie grants no identity/access.
    if request.method == 'GET' and request.endpoint in ('creative_checkout.checkout', 'creative_checkout.begin_login'):
        try:
            selected = current_offer(request.view_args['key'], request.args.get('addon', 'none'))
        except (ValueError, KeyError, TypeError):
            return response
        response.set_cookie('creative_selection', orders.signer().dumps({'key': selected['key'], 'addon': selected['addon']}),
                            max_age=1800, httponly=True, secure=request.is_secure, samesite='Lax', path='/')
    return response


def render(page, **kwargs):
    from creative_i18n import translate, messages
    return render_template('creative_checkout.html', page=page, money=orders.money, cs_t=translate, cs_messages=messages(), **kwargs)


def quotation(selected, user, error=None):
    message = 'Halo Kilas, saya ingin konsultasi dan quotation untuk ' + selected['name'] + '.'
    return make_response(render('quotation', selected=selected, user=user, error=error,
        consultation_url='https://wa.me/6282213039137?' + urlencode({'text': message})), 422 if error else 200)


@creative_checkout_bp.route('/checkout/<key>', methods=['GET', 'POST'])
def checkout(key):
    try:
        selected = current_offer(key, request.args.get('addon', 'none'))
    except ValueError:
        abort(404)
    user = security.current_user()
    if request.method == 'GET' and user:
        draft = request.args.get('draft', '')
        try:
            saved = orders.signer().loads(draft, max_age=86400)
            if saved.get('owner') != user['id'] or saved.get('key') != key:
                raise ValueError()
            previous = orders.find_draft(user['id'], saved['nonce'])
            if previous:
                invoice = payment_service.get_latest_invoice_for_project(previous['id'])
                if invoice:
                    return redirect(url_for('creative_checkout.payment', invoice_id=invoice['id']), code=303)
        except (BadSignature, ValueError, TypeError, AttributeError):
            if selected.get('quotation_required'):
                return quotation(selected, user)
            return redirect(url_for('creative_checkout.checkout', key=key,
                                    draft=orders.checkout_token(user['id'], key), addon=selected['addon']), code=303)
    if request.method == 'GET' and selected.get('quotation_required'):
        return quotation(selected, user)
    error = None
    if request.method == 'POST':
        if not user:
            if selected.get('quotation_required'):
                return quotation(selected, user, 'Paket ini memerlukan quotation tertulis sebelum invoice dapat dibuat.')
            abort(401)
        try:
            invoice_id = orders.create_order(user['id'], key, request.form)
            return redirect(url_for('creative_checkout.payment', invoice_id=invoice_id), code=303)
        except ValueError as exc:
            error = str(exc)
        try:
            selected = orders.offer(key, request.form.get('addon', 'none'))
        except ValueError:
            pass
    if selected.get('quotation_required'):
        return quotation(selected, user, error)
    token = request.form.get('order_token') if request.method == 'POST' else request.args.get('draft')
    response = make_response(render('checkout', selected=selected, user=user, error=error,
        values=request.form if request.method == 'POST' else {}, addons=orders.checkout_addons(selected['service']),
        token=token or (orders.checkout_token(user['id'], key) if user else ''),
        bank=orders.BANK), 422 if error else 200)
    if not user:
        response.set_cookie('creative_selection', orders.signer().dumps({'key': key, 'addon': selected['addon']}), max_age=1800,
                            httponly=True, secure=request.is_secure, samesite='Lax', path='/')
    return response


@creative_checkout_bp.route('/checkout/<key>/login')
def begin_login(key):
    try:
        selected = current_offer(key, request.args.get('addon', 'none'))
    except ValueError:
        abort(404)
    if selected.get('quotation_required'):
        return redirect(url_for('creative_checkout.checkout', key=key, addon=selected['addon']), code=303)
    response = redirect(url_for('auth.login_page'), code=303)
    response.set_cookie('creative_selection', orders.signer().dumps({'key': key, 'addon': selected['addon']}),
                        max_age=1800, httponly=True, secure=request.is_secure, samesite='Lax', path='/')
    return response


def owned_invoice(invoice_id):
    user = security.current_user()
    invoice = payment_service.get_invoice(invoice_id)
    project = projects_repo.get_project(invoice['project_id']) if invoice else None
    if not project or (project['created_by_user_id'] != user['id'] and user['role'] != 'KILAS_ADMIN'):
        abort(404)
    snapshot = project.get('requirements', {})
    if snapshot.get('creative_order') != 1:
        abort(404)
    return user, invoice, project, snapshot


@creative_checkout_bp.route('/payment/<int:invoice_id>', methods=['GET', 'POST'])
@security.login_required
def payment(invoice_id):
    user, invoice, project, snapshot = owned_invoice(invoice_id)
    error = None
    if request.method == 'POST':
        if project['created_by_user_id'] != user['id']:
            abort(403)
        try:
            orders.submit_proof(invoice_id, user['id'], request.files.get('proof'))
            return redirect(url_for('creative_checkout.payment', invoice_id=invoice_id), code=303)
        except ValueError as exc:
            error = str(exc)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    return render('payment', selected=snapshot, bank=snapshot['bank'], invoice=invoice,
                  payment=payment, error=error, user=user,
                  closed=not orders.payment_open(project, invoice),
                  cancelled=project["status"] in ("CANCELLED", "REJECTED") or invoice["status"] == "CANCELLED"), 422 if error else 200


@creative_checkout_bp.route('/payment/<int:invoice_id>/proof')
@security.login_required
def proof(invoice_id):
    _, invoice, project, _ = owned_invoice(invoice_id)
    payment = payment_service.get_payment_for_invoice(invoice_id)
    file = db.query_one('SELECT content FROM project_files WHERE id=? AND project_id=?',
                        (payment['proof_file_id'], project['id'])) if payment.get('proof_file_id') else None
    if not file:
        abort(404)
    response = make_response(bytes(file['content']))
    response.headers['Content-Type'] = 'image/jpeg'
    response.headers['Content-Disposition'] = 'inline; filename="bukti-transfer.jpg"'
    return response


@creative_checkout_bp.route('/orders')
@security.login_required
def history():
    rows = db.query_all("SELECT i.id, i.invoice_number, i.amount, p.title, pay.status, p.status AS project_status, i.status AS invoice_status FROM invoices i JOIN projects p ON p.id=i.project_id JOIN payments pay ON pay.invoice_id=i.id WHERE p.created_by_user_id=? AND p.catalog_key LIKE 'creative_%' ORDER BY i.id DESC LIMIT 100", (security.current_user()['id'],))
    return render('orders', rows=rows, error=None)
