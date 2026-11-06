"""Actual Interpreter HTTP/socket hooks with synthetic supplier and account data."""
import base64
import io
import json
import os
import unittest
from unittest.mock import patch,Mock
from uuid import uuid4
from werkzeug.datastructures import FileStorage
from test_kilas_interpreter import InterpreterTests as Base,SETTINGS
import db
import repo
from kilas_ai import credit_policy as policy, credit_wallet as wallet, credit_wallet_schema as schema, usage
from kilas_ai import interpreter as calls


class InterpreterRouteCreditTests(unittest.TestCase):
    config=Base.config
    shared=Base.shared
    lifetime=Base.lifetime
    enabled=Base.enabled
    login_other=Base.login_other

    def setUp(self):
        Base.setUp(self)
        conn=usage._connect()
        try:schema.apply(conn);conn.commit()
        finally:conn.close()
        self.flags=patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'yes','KILAS_CREDIT_TARIFFS_JSON':json.dumps({'version':'customer-credit-v1','rates':{'INTERPRETER':{'milli':2000,'units':1000}},'limits':{'INTERPRETER':{'models':['gemini-3.8-live'],'source_ms':1000,'output_ratio_milli':2000}}})})
        self.flags.start();self.addCleanup(self.flags.stop)

    def admit(self,ident,settings=None,headers=None):
        return self.client.post('/kilas-translator/interpreter/'+ident,headers={'X-CSRF-Token':'audio-csrf',**(headers or {})},data={'settings':json.dumps(settings or {**SETTINGS,'turn_mode':'tap','reuse_session':True})})

    def cleanup_call(self,ident):
        self.addCleanup(lambda:calls._calls.pop((self.user,ident),None));self.addCleanup(lambda:calls.end(self.user,ident))

    def test_real_sender_receiver_settle_source_once_with_no_idle_charge(self):
        with self.enabled(),patch.object(calls.Thread,'start'),patch.object(calls.wire,'connect') as provider:
            ident=uuid4().hex;self.assertEqual(self.admit(ident).status_code,202);self.cleanup_call(ident)
            call=calls.get(self.user,ident);call.accept(0,b'\xe8\x03'*8000);call.accept(1,b'\xe8\x03'*8000);call.finish_input(2)
            def send(raw):
                value=json.loads(raw)['realtimeInput']
                if value.get('audio'):
                    call.receive(json.dumps({'serverContent':{'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(b'\xe8\x03'*12000).decode()}}]},'outputTranscription':{'text':'Synthetic'}}}))
                if 'activityEnd' in value:
                    call.receive(json.dumps({'serverContent':{'turnComplete':True}}));call.closed.set()
            call.ws=Mock();call.ws.send.side_effect=send;call.send()
            row=db.query_one('SELECT * FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(self.user,'interpreter:'+ident+':turn:0'))
            self.assertEqual((row['status'],row['actual_units'],row['free_actual']),('CAPTURED',1000,1000))
            calls.end(self.user,ident);self.assertEqual(wallet.balance(self.user)['balance_milli'],0)
            self.assertEqual(self.admit(ident).status_code,409);provider.assert_not_called()

    def test_supplier_denial_releases_customer_admission_without_start(self):
        with self.enabled(),patch.object(calls.budget,'claim',side_effect=calls.CallError('budget_limit')),patch.object(calls.Thread,'start') as start:
            ident=uuid4().hex;self.assertEqual(self.admit(ident).status_code,503)
            row=db.query_one('SELECT status FROM kilas_credit_admissions WHERE user_id=?',(self.user,));self.assertEqual(row['status'],'RELEASED')
            start.assert_not_called()

    def test_paid_consent_account_fence_and_repeated_http_never_redispatch(self):
        admin=repo.create_user(self.id()+'-admin@example.test','hash',role='KILAS_ADMIN')
        ident=wallet.create_purchase(self.user,'synthetic')
        with patch('file_utils.validate_project_attachment_upload',return_value=('proof.png','image/png')):wallet.submit_proof(self.user,ident,FileStorage(io.BytesIO(b'synthetic'),filename='proof.png',content_type='image/png'))
        wallet.review(ident,admin,'VERIFIED',transfer_reference='SYNTHETIC-'+ident)
        policy.admit(self.user,'free-spent','TRANSLATOR',180000,'a'*64);policy.finish(self.user,'free-spent',180000,success=True)
        with self.enabled(),patch.object(calls.Thread,'start') as start:
            ident=uuid4().hex;first=self.admit(ident);self.assertEqual(first.status_code,402);start.assert_not_called()
            token=first.json['credit_consent_url'].rsplit('/',1)[-1];policy.consent(self.user,token,True)
            self.assertEqual(self.admit(ident,headers={'X-Kilas-Credit-Consent':token}).status_code,202);self.cleanup_call(ident)
            self.assertEqual(self.admit(ident,headers={'X-Kilas-Credit-Consent':token}).status_code,409);start.assert_called_once()
            self.login_other('CLIENT_OWNER')
            self.assertEqual(self.admit(ident,headers={'X-Kilas-Credit-Consent':token}).status_code,409)
            start.assert_called_once()


if __name__=='__main__':unittest.main()
