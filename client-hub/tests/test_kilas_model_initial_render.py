"""Selected labels are already correct in HTML; cache-only defaults do no IO."""
import hashlib
import os
import unittest
from html.parser import HTMLParser
from time import monotonic
from unittest.mock import patch
import test_kilas_model_preferences as preferences
from kilas_ai import chat_models,image_models,model_preferences,store,agent_store


class Labels(HTMLParser):
    def __init__(self,text):
        super().__init__();self.kind=None;self.active=None;self.labels={};self.icons={};self.warnings={};self.feed(text)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'data-model-kind' in attrs:self.kind=attrs['data-model-kind']
        if 'data-model-label' in attrs:self.active=self.kind;self.labels[self.kind]=''
        if 'data-selected-provider-icon' in attrs:self.icons[self.kind]=attrs
        if 'data-model-warning' in attrs:self.warnings[attrs['data-model-warning']]=attrs
    def handle_data(self,value):
        if self.active:self.labels[self.active]+=value
    def handle_endtag(self,tag):
        if tag=='span':self.active=None


class InitialModelRenderTests(preferences.PreferenceTests):
    # Include the existing preference lifecycle regressions alongside initial HTML.
    def page(self,path='/products/start',locale='en'):
        client=self.client();client.set_cookie('kilas_language',locale)
        with patch.object(chat_models.requests,'get',side_effect=AssertionError('Provider read forbidden')):
            response=client.get(path)
        self.assertEqual(response.status_code,200,response.text[:300]);return Labels(response.text)

    def test_saved_account_names_and_icons_exist_before_any_javascript(self):
        self.choose('chat','claude-opus-5-5');self.choose('image','gemini-3-pro-image')
        page=self.page();self.assertEqual(page.labels,{'chat':'Claude Opus 5.5','image':'Gemini 3 Pro Image'})
        self.assertEqual(page.icons['chat']['data-provider'],'anthropic');self.assertIn('claude.svg',page.icons['chat']['src'])
        self.assertEqual(page.icons['image']['data-provider'],'google');self.assertNotIn('hidden',page.icons['image'])

    def test_owned_conversations_keep_their_choice_instead_of_later_account_default(self):
        self.choose('chat','gpt-6-luna');self.choose('image','gpt-image-1-mini')
        thread=store.create_thread(self.owner);conversation=agent_store.new_conversation(self.owner)
        self.choose('chat','claude-opus-5-5');self.choose('image','gemini-3-pro-image')
        for path in (f'/kilas-ai/threads/{thread}',f'/kilas-ai/agent?conversation={conversation}'):
            self.assertEqual(self.page(path).labels,{'chat':'GPT-6 Luna','image':'GPT Image 1 Mini'})
        self.assertEqual(self.page().labels,{'chat':'Claude Opus 5.5','image':'Gemini 3 Pro Image'})

    def test_existing_chat_without_snapshot_does_not_inherit_a_later_default(self):
        self.choose('chat','claude-opus-5-5');self.choose('image','gemini-3-pro-image')
        import db
        for table in model_preferences.TABLES.values():db.execute('DELETE FROM '+table+' WHERE user_id=? AND surface=? AND conversation_id=?',(self.owner,'thread',self.thread))
        with patch.object(chat_models,'catalog',return_value=None),patch.object(image_models,'catalog',return_value=None):
            page=self.page(f'/kilas-ai/threads/{self.thread}')
        self.assertEqual(page.labels,{'chat':'Loading models…','image':'Loading models…'})

    def test_unavailable_saved_choice_keeps_name_and_initial_warning_without_fallback(self):
        self.choose('chat','gpt-6-luna');self.choose('image','gemini-3-pro-image')
        with patch.object(chat_models,'cached_metadata',side_effect=lambda m:{**chat_models.spec(m),'available':False}),patch.object(image_models,'cached_metadata',side_effect=lambda m:{**image_models.spec(m),'available':False}):
            page=self.page()
        self.assertEqual(page.labels,{'chat':'GPT-6 Luna','image':'Gemini 3 Pro Image'})
        for warning in page.warnings.values():self.assertNotIn('hidden',warning)
        self.assertEqual(model_preferences.get(self.owner,'image'),'gemini-3-pro-image')

    def test_cold_cache_loading_is_localized_and_never_guesses_an_available_default(self):
        for locale,label in (('id','Memuat model…'),('en','Loading models…'),('es','Cargando modelos…'),('zh','正在加载模型…')):
            with patch.object(chat_models,'_cache',{}),patch.object(image_models,'_cache',{}):
                self.assertEqual(self.page(locale=locale).labels,{'chat':label,'image':label})

    def test_complete_fresh_cache_uses_exact_catalog_default_and_checks_no_provider(self):
        def rows(module):
            return {m:{**module.spec(m),'available':True,'status':'verified','at':monotonic(),'fingerprint':hashlib.sha256(os.environ.get(chat_models.KEYS[module.spec(m)['provider']],'').strip().encode()).digest()} for m in module.CATALOG}
        with patch.object(chat_models,'_cache',rows(chat_models)),patch.object(image_models,'_cache',rows(image_models)):
            expected={'chat':chat_models.spec(chat_models.catalog(cache_only=True)['default'])['name'],'image':image_models.spec(image_models.catalog(cache_only=True)['default'])['name']}
            self.assertEqual(self.page().labels,expected)
        with patch.object(chat_models,'_cache',rows(chat_models)),patch.dict(os.environ,{'OPENAI_API_KEY':'changed-synthetic-key'}):
            self.assertIsNone(chat_models.catalog(cache_only=True))

    def test_foreign_saved_chat_still_denies_access(self):
        foreign=store.create_thread(self.other)
        self.assertEqual(self.client().get(f'/kilas-ai/threads/{foreign}').status_code,404)


if __name__=='__main__':unittest.main()
