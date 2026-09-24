"""Disposable, loopback-only browser QA. Never import this module from production.

Run: PYTHONPATH=/tmp/kilas-phase1-deps python client-hub/tests/public_chat_dev.py
Synthetic businesses, test-only owner entry, and deterministic model transport. Public routes,
JS, Core, storage, ownership checks and WEB Inbox are real. No legacy migrations or live IO.
"""
if __name__ == '__main__':
    from unittest.mock import patch
    from flask import redirect, session
    from test_public_chat_routes import WebTests

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
        if bid not in (7,8): return 'Not found',404
        session.clear()
        session.update(user_id=1 if bid==7 else 2,role='CLIENT_OWNER',
                       active_product='brain',_csrf_token='csrf-test')
        return redirect('/dashboard?product=brain')

    print('Disposable QA owner entry: http://127.0.0.1:8765/dev/owner/7',flush=True)
    try: app.run(host='127.0.0.1',port=8765,debug=False,use_reloader=False,threaded=True)
    finally:
        for stub in reversed(stubs): stub.stop()
        fixture.doCleanups(); WebTests.doClassCleanups()
