"""Private durable upload cards; no model/routing/schema changes."""
import io
import unittest
from unittest.mock import patch
from PIL import Image
import test_kilas_ai_unified as fixture
from kilas_ai import agent_attachments, agent_store, store, pdf


class CleanupTests(unittest.TestCase):
    setUp = fixture.UnifiedTests.setUp
    client = fixture.UnifiedTests.client
    submit = fixture.UnifiedTests.submit

    def uploads(self):
        raw = io.BytesIO()
        Image.new('RGB', (24,24), 'orange').save(raw, 'PNG')
        document = pdf.render('# Fakta\n\nKilas adalah nama yang dikonfirmasi untuk dokumen QA.')
        return [(io.BytesIO(raw.getvalue()), 'photo.png', 'image/png'),
                (io.BytesIO(document['content']), 'facts.pdf', 'application/pdf')]

    def send_files(self, **extra):
        with patch.object(fixture.providers, 'stream', side_effect=lambda *a,**k:fixture.answer()):
            return self.submit('Tolong jelaskan lampiran ini', source_files=self.uploads(), **extra)

    def test_sent_uploads_survive_new_messages_reload_reopen_and_new_chat(self):
        self.assertEqual(self.send_files().status_code, 303)
        origin = agent_store.messages(self.owner, conversation_id=self.conversation)[0]['id']
        files = agent_attachments.listing(self.owner, self.conversation, [origin])[origin]
        self.assertEqual([f['filename'] for f in files], ['photo.png','facts.pdf'])
        with patch.object(fixture.providers,'stream',side_effect=lambda *a,**k:fixture.answer()):
            self.submit('Terima kasih')
        self.client().post('/kilas-ai/agent/conversations',data={'csrf_token':'work-csrf'})
        for _ in range(2):
            html = self.client().get(f'/kilas-ai/agent?conversation={self.conversation}').text
            self.assertIn(f'data-message-id="{origin}"', html)
            self.assertEqual(html.count('class="work-attachment-card work-sent-file"'), 2)
            self.assertLess(html.index('photo.png'), html.index('Terima kasih'))
        self.assertEqual(len(agent_store.messages(self.owner,conversation_id=self.conversation)), 4)
        self.assertEqual(fixture.UnifiedTests.jobs.list_jobs(self.owner), [])

    def test_downloads_keep_original_bytes_and_deny_other_owner(self):
        self.send_files()
        origin = agent_store.messages(self.owner,conversation_id=self.conversation)[0]['id']
        for item in agent_attachments.listing(self.owner,self.conversation,[origin])[origin]:
            path = f"/kilas-ai/threads/{item['thread_id']}/attachments/{item['id']}"
            response = self.client().get(path+'?inline=1')
            self.assertEqual(response.status_code,200)
            stored = store.attachment(self.owner,item['thread_id'],item['id'])
            self.assertEqual(response.data,bytes(stored['content']))
            self.assertEqual(response.headers['Cache-Control'],'private, no-store')
            self.assertEqual(self.client(self.other).get(path).status_code,404)
        self.assertEqual(agent_attachments.listing(self.other,self.conversation,[origin]),{})
        other_chat = agent_store.new_conversation(self.owner)
        self.assertEqual(agent_attachments.listing(self.owner,other_chat,[origin]),{})

    def test_adapter_does_not_add_fake_visible_history_or_change_legacy_data(self):
        legacy = store.create_thread(self.owner)
        old = store.append_user_once(self.owner,legacy,'Pesan asli','SMART','original-key')[0]
        self.send_files()
        self.assertEqual([r['id'] for r in store.list_threads(self.owner)],[legacy])
        self.assertEqual(store.messages(self.owner,legacy)[0]['id'],old)
        self.assertEqual(store.messages(self.owner,legacy)[0]['content'],'Pesan asli')
        self.assertEqual(len(agent_store.recent_conversations(self.owner)),1)

    def test_duplicate_submission_never_duplicates_uploads(self):
        key = 'cleanup-operation-12345'
        self.assertEqual(self.send_files(operation_key=key).status_code,303)
        self.assertEqual(self.send_files(operation_key=key).status_code,409)
        origin = agent_store.messages(self.owner,conversation_id=self.conversation)[0]['id']
        self.assertEqual(len(agent_attachments.listing(self.owner,self.conversation,[origin])[origin]),2)

    def test_old_stored_image_input_is_displayed_without_rewriting_history(self):
        origin = agent_store.append(self.owner,'user','Ubah foto ini',self.conversation)
        raw = self.uploads()[0][0].getvalue()
        job = fixture.UnifiedTests.jobs.create(self.owner,'Ubah foto ini',conversation_id=self.conversation,
            origin_message_id=origin,image_input={'filename':'photo.png','mime_type':'image/png','content':raw})
        items = agent_attachments.listing(self.owner,self.conversation,[origin])[origin]
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['job_id'],job)
        self.assertIn('work-sent-file',self.client().get('/kilas-ai/agent').text)
        self.assertEqual(len(agent_store.messages(self.owner,conversation_id=self.conversation)),1)
        self.assertEqual(store.list_threads(self.owner),[])

    def test_attachment_failure_rolls_back_message_and_storage_together(self):
        before = agent_store.messages(self.owner,conversation_id=self.conversation)
        with patch.object(agent_attachments,'save',side_effect=RuntimeError('storage failure')):
            with self.assertRaises(RuntimeError):
                agent_store.append(self.owner,'user','Upload gagal',self.conversation,attachments=[{}])
        self.assertEqual(agent_store.messages(self.owner,conversation_id=self.conversation),before)

    def test_sidebar_removed_but_background_architecture_preserved(self):
        job = fixture.UnifiedTests.jobs.create(self.owner,'Pekerjaan terjadwal',conversation_id=self.conversation)
        html = self.client().get('/kilas-ai/agent').text
        self.assertNotIn('data-active-count',html)
        self.assertNotIn('data-notification-count',html)
        self.assertNotIn('view=tasks',html)
        self.assertNotIn('view=notifications',html)
        self.assertIn(f'data-job-id="{job}"',html)
        self.assertEqual(fixture.UnifiedTests.jobs.get(self.owner,job)['status'],'PLANNING')


if __name__ == '__main__':
    unittest.main()
