"""App locale contracts: actual cookie/CSRF/SSE, mocked providers, opaque content."""
import json
import re
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
import test_kilas_copilot as fixture
import ui_i18n
from kilas_ai import copilot


class CopilotLocaleTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.CopilotTests();self.case.setUp()
        self.app=self.case.app;self.client=self.case.client

    def test_default_supported_locales_and_invalid_cookie_fallback(self):
        self.client.delete_cookie('kilas_language')
        page=self.client.get('/kilas-ai')
        self.assertIn('<html lang="en">',page.text)
        self.assertIn('Automatic conversation language',page.text)
        self.assertNotIn('>Dengarkan<',page.text)
        expected={'en':('Show translation','Casual','New session','Indonesian'),
                  'id':('Tampilkan terjemahan','Santai','Sesi baru','Bahasa Indonesia'),
                  'es':('Mostrar traducción','Informal','Nueva sesión','indonesio'),
                  'zh':('显示翻译','随和','新会话','印度尼西亚语')}
        for code,labels in expected.items():
            self.client.set_cookie('kilas_language',code)
            page=self.client.get('/kilas-ai')
            self.assertIn(f'<html lang="{code}">',page.text)
            for label in labels:self.assertIn(label,page.text)
            self.assertIn('<option value="id" selected>',page.text)
        self.client.set_cookie('kilas_language','unsupported')
        self.assertIn('<html lang="en">',self.client.get('/kilas-ai').text)
        self.assertEqual(tuple(ui_i18n.LANGUAGES),('id','en','es','zh'))

    def test_apply_csrf_cookie_reload_new_page_and_open_redirect_guard(self):
        self.assertEqual(self.client.post('/language',data={'language':'en'}).status_code,400)
        for code in ('en','id'):
            response=self.client.post('/language',data={'language':code,'next':f'/kilas-ai/copilot/sessions/{self.case.ident}','csrf_token':'copilot-csrf'})
            self.assertEqual(response.status_code,303)
            self.assertIn('HttpOnly',response.headers['Set-Cookie'])
            self.assertIn('SameSite=Lax',response.headers['Set-Cookie'])
            for path in (response.location,'/kilas-ai','/kilas-translator?mode=voiceover','/kilas-translator/live?classic=1'):
                page=self.client.get(path)
                self.assertEqual(page.status_code,200)
                self.assertIn(f'<html lang="{code}">',page.text)
        self.assertEqual(self.client.post('/language',data={'language':'invalid','csrf_token':'copilot-csrf'}).status_code,400)
        response=self.client.post('/language',data={'language':'en','next':'https://example.test','csrf_token':'copilot-csrf'})
        self.assertEqual(response.location,'/products/start')

    def test_stream_ui_status_only_content_titles_options_and_prompt_unchanged(self):
        self.case.premium()
        source='Dengarkan'
        reply='Saya bersekolah di … (isi sendiri). Dengarkan.'
        translated='I studied at … (fill in yourself). Show translation.'
        primaries=[]
        for code in ('en','id'):
            self.client.set_cookie('kilas_language',code)
            ident=copilot.create(self.case.owner)
            streams=[fixture.answer(reply),fixture.answer(json.dumps({'source_translation':'Listen','reply_translation':translated}))]
            with patch.object(copilot,'configured',return_value=True),patch.object(copilot,'transcribe',return_value=source),patch.object(copilot,'text_stream',side_effect=streams) as text:
                response=self.client.post(f'/kilas-ai/copilot/sessions/{ident}/{uuid.uuid4().hex}/process',data={'audio':(fixture.io.BytesIO(fixture.recording()),'voice.wav','audio/wav'),'csrf_token':'copilot-csrf','consent':'yes','style':'santai','translate':'yes','target':'en'})
                response=fixture.await_operation(self.client,response)
            snapshot=response.json
            statuses=snapshot['statuses']
            complete=snapshot['result']
            self.assertIn('Recognizing speech…' if code=='en' else 'Mengenali ucapan…',statuses)
            self.assertIn('Translating…' if code=='en' else 'Menerjemahkan…',statuses)
            self.assertEqual(complete['type'],'complete')
            self.assertEqual(complete['title'],source)
            self.assertEqual(complete['turn']['source'],source)
            self.assertEqual(complete['turn']['reply'],reply)
            self.assertEqual(complete['turn']['reply_translation'],translated)
            self.assertEqual(complete['turn']['target'],'en')
            self.assertEqual(snapshot['text'],reply)
            self.assertEqual(copilot.turns(self.case.owner,ident)[-1]['reply'],reply)
            primaries.append(text.call_args_list[0].args)
            self.assertIn('to English',text.call_args_list[1].args[0])
        self.assertEqual(primaries[0],primaries[1])

    def test_owned_titles_matching_ui_keys_are_not_localized(self):
        op=uuid.uuid4().hex
        copilot.claim(self.case.owner,self.case.ident,op,'synthetic')
        copilot.update(self.case.owner,self.case.ident,op,'complete','Tampilkan terjemahan',source='Dengarkan',target=None,style='santai')
        fixture.store.rename_thread(self.case.owner,self.case.ident,'Dengarkan')
        self.client.set_cookie('kilas_language','en')
        page=self.client.get(f'/kilas-ai/copilot/sessions/{self.case.ident}')
        self.assertIn('Show translation',page.text)
        self.assertIn('"reply": "Tampilkan terjemahan"',page.text)
        items=self.client.get('/kilas-ai/sidebar/history').json['items']
        self.assertEqual(items[0]['title'],'Dengarkan')
        self.assertIn('>Dengarkan</a>',page.text)

    def test_explicit_copilot_catalog_coverage_and_placeholders_all_app_choices(self):
        root=Path(__file__).parents[1]
        script=(root/'static/kilas_copilot.mjs').read_text()
        keys=set(re.findall(r"\bt\('([^']+)'",script))
        self.assertGreater(len(keys),30)
        for key in keys:
            self.assertIn(key,ui_i18n.CLIENT_MESSAGES,key)
            self.assertIn(key,ui_i18n.CATALOG,key)
            for locale in ui_i18n.LANGUAGES:
                value=ui_i18n.CATALOG[key].get(locale)
                self.assertTrue(value,(key,locale))
                self.assertEqual(set(re.findall(r'\{\w+\}',key)),set(re.findall(r'\{\w+\}',value)),(key,locale))
        self.assertNotIn('ui_i18n',copilot.SYSTEM)

    def test_tool_chrome_and_controls_follow_locale_without_sidebar(self):
        for code in ('en','id'):
            self.client.set_cookie('kilas_language',code)
            voice=self.client.get('/kilas-translator?mode=voiceover').text
            live=self.client.get('/kilas-translator/live?classic=1').text
            for page in (voice,live):
                self.assertNotIn('id="premium-sidebar"',page)
                self.assertNotIn('data-premium-menu',page)
                self.assertIn('Profile' if code=='en' else 'Profil',page)
            self.assertIn('Generate Voice Over' if code=='en' else 'Buat Voice Over',voice)
            self.assertIn('History' if code=='en' else 'Riwayat',voice)
            self.assertIn('>Start<' if code=='en' else '>Mulai<',live)
            self.assertNotIn('>Start<' if code=='id' else '>Mulai<',live)

    def test_tool_dynamic_ui_literals_have_registered_en_and_id_messages(self):
        root=Path(__file__).parents[1]
        keys=set()
        for path in (root/'static').iterdir():
            if path.suffix not in ('.js','.mjs') or not re.match(r'kilas_(?:reference_ui|voice|audio|personal|transcription|video|native|interpreter|live_translator)',path.name):
                continue
            keys.update(key for _,key in re.findall(r"\bt\(\s*(['\"])(.*?)\1",path.read_text()))
        self.assertGreater(len(keys),200)
        for key in keys:
            self.assertIn(key,ui_i18n.CLIENT_MESSAGES,key)
            english=ui_i18n.EN_MESSAGES.get(key,ui_i18n.CATALOG.get(key,{}).get('en'))
            self.assertTrue(english,key)
            if english==key:
                self.assertTrue(ui_i18n.CATALOG.get(key,{}).get('id'),key)

    def test_public_login_catalog_read_only_smoke_contract(self):
        public=self.app.test_client()
        for locale,listen,record in (('en','Listen','Record Script'),('id','Dengarkan','Rekam Naskah')):
            public.set_cookie('kilas_language',locale)
            response=public.get('/login')
            self.assertEqual(response.status_code,200)
            self.assertIn(f'<html lang="{locale}">',response.text)
            found=re.search(r'<script[^>]+id="kw-ui-translations"[^>]*>(.*?)</script>',response.text,re.S)
            self.assertIsNotNone(found)
            messages=json.loads(found.group(1))
            self.assertEqual(messages.get('Dengarkan','Dengarkan'),listen)
            self.assertEqual(messages.get('Record Script','Record Script'),record)


if __name__=='__main__':unittest.main()
