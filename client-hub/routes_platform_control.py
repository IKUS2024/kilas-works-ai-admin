"""SaaS control center and explicit, scoped support sessions."""
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
import db
import repo
import security
import platform_control as control
import platform_console as console
import assist_connections as connections

platform_bp=Blueprint('platform_control',__name__,url_prefix='/platform')


@platform_bp.get('/')
@platform_bp.get('/<section>')
@security.admin_required
def page(section='overview'):
    if section in dict(console.SECTIONS):
        query=(request.args.get('q') or '').strip()[:100]
        product=(request.args.get('product') or '').strip().lower()
        status=(request.args.get('status') or '').strip().lower()
        try: page_number=max(1,min(1000,int(request.args.get('page','1'))))
        except ValueError: page_number=1
        data=(console.overview() if section=='overview' else
              console.customers(query,product or ('ai' if section=='kilas-ai' else ''),status,page_number) if section in ('customers','kilas-ai') else
              console.finance_businesses(query,page_number) if section=='finance' else
              console.payments() if section=='payments' else
              console.usage_cost() if section=='usage-cost' else console.settings())
        return render_template('platform_console.html',section=section,sections=console.SECTIONS,
                               data=data,query=query,product=product,status=status)
    if section not in dict(control.SECTIONS): abort(404)
    rows=control.businesses() if section in ('overview','businesses','whatsapp','subscriptions') else []
    economics=control.economics() if section in ('overview','cost','finance') else None
    return render_template('platform_control.html',section=section,sections=control.SECTIONS,rows=rows,
        metrics=control.overview(rows) if section=='overview' else {},economics=economics,
        system=control.system() if section=='system' else {},plans=__import__('pricing_config').ASSIST_PLANS)


@platform_bp.get('/customers/<int:user_id>')
@security.admin_required
def customer_detail(user_id):
    data=console.ai_customer(user_id)
    if data is None: abort(404)
    return render_template('platform_console.html',section='customer-detail',sections=console.SECTIONS,
                           data=data,query='',product='',status='')


@platform_bp.get('/business/<int:bid>')
@security.admin_required
def detail(bid):
    business=repo.get_business(bid)
    if not business: abort(404)
    owners=db.query_all('''SELECT u.full_name,u.email,u.id FROM users u JOIN business_memberships m ON m.user_id=u.id
        WHERE m.business_id=? AND m.role_in_business='OWNER' ''',(bid,))
    import assist_journey,assist_costs,subscription_service
    cost=next((r for r in assist_costs.platform_report()['businesses'] if r['business_id']==bid),None)
    return render_template('platform_business.html',business=business,owners=owners,
        journey=assist_journey.state(business),connection=connections.get(bid),
        mapping=repo.get_whatsapp_config(bid) or {},subscription=subscription_service.get_subscription(bid),
        cost=cost,sections=control.SECTIONS,section='businesses',test_code=session.pop('assist_connection_test_'+str(bid),None))


@platform_bp.post('/business/<int:bid>/connection')
@security.admin_required
def connection_action(bid):
    actor=security.current_user()
    if not repo.get_business(bid):abort(404)
    action=request.form.get('action')
    try:
        if action=='enqueue':
            with connections.binding_lock():connections.enqueue(bid,actor['id'])
        elif action in ('Processing','Waiting OTP','Disconnected'):
            connections.set_stage(bid,actor,action)
        elif action=='sync':
            connections.sync_mapping(bid,actor,request.form.get('waba_id','').strip(),
                request.form.get('phone_number_id','').strip(),request.form.get('credentials_reference','').strip())
        elif action=='inbound':
            session['assist_connection_test_'+str(bid)]=connections.start_inbound_test(bid,actor)
        elif action=='outbound':connections.test_outbound(bid,actor)
        elif action=='activate':connections.activate(bid,actor)
        else:abort(400)
        flash('Tindakan koneksi tersimpan. Periksa hasil uji sebelum aktivasi.','success')
    except (ValueError,PermissionError) as exc:
        messages={'both_tests_required':'Uji inbound dan bukti outbound delivered harus lulus pada pemetaan yang sama.',
                  'training_required':'Pemilik perlu menyelesaikan enam bagian onboarding, Latih dan Tes AI.',
                  'verified_subscription_required':'Langganan aktif dan pembayaran terverifikasi diperlukan.',
                  'requested_phone_required':'Lengkapi nomor WhatsApp bisnis pada Business Profile.',
                  'owner_phone_required':'Lengkapi nomor pemilik terpercaya pada Business Profile.',
                  'mapping_already_assigned':'Phone Number ID sudah digunakan bisnis lain.',
                  'requested_number_mismatch':'Nomor Meta tidak sama dengan nomor yang diajukan.',
                  'connection_bridge_unavailable':'Layanan koneksi belum dapat dihubungi. Periksa System.'}
        flash(messages.get(str(exc),'Tindakan belum berhasil. Periksa tahap, pemetaan, dan hasil uji lalu coba lagi.'),'error')
    return redirect(url_for('platform_control.detail',bid=bid),code=303)


@platform_bp.post('/business/<int:bid>/support')
@security.admin_required
def support(bid):
    business=repo.get_business(bid)
    if not business:abort(404)
    repo.write_audit(security.current_user()['id'],bid,'ADMIN_SUPPORT_STARTED','explicit scoped workspace access')
    session['support_business_id']=bid
    session['workspace_ai_business']=bid
    session.pop('active_product',None)
    return redirect(url_for('workspace.ai_home'),code=303)


@platform_bp.post('/support/exit')
@security.admin_required
def support_exit():
    bid=session.pop('support_business_id',None)
    if bid:repo.write_audit(security.current_user()['id'],bid,'ADMIN_SUPPORT_ENDED',None)
    return redirect(url_for('platform_control.page'),code=303)


@platform_bp.app_context_processor
def support_context():
    bid=session.get('support_business_id') if session.get('role')=='KILAS_ADMIN' else None
    return {'support_business':repo.get_business(bid) if bid else None}


@platform_bp.before_app_request
def support_scope():
    if session.get('role')!='KILAS_ADMIN':return
    # Finance keeps its existing admin permissions; an active support session narrows its scope.
    if request.blueprint=='finance' and not session.get('support_business_id'):return
    if request.blueprint not in ('client','assist','owner_web','core_customers','core_jobs','core_operations','core_finance_bridge','finance'):
        return
    bid=(request.view_args or {}).get('business_id',(request.view_args or {}).get('bid'))
    if bid is None:return
    # Kilas Works' existing internal CRM is its own explicit stored workspace,
    # not a customer tenant or a default scope. Preserve its admin-only routes.
    # An active support session must still prevent leaving the selected tenant.
    if not session.get('support_business_id'):
        import platform_workspace
        if platform_workspace.is_scope_business(bid):return
    # Admin CRM/support is explicit; platform endpoints remain separate administrative actions.
    if session.get('support_business_id') != bid:abort(404)


@platform_bp.after_app_request
def audit_support_write(response):
    bid=session.get('support_business_id') if session.get('role')=='KILAS_ADMIN' else None
    if bid and request.method not in ('GET','HEAD','OPTIONS') and response.status_code<400:
        scoped=(request.view_args or {}).get('business_id',(request.view_args or {}).get('bid'))
        if scoped==bid and request.blueprint!='platform_control':
            repo.write_audit(security.current_user()['id'],bid,'ADMIN_SUPPORT_WRITE',request.endpoint)
    return response
