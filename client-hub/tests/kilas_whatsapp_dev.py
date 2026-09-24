"""Loopback-only synthetic owner Inbox QA. No production credentials or outgoing network."""
import os
if __name__=='__main__':
    if os.environ.get('KILAS_PHASE8_BROWSER_QA')!='1': raise SystemExit('Explicit test harness flag required')
    from flask import session, redirect, abort, jsonify
    from test_kilas_whatsapp import WhatsAppTests
    WhatsAppTests.setUpClass()
    fixture=WhatsAppTests();app=fixture.app
    from kilas_core.adapters import whatsapp as wa
    from public_chat import store
    # Unique provider IDs for each stubbed outbound call.
    from unittest.mock import Mock
    def accepted(*args,**kwargs):
        response=Mock(status_code=200);response.json.return_value={'messages':[{'id':'stub-'+str(fixture.http.call_count)}]}
        return response
    @app.get('/dev/owner/<int:bid>')
    def owner(bid):
        if bid not in (7,8): abort(404)
        session.update(user_id=1 if bid==7 else 2,role='CLIENT_OWNER',active_product='brain',_csrf_token='csrf-test')
        return redirect('/business/'+str(bid)+'/inbox?channel=web'+('&conversation='+cid if bid==7 else ''))
    @app.get('/dev/health')
    def health(): return {'ready':True}
    @app.post('/dev/inbound')
    def inbound():
        if session.get('user_id')!=1: abort(404)
        fixture.response.json.return_value={'messages':[{'id':'next-model-out'}]}
        fixture.receive('volumenya 0.2 m3',{'volume_cbm':'0.2 m³'},'browser-second')
        return {'ok':True}
    @app.get('/dev/evidence')
    def evidence():
        if session.get('user_id')!=1: abort(404)
        with store.transaction() as tx:
            sends=tx.execute('SELECT status FROM kw_core_wa_outbound WHERE business_id=7')
        return jsonify(conversation=cid,attempts=len(sends),statuses=[r['status'] for r in sends])
    fixture.setUp()
    fixture.receive()
    cid=fixture.link()['conversation_id']
    fixture.http.side_effect=accepted
    app.run(host='127.0.0.1',port=8769,threaded=False,use_reloader=False)
