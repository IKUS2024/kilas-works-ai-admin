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
    fixture=WebTests(); fixture.setUp()
    app=fixture.app
    fixture.db.execute("UPDATE businesses SET business_name='Kedai Demo' WHERE id=7")
    fixture.db.execute("UPDATE businesses SET business_name='Bisnis Kedua' WHERE id=8")
    # Each synthetic owner has one business; no production memberships or credentials.
    fixture.db.execute('UPDATE business_memberships SET user_id=2 WHERE business_id=8')
    fixture.db.execute("UPDATE ai_settings SET normalized_config_json=? WHERE business_id=7",
                       ('{"business_name":"Kedai Demo","hours":"09.00–17.00"}',))

    def own_businesses(uid, product):
        return [fixture.repo.get_business(7 if uid==1 else 8)]
    stubs=[patch('routes_products._product_businesses',side_effect=own_businesses),
           patch.object(fixture.repo,'required_fields_missing',return_value=[]),
           patch('payment_service.has_verified_ai_admin_payment',return_value=True),
           patch('inbox_service.list_conversations',return_value=[]),
           patch.object(fixture.ai,'_call_claude',return_value=(
               'Halo! Kedai Demo buka pukul 09.00–17.00. Ada yang bisa kami bantu?', 'end_turn', None))]
    for stub in stubs: stub.start()

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
