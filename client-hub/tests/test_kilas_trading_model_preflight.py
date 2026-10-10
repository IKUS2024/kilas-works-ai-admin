"""Synthetic catalog transport only; no real provider request or inference."""
import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch
import requests
import test_kilas_trading as f
from kilas_trading import analysis

PATH='/products/services/trading/model/catalog-preflight'
FIELDS={'credential','http_status','model_id_match','checked_at'}

class Reply:
    def __init__(self,status=200,body=None):
        self.status_code=status
        self.body=json.dumps(body if body is not None else {'id':'gpt-6.1-sol','private':'synthetic-private-body'}).encode()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def raise_for_status(self):
        if self.status_code>=400:raise requests.HTTPError('synthetic-private-error',response=self)
    def iter_content(self,n):yield self.body

class CatalogPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not hasattr(f.TradingTests,'user'):f.TradingTests.setUpClass()
    def setUp(self):
        self.base=f.TradingTests('test_xauusd_contract_and_units');self.base.setUp()
        self.addCleanup(self.base.doCleanups);self.client=self.base.client
        self.env=patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-private-key','KILAS_TRADING_AI_ENABLED':'false','KILAS_TRADING_CONTROL_ENABLED':'false'})
        self.env.start();self.addCleanup(self.env.stop)
    def post(self,client=None,**kwargs):
        return (client or self.client).post(PATH,json={},headers={'X-CSRF-Token':'paper-csrf'},**kwargs)
    def verify(self,response,status,match,credential='PRESENT'):
        self.assertEqual(response.status_code,200);data=response.get_json()
        self.assertEqual(set(data),FIELDS);self.assertEqual(data['credential'],credential)
        self.assertEqual(data['http_status'],status);self.assertIs(data['model_id_match'],match)
        self.assertIsNotNone(datetime.fromisoformat(data['checked_at']).tzinfo)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        for value in ('synthetic-private-key','synthetic-private-body','synthetic-private-error','Authorization'):
            self.assertNotIn(value,response.text)
    def test_get_only_fixed_destination_no_inference_or_state_mutation(self):
        before=f.store.snapshot(f.TradingTests.user)
        with patch.object(analysis.requests,'request',return_value=Reply()) as transport,patch.object(analysis,'analyze',side_effect=AssertionError('No analyze')):
            self.verify(self.post(),200,True)
        transport.assert_called_once_with('GET','https://api.openai.com/v1/models/gpt-6.1-sol',headers={'Authorization':'Bearer synthetic-private-key','Content-Type':'application/json'},json=None,timeout=(5,10),allow_redirects=False,stream=True)
        self.assertIsNone(analysis.market_source);self.assertEqual(f.store.snapshot(f.TradingTests.user),before)
        self.assertEqual(os.environ['KILAS_TRADING_AI_ENABLED'],'false');self.assertEqual(os.environ['KILAS_TRADING_CONTROL_ENABLED'],'false')
    def test_credential_missing_never_contacts_provider(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}),patch.object(analysis,'_http') as transport:
            self.verify(self.post(),None,False,'MISSING');transport.assert_not_called()
    def test_catalog_id_mismatch_and_non_object(self):
        for body in ({'id':'other'},[],{'id':True}):
            with self.subTest(body=body),patch.object(analysis.requests,'request',return_value=Reply(body=body)):
                self.verify(self.post(),200,False)
    def test_http_failure_and_redirect_not_followed(self):
        for status in (301,302,307,401,403,404,429,500):
            with self.subTest(status=status),patch.object(analysis.requests,'request',return_value=Reply(status)) as transport:
                self.verify(self.post(),status,False);self.assertEqual(transport.call_count,1)
                self.assertFalse(transport.call_args.kwargs['allow_redirects'])
    def test_transport_unavailable_safe_no_retry(self):
        with patch.object(analysis.requests,'request',side_effect=requests.Timeout('synthetic-private-error')) as transport:
            self.verify(self.post(),None,False);self.assertEqual(transport.call_count,1)
    def test_malformed_and_oversized_provider_body(self):
        for body in (b'{',b'x'*65537,b'{"id":NaN}'):
            reply=Reply();reply.body=body
            with self.subTest(size=len(body)),patch.object(analysis.requests,'request',return_value=reply):
                self.verify(self.post(),200,False)
    def test_owner_login_csrf_and_method_isolation(self):
        with patch.object(analysis,'_http') as transport:
            anonymous=f.app.app.test_client()
            with anonymous.session_transaction() as session:session['_csrf_token']='paper-csrf'
            self.assertEqual(self.post(anonymous).status_code,302)
            for user in (f.TradingTests.other,f.TradingTests.admin):self.assertEqual(self.post(self.base.login(user)).status_code,404)
            self.assertEqual(self.client.post(PATH,json={}).status_code,400)
            self.assertEqual(self.client.get(PATH).status_code,405)
            with self.client.session_transaction() as session:session['support_business_id']=999
            self.assertEqual(self.post().status_code,404);transport.assert_not_called()
    def test_revoked_identity_and_disabled_product(self):
        with patch.object(analysis,'_http') as transport:
            with patch.dict(os.environ,{'KILAS_TRADING_ENABLED':'false'}):self.assertEqual(self.post().status_code,404)
            f.db.execute('DELETE FROM oauth_identities WHERE user_id=?',(f.TradingTests.user,))
            try:self.assertEqual(self.post().status_code,404)
            finally:f.db.execute("INSERT INTO oauth_identities(provider,provider_subject,user_id,email_at_link) VALUES ('google','synthetic-paper-pilot',?,?)",(f.TradingTests.user,'irvankarnavi@gmail.com'))
            transport.assert_not_called()
    def test_request_payload_cannot_choose_model_destination_or_secret(self):
        with patch.object(analysis,'_http') as transport:
            for body in ('[]','null','{"model":"other"}','{"url":"https://evil.test"}','{"key":"private"}','{"x":1,"x":2}'):
                response=self.client.post(PATH,data=body,content_type='application/json',headers={'X-CSRF-Token':'paper-csrf'})
                self.assertEqual(response.status_code,400)
            self.assertEqual(self.post(query_string={'model':'other'}).status_code,400)
            self.assertEqual(self.client.post(PATH,data='{}',headers={'X-CSRF-Token':'paper-csrf'}).status_code,400)
            self.assertEqual(self.client.post(PATH,data=' '*8193,content_type='application/json',headers={'X-CSRF-Token':'paper-csrf'}).status_code,413)
            transport.assert_not_called()
    def test_host_isolation(self):
        with patch.object(analysis,'_http') as transport:
            for host,status in (('https://app.kilasworks.id',404),('https://evil.test',400)):
                self.assertEqual(self.post(base_url=host).status_code,status)
            transport.assert_not_called()
    def test_diagnostic_page_owner_only_and_no_automatic_provider_call(self):
        path='/products/services/trading/model/diagnostics'
        with patch.object(analysis,'_http') as transport:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200)
            self.assertIn('Check model access',response.text)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertEqual(f.app.app.test_client().get(path).status_code,302)
            for user in (f.TradingTests.other,f.TradingTests.admin):self.assertEqual(self.base.login(user).get(path).status_code,404)
            with self.client.session_transaction() as session:session['support_business_id']=999
            self.assertEqual(self.client.get(path).status_code,404)
            transport.assert_not_called()

if __name__=='__main__':unittest.main()
