import unittest
from unittest.mock import patch
import test_owner_intent_target_resolution as fixture
import app as bot
import owner_intent_routing as routing

class OwnerRoutingTests(unittest.TestCase):
    def setUp(self):
        fixture.reset_state()
        bot.tenant_owner_conversations.clear()
        bot._tenant_active_customer_context.clear()

    def test_intent_distinctions(self):
        examples = {'dari semuanya paling minat siapa?':'GLOBAL_ANALYZE', 'customer mana paling berpotensi closing?':'GLOBAL_ANALYZE',
            'dari semuanya siapa paling oke?':'GLOBAL_ANALYZE', 'siapa terakhir chat?':'LOOKUP', 'Putri terakhir ngomong apa?':'LOOKUP',
            'yang belum bayar siapa aja?':'QUERY', 'follow up Putri':'ACTION', 'kirim ke Putri bilang udah bayar belum':'SEND',
            'siapa yang perlu follow up?':'QUERY', 'siapa yang sudah dikirim katalog?':'QUERY', 'dia mau nego berapa coba tanyain':'SEND'}
        for text, kind in examples.items():
            with self.subTest(text=text): self.assertEqual(routing.classify(text),kind)

    def test_global_ranking_ignores_stale_target_and_cannot_send(self):
        bot.active_customer_context[bot.OWNER_WHATSAPP_NUMBER]='628123'
        bot.pending_owner_questions['628123']='tolong kabari'
        with patch.object(bot,'call_claude_owner',return_value='Budi lebih siap. PESAN_UNTUK_CUSTOMER: jangan kirim') as ai, patch.object(bot,'send_whatsapp_message',return_value=(True,None)) as send:
            response=fixture.client.post('/webhook',json=fixture._owner_payload('dari semuanya paling minat siapa?','targeted.rank'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(ai.call_args.args[2:4],(None,None))
        self.assertEqual(send.call_count,1)
        self.assertEqual(send.call_args.args[0],bot.OWNER_WHATSAPP_NUMBER)
        self.assertNotIn('PESAN_UNTUK_CUSTOMER',send.call_args.args[1])

    def test_query_does_not_inherit_active_or_pending_action(self):
        bot.active_customer_context[bot.OWNER_WHATSAPP_NUMBER]='628123'
        with patch.object(bot,'call_claude_owner',return_value='Belum cukup data.') as ai, patch.object(bot,'send_whatsapp_message',return_value=(True,None)) as send:
            fixture.client.post('/webhook',json=fixture._owner_payload('yang belum bayar siapa aja?','targeted.query'))
        self.assertEqual(ai.call_args.args[2:4],(None,None))
        self.assertTrue(all(c.args[0]==bot.OWNER_WHATSAPP_NUMBER for c in send.call_args_list))

    def test_named_lookup_is_read_only(self):
        bot.customer_names['628123']='Putri'
        with patch.object(bot,'call_claude_owner',return_value='Putri tanya jadwal.') as ai, patch.object(bot,'send_whatsapp_message',return_value=(True,None)) as send:
            fixture.client.post('/webhook',json=fixture._owner_payload('Putri terakhir ngomong apa?','targeted.lookup'))
        self.assertEqual(ai.call_args.args[3],'628123')
        self.assertEqual(send.call_args.args[0],bot.OWNER_WHATSAPP_NUMBER)

    def test_global_summary_scoped_and_bounded(self):
        for tenant in (1,2):
            for i in range(40):
                key=bot._ck(tenant,str(62810000+i));bot.customer_names[key]=f'Tenant{tenant} Customer{i}'
                bot.conversations[key]=[{'role':'user','content':f'TENANT{tenant} '+('x'*10000)} for _ in range(20)]
        bot.conversations[bot._ck(1,'628999')]=[{'role':'user','content':'belum menyebut nama'}]
        summary=bot._global_owner_summary(1)
        self.assertIn('628999',summary)
        self.assertIn('TENANT1',summary);self.assertNotIn('TENANT2',summary)
        self.assertLessEqual(len(summary),22000)
        self.assertLessEqual(summary.count('Customer'),25)

    def test_platform_global_prompt_uses_multiple_customers_not_stale_history(self):
        bot.customer_names.update({'62811':'Putri','62812':'Budi',bot._ck(2,'62813'):'Foreign'})
        for n in bot.customer_names:bot.conversations[n]=[{'role':'user','content':'mau order'}]
        blocks=bot.build_owner_system_prompt('stale question','62811',query='dari semuanya paling minat siapa?')
        self.assertIn('Putri',blocks[1]['text']);self.assertIn('Budi',blocks[1]['text'])
        self.assertNotIn('Foreign',blocks[1]['text']);self.assertNotIn('stale question',blocks[1]['text'])

    def test_simple_ranking_keeps_fast_reasoning_policy(self):
        self.assertFalse(routing.needs_stronger_reasoning('customer mana paling berpotensi closing?'))
        self.assertTrue(routing.needs_stronger_reasoning('dari semuanya siapa paling potensial, bandingkan budget dan risiko?'))

if __name__=='__main__':unittest.main()
