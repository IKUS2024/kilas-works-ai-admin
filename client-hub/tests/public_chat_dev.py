"""Disposable browser QA harness for Kilas Public Web Chat.

Default use is loopback-only:
  PYTHONPATH=client-hub:client-hub/tests python client-hub/tests/public_chat_dev.py

For an isolated public staging QA service only, set:
  KILAS_PUBLIC_CHAT_QA_STAGING=true
  KILAS_PUBLIC_CHAT_QA_TOKEN=<unguessable token>
  PORT=<assigned port>

Synthetic businesses, test-only owner entry, deterministic model transport, and disposable
SQLite are used. Public routes, JS, Core, storage, ownership checks and WEB Inbox are real.
No production credentials, production database, legacy migrations, Finance writes or live
WhatsApp/model IO are used. Never import this module from production.
"""
if __name__ == '__main__':
    import hmac
    import os
    from unittest.mock import patch
    from flask import abort, redirect, request, session
    from test_public_chat_routes import WebTests

    public_staging = os.environ.get('KILAS_PUBLIC_CHAT_QA_STAGING', '').strip().lower() == 'true'
    qa_token = os.environ.get('KILAS_PUBLIC_CHAT_QA_TOKEN', '')
    if public_staging and len(qa_token) < 24:
        raise RuntimeError('KILAS_PUBLIC_CHAT_QA_TOKEN must be at least 24 characters for public staging QA')

    WebTests.setUpClass()
    from kilas_core import customer_schema
    customer_schema.apply_schema()
    os.environ['KILAS_CUSTOMERS_V2_ENABLED']='true'
    fixture=WebTests(); fixture.setUp()
    app=fixture.app
    jobs_qa = os.environ.get('KILAS_JOBS_QA') == 'true'
    if jobs_qa:
        from kilas_core import job_schema
        job_schema.apply_schema()
        os.environ['KILAS_JOBS_V2_ENABLED']='true'
        fixture.db.execute('CREATE TABLE IF NOT EXISTS business_profiles(business_id INTEGER PRIMARY KEY,category TEXT)')
        fixture.db.execute("INSERT INTO business_profiles VALUES (7,'Restaurant'),(8,'Salon')")
    fixture.db.execute("UPDATE businesses SET business_name='Kedai Demo' WHERE id=7")
    fixture.db.execute("UPDATE businesses SET business_name='Bisnis Kedua' WHERE id=8")
    # Each synthetic owner has one business; no production memberships or credentials.
    fixture.db.execute('UPDATE business_memberships SET user_id=2 WHERE business_id=8')
    fixture.db.execute("UPDATE ai_settings SET normalized_config_json=? WHERE business_id=7",
                       ('{"business_name":"Kedai Demo","hours":"09.00–17.00"}',))

    def own_businesses(uid, product):
        if jobs_qa and product == 'finance':
            return []  # Existing Finance entry UI, synthetic account with no Finance businesses.
        return [fixture.repo.get_business(7 if uid==1 else 8)]
    # This harness deliberately has no Finance schema or business created_at column.
    # Workspace presentation reads use the same synthetic membership identity as its
    # pre-Phase-9 product entry. Core conversations/actions still use real storage.
    stubs=[patch('routes_products._product_businesses',side_effect=own_businesses),
           patch.object(fixture.repo,'list_businesses_for_user',side_effect=lambda uid: own_businesses(uid,'brain')),
           patch('routes_products._finance_business_claimed',return_value=False),
           patch('subscription_service.get_subscription_banner',return_value=None),
           patch.object(fixture.repo,'required_fields_missing',return_value=[]),
           patch('payment_service.has_verified_ai_admin_payment',return_value=True),
           patch('inbox_service.list_conversations',return_value=[]),
           patch.object(fixture.ai,'_call_claude',return_value=(
               'Halo! Kedai Demo buka pukul 09.00–17.00. Ada yang bisa kami bantu?', 'end_turn', None))]
    if os.environ.get('KILAS_PLAYBOOKS_QA') == 'true':
        if public_staging or not jobs_qa:
            raise RuntimeError('Phase 5 browser QA requires disposable loopback Jobs harness')
        from playbook_qa_provider import reply as playbook_reply
        os.environ['KILAS_PLAYBOOKS_V2_ENABLED'] = 'true'
        fixture.db.execute("UPDATE business_profiles SET category='Logistics' WHERE business_id=7")
        stubs[-1] = patch.object(fixture.ai,'_call_claude',side_effect=playbook_reply)
    if os.environ.get('KILAS_OPERATIONS_QA') == 'true':
        if public_staging or not jobs_qa or os.environ.get('KILAS_PLAYBOOKS_QA') != 'true':
            raise RuntimeError('Phase 6 requires disposable loopback Jobs + Playbooks harness')
        import time
        from kilas_core import operation_schema, automations
        operation_schema.apply_schema()
        os.environ['KILAS_OPERATIONS_V2_ENABLED']='true'
        qa_clock={'offset':0}
        stubs.append(patch.object(automations,'clock',side_effect=lambda now=None:
            int(time.time())+qa_clock['offset'] if now is None else now))

        @app.post('/dev/operations/legacy-complete')
        def legacy_complete():
            if session.get('user_id') != 1: abort(404)
            from kilas_core import jobs
            for row in jobs.list_jobs(7)[0]:
                if row['status']=='IN_PROGRESS':
                    jobs.update_job(7,row['id'],expected_version=row['version'],actor_id=1,
                        operation_key='fixture-complete-'+row['id'],status='COMPLETED')
            return {'ok':True}

        @app.post('/dev/operations/advance')
        def dev_advance():
            # Test-only synthetic clock; normal app CSRF still applies.
            if session.get('user_id') != 1 or session.get('active_product') == 'finance': abort(404)
            qa_clock['offset']+=3601
            return {'offset':qa_clock['offset']}
    for stub in stubs: stub.start()

    @app.post('/dev/confirm-customer/<int:bid>')
    def confirm_customer(bid):
        if public_staging or session.get('user_id') != (1 if bid==7 else 2) or bid not in (7,8): abort(404)
        from kilas_core import customers
        rows,_,_,_=customers.list_customers(bid)
        for customer in rows:
            customers.update_customer(bid,customer['id'],display_name=customer['display_name'],
                phone=customer.get('phone'),email=customer.get('email'),notes=customer.get('notes'),
                stage='CUSTOMER',actor_id=session['user_id'])
        return {'ok':True}

    @app.get('/dev/owner/<int:bid>')
    def dev_owner(bid):
        if bid not in (7,8):
            return 'Not found',404
        if public_staging:
            supplied=request.args.get('token','')
            if not supplied or not hmac.compare_digest(supplied,qa_token):
                abort(404)
        session.clear()
        session.update(user_id=1 if bid==7 else 2,role='CLIENT_OWNER',
                       active_product='brain',_csrf_token='csrf-test')
        return redirect('/dashboard?product=brain')

    if jobs_qa:
        @app.get('/dev/finance')
        def dev_finance():
            if public_staging:
                abort(404)  # Local disposable CI only; never a public Finance test entry.
            session.clear()
            session.update(user_id=1,role='CLIENT_OWNER',active_product='finance',_csrf_token='csrf-test')
            return redirect('/products/finance')

    @app.get('/dev/health')
    def dev_health():
        return {'ok':True,'synthetic':True,'public_staging':public_staging}

    host='0.0.0.0' if public_staging else '127.0.0.1'
    port=int(os.environ.get('PORT','8765'))
    shown_host='PUBLIC_STAGING_URL' if public_staging else f'http://127.0.0.1:{port}'
    print(f'Disposable QA owner entry base: {shown_host}/dev/owner/7',flush=True)
    try:
        app.run(host=host,port=port,debug=False,use_reloader=False,threaded=True)
    finally:
        for stub in reversed(stubs): stub.stop()
        fixture.doCleanups(); WebTests.doClassCleanups()
