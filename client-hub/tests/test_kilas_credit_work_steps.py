"""Existing Work paths, synthetic tariffs and mocked suppliers; no paid IO."""
import io
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch,Mock
from werkzeug.datastructures import FileStorage
import test_kilas_credit_routes as fixture
import db
from kilas_ai import credit_policy as policy,credit_wallet as wallet,credit_work,credit_work_steps as steps,usage
from kilas_ai import autonomous_store as store,autonomous_runner as runner
from kilas_ai.agent_workers import content_worker

MODEL='gpt-6-luna'
BOUNDS={'text':{'models':[MODEL,'gpt-6.1-sol'],'max_calls':1,'input_bytes':100000,'output_tokens':3000}}
TARIFFS={'version':'customer-credit-v1','work_allocation':'per_successful_logical_step','watch_billing':'per_completed_observation',
 'rates':{key:{'milli':1000,'units':1} for key in ('WORK_TEXT','WORK_WEB','WORK_WATCH','WORK_DOCUMENT','WORK_CODE','WORK_PROJECT')},
 'limits':{
 'WORK_TEXT':{'operations':BOUNDS},'WORK_CODE':{'operations':BOUNDS},
 'WORK_WEB':{'operations':{'search':{'models':[MODEL],'max_calls':1,'input_bytes':100000,'output_tokens':2048}}},
 'WORK_WATCH':{'operations':{**BOUNDS,'search':{'models':[MODEL],'max_calls':1,'input_bytes':100000,'output_tokens':2048}}},
 'WORK_DOCUMENT':{'operations':{**BOUNDS,'author':{'models':[MODEL],'max_calls':1,'input_bytes':100000,'output_tokens':24576}}},
 'WORK_PROJECT':{'operations':{'native':{'models':[MODEL],'max_calls':4,'input_bytes':1000000,'output_tokens':16384}}}}}


class WorkStepsTests(unittest.TestCase):
    setUpClass=classmethod(fixture.CreditRoutesTests.setUpClass.__func__)
    client_for=fixture.CreditRoutesTests.client_for

    def setUp(self):
        self.user=fixture.fixture.repo.create_user(self.id()+'@example.test','hash')
        self.flags=patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'yes','KILAS_AI_AUTOMATION_ENABLED':'true','KILAS_AI_AUTONOMOUS_ENABLED':'true','OPENAI_API_KEY':'synthetic-no-network','KILAS_AI_OPENAI_WEB_MODEL':MODEL,'KILAS_CREDIT_TARIFFS_JSON':json.dumps(TARIFFS)})
        self.flags.start();self.addCleanup(self.flags.stop)
        ident=wallet.create_purchase(self.user,'synthetic')
        with patch('file_utils.validate_project_attachment_upload',return_value=('proof.png','image/png')):wallet.submit_proof(self.user,ident,FileStorage(io.BytesIO(b'synthetic'),filename='proof.png',content_type='image/png'))
        wallet.review(ident,self.admin,'VERIFIED',transfer_reference='SYNTHETIC-WORK-STEPS-'+ident)
        self.job=store.create(self.user,'Create a useful result',mode='ONE_SHOT')
        db.execute("UPDATE kilas_agent_jobs SET status='RUNNING',next_wake_at=?,plan_json='{\"steps\":[]}' WHERE id=?",(store.stamp(),self.job))
        self.addCleanup(self.cleanup_job)

    def cleanup_job(self):
        current=store.get(self.user,self.job)
        if current and current['status'] not in store.TERMINAL:store.control(self.user,self.job,'stop')

    def add_step(self,worker='AI_TEXT',action='write',data=None,sequence=1):
        key='work-step-'+str(self.job)+'-'+str(sequence)
        db.execute('INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,input_json,idempotency_key) VALUES (?,?,?,?,?,?,?)',(self.job,sequence,worker,action,'Synthetic request',json.dumps(data or {'prompt':'Write a short factual note'}),key))
        return key

    def tick(self):
        token='synthetic-lease'
        db.execute('UPDATE kilas_agent_jobs SET lease_token=?,lease_until=? WHERE id=?',(token,(usage._now()+timedelta(minutes=10)).isoformat(),self.job))
        runner.execute(self.job,token)

    def quote(self):
        row=db.query_one("SELECT * FROM kilas_credit_work_waits WHERE job_id=? AND state='WAITING' ORDER BY created_at DESC LIMIT 1",(self.job,))
        self.assertIsNotNone(row);return row['token']

    def response(self,content='A useful synthetic result'):
        value=Mock();value.status_code=200;value.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':content}}],'usage':{'prompt_tokens':100,'completion_tokens':50}};return value

    def test_multistep_text_consent_completed_steps_and_no_internal_chat_quota(self):
        self.add_step('FILE','create',{'name':'first.txt','format':'txt','content':'First completed step'})
        key=self.add_step(sequence=2)
        with patch.object(content_worker.requests,'post',return_value=self.response()) as provider:
            self.tick();self.assertEqual(store.steps(self.job)[0]['status'],'SUCCEEDED');provider.assert_not_called()
            self.tick();token=self.quote();provider.assert_not_called()
            self.assertEqual(db.query_one('SELECT feature FROM kilas_credit_consents WHERE token=?',(token,))['feature'],'WORK')
            self.assertEqual(self.client_for(self.user).post('/kilas-ai/credits/consent/'+token,data={'csrf_token':'console-csrf','decision':'approve'}).status_code,200)
            self.tick();provider.assert_called_once()
            self.assertEqual(store.get(self.user,self.job)['status'],'COMPLETED')
            self.assertEqual(wallet.balance(self.user)['balance_milli'],1999000)
            with wallet._locked(self.user) as conn:self.assertEqual(policy.remaining_in(conn,self.user,'CHAT',usage._now()),70)
            self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_work_usage WHERE user_id=?',(self.user,))['n'],1)
            self.assertEqual(db.query_one('SELECT status FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(self.user,key))['status'],'CAPTURED')

    def test_decline_expiry_changed_model_input_account_and_concurrent_resume(self):
        self.add_step()
        with patch.object(content_worker.requests,'post') as provider:
            self.tick();token=self.quote()
            with self.assertRaises(wallet.WalletError):credit_work.decide(self.other,token,True)
            with patch.dict(os.environ,{'KILAS_AI_OPENAI_WEB_MODEL':'changed'}):
                with self.assertRaisesRegex(wallet.WalletError,'changed'):credit_work.decide(self.user,token,True)
            original=store.steps(self.job)[0]['input_json']
            db.execute("UPDATE kilas_agent_steps SET input_json='{}' WHERE job_id=?",(self.job,))
            with self.assertRaises(wallet.WalletError):credit_work.decide(self.user,token,True)
            db.execute('UPDATE kilas_agent_steps SET input_json=? WHERE job_id=?',(original,self.job))
            expiry=db.query_one('SELECT expires_at FROM kilas_credit_consents WHERE token=?',(token,))['expires_at']
            db.execute('UPDATE kilas_credit_consents SET expires_at=? WHERE token=?',((usage._now()-timedelta(seconds=1)).isoformat(),token))
            with self.assertRaisesRegex(wallet.WalletError,'expired'):credit_work.decide(self.user,token,True)
            db.execute('UPDATE kilas_credit_consents SET expires_at=? WHERE token=?',(expiry,token))
            with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:credit_work.decide(self.user,token,False),range(8)))
            self.assertEqual(results,['DECLINED']*8)
            with self.assertRaises(wallet.WalletError):credit_work.decide(self.user,token,True)
            provider.assert_not_called();self.assertEqual(wallet.balance(self.user)['reserved_milli'],0)

    def test_interrupted_text_no_redispatch_or_new_attempt_tariff(self):
        key=self.add_step()
        import requests
        with patch.object(content_worker.requests,'post',side_effect=requests.Timeout) as provider:
            self.tick();credit_work.decide(self.user,self.quote(),True)
            self.tick();provider.assert_called_once()
            self.assertEqual(store.get(self.user,self.job)['status'],'FAILED')
            self.assertEqual(db.query_one('SELECT status FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(self.user,key))['status'],'RESERVED')
            self.assertEqual(wallet.balance(self.user)['reserved_milli'],1000)
            with self.assertRaises(ValueError):store.control(self.user,self.job,'resume')
            provider.assert_called_once()

    def test_provider_bounds_and_supplier_unavailability_release_without_charge(self):
        self.add_step()
        with patch.object(content_worker.requests,'post') as provider:
            self.tick();credit_work.decide(self.user,self.quote(),True)
            with patch.object(content_worker.providers,'candidates',return_value=iter(())):self.tick()
            provider.assert_not_called()
            self.assertEqual(wallet.balance(self.user)['reserved_milli'],0)
            self.assertEqual(wallet.balance(self.user)['balance_milli'],2000000)

    def test_cancellation_and_rollback_never_dispatch(self):
        self.add_step()
        with patch.object(content_worker.requests,'post') as provider:
            self.tick();token=self.quote();store.control(self.user,self.job,'stop')
            with self.assertRaises(wallet.WalletError):credit_work.decide(self.user,token,True)
            provider.assert_not_called()
            self.assertEqual(wallet.balance(self.user)['reserved_milli'],0)

    def test_unpriced_execution_market_and_project_execution_fail_before_provider(self):
        for worker,action,data in [('EXECUTION','python',{'request':'Run main.py'}),('MARKET','observe',{'symbol':'XAUUSD','timeframe':'1h','operator':'gt','threshold':1}),('CODE','test',{'repo':'synthetic'}),('PROJECT','create',{'request':'Create output files'})]:
            step={'id':99,'worker':worker,'action':action,'input_json':json.dumps(data),'idempotency_key':'synthetic'}
            job=store.get(self.user,self.job)
            if worker=='PROJECT':job['checkpoint_json']=json.dumps({'generate_outputs':True})
            callback=Mock()
            with self.assertRaisesRegex(wallet.WalletError,'unapproved'):steps.execute(job,step,callback)
            callback.assert_not_called()
        self.assertEqual(wallet.balance(self.user)['balance_milli'],2000000)

    def test_web_and_watch_each_have_one_work_charge_not_internal_chat_messages(self):
        self.add_step('WATCH','observe',{'query':'Observe a synthetic value','operator':'gt','threshold':20})
        web={'output':[{'type':'web_search_call','status':'completed'},{'type':'message','content':[{'type':'output_text','text':'Synthetic observation','annotations':[{'type':'url_citation','url':'https://example.test/value','title':'Synthetic'}]}]}],'usage':{'input_tokens':20,'output_tokens':30}}
        search=Mock();search.status_code=200;search.json.return_value=web
        with patch.object(content_worker.requests,'post',side_effect=[search,self.response('{"value":10}')]) as provider:
            self.tick();credit_work.decide(self.user,self.quote(),True);self.tick()
            self.assertEqual(provider.call_count,2)
            self.assertEqual(store.get(self.user,self.job)['status'],'WAITING')
            self.assertEqual(wallet.balance(self.user)['balance_milli'],1999000)
            with wallet._locked(self.user) as conn:self.assertEqual(policy.remaining_in(conn,self.user,'CHAT',usage._now()),70)
            self.tick();self.assertIsNotNone(self.quote());self.assertEqual(provider.call_count,2)
            self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_work_calls WHERE user_id=?',(self.user,))['n'],2)

    def test_document_default_and_selected_author_keep_model_bound_single_settlement(self):
        from kilas_ai import providers,chat_models
        self.add_step('DOCUMENT','create',{'request':'Create a synthetic text document','format':'md'})
        db.execute('UPDATE kilas_agent_jobs SET checkpoint_json=? WHERE id=?',(json.dumps({'author_model':MODEL}),self.job))
        events=[{'type':'provider','provider':'openai','model':MODEL},{'type':'delta','text':'# Synthetic document\n\nUseful complete source content for this synthetic document.'},{'type':'usage','input_tokens':100,'output_tokens':40},{'type':'finish','reason':'stop'}]
        with patch.object(chat_models,'check',return_value={'available':True,'images':True}),patch.object(providers,'stream',return_value=iter(events)) as provider:
            self.tick();provider.assert_not_called();credit_work.decide(self.user,self.quote(),True);self.tick();provider.assert_called_once()
            self.assertEqual(store.get(self.user,self.job)['status'],'COMPLETED')
            self.assertEqual(wallet.balance(self.user)['balance_milli'],1999000)
            self.assertEqual(db.query_one('SELECT kind FROM kilas_credit_work_calls WHERE user_id=?',(self.user,))['kind'],'author')

    def test_generated_code_has_one_work_charge_and_no_extra_chat_unit(self):
        import tempfile
        from pathlib import Path
        from kilas_ai.agent_workers import code_worker
        self.add_step('CODE','patch',{'repo':'synthetic','patch':'__GENERATE__'})
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'work').mkdir();(root/'original').mkdir()
            (root/'repository.json').write_text(json.dumps({'alias':'synthetic'}))
            with patch.object(code_worker,'prepare',return_value=root),patch.object(content_worker.requests,'post',return_value=self.response('{"main.py":"print(1)"}')) as provider:
                self.tick();credit_work.decide(self.user,self.quote(),True);self.tick();provider.assert_called_once()
                self.assertEqual(store.get(self.user,self.job)['status'],'COMPLETED')
                self.assertEqual((root/'work'/'main.py').read_text(),'print(1)')
                self.assertEqual(wallet.balance(self.user)['balance_milli'],1999000)

    def test_native_project_authoring_preserves_existing_supplier_tools_and_no_execution(self):
        from kilas_ai import chat_models,workspace_execution
        self.add_step('PROJECT','create',{'request':'Create a synthetic source project'})
        db.execute('UPDATE kilas_agent_jobs SET checkpoint_json=? WHERE id=?',(json.dumps({'author_model':MODEL}),self.job))
        value=Mock();value.status_code=200;value.json.return_value={'status':'completed','model':MODEL,'output':[{'type':'function_call','call_id':'synthetic','name':'publish_project','arguments':json.dumps({'files':[{'name':'README.md','content':'# Synthetic project'},{'name':'main.py','content':'print(1)'}]})}],'usage':{'input_tokens':100,'output_tokens':60}}
        with patch.object(chat_models,'check',return_value={'available':True,'provider':'openai'}),patch.object(content_worker.requests,'post',return_value=value) as provider,patch.object(workspace_execution,'execute') as sandbox:
            self.tick();provider.assert_not_called();credit_work.decide(self.user,self.quote(),True);self.tick();provider.assert_called_once();sandbox.assert_not_called()
            self.assertEqual(store.get(self.user,self.job)['status'],'COMPLETED')
            self.assertEqual(wallet.balance(self.user)['balance_milli'],1999000)

    def test_provider_envelope_rejects_before_network_and_auto_planning_is_unpriced(self):
        self.add_step()
        with patch.object(content_worker.requests,'post') as provider:
            self.tick();credit_work.decide(self.user,self.quote(),True)
            # Config changes invalidate consent; keep original root terms and test
            # the actual bounded payload instead of inventing a new price.
            with patch.object(content_worker.intelligence,'playbook',return_value='x'*100001):self.tick()
            provider.assert_not_called();self.assertEqual(wallet.balance(self.user)['reserved_milli'],0)
        from kilas_ai import autonomous_planner
        with patch.object(autonomous_planner.requests,'post') as provider:
            with self.assertRaisesRegex(wallet.WalletError,'planning_terms'):autonomous_planner.propose(store.get(self.user,self.job),[])
            provider.assert_not_called()

    def test_web_search_path_has_one_work_quote_and_one_supplier_request(self):
        self.add_step('WEB','search',{'query':'Find a synthetic public source'})
        value=Mock();value.status_code=200;value.json.return_value={'output':[{'type':'web_search_call','status':'completed'},{'type':'message','content':[{'type':'output_text','text':'A synthetic result','annotations':[{'type':'url_citation','url':'https://example.test/source','title':'Source'}]}]}],'usage':{'input_tokens':20,'output_tokens':30}}
        with patch.object(content_worker.requests,'post',return_value=value) as provider:
            self.tick();credit_work.decide(self.user,self.quote(),True);self.tick();provider.assert_called_once()
            self.assertEqual(store.get(self.user,self.job)['status'],'COMPLETED')
            self.assertEqual(wallet.balance(self.user)['balance_milli'],1999000)
            with wallet._locked(self.user) as conn:self.assertEqual(policy.remaining_in(conn,self.user,'CHAT',usage._now()),70)

    def test_default_document_author_uses_the_same_work_quote(self):
        self.add_step('DOCUMENT','create',{'request':'Create a synthetic text document','format':'md'})
        with patch.object(content_worker.requests,'post',return_value=self.response('# Synthetic document\n\nUseful complete factual content for a synthetic document.')) as provider:
            self.tick();credit_work.decide(self.user,self.quote(),True);self.tick();provider.assert_called_once()
            self.assertEqual(store.get(self.user,self.job)['status'],'COMPLETED')
            self.assertEqual(wallet.balance(self.user)['balance_milli'],1999000)


if __name__=='__main__':unittest.main()
