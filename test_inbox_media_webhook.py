"""Media regression through the bot's actual webhook and internal media routes."""
import io
import json
import time
import unittest
from unittest.mock import patch
import test_platform_takeover as f

bot=f.appmod
media=bot._inbox_media

class WebhookMediaTests(unittest.TestCase):
    def setUp(self):
        f.reset_state()
        f.chdb.execute('DELETE FROM inbox_media')
        f.chdb.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT NOT NULL, mode TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        f.chdb.execute('DELETE FROM messages')
        self.phone='628700111019'
        self.counter=0

    def event(self,kind='image',event_id=None):
        self.counter+=1
        return {'id':event_id or f'media-{time.time_ns()}-{self.counter}', 'from':self.phone,
                'timestamp':str(int(time.time())), 'type':kind,
                kind:{'id':'12345678','mime_type':next(iter(media.TYPES[kind])), 'caption':'caption'}}

    def webhook(self,events):
        value={'metadata':{'phone_number_id':'kilas-global-123'},'messages':events}
        with patch.object(bot,'notify_owner_new_message',return_value=True), patch.object(bot,'call_claude',return_value='reply') as ai, patch.object(bot,'send_whatsapp_message',return_value=(True,None)) as send:
            result=f.client.post('/webhook',json={'entry':[{'changes':[{'value':value}]}]})
        return result,ai,send

    def test_all_media_persist_in_human_without_ai_or_send(self):
        f.platform_inbox_service.start_human_takeover(self.phone)
        events=[self.event(kind) for kind in media.TYPES]
        result,ai,send=self.webhook(events)
        self.assertEqual(result.status_code,200)
        self.assertTrue(result.json['human_takeover'])
        ai.assert_not_called();send.assert_not_called()
        rows=f.platform_inbox_service.get_thread(self.phone)
        self.assertEqual(len(rows),5)
        self.assertEqual({r['media']['message_type'] for r in rows},set(media.TYPES))
        self.assertEqual(f.platform_inbox_service.get_state(self.phone),'HUMAN_TAKEOVER')
        self.webhook(events)
        self.assertEqual(len(f.platform_inbox_service.get_thread(self.phone)),5)

    def test_image_ai_processing_updates_same_row_not_duplicate(self):
        event=self.event()
        # Use actual call_claude persistence entry through save_message_to_db, without an LLM call.
        def ai(number,text,**kwargs):
            bot.save_message_to_db(number,'customer','user','image caption context')
            return 'reply'
        with patch.object(bot,'download_whatsapp_media',return_value=('base64','image/png')), patch.object(bot,'call_claude',side_effect=ai), patch.object(bot,'notify_owner_new_message',return_value=True), patch.object(bot,'send_whatsapp_message',return_value=(True,None)), patch.object(bot,'send_typing_indicator'), patch.object(bot.time,'sleep'):
            result=f.client.post('/webhook',json={'entry':[{'changes':[{'value':{'metadata':{'phone_number_id':'kilas-global-123'},'messages':[event]}}]}]})
        self.assertEqual(result.status_code,200)
        rows=f.platform_inbox_service.get_thread(self.phone)
        inbound=[r for r in rows if r['role']=='user']
        self.assertEqual(len(inbound),1)
        self.assertEqual(inbound[0]['content'],'image caption context')
        self.assertEqual(inbound[0]['media']['message_type'],'image')

    def test_mixed_media_text_batch_does_not_reuse_media_row(self):
        f.platform_inbox_service.start_human_takeover(self.phone)
        image = self.event()
        text = {'id': 'text-' + str(time.time_ns()), 'from': self.phone,
                'type': 'text', 'text': {'body': 'separate text'}}
        result, ai, send = self.webhook([image, text])
        self.assertEqual(result.status_code, 200)
        row = f.platform_inbox_service.get_thread(self.phone)[0]
        self.assertEqual(row['content'], 'caption')
        self.assertEqual(row['media']['caption'], 'caption')
        ai.assert_not_called(); send.assert_not_called()

    def test_platform_upload_success_uses_platform_channel(self):
        from unittest.mock import Mock
        media.record(None, self.phone, self.event())
        f.platform_inbox_service.start_human_takeover(self.phone)
        def response(body):
            result = Mock(status_code=200)
            result.json.return_value = body
            result.__enter__ = Mock(return_value=result)
            result.__exit__ = Mock(return_value=False)
            return result
        with patch.object(bot, 'INTERNAL_SERVICE_SECRET', 'test-only'), patch.object(media.requests, 'post',
                side_effect=[response({'id':'123'}), response({'messages':[{'id':'outgoing-media'}]})]) as post:
            result = f.client.post('/internal/platform-inbox-media', headers={'X-Internal-Service-Secret':'test-only'},
                data={'customer_phone':self.phone, 'file':(io.BytesIO(b'%PDF-1.4'), 'a.pdf')})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(post.call_args_list[0].kwargs['headers']['Authorization'], 'Bearer ' + bot.WHATSAPP_ACCESS_TOKEN)
        self.assertIn('/' + bot.WHATSAPP_PHONE_NUMBER_ID + '/media', post.call_args_list[0].args[0])
        self.assertEqual(f.platform_inbox_service.get_thread(self.phone)[-1]['role'], 'assistant')

    def test_metadata_failure_before_dedupe_claim(self):
        with patch.object(media,'record',side_effect=RuntimeError('private')), patch.object(bot,'is_duplicate_event') as dedupe:
            response,_,_=self.webhook([self.event()])
        self.assertEqual(response.status_code,503)
        dedupe.assert_not_called()

    def test_platform_bridge_auth_and_scope(self):
        row=media.record(101,self.phone,self.event())
        with patch.object(bot,'INTERNAL_SERVICE_SECRET','test-only'), patch.object(media,'download') as download:
            self.assertEqual(f.client.get('/internal/platform-inbox-media/'+row['id']).status_code,403)
            self.assertEqual(f.client.get('/internal/platform-inbox-media/'+row['id'],headers={'X-Internal-Service-Secret':'test-only'}).status_code,404)
            download.assert_not_called()

    def test_platform_download_uses_explicit_platform_credentials(self):
        row=media.record(None,self.phone,self.event())
        with patch.object(bot,'INTERNAL_SERVICE_SECRET','test-only'), patch.object(media,'download',return_value=(io.BytesIO(b'png'),'image/png')) as download:
            result=f.client.get('/internal/platform-inbox-media/'+row['id'],headers={'X-Internal-Service-Secret':'test-only'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(download.call_args.args[1:],(bot.WHATSAPP_ACCESS_TOKEN,bot.WHATSAPP_PHONE_NUMBER_ID))

    def test_platform_send_bridge_checks_human_and_window(self):
        media.record(None,self.phone,self.event())
        with patch.object(bot,'INTERNAL_SERVICE_SECRET','test-only'), patch.object(media.requests,'post') as upstream:
            result=f.client.post('/internal/platform-inbox-media',headers={'X-Internal-Service-Secret':'test-only'},
                                 data={'customer_phone':self.phone,'file':(io.BytesIO(b'%PDF-1.4'),'a.pdf')})
            self.assertEqual(result.status_code,409)
            upstream.assert_not_called()

    def test_tenant_media_event_never_enters_platform_scope(self):
        event=self.event()
        with patch.object(bot,'ENABLE_MULTI_TENANT',True), patch.object(bot,'_resolve_tenant_or_unknown',return_value=(101,False)), patch.object(bot,'multi_tenant_blockers',return_value=[]), patch.object(bot,'_get_tenant_whatsapp_channel_safe',return_value={'phone_number_id':'tenant-101','access_token':'tenant-token'}), patch.object(bot,'_get_trusted_owner_phone_safe',return_value='628700111099'), patch.object(bot,'_get_conversation_mode_safe',return_value='HUMAN_TAKEOVER'), patch.object(bot,'notify_owner_new_message',return_value=True), patch.object(bot,'_tf_mark_activity_safe'), patch.object(bot,'call_claude') as ai:
            result=f.client.post('/webhook',json={'entry':[{'changes':[{'value':{'metadata':{'phone_number_id':'tenant-101'},'messages':[event]}}]}]})
        self.assertEqual(result.status_code,200)
        rows=f.chdb.query_all('SELECT scope_key FROM inbox_media')
        self.assertEqual([r['scope_key'] for r in rows],['tenant:101'])
        self.assertEqual(f.platform_inbox_service.get_thread(self.phone),[])
        ai.assert_not_called()

if __name__ == '__main__':unittest.main()
