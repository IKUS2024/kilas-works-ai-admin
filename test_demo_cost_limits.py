"""Public demo cost limits, with all model and outbound requests mocked."""
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch
import _test_bootstrap
import app as bot
import ai_brain_shared

class DemoCostTests(unittest.TestCase):
    def setUp(self):
        self.client=bot.app.test_client()
        bot.demo_sessions.clear()
        bot.demo_daily_usage.update(date=bot._utcnow().strftime('%Y-%m-%d'),messages=0)
        self.response=Mock();self.response.json.return_value={'content':[{'text':'Bisa kak.'}],'usage':{}}
        self.network=patch('requests.sessions.Session.request',side_effect=AssertionError('paid API prohibited'))
        self.network.start();self.addCleanup(self.network.stop)

    def send(self,sid='demo',message='Halo'):
        return self.client.post('/demo/api',json={'session_id':sid,'message':message})

    def test_limits_and_eleventh_message_never_calls_model(self):
        self.assertEqual((bot.DEMO_MAX_MESSAGES_PER_SESSION,bot.DEMO_MAX_MESSAGES_PER_DAY,bot.DEMO_SESSION_TTL_HOURS),(10,100,3))
        with patch.object(bot.requests,'post',return_value=self.response) as post:
            for _ in range(10):self.assertEqual(self.send().status_code,200)
            response=self.send()
        self.assertEqual(post.call_count,10)
        self.assertIn('chat tim Kilas Works',response.get_json()['reply'])

    def test_hundred_daily_calls_then_quota(self):
        with patch.object(bot.requests,'post',return_value=self.response) as post:
            for n in range(100):self.send(sid='session-'+str(n))
            response=self.send(sid='over-limit')
        self.assertEqual(post.call_count,100)
        self.assertIn('Kuota demo hari ini sudah penuh',response.get_json()['reply'])

    def test_reset_is_local_and_free(self):
        bot.demo_sessions['demo']={'history':[{'role':'user','content':'Earlier'}],'count':10,'created_at':bot._utcnow(),'notified':False}
        with patch.object(bot.requests,'post') as post:
            response=self.send(message='reset demo')
        post.assert_not_called();self.assertTrue(response.get_json()['reset'])
        self.assertEqual(bot.demo_sessions['demo']['count'],0)

    def test_three_hour_expiry_and_utc_daily_reset(self):
        bot.demo_sessions['old']={'history':[],'count':10,'created_at':bot._utcnow()-timedelta(hours=3,minutes=1),'notified':False}
        bot.demo_sessions['recent']={'history':[],'count':10,'created_at':bot._utcnow()-timedelta(hours=2),'notified':False}
        bot._demo_cleanup_stale_sessions()
        self.assertNotIn('old',bot.demo_sessions);self.assertIn('recent',bot.demo_sessions)
        bot.demo_daily_usage.update(date='2000-01-01',messages=100)
        with patch.object(bot.requests,'post',return_value=self.response) as post:self.send('new-day')
        post.assert_called_once();self.assertEqual(bot.demo_daily_usage['messages'],1)

    def test_fast_model_budget_message_length_and_shared_core_unchanged(self):
        with patch.object(bot.requests,'post',return_value=self.response) as post:self.send(message='x'*1200)
        post.assert_called_once();payload=post.call_args.kwargs['json']
        self.assertEqual(payload['model'],bot.MODEL_FAST);self.assertIn('haiku',bot.MODEL_FAST)
        self.assertEqual(payload['max_tokens'],300)
        self.assertEqual(len(payload['messages'][-1]['content']),1000)
        self.assertIn(ai_brain_shared.AI_ADMIN_CORE_BEHAVIOR,payload['system'])

    def test_fallback_only_when_primary_fails(self):
        with patch.object(bot.requests,'post',side_effect=[TimeoutError('test'),self.response]) as post:self.send()
        self.assertEqual(post.call_count,2)
        self.assertEqual(post.call_args_list[0].kwargs['json']['model'],bot.MODEL_FAST)
        self.assertEqual(post.call_args_list[1].kwargs['json']['model'],bot.MODEL_FALLBACK)
        self.assertEqual(post.call_args_list[1].kwargs['json']['max_tokens'],300)
        with patch.object(bot.requests,'post',side_effect=TimeoutError('test')) as post:self.send('failure')
        self.assertEqual(post.call_count,2)

    def test_production_tags_are_stripped_without_actions(self):
        before_appointments=dict(bot.appointments);before_customers=dict(bot.customer_names)
        self.response.json.return_value={'content':[{'text':'Simulasi. [TANYA_OWNER] [GIVE_PAYMENT_INFO] [BOOKING_MEETING: tomorrow]'}]}
        with patch.object(bot.requests,'post',return_value=self.response),patch.object(bot,'send_whatsapp_message') as send:
            response=self.send(message='Booking simulasi')
        send.assert_not_called()
        self.assertEqual(response.get_json()['reply'],'Simulasi.')
        self.assertEqual(bot.appointments,before_appointments);self.assertEqual(bot.customer_names,before_customers)

if __name__=='__main__':unittest.main()
