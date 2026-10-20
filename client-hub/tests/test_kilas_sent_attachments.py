"""Owned sent-attachment presentation and repeat delivery on synthetic fixtures."""
import io
import unittest
from html.parser import HTMLParser
from unittest.mock import patch
from PIL import Image
import test_kilas_model_preferences as fixture
from kilas_ai import store,providers,usage,agent_store,agent_attachments


class SentAttachmentTests(unittest.TestCase):
    setUp=fixture.PreferenceTests.setUp
    client=fixture.PreferenceTests.client

    def image(self):
        out=io.BytesIO();Image.new('RGB',(12,8),'#edc6a7').save(out,'PNG');return out.getvalue()

    def send(self,thread,key='sent_attachments_000001',fail=False):
        self.last_dispatches=0
        def answer(*a,**k):
            self.last_dispatches+=1
            if fail:raise providers.ProviderError('synthetic_failure')
            yield {'type':'provider','provider':'openai','model':'gpt-6-luna'}
            yield {'type':'delta','text':'Synthetic stored attachment answer.'}
            yield {'type':'finish','reason':'stop'}
        with patch.object(usage,'attachment_plan',return_value='PRO'),patch.object(providers,'stream',side_effect=answer):
            response=self.client().post(f'/kilas-ai/threads/{thread}/send',data={
                'csrf_token':'work-csrf','content':'Keep the user caption.','operation_key':key,'selected_model':'gpt-6-luna',
                'attachments':[(io.BytesIO(self.image()),'12345.png','image/png'),
                               (io.BytesIO(self.image()),'67890.png','image/png'),
                               (io.BytesIO(b'Synthetic note'),'note.txt','text/plain')]},headers={'X-CSRF-Token':'work-csrf'})
            response.get_data();return response

    def test_saved_user_images_are_image_only_and_files_have_private_download_cards(self):
        thread=store.create_thread(self.owner);self.assertEqual(self.send(thread).status_code,200)
        client=self.client();client.set_cookie('kilas_language','en');page=client.get(f'/kilas-ai/threads/{thread}')
        self.assertEqual(page.status_code,200)
        self.assertIn('chat-upload-image',page.text);self.assertIn('Keep the user caption.',page.text)
        self.assertNotIn('12345.png',page.text);self.assertNotIn('67890.png',page.text)
        self.assertIn('note.txt',page.text);self.assertIn('ai-file-card',page.text)
        self.assertEqual(len(store.attachment_list(self.owner,thread)),3)
        for item in store.attachment_list(self.owner,thread):
            url=f'/kilas-ai/threads/{thread}/attachments/{item["id"]}?inline=1'
            response=client.get(url);self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['Cache-Control'],'private, no-store')
            self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
            self.assertEqual(self.client(self.other).get(url).status_code,404)

    def test_same_operation_does_not_store_or_dispatch_uploaded_files_twice(self):
        thread=store.create_thread(self.owner);self.assertEqual(self.send(thread).status_code,200)
        self.assertEqual(self.last_dispatches,1)
        self.assertEqual(self.send(thread).status_code,200)
        self.assertEqual(self.last_dispatches,0)
        self.assertEqual(len(store.attachment_list(self.owner,thread)),3)
        self.assertEqual(len([m for m in store.messages(self.owner,thread) if m['role']=='user']),1)

    def test_provider_failure_keeps_accepted_user_uploads_in_history(self):
        thread=store.create_thread(self.owner);self.assertEqual(self.send(thread,fail=True).status_code,200)
        self.assertEqual(len(store.attachment_list(self.owner,thread)),3)
        page=self.client().get(f'/kilas-ai/threads/{thread}').text
        self.assertIn('chat-upload-image',page);self.assertIn('note.txt',page)
        self.assertNotIn('12345.png',page)

    def test_pdf_card_keeps_existing_inline_open_and_private_download(self):
        thread=store.create_thread(self.owner)
        ident,_=store.append_user_once(self.owner,thread,'Read PDF','FAST','pdf_card_synthetic_001')
        store.save_attachments(self.owner,thread,ident,[{'filename':'report.pdf','mime_type':'application/pdf','byte_size':4,'content':b'%PDF','extracted_text':'synthetic'}])
        client=self.client();client.set_cookie('kilas_language','en')
        html=client.get(f'/kilas-ai/threads/{thread}').text
        item=store.attachment_list(self.owner,thread)[0]
        url=f'/kilas-ai/threads/{thread}/attachments/{item["id"]}'
        self.assertIn(f'href="{url}?inline=1"',html)
        self.assertIn(f'href="{url}"',html)
        self.assertEqual(client.get(url+'?inline=1').headers['Content-Security-Policy'],"default-src 'none'; sandbox")

    def test_document_filename_is_escaped_in_history(self):
        name='<img src=x onerror=alert(1)>.txt'
        prepared=[{'filename':name,'mime_type':'text/plain','byte_size':4,'content':b'note','extracted_text':'note'}]
        agent_store.append(self.owner,'user','Caption',self.conversation,attachments=prepared)
        page=self.client().get(f'/kilas-ai/agent?conversation={self.conversation}').text
        self.assertNotIn('<img src=x',page)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;.txt',page)

    def test_agent_history_projects_existing_private_uploads_without_image_filename(self):
        prepared=[{'filename':'agent-987.png','mime_type':'image/png','byte_size':len(self.image()),'content':self.image(),'extracted_text':None},
                  {'filename':'safe-note.txt','mime_type':'text/plain','byte_size':4,'content':b'note','extracted_text':'note'}]
        message=agent_store.append(self.owner,'user','Original caption',self.conversation,attachments=prepared)
        listing=agent_attachments.listing(self.owner,self.conversation,[message]);self.assertEqual(len(listing[message]),2)
        page=self.client().get(f'/kilas-ai/agent?conversation={self.conversation}').text
        self.assertIn('Original caption',page);self.assertIn('safe-note.txt',page);self.assertNotIn('agent-987.png',page)


if __name__=='__main__':unittest.main()
