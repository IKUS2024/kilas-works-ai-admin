import importlib.util
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch
import test_knowledge_setup_v2 as fixture
import ai_onboarding as ai
import ai_brain_shared

repo, db, hub = fixture.repo, fixture.db, fixture.hub

class SimulationCostTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.KnowledgeTests();self.base.setUp()
        self.client=self.base.client;self.bid=self.base.bid
        self.url=f'/business/{self.bid}/simulate/message'
        self.client.get(f'/business/{self.bid}/simulate')
        with self.client.session_transaction() as s:self.token=s[f'sim_token_{self.bid}']
        self.network=patch('requests.sessions.Session.request',side_effect=AssertionError('paid API prohibited'))
        self.network.start();self.addCleanup(self.network.stop)

    def add(self,count,role='user',bid=None,token='another-browser'):
        for n in range(count):repo.save_simulation_message(bid or self.bid,token,role,'Stored '+str(n))

    def test_models_defaults_and_independent_environment_override(self):
        spec=importlib.util.spec_from_file_location('cost_ai_isolated',ai.__file__)
        with patch.dict(os.environ,{},clear=False):
            os.environ.pop('CLIENT_HUB_MODEL',None);os.environ.pop('CLIENT_HUB_SIMULATION_MODEL',None)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertEqual(module.CLIENT_HUB_MODEL,'claude-sonnet-4-6')
            self.assertEqual(module.CLIENT_HUB_SIMULATION_MODEL,'claude-haiku-4-5-20251001')
            os.environ['CLIENT_HUB_SIMULATION_MODEL']='configured-sandbox-model'
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertEqual(module.CLIENT_HUB_SIMULATION_MODEL,'configured-sandbox-model')
            self.assertEqual(module.CLIENT_HUB_MODEL,'claude-sonnet-4-6')

    def test_simulation_one_call_model_output_and_shared_brain(self):
        response=Mock();response.json.return_value={'content':[{'text':'Jawaban singkat'}],'stop_reason':'end_turn'}
        history=[{'role':'user' if n%2==0 else 'assistant','content':str(n)} for n in range(20)]
        with patch.object(ai,'ANTHROPIC_API_KEY','test-key'),patch.object(ai.requests,'post',return_value=response) as post:
            reply,error=ai.simulate_customer_reply({'business_name':'Own Business'},{'description':'Only own facts'},history,'Pertanyaan')
        self.assertIsNone(error);self.assertEqual(reply,'Jawaban singkat');post.assert_called_once()
        payload=post.call_args.kwargs['json']
        self.assertEqual(payload['model'],ai.CLIENT_HUB_SIMULATION_MODEL)
        self.assertEqual(payload['max_tokens'],300)
        self.assertEqual(payload['messages'],history[-10:]+[{'role':'user','content':'Pertanyaan'}])
        self.assertIn(ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR,payload['system'])
        self.assertIn('Only own facts',payload['system'])

    def test_normalization_keeps_original_model_and_budget(self):
        config={k:{} for k in ai.REQUIRED_CONFIG_KEYS}
        config.update(business_name='Own Business',category='Coffee',description='Coffee',languages={'primary':'id','additional':[]},services=[],faqs=[],tone='ramah')
        response=Mock();response.json.return_value={'content':[{'text':json.dumps(config)}],'stop_reason':'end_turn'}
        with patch.object(ai,'ANTHROPIC_API_KEY','test-key'),patch.object(ai.requests,'post',return_value=response) as post:
            result,error=ai.normalize_business_data({'business_name':'Own Business'},{},[],[],[])
        self.assertIsNone(error);self.assertIsNotNone(result);post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['json']['model'],ai.CLIENT_HUB_MODEL)
        self.assertGreater(post.call_args.kwargs['json']['max_tokens'],300)

    def test_api_failure_does_not_retry(self):
        with patch.object(ai,'ANTHROPIC_API_KEY','test-key'),patch.object(ai.requests,'post',side_effect=TimeoutError('test timeout')) as post:
            reply,error=ai.simulate_customer_reply({'business_name':'Own'}, {}, [], 'Halo')
        self.assertIsNone(reply);self.assertIsNotNone(error);post.assert_called_once()

    def test_route_uses_last_ten_in_order_without_deleting_history(self):
        for n in range(20):repo.save_simulation_message(self.bid,self.token,'user' if n%2==0 else 'assistant',str(n))
        with patch.object(ai,'simulate_customer_reply',return_value=('Jawaban',None)) as call:
            response=self.client.post(self.url,json={'message':'Baru'})
        self.assertEqual(response.status_code,200);call.assert_called_once()
        self.assertEqual([x['content'] for x in call.call_args.args[2]],[str(n) for n in range(10,20)])
        rows=repo.get_simulation_history(self.bid,self.token,limit=100)
        self.assertEqual(len(rows),22);self.assertEqual(rows[0]['content'],'0')
        self.assertEqual(rows[-2]['content'],'Baru')

    def test_thirty_allowed_thirty_first_blocked_with_no_fake_rows(self):
        with patch.object(ai,'simulate_customer_reply',return_value=('Jawaban',None)) as call:
            for n in range(30):self.assertEqual(self.client.post(self.url,json={'message':str(n)}).status_code,200)
            before=db.query_all('SELECT * FROM simulation_messages ORDER BY id')
            response=self.client.post(self.url,json={'message':'31st'})
        self.assertEqual(call.call_count,30);self.assertEqual(response.status_code,429)
        self.assertIn('Batas Test AI hari ini',response.get_json()['reply'])
        self.assertIsNone(response.get_json()['message_id'])
        self.assertEqual(db.query_all('SELECT * FROM simulation_messages ORDER BY id'),before)

    def test_quota_is_business_wide_and_other_business_is_independent(self):
        self.add(30)
        other=repo.create_business(self.base.uid,'Second business','AI_ADMIN_BASIC')
        self.client.get(f'/business/{other}/simulate')
        with patch.object(ai,'simulate_customer_reply',return_value=('Jawaban',None)) as call:
            self.assertEqual(self.client.post(self.url,json={'message':'Blocked across sessions'}).status_code,429)
            self.assertEqual(self.client.post(f'/business/{other}/simulate/message',json={'message':'Allowed'}).status_code,200)
        call.assert_called_once();self.assertEqual(call.call_args.args[0]['id'],other)

    def test_only_today_user_rows_count_utc(self):
        self.add(30,'assistant');self.add(30,'user')
        yesterday=(datetime.now(timezone.utc).date()-timedelta(days=1)).isoformat()+' 12:00:00'
        db.execute("UPDATE simulation_messages SET created_at=? WHERE role='user'",(yesterday,))
        # Local date may be today while the instant is still yesterday UTC.
        local=(datetime.combine(datetime.now(timezone.utc).date(),datetime.min.time(),timezone.utc)-timedelta(minutes=30)).astimezone(timezone(timedelta(hours=7)))
        repo.save_simulation_message(self.bid,'local-date','user','Old UTC instant')
        db.execute("UPDATE simulation_messages SET created_at=? WHERE session_token='local-date'",(local.isoformat(),))
        with patch.object(ai,'simulate_customer_reply',return_value=('Jawaban',None)) as call:
            self.assertEqual(self.client.post(self.url,json={'message':'Today'}).status_code,200)
        call.assert_called_once()
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM simulation_messages')['n'],63)

    def test_concurrent_last_slot_is_atomic(self):
        self.add(29);barrier=Barrier(2)
        def reserve(n):
            try:
                barrier.wait(timeout=5)
                return repo.reserve_simulation_user_message(self.bid,'concurrent-'+str(n),'Message')
            finally:db.reset_connection_for_new_db_path()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,range(2)))
        self.assertEqual(sum(results),1)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM simulation_messages WHERE role='user'")['n'],30)

    def test_ownership_csrf_and_flag_unchanged(self):
        other=repo.create_user('other-sim@test.com',fixture.security.hash_password('password123'))
        client=hub.app.test_client()
        with client.session_transaction() as s:s['user_id']=other
        with patch.object(ai,'simulate_customer_reply',return_value=('Jawaban',None)) as call:
            self.assertEqual(client.post(self.url,json={'message':'Forbidden'}).status_code,404)
            with patch.dict(hub.app.config,{'CLIENT_HUB_FORCE_CSRF_IN_TESTS':True}):
                self.assertEqual(self.client.post(self.url,json={'message':'No CSRF'}).status_code,400)
            call.assert_not_called()
            response=self.client.post(self.url,json={'message':'Halo'})
        mid=response.get_json()['message_id']
        self.assertEqual(self.client.post(f'/business/{self.bid}/simulate/flag',json={'message_id':mid,'note':'Check'}).status_code,200)
        self.assertTrue(db.query_one('SELECT flagged_wrong FROM simulation_messages WHERE id=?',(mid,))['flagged_wrong'])

    def test_page_and_quota_create_no_production_rows_or_calls(self):
        tables=('projects','invoices','payments','businesses')
        before={t:db.query_all('SELECT * FROM '+t) for t in tables}
        self.add(30)
        with patch.object(ai,'simulate_customer_reply',side_effect=AssertionError('No model expected')) as call:
            self.assertEqual(self.client.get(f'/business/{self.bid}/simulate').status_code,200)
            self.assertEqual(self.client.post(self.url,json={'message':'Blocked'}).status_code,429)
        call.assert_not_called()
        for t,rows in before.items():self.assertEqual(db.query_all('SELECT * FROM '+t),rows)

if __name__=='__main__':unittest.main()
