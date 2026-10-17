"""Last explicit selection survives new-chat/reload without crossing owners."""
import unittest
from unittest.mock import patch
import test_kilas_chat_models as fixture
from kilas_ai import chat_models,image_models,model_preferences,store,agent_store


class PreferenceTests(unittest.TestCase):
    client=fixture.RouteTests.client

    def setUp(self):
        fixture.RouteTests.setUp(self)
        p=patch.object(image_models,'check',side_effect=lambda m:{**image_models.spec(m),'available':True,'status':'verified'})
        p.start();self.addCleanup(p.stop)

    def choose(self,kind,model,**scope):
        return self.client().post('/kilas-ai/chat/'+('model' if kind=='chat' else 'image-model'),json={'model':model,**scope},headers={'X-CSRF-Token':'work-csrf'})

    def catalog(self,kind='chat',client=None,**scope):
        return (client or self.client()).get('/kilas-ai/chat/'+('models' if kind=='chat' else 'image-models'),query_string=scope)

    def test_unsent_home_choice_survives_new_authenticated_sessions_and_reopening(self):
        for kind,model in [('chat','claude-sonnet-5-5'),('image','gemini-3-pro-image')]:
            self.assertEqual(self.choose(kind,model,surface='thread',conversation_id=None).status_code,200)
            for _ in range(2):
                self.assertEqual(self.catalog(kind).json['selected'],model)
            self.assertEqual(model_preferences.get(self.owner,kind),model)
        self.assertEqual(self.catalog().json['selected'],'claude-sonnet-5-5')

    def test_new_chats_snapshot_both_choices_existing_chats_keep_their_models(self):
        for kind,model in [('chat','claude-sonnet-5-5'),('image','gpt-image-1-mini')]:self.assertEqual(self.choose(kind,model).status_code,200)
        thread=store.create_thread(self.owner);conversation=agent_store.new_conversation(self.owner)
        for surface,ident in [('thread',thread),('conversation',conversation)]:
            self.assertEqual(chat_models.preference(self.owner,surface,ident),'claude-sonnet-5-5')
            self.assertEqual(image_models.preference(self.owner,surface,ident),'gpt-image-1-mini')
        self.choose('chat','gemini-4-argon');self.choose('image','gemini-3-pro-image')
        for surface,ident in [('thread',thread),('conversation',conversation)]:
            self.assertEqual(self.catalog(surface=surface,conversation_id=ident).json['selected'],'claude-sonnet-5-5')
            self.assertEqual(self.catalog('image',surface=surface,conversation_id=ident).json['selected'],'gpt-image-1-mini')
        created=self.client().post('/kilas-ai/threads',json={'first_message':'Synthetic unsent chat'},headers={'X-CSRF-Token':'work-csrf'})
        self.assertEqual(created.status_code,201)
        self.assertEqual(chat_models.preference(self.owner,'thread',created.json['thread_id']),'gemini-4-argon')
        created=self.client().post('/kilas-ai/agent/conversations',data={'csrf_token':'work-csrf'})
        self.assertEqual(created.status_code,303)
        ident=int(created.location.split('conversation=')[1])
        self.assertEqual(image_models.preference(self.owner,'conversation',ident),'gemini-3-pro-image')

    def test_explicit_existing_chat_selection_updates_default_without_rewriting_others(self):
        self.choose('chat','gpt-6-luna',surface='thread',conversation_id=self.thread)
        self.choose('image','gpt-image-1-mini',surface='conversation',conversation_id=self.conversation)
        self.assertEqual(self.catalog().json['selected'],'gpt-6-luna')
        self.assertEqual(self.catalog('image').json['selected'],'gpt-image-1-mini')
        self.assertEqual(self.catalog(surface='thread',conversation_id=self.thread).json['selected'],'gpt-6-luna')
        self.assertEqual(self.catalog(surface='conversation',conversation_id=self.conversation).json['selected'],'gpt-6.1-sol')

    def test_account_isolation_csrf_and_reserved_row_cannot_be_addressed_as_chat(self):
        self.choose('chat','claude-opus-5-5',user_id=self.other)
        self.choose('image','gemini-3-pro-image',user_id=self.other)
        self.assertEqual(self.catalog(client=self.client(self.other)).json['selected'],'gpt-6.1-sol')
        self.assertIsNone(model_preferences.get(self.other,'image'))
        for path in ('/kilas-ai/chat/model','/kilas-ai/chat/image-model'):
            self.assertNotEqual(self.client().post(path,json={'model':'gpt-6-luna'}).status_code,200)
        self.assertEqual(self.choose('chat','gpt-6-luna',surface='thread',conversation_id=0).status_code,404)
        self.assertEqual(self.choose('chat','gpt-6-luna',surface='thread',conversation_id=store.create_thread(self.other)).status_code,404)
        self.assertEqual(self.catalog(surface='thread',conversation_id=0).status_code,404)

    def test_unavailable_saved_choice_remains_explicit_on_home_and_new_chat(self):
        self.choose('chat','gpt-6-luna');self.choose('image','gemini-3-pro-image')
        def unavailable(model):return {**fixture.available(model),'available':model!='gpt-6-luna','status':'access_unavailable' if model=='gpt-6-luna' else 'verified'}
        def unavailable_image(model):return {**image_models.spec(model),'available':model!='gemini-3-pro-image','status':'access_unavailable'}
        with patch.object(chat_models,'check',side_effect=unavailable),patch.object(image_models,'check',side_effect=unavailable_image):
            self.assertEqual(self.catalog().json['selected'],'gpt-6-luna')
            data=self.catalog('image').json
            self.assertEqual(data['selected'],'gemini-3-pro-image');self.assertFalse(data['selected_info']['available'])
            self.assertNotIn('gemini-3-pro-image',[m['id'] for m in data['models']])
            ident=store.create_thread(self.owner)
            self.assertEqual(self.catalog(surface='thread',conversation_id=ident).json['selected'],'gpt-6-luna')
            with self.assertRaises(chat_models.SelectionError):chat_models.request_model(self.owner,'thread',ident)
            self.assertEqual(self.choose('chat','gpt-6-luna').status_code,400)
            self.assertEqual(self.choose('image','gemini-3-pro-image').status_code,400)
            self.assertEqual(model_preferences.get(self.owner,'chat'),'gpt-6-luna')


if __name__=='__main__':unittest.main()
