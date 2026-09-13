"""Focused media persistence, authorization, rendering and bounded transports."""
import io
import unittest
from unittest.mock import patch, Mock
from datetime import datetime, timezone
from werkzeug.datastructures import FileStorage
import test_inbox_unification as f
import inbox_media_service as media


def response(body=None, data=b'file', mime='image/png', status=200):
    result = Mock(status_code=status, headers={'Content-Type':mime})
    result.json.return_value = body
    result.iter_content.return_value = [data]
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


class MediaTests(unittest.TestCase):
    def setUp(self):
        f.reset_db()
        self.user, self.biz = f._make_active_ai_admin_tenant('Media A', 'a@example.test')
        self.other_user, self.other = f._make_active_ai_admin_tenant('Media B', 'b@example.test')
        self.admin = f._make_admin()
        self.client = f.fresh_client()
        self.phone = '628700111010'

    def login(self, user):
        with self.client.session_transaction() as session:
            session['user_id'] = user

    def record(self, kind='image', biz=None, event='evt', mime=None):
        return media.record(biz, self.phone, {'id':event,'type':kind,
            'timestamp':int(datetime.now(timezone.utc).timestamp()),
            kind:{'id':'123456789','mime_type':mime or next(iter(media.TYPES[kind])),
                  'filename':'../../contoh.pdf','caption':'<script>caption</script>'}})

    def test_inbound_image_stored_and_rendered(self):
        row=self.record()
        self.login(self.admin['id'])
        page=self.client.get('/admin/inbox?customer='+self.phone)
        self.assertEqual(page.status_code,200)
        self.assertIn(('/admin/inbox/media/'+row['id']).encode(),page.data)
        self.assertIn(b'&lt;script&gt;caption&lt;/script&gt;',page.data)
        self.assertNotIn(b'123456789',page.data)

    def test_document_and_audio_and_video_and_sticker(self):
        self.login(self.user)
        for kind,tag in [('document',b'Unduh contoh.pdf'),('audio',b'<audio'),('video',b'<video'),('sticker',b'<img')]:
            with self.subTest(kind=kind):
                row=self.record(kind,self.biz,event=kind)
                page=self.client.get(f'/business/{self.biz}/inbox?customer='+self.phone)
                self.assertEqual(page.status_code,200)
                self.assertIn(tag,page.data)
                self.assertIn(row['id'].encode(),page.data)

    def test_persistence_dedupes_per_scope_and_survives_history(self):
        a=self.record(biz=self.biz)
        again=self.record(biz=self.biz)
        b=self.record(biz=self.other)
        self.assertEqual(a['id'],again['id'])
        self.assertNotEqual(a['id'],b['id'])
        self.assertEqual(len(f.inbox_service.get_thread(self.biz,self.phone)),1)
        self.assertNotIn(b['id'],str(f.inbox_service.get_thread(self.biz,self.phone)))
        self.assertTrue(f.inbox_service.freeform_window_status(self.biz,self.phone)['allowed'])
        f.db.init_schema()  # additive migration is idempotent
        self.assertEqual(media.get(a['id'],self.biz)['id'],a['id'])

    def test_admin_can_download_platform(self):
        row=self.record(mime='image/png')
        self.login(self.admin['id'])
        with patch.object(media,'platform_download',return_value=(io.BytesIO(b'png'),'image/png')):
            result=self.client.get('/admin/inbox/media/'+row['id'])
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.data,b'png')
        self.assertEqual(result.headers['Cache-Control'],'private, no-store')

    def test_tenant_download_uses_own_credentials(self):
        row=self.record(biz=self.biz)
        self.login(self.user)
        with patch.object(media,'download',return_value=(io.BytesIO(b'png'),'image/png')) as download:
            result=self.client.get(f'/business/{self.biz}/inbox/media/'+row['id'])
        self.assertEqual(result.status_code,200)
        self.assertEqual(download.call_args.args[1],f'secret-token-{self.biz}')
        self.assertEqual(download.call_args.args[2],f'pnid-{self.biz}')

    def test_cross_tenant_and_platform_access_denied(self):
        platform=self.record()
        row=self.record(biz=self.other)
        self.login(self.user)
        with patch.object(media,'download') as download, patch.object(media,'platform_download') as bridge:
            for url in [f'/business/{self.other}/inbox/media/'+row['id'],
                        f'/business/{self.biz}/inbox/media/'+row['id'],
                        f'/business/{self.biz}/inbox/media/'+platform['id'],
                        '/admin/inbox/media/'+platform['id']]:
                self.assertIn(self.client.get(url).status_code,(403,404))
            download.assert_not_called();bridge.assert_not_called()
        self.login(self.admin['id'])
        self.assertEqual(self.client.get('/admin/inbox/media/'+row['id']).status_code,404)

    def test_download_failure_is_safe(self):
        row=self.record()
        self.login(self.admin['id'])
        with patch.object(media,'platform_download',side_effect=RuntimeError('private-token-url')):
            result=self.client.get('/admin/inbox/media/'+row['id'])
        self.assertEqual(result.status_code,404)
        self.assertEqual(result.data,b'Media tidak tersedia')

    def test_download_uses_fresh_url_no_redirect_and_size_bound(self):
        row=self.record(mime='image/png')
        meta=response({'mime_type':'image/png','url':'https://lookaside.fbsbx.com/media'})
        with patch.object(media.requests,'get',side_effect=[meta,response(data=b'png')]) as get:
            stream,mime=media.download(row,'test-token','pnid')
            self.assertEqual(stream.read(),b'png');stream.close()
            for call in get.call_args_list:
                self.assertFalse(call.kwargs['allow_redirects'])
            self.assertEqual(get.call_args_list[0].kwargs['params'],{'phone_number_id':'pnid'})
        bad=response(data=b'x'*(1024*1024))
        with patch.object(media,'MAX_BYTES',10):
            with self.assertRaises(ValueError):media._read(bad)

    def test_ssrf_and_active_mime_rejected_before_download(self):
        row=self.record()
        for url in ['http://lookaside.fbsbx.com/a','https://127.0.0.1/a','https://lookaside.fbsbx.com.evil.test/a',
                    'https://user@lookaside.fbsbx.com/a','https://lookaside.fbsbx.com:444/a']:
            with patch.object(media.requests,'get',return_value=response({'mime_type':'image/png','url':url})) as get:
                with self.assertRaises(ValueError):media.download(row,'test-token','pnid')
                self.assertEqual(get.call_count,1)
        with patch.object(media.requests,'get',return_value=response({'mime_type':'text/html','url':'https://lookaside.fbsbx.com/a'})):
            with self.assertRaises(ValueError):media.download(row,'test-token','pnid')

    def test_text_history_unchanged(self):
        f._seed_message(self.biz,self.phone,'user','Teks biasa')
        rows=f.inbox_service.get_thread(self.biz,self.phone)
        self.assertEqual(rows[0]['content'],'Teks biasa')
        self.assertNotIn('media',rows[0])
        self.login(self.user)
        self.assertIn(b'Teks biasa',self.client.get(f'/business/{self.biz}/inbox?customer='+self.phone).data)

    def upload(self):
        return FileStorage(stream=io.BytesIO(b'%PDF-1.4\ntest'),filename='../../test.pdf')

    def test_outbound_pdf_acceptance_and_history(self):
        self.record(biz=self.biz)
        f.wa_takeover_service.start_human_takeover(self.biz,self.phone,self.user)
        channel,_=f.inbox_service._tenant_channel(self.biz)
        with patch.object(media.requests,'post',side_effect=[response({'id':'112233'}),response({'messages':[{'id':'sent-1'}]})]) as post:
            ok,reason=media.send_upload(self.biz,self.phone,self.upload(),'Caption',channel,
                                       lambda: media.human_window_allowed(self.biz,self.phone))
        self.assertTrue(ok)
        self.assertEqual(post.call_args_list[1].kwargs['json']['document']['filename'],'test.pdf')
        self.assertEqual(post.call_args_list[0].kwargs['headers']['Authorization'],'Bearer '+channel['access_token'])
        rows=f.inbox_service.get_thread(self.biz,self.phone)
        self.assertEqual(rows[-1]['role'],'assistant')
        self.assertEqual(rows[-1]['media']['message_type'],'document')

    def test_no_upload_outside_human_or_window(self):
        self.record(biz=self.biz)
        channel,_=f.inbox_service._tenant_channel(self.biz)
        with patch.object(media.requests,'post') as post:
            ok,_=media.send_upload(self.biz,self.phone,self.upload(),'',channel,lambda:media.human_window_allowed(self.biz,self.phone))
            self.assertFalse(ok)
            f.wa_takeover_service.start_human_takeover(self.biz,self.phone,self.user)
            f.db.execute("UPDATE messages SET created_at = '2000-01-01 00:00:00'")
            ok,_=media.send_upload(self.biz,self.phone,self.upload(),'',channel,lambda:media.human_window_allowed(self.biz,self.phone))
            self.assertFalse(ok);post.assert_not_called()

    def test_recheck_before_send_and_no_retry_on_error(self):
        channel={'access_token':'test-token','phone_number_id':'pnid'}
        with patch.object(media.requests,'post',return_value=response({'id':'123'})) as post:
            ok,_=media.send_upload(None,self.phone,self.upload(),'',channel,Mock(side_effect=[True,False]))
            self.assertFalse(ok);self.assertEqual(post.call_count,1)
        with patch.object(media.requests,'post',side_effect=[response({'id':'123'}),response({'error':{'message':'private'}},status=429)]) as post:
            ok,reason=media.send_upload(None,self.phone,self.upload(),'',channel,lambda:True)
            self.assertFalse(ok);self.assertEqual(reason,'media_send_failed');self.assertEqual(post.call_count,2)

    def test_upload_allowlist_and_limits(self):
        from PIL import Image
        blob=io.BytesIO();Image.new('RGB',(2,2)).save(blob,format='PNG');blob.seek(0)
        self.assertEqual(media.validate_upload(FileStorage(stream=blob,filename='x.png'))[1],'image')
        for data in [b'<script>evil</script>',b'x'*(10*1024*1024+1)]:
            with self.assertRaises(ValueError):media.validate_upload(FileStorage(stream=io.BytesIO(data),filename='x.png'))

    def test_platform_upload_uses_bridge_not_meta_credentials(self):
        self.record()
        f.platform_inbox_service.start_human_takeover(self.phone)
        with patch.object(f.platform_inbox_service, '_bot_platform_reply_url', return_value='https://bot.example.test/internal/platform-cs-reply'), patch.dict(f.os.environ, {'INTERNAL_SERVICE_SECRET':'test-only'}), patch.object(media.requests,'post',return_value=response({'status':'ok'})) as post:
            ok,reason=media.platform_send(self.phone,self.upload(),'Caption')
        self.assertTrue(ok)
        self.assertEqual(post.call_args.args[0],'https://bot.example.test/internal/platform-inbox-media')
        self.assertEqual(post.call_args.kwargs['headers'],{'X-Internal-Service-Secret':'test-only'})
        self.assertFalse(post.call_args.kwargs['allow_redirects'])

    def test_graph_version_default_and_override_for_all_media_operations(self):
        row = self.record(mime='image/png')
        for configured, expected in [(None, 'v21.0'), ('', 'v21.0'), (' v22.0 ', 'v22.0')]:
            with self.subTest(configured=configured), patch.dict(f.os.environ):
                f.os.environ.pop('META_GRAPH_API_VERSION', None)
                if configured is not None:
                    f.os.environ['META_GRAPH_API_VERSION'] = configured
                base = 'https://graph.facebook.com/' + expected
                with patch.object(media.requests, 'get', side_effect=[
                        response({'mime_type':'image/png','url':'https://lookaside.fbsbx.com/media'}),
                        response(data=b'png')]) as get:
                    stream, _ = media.download(row, 'test-token', 'pnid')
                    stream.close()
                self.assertEqual(get.call_args_list[0].args[0], base + '/' + row['media_id'])
                with patch.object(media.requests, 'post', side_effect=[
                        response({'id':'112233'}), response({'messages':[{'id':'sent-' + expected}]})]) as post:
                    ok, _ = media.send_upload(None, self.phone, self.upload(), '',
                        {'access_token':'test-token','phone_number_id':'pnid'}, lambda:True)
                self.assertTrue(ok)
                self.assertEqual([call.args[0] for call in post.call_args_list],
                                 [base + '/pnid/media', base + '/pnid/messages'])

    def test_upload_requires_csrf(self):
        self.record(biz=self.biz)
        self.login(self.user)
        with patch.dict(f.FLASK_APP.config, {'CLIENT_HUB_FORCE_CSRF_IN_TESTS':True}), patch.object(media,'send_upload') as send:
            result=self.client.post(f'/business/{self.biz}/inbox/media', data={'customer_phone':self.phone,'file':(io.BytesIO(b'%PDF-1.4'),'a.pdf')})
        self.assertEqual(result.status_code,400)
        send.assert_not_called()

    def test_tenant_cannot_post_other_business(self):
        self.login(self.user)
        with patch.object(media,'send_upload') as send:
            result=self.client.post(f'/business/{self.other}/inbox/media',data={'customer_phone':self.phone,'file':(io.BytesIO(b'%PDF-1.4'),'test.pdf')})
        self.assertEqual(result.status_code,404);send.assert_not_called()

if __name__ == '__main__':unittest.main()
