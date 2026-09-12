"""Behavioral regression for production fixes. All provider calls are mocked."""
import contextlib
import hashlib
import hmac
import io
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import _test_bootstrap
import app as bot
import context_engine as ctx
import test_tenant_persistence_and_payment_review as fixtures

class PgCursor:
    def __init__(self, conn): self.cur = conn.cursor()
    def __enter__(self): return self
    def __exit__(self, *args): self.cur.close()
    def execute(self, sql, params=()):
        self.cur.execute(sql.replace('%s', '?').replace('NOW()', 'CURRENT_TIMESTAMP'), params)
    def fetchone(self): return self.cur.fetchone()

class PgConnection:
    def __init__(self, path): self.conn = sqlite3.connect(path)
    def cursor(self): return PgCursor(self.conn)
    def commit(self): self.conn.commit()
    def close(self): self.conn.close()

class ProductionFixTests(unittest.TestCase):
    def setUp(self):
        fixtures.reset_bot_state()
        bot._clear_active_whatsapp_channel()
        bot.conversations.clear()
        bot.customer_names.clear()
        bot.agreed_facts.clear()
        bot.new_customer_notified.clear()
        bot.pending_owner_questions.clear()
        bot.handoff_notification_status.clear()

    def response(self, text='Halo.'):
        r = Mock(status_code=200)
        r.json.return_value = {'content':[{'type':'text','text':text}], 'usage':{'input_tokens':42,'output_tokens':5}}
        return r

    def test_prompt_reduction_preserves_core_and_prices(self):
        old = bot.build_customer_system_prompt('62811')
        blocks = bot.build_focused_customer_prompt('62811','halo')
        self.assertLess(sum(len(b['text']) for b in blocks), len(old)*0.5)
        self.assertIn(bot.AI_ADMIN_CORE_BEHAVIOR, blocks[0]['text'])
        self.assertIn(bot.PRICING_TEXT_BLOCK, blocks[0]['text'])
        self.assertEqual(blocks[0]['cache_control'], {'type':'ephemeral'})
        self.assertNotIn('cache_control', blocks[1])

    def test_relevant_old_fact_and_recent_decisions_preserved_exactly(self):
        old = 'Revisi logo maksimal 3x, kecuali ganti konsep.'
        rows = [old] + [f'Catatan {i} tentang foto' for i in range(15)]
        found = ctx.relevant_records(rows, 'revisi logo berapa')
        self.assertIn(old, found)
        self.assertEqual(found[-4:], rows[-4:])
        self.assertEqual(ctx.relevant_records(rows,'rekap semua keputusan'),rows)

    def test_cache_prefix_never_contains_customer_memory(self):
        bot.customer_names['62811']='PERSON_PRIVATE'
        bot.agreed_facts['62811']=['DECISION_PRIVATE']
        blocks=bot.build_focused_customer_prompt('62811','halo')
        self.assertNotIn('PERSON_PRIVATE',blocks[0]['text'])
        self.assertNotIn('DECISION_PRIVATE',blocks[0]['text'])
        self.assertIn('DECISION_PRIVATE',blocks[1]['text'])

    def test_owner_summary_excludes_other_tenant_even_without_db(self):
        bot.conversations.update({'62811':[{'role':'user','content':'platform visible'}],
                                  'T2:62811':[{'role':'user','content':'TENANT_SECRET'}]})
        result=bot.build_customer_context_summary()
        self.assertIn('platform visible',result)
        self.assertNotIn('TENANT_SECRET',result)

    def test_named_owner_query_fetches_selected_customer(self):
        bot.customer_names.update({'62811':'Budi','62812':'Asep'})
        bot.conversations.update({'62811':[{'role':'user','content':'foto makanan'}],
                                  '62812':[{'role':'user','content':'UNRELATED'}]})
        result=bot.build_customer_context_summary(query='Budi nanya apa?')
        self.assertIn('foto makanan',result)
        self.assertNotIn('UNRELATED',result)

    def test_tenant_direct_call_cannot_fall_back_to_platform_prompt(self):
        with patch.object(bot,'_build_tenant_context_block_safe',return_value=''), patch('requests.post',return_value=self.response()) as post:
            bot.call_claude('62811','apa layanan bisnis ini?',tenant_id=9)
        wire=json.dumps(post.call_args.kwargs['json']['system'])
        self.assertNotIn('Content Growth',wire)
        self.assertIn('BELUM',wire)

    def test_deferred_draft_only_committed_after_actual_reply(self):
        with patch('requests.post',return_value=self.response('sudah diteruskan')), patch.object(bot,'save_message_to_db') as save:
            bot.call_claude('62811','tolong bantu',defer_delivery=True)
            self.assertFalse(any(m['role']=='assistant' for m in bot.conversations['62811']))
            bot._record_delivered_reply('62811','Pengiriman belum terkonfirmasi.')
            self.assertEqual(bot.conversations['62811'][-1]['content'],'Pengiriman belum terkonfirmasi.')
            self.assertFalse(any(c.args[-1]=='sudah diteruskan' for c in save.call_args_list))

    def test_transport_retry_does_not_escalate_model(self):
        with patch('requests.post',side_effect=[OSError('offline'),self.response()]) as post:
            bot.call_claude('62811','layanan mana yang cocok untuk cafe?')
        self.assertEqual([c.kwargs['json']['model'] for c in post.call_args_list],[bot.MODEL_FAST]*2)

    def test_meta_requires_message_acceptance_and_redacts_errors(self):
        r=Mock(status_code=200);r.json.return_value={}
        self.assertFalse(bot._whatsapp_result(r)[0])
        r.json.return_value={'messages':[{'id':'wamid.test'}]}
        self.assertTrue(bot._whatsapp_result(r)[0])
        r.status_code=400;r.json.return_value={'error':{'message':'SECRET_TOKEN','code':131047}}
        self.assertEqual(bot._whatsapp_result(r),(False,'meta_http_400_code_131047'))

    def test_signature_failure_has_zero_actions(self):
        with patch.dict(os.environ,{'WHATSAPP_APP_SECRET':'test-secret'}),patch.object(bot,'_webhook_body_impl') as process:
            result=bot.app.test_client().post('/webhook',json={'entry':[]})
        self.assertEqual(result.status_code,403);process.assert_not_called()

    def test_valid_signature_and_batched_messages(self):
        data={'entry':[{'changes':[{'value':{'messages':[{'id':'a'},{'id':'b'}]}}]}]}
        raw=json.dumps(data).encode()
        signature='sha256='+hmac.new(b'test-secret',raw,hashlib.sha256).hexdigest()
        with patch.dict(os.environ,{'WHATSAPP_APP_SECRET':'test-secret'}),patch.object(bot,'_webhook_body_impl',return_value=None) as process:
            result=bot.app.test_client().post('/webhook',data=raw,content_type='application/json',headers={'X-Hub-Signature-256':signature})
        self.assertEqual(result.status_code,200)
        self.assertEqual([c.args[0]['entry'][0]['changes'][0]['value']['messages'][0]['id'] for c in process.call_args_list],['a','b'])

    def test_new_customer_failure_remains_retryable(self):
        payload=fixtures._text_payload('62811222','halo',phone_number_id=bot.WHATSAPP_PHONE_NUMBER_ID)
        with patch.object(bot,'notify_owner_new_message',return_value=False),patch.object(bot,'_get_conversation_mode_safe',return_value='HUMAN_TAKEOVER'):
            result=bot.app.test_client().post('/webhook',json=payload)
        self.assertEqual(result.status_code,200)
        self.assertNotIn('62811222',bot.new_customer_notified)
        self.assertEqual(bot.conversations['62811222'][-1]['content'],'halo')

    def test_new_customer_success_marks_after_send(self):
        payload=fixtures._text_payload('62811223','halo',phone_number_id=bot.WHATSAPP_PHONE_NUMBER_ID)
        def notify(*a,**kw):
            self.assertNotIn('62811223',bot.new_customer_notified)
            return True
        with patch.object(bot,'notify_owner_new_message',side_effect=notify),patch.object(bot,'_get_conversation_mode_safe',return_value='HUMAN_TAKEOVER'):
            bot.app.test_client().post('/webhook',json=payload)
        self.assertIn('62811223',bot.new_customer_notified)

    def test_expired_owner_outbound_does_not_send_freeform(self):
        bot.followup_state['62811']={'last_customer_msg_at':bot._utcnow()-bot.timedelta(hours=25)}
        with patch.object(bot,'send_whatsapp_message') as send:
            ok,err=bot.send_owner_outbound(None,'62811','follow up')
        self.assertFalse(ok);self.assertIn('template',err);send.assert_not_called()

    def test_notification_template_used_only_on_definitive_window_error(self):
        with patch.dict(os.environ,{'WHATSAPP_OWNER_NOTIFICATION_TEMPLATE_NAME':'owner_alert'}),patch.object(bot,'send_whatsapp_message',return_value=(False,'meta_http_400_code_131047')),patch.object(bot,'send_whatsapp_template_message',return_value=(True,None)) as send:
            self.assertTrue(bot._send_notification_with_template('62811','hello',None)[0])
            send.assert_called_once_with('62811','owner_alert','id',params=['hello'])
        with patch.object(bot,'send_whatsapp_message',return_value=(False,'meta_transport_error')),patch.object(bot,'send_whatsapp_template_message') as send:
            self.assertFalse(bot._send_notification_with_template('62811','hello',None)[0]);send.assert_not_called()

    def test_platform_cron_skips_human_takeover_without_llm(self):
        with patch.object(bot,'CRON_SECRET','test-cron'),patch.object(bot,'send_appointment_reminders',return_value=[]),patch.object(bot,'get_customers_due_for_followup',return_value=['62811']),patch.object(bot,'_get_conversation_mode_safe',return_value='HUMAN_TAKEOVER'),patch.object(bot,'call_claude') as ai:
            result=bot.app.test_client().get('/cron/followups?key=test-cron')
        self.assertEqual(result.json['results'][0]['status'],'skipped');ai.assert_not_called()

    def test_usage_log_has_cache_counts_no_payload(self):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            bot.log_ai_usage('customer','haiku',{'usage':{'input_tokens':1,'cache_read_input_tokens':4000,'cache_creation_input_tokens':100},'content':'SECRET'})
        self.assertIn('4000',stream.getvalue());self.assertNotIn('SECRET',stream.getvalue())

    def test_multitenant_prerequisites_fail_closed(self):
        with patch.dict(os.environ,{},clear=True):
            result=bot.multi_tenant_blockers()
        self.assertIn('shared_postgres_required',result)
        self.assertIn('webhook_signature_secret_required',result)

    def test_scoped_appointment_payment_and_foreign_proof(self):
        fixtures.reset_client_hub_db()
        a=fixtures._make_active_tenant('astra-a','628801')
        b=fixtures._make_active_tenant('astra-b','628802')
        appt=bot._appt_repo.create_appointment(b,'62811','Budi','besok')
        self.assertFalse(bot._appt_repo.update_scoped(a,appt,status='CANCELLED'))
        self.assertEqual(bot._appt_repo.get_latest_for_customer(b,'62811')['status'],'REQUESTED')
        self.assertTrue(bot._appt_repo.update_scoped(b,appt,status='CONFIRMED'))
        proof=bot._pay_review_repo.store_proof_image(b,b'image','image/jpeg')
        with self.assertRaises(ValueError):bot._pay_review_repo.create_review(a,'62811','Budi',proof_file_id=proof)
        review=bot._pay_review_repo.create_review(b,'62811','Budi',proof_file_id=proof)
        self.assertFalse(bot._pay_review_repo.update_status_scoped(a,review,'CONFIRMED'))
        self.assertTrue(bot._pay_review_repo.update_status_scoped(b,review,'CONFIRMED'))
        self.assertFalse(bot._pay_review_repo.update_status_scoped(b,review,'REJECTED'))

    def test_exact_owner_count_has_no_llm_and_no_false_zero_on_failure(self):
        with patch.object(bot._payment_service,'list_payments_pending_review',return_value=[{},{}]),patch('requests.post') as post:
            answer=bot.call_claude_owner('62811','berapa pembayaran belum dicek',None,None)
        self.assertIn('2 pembayaran',answer);post.assert_not_called()
        with patch.object(bot._payment_service,'list_payments_pending_review',side_effect=RuntimeError()):
            self.assertIn('belum bisa dibaca',bot._exact_owner_query(None,'berapa pembayaran belum dicek'))

    def test_simple_routes_need_no_llm_but_contextual_followups_still_do(self):
        with patch('requests.post') as post:
            self.assertIn('Halo',bot.call_claude('628new','halo'))
            self.assertIn('demo.kilasworks.id',bot.call_claude('628demo','link demo'))
            self.assertIn('[KIRIM_KATALOG]',bot.call_claude('628catalog','kirim katalog'))
        post.assert_not_called()
        self.assertIsNone(bot._exact_customer_route('halo',[{'role':'user','content':'komplain'}]))

    def test_exact_catalog_price_bypasses_llm_and_uses_current_row(self):
        row={'name':'Kilas Brain Basic','pricing_mode':'FIXED_PRICE','price_amount':523000,'price_unit':'per bulan'}
        with patch.object(bot._catalog_service,'list_active_catalog',return_value=[row]),patch('requests.post') as post:
            result=bot.call_claude('62811','harga Kilas Brain Basic berapa?',defer_delivery=True)
        self.assertIn('523.000',result);post.assert_not_called()
        with patch.object(bot._catalog_service,'list_active_catalog',return_value=[row]):
            self.assertIsNone(bot._exact_customer_price_query('Kilas Brain Basic berapa dan apa cocok buat cafe?'))

    def test_platform_name_resolver_excludes_tenant_names(self):
        bot.customer_names.update({'T8:62811':'Private Tenant Customer','62812':'Platform Customer'})
        self.assertEqual(bot.find_customers_by_name('Private Tenant'),[])
        self.assertEqual(bot.find_customers_by_name('Platform'),[('62812','Platform Customer')])

    def test_durable_claims_survive_process_cache_clear_and_isolate_channels(self):
        with tempfile.TemporaryDirectory() as d:
            path=d+'/claims.db';conn=sqlite3.connect(path)
            conn.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY, number TEXT, mode TEXT, role TEXT, content TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
            conn.execute("CREATE UNIQUE INDEX claims ON messages(number, mode) WHERE mode IN ('_webhook_claim', '_outbound_claim')")
            conn.commit();conn.close()
            with patch.object(bot,'db_enabled',return_value=True),patch.object(bot,'get_db_connection',side_effect=lambda:PgConnection(path)):
                bot._set_active_whatsapp_channel('channel-a','dummy')
                self.assertFalse(bot.is_duplicate_event('same-id'))
                bot.PROCESSED_MESSAGE_IDS.clear()
                self.assertTrue(bot.is_duplicate_event('same-id'))
                bot._set_active_whatsapp_channel('channel-b','dummy')
                self.assertFalse(bot.is_duplicate_event('same-id'))
                action=Mock(return_value=(True,None))
                self.assertTrue(bot._send_once('notify:a:1',action)[0])
                self.assertTrue(bot._send_once('notify:a:1',action)[0]);action.assert_called_once()
                uncertain=Mock(side_effect=OSError('crash'))
                self.assertFalse(bot._send_once('notify:a:2',uncertain)[0])
                self.assertFalse(bot._send_once('notify:a:2',uncertain)[0]);uncertain.assert_called_once()
                failed=Mock(side_effect=[(False,'meta_http_400_code_131047'),(True,None)])
                self.assertFalse(bot._send_once('notify:a:3',failed)[0])
                self.assertTrue(bot._send_once('notify:a:3',failed)[0])

if __name__=='__main__':unittest.main(verbosity=2)
