"""Customer product entry and independent Finance subscription UI."""
import io
import os
import uuid
from urllib.parse import quote
from functools import wraps
from flask import Blueprint, render_template, request, session, redirect, url_for, abort, flash, send_file, jsonify
import db
import repo
import security
import product_flow
import finance_entitlements as entitlement
import finance_subscription as subscription
import finance_service as finance
import catalog_service
import payment_service
from pricing_config import BRAIN_PLAN,FINANCE_PLAN

products_bp=Blueprint('products',__name__)


def _kilas_order_whatsapp_url(item):
    raw_number=(os.environ.get('KILAS_ORDER_WHATSAPP_NUMBER') or '6282213039137').strip()
    number=''.join(ch for ch in raw_number if ch.isdigit()) or '6282213039137'
    request_code=str((item or {}).get('request_code') or '').strip()
    request_text=str((item or {}).get('request_text') or '').strip()
    if (item or {}).get('location_source')=='manual' and (item or {}).get('location_label'):
        location=str(item.get('location_label')).strip()
    elif (item or {}).get('location_source')=='gps':
        location='Lokasi GPS tersimpan di request Kilas Order'
    else:
        location='Belum ditentukan'
    lines=[
        'Halo Kilas, saya mau minta bantuan Cari Order.',
        '',
        'Kode request: '+request_code,
        'Permintaan: '+request_text,
        'Lokasi: '+location,
        '',
        'Mohon dibantu carikan pilihan yang cocok dan kabari saya lewat WhatsApp ini.',
    ]
    return 'https://wa.me/'+number+'?text='+quote('\n'.join(lines))


def _kilas_catalog_whatsapp_url(product):
    import order_catalog_service
    raw_number=(os.environ.get('KILAS_ORDER_WHATSAPP_NUMBER') or '6282213039137').strip()
    number=''.join(ch for ch in raw_number if ch.isdigit()) or '6282213039137'
    code=str((product or {}).get('product_code') or '').strip().upper()
    name=str((product or {}).get('name') or 'Produk Kilas').strip()
    price=order_catalog_service.customer_price_text(product)
    message='\n'.join([
        'Halo Kilas, saya tertarik dengan produk ini.',
        '',
        'Kode produk: '+code,
        'Produk: '+name,
        'Harga Kilas: '+price,
        '',
        'Tolong cek ketersediaannya ya.',
    ])
    return 'https://wa.me/'+number+'?text='+quote(message)


def _finance_business_claimed(business_id):
    """True when this business already belongs to the Finance product lane.

    Existing production rows are never rewritten. Old businesses with Finance master data count
    as Finance even if they predate self-service entitlements; new businesses become Finance when
    a trial/subscription row is created.
    """
    state = entitlement.state(business_id)
    if state.get('customer_hidden'):
        return False
    if state['status'] != 'NOT_ACTIVATED':
        return True
    return bool(db.query_one(
        'SELECT 1 FROM finance_accounts WHERE business_id=? LIMIT 1',
        (business_id,)
    ))


def _product_businesses(user_id, key):
    rows = repo.list_businesses_for_user(user_id)
    if key == 'finance':
        return [row for row in rows if _finance_business_claimed(row['id'])]
    if key == 'brain':
        return [row for row in rows if row['package'] != 'NONE']
    return rows


def _start_finance_trial_now(business_id, user):
    """One-click trial entry used by dashboard/product flows; never creates ledger activity."""
    business = security.require_business_access(business_id, user)
    # New AI Admin-only businesses may not be converted into Finance businesses in place.
    # Legacy combined records are allowed only when Finance data already exists, so old IDs/data
    # remain usable without creating any migration or duplicate ledger.
    if business['package'] != 'NONE' and not _finance_business_claimed(business_id):
        session['product_intent'] = 'finance'
        flash('Kilas Finance memakai bisnis terpisah dari AI Admin. Tambahkan bisnis Finance untuk melanjutkan.', 'info')
        return url_for('products.continue_product')
    state = entitlement.state(business_id)
    if state['active']:
        session['dashboard_business_id'] = business_id
        session.pop('product_intent', None)
        return url_for('finance.workspace_choice', business_id=business_id)

    if state['status'] != 'NOT_ACTIVATED' or state['trial_used']:
        return url_for('products.finance_setup', business_id=business_id)

    idr_accounts = [
        account for account in finance.list_accounts(
            business_id, actor_user_id=user['id'])
        if account['is_active'] and account['currency'] == 'IDR'
    ]
    if not idr_accounts:
        entitlement.setup(
            business_id, user['id'], 'Kas', 'CASH', 0)

    state = entitlement.start_trial(business_id, user['id'])
    if not state['active']:
        return url_for('products.finance_setup', business_id=business_id)

    # Old/imported businesses may already have an account but no default categories.
    # Complete only the missing harmless master data after the trial is active.
    existing = {
        (row['direction'], row['name'])
        for row in finance.list_categories(
            business_id, include_inactive=False, actor_user_id=user['id'])
    }
    for direction, names in finance.DEFAULT_CATEGORIES.items():
        for name in names:
            if (direction, name) not in existing:
                finance.create_category(
                    business_id, direction, name, actor_user_id=user['id'])

    session['dashboard_business_id'] = business_id
    session.pop('product_intent', None)
    flash('Kilas Finance aktif. Kamu bisa langsung mulai.', 'success')
    return url_for('finance.workspace_choice', business_id=business_id)


@products_bp.after_request
def privacy(response):
    if request.endpoint=='products.order_product_image':
        response.headers['Cache-Control']='public, max-age=21600'
    else:
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


@products_bp.route('/products/start',methods=['GET','POST'])
@security.login_required
def product_start():
    user=security.current_user()
    if request.method=='POST':
        choice=(request.form.get('product') or '').strip().lower()
        if choice=='both':
            session['onboarding_goal']='both'
            session['active_product']='brain'
            session.pop('product_intent',None)
            return redirect(url_for('products.assist_entry'),code=303)
        if choice=='finance':
            session['onboarding_goal']='finance'
            session['active_product']='finance'
            session.pop('product_intent',None)
            return redirect(url_for('products.finance_entry'),code=303)
        if choice=='assist':
            session['onboarding_goal']='ai'
            session['active_product']='brain'
            session.pop('product_intent',None)
            return redirect(url_for('products.assist_entry'),code=303)
        if choice=='services':
            session.pop('product_intent',None)
            session.pop('active_product',None)
            return redirect(url_for('projects.service_catalog_page'),code=303)
        if choice=='order':
            return render_template('order_retired.html'),410
        abort(400)
    return render_template('product_start.html',user=user)


@products_bp.route('/products/order')
@security.login_required
def order_entry():
    import order_service
    import order_catalog_service
    user=security.current_user()
    catalog=order_catalog_service.list_public_products(limit=10)
    for product in catalog:
        product['price_text']=order_catalog_service.customer_price_text(product)
    return render_template(
        'order_marketplace.html',
        user=user,
        recent_order_requests=order_service.list_user_requests(user['id'],limit=3),
        catalog_products=catalog,
    )


@products_bp.route('/products/order/catalog/<product_code>')
@security.login_required
def order_catalog_product(product_code):
    import order_catalog_service
    product=order_catalog_service.get_public_product(product_code)
    if not product:
        abort(404)
    product['price_text']=order_catalog_service.customer_price_text(product)
    return render_template(
        'order_catalog_product.html',
        user=security.current_user(),
        product=product,
        whatsapp_url=_kilas_catalog_whatsapp_url(product),
    )


@products_bp.route('/products/order/catalog/<product_code>/image')
@security.login_required
def order_product_image(product_code):
    import requests
    import order_catalog_service
    product=order_catalog_service.get_internal_product(product_code)
    if not product or not product.get('is_active'):
        abort(404)
    source=str(product.get('image_source_url') or '').strip()
    if not source.startswith('https://'):
        abort(404)
    try:
        upstream=requests.get(
            source,
            headers={'User-Agent':'Mozilla/5.0 (compatible; KilasOrder/1.0)'},
            timeout=(3,10),
            allow_redirects=True,
        )
        upstream.raise_for_status()
    except requests.RequestException:
        abort(404)
    body=upstream.content
    content_type=(upstream.headers.get('Content-Type') or 'image/jpeg').split(';',1)[0].strip().lower()
    if not content_type.startswith('image/') or len(body)>8*1024*1024:
        abort(404)
    return send_file(io.BytesIO(body),mimetype=content_type,max_age=21600)


@products_bp.route('/products/order/whatsapp',methods=['POST'])
@security.login_required
def order_whatsapp_handoff():
    import order_service
    user=security.current_user()
    request_text=(request.form.get('request_text') or '').strip()
    if len(request_text)<3:
        flash('Ceritakan barang yang sedang kamu cari.','error')
        return redirect(url_for('products.order_entry'),code=303)

    location_source=(request.form.get('location_source') or '').strip()
    location_label=(request.form.get('location_label') or '').strip()
    latitude=(request.form.get('latitude') or '').strip()
    longitude=(request.form.get('longitude') or '').strip()
    draft={
        'request_text':request_text[:800],
        'location_source':location_source if location_source in ('gps','manual') else '',
        'location_label':location_label[:120],
        'latitude':latitude[:32],
        'longitude':longitude[:32],
        'conversation':[],
        'draft_token':uuid.uuid4().hex,
    }
    saved=order_service.create_whatsapp_request(user['id'],draft)
    session['kilas_order_last_request']=saved['request_code']
    session.pop('kilas_order_draft',None)
    return redirect(_kilas_order_whatsapp_url(saved),code=303)


@products_bp.route('/products/order/request',methods=['GET','POST'])
@security.login_required
def order_request():
    import order_intake_ai

    def location_description(draft):
        if draft.get('location_source')=='manual' and draft.get('location_label'):
            return 'Area pilihan customer: ' + draft['location_label']
        if draft.get('location_source')=='gps':
            return 'GPS customer aktif dan tersedia untuk tahap pencarian.'
        return 'Lokasi belum dipilih.'

    def run_intake(draft):
        result,error=order_intake_ai.analyze(
            draft['request_text'],
            conversation=draft.get('conversation') or [],
            location_description=location_description(draft),
        )
        draft['ai_state']=result
        draft['ai_error']=bool(error)
        return draft

    if request.method=='POST':
        action=(request.form.get('action') or 'start').strip().lower()

        if action=='start_search':
            import order_service
            draft=session.get('kilas_order_draft') or {}
            state=draft.get('ai_state') or {}
            if not draft.get('request_text') or draft.get('ai_error') or not state.get('ready'):
                flash('Permintaan belum siap dicari. Lengkapi dulu bersama Kilas Buyer.','error')
                return redirect(url_for('products.order_request'),code=303)
            if not draft.get('draft_token'):
                draft['draft_token']=uuid.uuid4().hex
                session['kilas_order_draft']=draft
            saved=order_service.create_request(security.current_user()['id'],draft)
            session['kilas_order_last_request']=saved['request_code']
            return redirect(url_for('products.order_request_detail',request_code=saved['request_code']),code=303)

        if action in ('answer','retry'):
            draft=session.get('kilas_order_draft') or {}
            if not draft.get('request_text'):
                return redirect(url_for('products.order_entry'),code=303)
            if action=='answer':
                answer=(request.form.get('answer') or '').strip()
                if not answer or len(answer)>400:
                    flash('Jawaban belum bisa diproses. Coba tulis lebih singkat.','error')
                    return redirect(url_for('products.order_request'),code=303)
                state=draft.get('ai_state') or {}
                question=(state.get('question') or '').strip()
                conversation=list(draft.get('conversation') or [])
                if question:
                    conversation.append({'role':'assistant','content':question[:300]})
                conversation.append({'role':'user','content':answer[:400]})
                draft['conversation']=conversation[-8:]
            draft=run_intake(draft)
            session['kilas_order_draft']=draft
            return redirect(url_for('products.order_request'),code=303)

        request_text=(request.form.get('request_text') or '').strip()
        if len(request_text)<3:
            flash('Ceritakan barang yang sedang kamu cari.','error')
            return redirect(url_for('products.order_entry'),code=303)
        location_source=(request.form.get('location_source') or '').strip()
        location_label=(request.form.get('location_label') or '').strip()
        latitude=(request.form.get('latitude') or '').strip()
        longitude=(request.form.get('longitude') or '').strip()
        draft={
            'request_text':request_text[:800],
            'location_source':location_source if location_source in ('gps','manual') else '',
            'location_label':location_label[:120],
            'latitude':latitude[:32],
            'longitude':longitude[:32],
            'conversation':[],
            'draft_token':uuid.uuid4().hex,
        }
        draft=run_intake(draft)
        session['kilas_order_draft']=draft
        return redirect(url_for('products.order_request'),code=303)

    draft=session.get('kilas_order_draft') or {}
    if not draft.get('request_text'):
        return redirect(url_for('products.order_entry'),code=303)
    if not draft.get('draft_token'):
        draft['draft_token']=uuid.uuid4().hex
        session['kilas_order_draft']=draft
    return render_template('order_request.html',user=security.current_user(),draft=draft)


@products_bp.route('/products/order/requests')
@security.login_required
def order_requests():
    import order_service
    user=security.current_user()
    return render_template(
        'order_requests.html',
        user=user,
        requests_list=order_service.list_user_requests(user['id'],limit=50),
    )


@products_bp.route('/products/order/requests/<request_code>/search-run',methods=['GET','POST'])
@security.login_required
def order_request_search_run(request_code):
    import order_service
    import order_search
    user=security.current_user()
    item=order_service.get_user_request(user['id'],request_code)
    if not item:
        abort(404)
    if item.get('is_whatsapp_handoff'):
        return jsonify({
            'ok': False,
            'status': 'WHATSAPP_HANDOFF',
            'status_label': item.get('status_label'),
            'candidate_count': len(order_service.list_candidates(item['id'])),
            'active': False,
            'error_code': '',
        }), 409

    if request.method=='POST':
        if item.get('status') not in ('SEARCH_REQUESTED','SEARCHING','ISSUE'):
            return jsonify({
                'ok': item.get('status')=='RESULTS_READY',
                'status': item.get('status'),
                'status_label': item.get('status_label'),
                'candidate_count': len(order_service.list_candidates(item['id'])),
                'active': False,
                'error_code': '',
            })
        started=order_search.start_background_search(item)
        refreshed=order_service.get_user_request(user['id'],request_code) or item
        return jsonify({
            'ok': True,
            'started': started,
            'status': refreshed.get('status'),
            'status_label': refreshed.get('status_label'),
            'candidate_count': len(order_service.list_candidates(item['id'])),
            'active': order_search.is_background_search_active(item['id']),
            'error_code': order_search.get_background_search_error(item['id']),
        })

    refreshed=order_service.get_user_request(user['id'],request_code) or item
    return jsonify({
        'ok': refreshed.get('status')!='ISSUE',
        'status': refreshed.get('status'),
        'status_label': refreshed.get('status_label'),
        'candidate_count': len(order_service.list_candidates(item['id'])),
        'active': order_search.is_background_search_active(item['id']),
        'error_code': order_search.get_background_search_error(item['id']),
    })


@products_bp.route('/products/order/requests/<request_code>',methods=['GET','POST'])
@security.login_required
def order_request_detail(request_code):
    import order_service
    user=security.current_user()
    item=order_service.get_user_request(user['id'],request_code)
    if not item:
        abort(404)
    if request.method=='POST':
        action=(request.form.get('action') or '').strip().lower()
        if action=='retry_search':
            if item.get('is_whatsapp_handoff'):
                return redirect(_kilas_order_whatsapp_url(item),code=303)
            if item.get('status') not in ('SEARCH_REQUESTED','SEARCHING','ISSUE'):
                return redirect(url_for('products.order_request_detail',request_code=item['request_code']),code=303)
            import order_search
            order_search.start_background_search(item)
            flash('AI Kilas mulai mencari. Kamu bisa tetap di halaman status ini.','info')
            return redirect(url_for('products.order_request_detail',request_code=item['request_code']),code=303)
        abort(400)
    return render_template('order_request_status.html',user=user,item=item,whatsapp_url=_kilas_order_whatsapp_url(item))


@products_bp.route('/products/finance',methods=['GET','POST'])
@security.login_required
def finance_entry():
    user=security.current_user()
    businesses=_product_businesses(user['id'],'finance')
    cards=[]
    import math
    for business in businesses:
        state=entitlement.state(business['id'])
        if entitlement.unlimited_trial_mode() and state['status']=='NOT_ACTIVATED':
            state=entitlement.start_trial(business['id'],user['id'])
        remaining_days=None
        if state.get('active') and state.get('until'):
            seconds=(entitlement.parse(state['until'])-entitlement.now()).total_seconds()
            remaining_days=max(0,math.ceil(seconds/86400))
        cards.append({**business,'finance_state':state,'remaining_days':remaining_days})

    if request.method=='POST':
        action=(request.form.get('action') or '').strip()
        if action=='begin_trial':
            if businesses:
                return redirect(url_for('products.finance_entry'),code=303)
            setup_identity=request.form.get('setup_identity')
            try:
                business_id=product_flow.create_business(
                    user['id'],'Bisnis Utama',setup_identity)
            except ValueError:
                abort(400)
            target=_start_finance_trial_now(business_id,user)
            session['active_product']='finance'
            return redirect(target,code=303)
        if action=='create_trial':
            business_name=(request.form.get('business_name') or '').strip()
            try:
                business_id=product_flow.create_business(
                    user['id'],business_name,request.form.get('setup_identity'))
            except ValueError:
                flash('Nama bisnis wajib diisi dengan benar.','error')
                return redirect(url_for('products.finance_entry',step='business'),code=303)
            target=_start_finance_trial_now(business_id,user)
            if entitlement.state(business_id)['active']:
                session['active_product']='finance'
                return redirect(url_for('client.dashboard',product='finance'),code=303)
            return redirect(target,code=303)
        if action=='open':
            business_id=request.form.get('business_id',type=int)
            if not business_id:
                abort(400)
            allowed={row['id'] for row in businesses}
            if business_id not in allowed:
                abort(403)
            state=entitlement.state(business_id)
            if state['active']:
                session['dashboard_business_id']=business_id
                session['active_product']='finance'
                return redirect(url_for('finance.workspace_choice',business_id=business_id),code=303)
            return redirect(url_for('products.finance_setup',business_id=business_id),code=303)
        if action=='rename':
            business_id=request.form.get('business_id',type=int)
            name=(request.form.get('business_name') or '').strip()
            allowed={row['id'] for row in businesses}
            if not business_id or business_id not in allowed:
                abort(404)
            if not name or len(name)>160:
                flash('Nama bisnis wajib diisi dan maksimal 160 karakter.','error')
                return redirect(url_for('products.finance_entry'),code=303)
            repo.update_business_identity(business_id,name,user['id'])
            try:
                import finance_invoice_editor as invoice_editor
                invoice_editor.sync_sender_identity(business_id,name,user['id'])
            except Exception:
                pass
            flash('Nama bisnis Finance diperbarui.','success')
            return redirect(url_for('products.finance_entry'),code=303)
        if action=='archive':
            business_id=request.form.get('business_id',type=int)
            allowed={row['id'] for row in businesses}
            if not business_id or business_id not in allowed:
                abort(404)
            security.require_business_access(business_id,user)
            # Hide only the Finance lane. Never delete ledger rows and never hide the same
            # business from Kilas Assist, which is a separate product surface.
            db.execute(
                "UPDATE finance_entitlements SET customer_hidden=TRUE, updated_at=? WHERE business_id=?",
                (entitlement.now().isoformat(),business_id)
            )
            repo.write_audit(user['id'],business_id,'FINANCE_BUSINESS_HIDDEN','customer hid finance business from finance list')
            if session.get('dashboard_business_id')==business_id:
                session.pop('dashboard_business_id',None)
            flash('Bisnis Finance dihapus dari daftar Finance. Data Finance lama tetap tersimpan.','success')
            return redirect(url_for('products.finance_entry'),code=303)
        abort(400)

    return render_template(
        'finance_entry.html',
        user=user,
        businesses=cards,
        trial_days=FINANCE_PLAN['trial_days'],
        setup_identity=uuid.uuid4().hex,
        show_business_form=(request.args.get('step')=='business')
    )


def _assist_missing_labels(missing):
    labels={
        'business_name':'Nama bisnis','owner_name':'Nama owner','category':'Kategori bisnis',
        'short_description':'Tentang bisnis','operating_hours':'Jam operasional',
        'online_or_offline':'Model layanan','business_phone':'WhatsApp bisnis / nomor robot',
        'trusted_owner_phone':'WhatsApp pengelola','primary_language':'Bahasa utama',
        'customer_salutation':'Sapaan customer','core_product_or_service':'Produk / layanan utama',
    }
    return [labels.get(field,field) for field in (missing or [])]


def _assist_fix_step(missing):
    missing=set(missing or [])
    if missing & {'business_name','owner_name','category','short_description'}: return 'basics'
    if 'core_product_or_service' in missing: return 'services'
    if missing & {'operating_hours','online_or_offline','business_phone','trusted_owner_phone'}: return 'operations'
    if missing & {'primary_language','customer_salutation'}: return 'style'
    return 'basics'


@products_bp.route('/products/assist',methods=['GET','POST'])
@security.login_required
def assist_entry():
    user=security.current_user()
    raw_businesses=_product_businesses(user['id'],'brain')
    businesses=[]
    for business in raw_businesses:
        missing=repo.required_fields_missing(business['id'])
        ai_settings=repo.get_ai_settings(business['id']) or {}
        businesses.append({
            **business,
            'assist_missing':missing,
            'assist_missing_labels':_assist_missing_labels(missing),
            'assist_fix_step':_assist_fix_step(missing),
            'assist_review_pending':ai_settings.get('ai_status')=='STALE',
            'assist_payment_verified':payment_service.has_verified_ai_admin_payment(business['id']),
        })

    if request.method=='POST':
        action=(request.form.get('action') or '').strip()
        if action=='create':
            name=(request.form.get('business_name') or '').strip()
            try:
                business_id=product_flow.create_business(user['id'],name,request.form.get('setup_identity'))
            except ValueError:
                flash('Nama bisnis wajib diisi dengan benar.','error')
                return redirect(url_for('products.assist_entry',step='business'),code=303)
            with db.app_purchase_transaction(business_id,None):
                security.require_business_access(business_id,user)
                if repo.get_business(business_id)['package']=='NONE':
                    repo.upgrade_business_package(business_id,'AI_ADMIN',user['id'])
            session['active_product']='brain'
            return redirect(url_for('client.wizard_step',business_id=business_id,step='basics'),code=303)
        abort(400)

    return render_template(
        'assist_entry.html',
        user=user,
        businesses=businesses,
        setup_identity=uuid.uuid4().hex,
        show_business_form=(request.args.get('step')=='business' or not businesses)
    )


@products_bp.route('/products')
def index():
    if security.current_user():
        return redirect(url_for('products.product_start'),code=303)
    return redirect(url_for('auth.login_page'),code=303)


@products_bp.route('/products/select',methods=['POST'])
def select():
    key=product_flow.intent(request.form.get('product'))
    if not key:abort(400)
    # Talent uses the visual marketplace as the only customer entry point. Do not create a
    # generic "Talent Management" project from the product catalog; the customer must pick the
    # actual talent first so admin receives a concrete request.
    if key == 'talent_management':
        return redirect(url_for('talent.talent_list'), code=303)
    session['product_intent']=key
    return redirect(url_for('products.continue_product') if security.current_user() else url_for('auth.login_page'),code=303)


@products_bp.route('/products/continue',methods=['GET','POST'])
@security.login_required
def continue_product():
    user=security.current_user();key=product_flow.intent(session.get('product_intent'))
    if not key:return redirect(url_for('products.index'))
    if key == 'talent_management':
        session.pop('product_intent', None)
        return redirect(url_for('talent.talent_list'))
    if request.method=='POST':
        if request.form.get('create')=='yes':
            business_name=request.form.get('business_name')
            try: business_id=product_flow.create_business(user['id'],business_name,request.form.get('setup_identity'))
            except ValueError:abort(400)
        else:
            business_id=request.form.get('business_id',type=int)
            if business_id:
                selected_business=security.require_business_access(business_id,user)
                # Do not let a new Finance setup silently become an AI Admin business (or vice
                # versa). Legacy businesses that already contain both remain valid in both lanes.
                if key=='finance' and not _finance_business_claimed(business_id):
                    abort(400)
                if key=='brain' and selected_business['package']=='NONE':
                    abort(400)
            elif key in ('brain','finance'):abort(400)
        if key=='finance':
            target=_start_finance_trial_now(business_id, user)
            if request.form.get('create')=='yes' and entitlement.state(business_id)['active']:
                session['active_product']='finance'
                return redirect(url_for('client.dashboard',product='finance'),code=303)
            return redirect(target, code=303)
        if key=='brain':
            session['active_product']='brain'
            with db.app_purchase_transaction(business_id,None):
                security.require_business_access(business_id,user)
                if repo.get_business(business_id)['package']=='NONE':repo.upgrade_business_package(business_id,'AI_ADMIN',user['id'])
            return redirect(url_for('client.wizard_step',business_id=business_id,step='basics'),code=303)
        # Render explicit existing checkout/brief POST with the selected, authorized business.
        item=catalog_service.get_catalog_item(key)
        if not item or not item['is_active']:abort(404)
        return render_template('product_continue.html',item=item,chosen_business_id=business_id,ready=True)
    businesses=_product_businesses(user['id'],key)
    # Returning customers enter the selected product home first. Product switching belongs
    # on the initial picker, not inside the product dashboard.
    if key=='finance' and businesses:
        session['active_product']='finance'
    if key=='brain' and businesses:
        session['active_product']='brain'
    return render_template(
        'product_continue.html',product=key,user=user,
        businesses=businesses,
        setup_identity=uuid.uuid4().hex,ready=False
    )


@products_bp.route('/business/<int:business_id>/finance-trial/start',methods=['POST'])
@security.login_required
def start_finance_trial(business_id):
    user = security.current_user()
    return redirect(_start_finance_trial_now(business_id, user), code=303)


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
            if entitlement.state(business_id)['status']=='TRIAL_ACTIVE':
                flash('Trial Finance masih aktif. Tagihan langganan baru tersedia setelah trial berakhir.','info')
                return redirect(url_for('products.finance_setup',business_id=business_id),code=303)
            bill_id=subscription.create_bill(business_id,user['id'],request.form.get('request_key'))
            return redirect(url_for('products.bill_page',business_id=business_id,bill_id=bill_id),code=303)
        else:abort(400)
        return redirect(url_for('products.finance_setup',business_id=business_id),code=303)
    finance_state=entitlement.state(business_id)
    bill_search=(request.args.get('q') or '').strip()
    bill_needle=bill_search.casefold()
    bills=[] if finance_state['status']=='TRIAL_ACTIVE' else db.query_all(
        'SELECT id,status,amount_minor,created_at FROM finance_subscription_bills WHERE business_id=? ORDER BY id DESC',
        (business_id,)
    )
    if bill_needle:
        bills=[bill for bill in bills if (
            bill_needle in str(bill.get('id') or '').casefold()
            or bill_needle in str(bill.get('status') or '').casefold()
            or bill_needle in str(bill.get('amount_minor') or '').casefold()
        )]
    bills_total=len(bills)
    bill_per_page=10
    bill_total_pages=max(1,(bills_total+bill_per_page-1)//bill_per_page)
    bill_page=request.args.get('page',1,type=int) or 1
    bill_page=min(max(1,bill_page),bill_total_pages)
    bill_start=(bill_page-1)*bill_per_page
    bills=bills[bill_start:bill_start+bill_per_page]
    return render_template(
        'finance_subscription.html',business=business,entitlement=finance_state,finance_plan=FINANCE_PLAN,
        bill_request_key=uuid.uuid4().hex,self_service_enabled=entitlement.self_service(),
        accounts=[a for a in finance.list_accounts(business_id,actor_user_id=user['id']) if a['currency']=='IDR'],
        bank=subscription.payment_details(),bills=bills,bills_total=bills_total,bill_search=bill_search,
        bill_page=bill_page,bill_total_pages=bill_total_pages
    )


@products_bp.route('/business/<int:business_id>/finance-bills/<int:bill_id>',methods=['GET','POST'])
@security.login_required
def bill_page(business_id,bill_id):
    user=security.current_user();business=security.require_business_access(business_id,user)
    if user['role']!='KILAS_ADMIN' and entitlement.state(business_id)['status']=='TRIAL_ACTIVE':
        flash('Trial Finance masih aktif. Tagihan langganan baru tersedia setelah trial berakhir.','info')
        return redirect(url_for('products.finance_setup',business_id=business_id),code=303)
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
    search=(request.args.get('q') or '').strip()
    needle=search.casefold()
    businesses=repo.list_businesses_for_user(user['id'])
    if needle:
        businesses=[b for b in businesses if (
            needle in str(b.get('business_name') or '').casefold()
            or needle in str(b.get('package') or '').casefold()
            or needle in str(b.get('status') or '').casefold()
            or (b.get('package')!='NONE' and needle in 'kilas brain ai customer service')
            or needle in 'kilas finance keuangan bisnis'
        )]
    businesses_total=len(businesses)
    per_page=10
    total_pages=max(1,(businesses_total+per_page-1)//per_page)
    page=request.args.get('page',1,type=int) or 1
    page=min(max(1,page),total_pages)
    start=(page-1)*per_page
    businesses=businesses[start:start+per_page]
    return render_template(
        'account_bills.html',businesses=businesses,businesses_total=businesses_total,
        search=search,page=page,total_pages=total_pages
    )


@products_bp.route('/products/dashboard-business',methods=['POST'])
@security.login_required
def dashboard_business():
    business_id=request.form.get('business_id',type=int)
    if not business_id:abort(400)
    security.require_business_access(business_id,security.current_user())
    session['dashboard_business_id']=business_id
    return redirect(url_for('client.dashboard'),code=303)
