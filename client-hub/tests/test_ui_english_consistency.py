"""Real Flask rendering with synthetic accounts; no browser or paid provider IO."""
import json
import os
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import test_kilas_audio as fixture
import test_kilas_audio_history as history_fixture
from kilas_ai import providers, audio_provider, content_projects, content_schema, audio_branded_voices


class VisibleUI(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.hidden = []; self.text = []; self.controls = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if not self.hidden:
            self.text.extend(value for key, value in attrs if key in ('aria-label', 'title', 'placeholder') and value)
            values = dict(attrs)
            if values.get('id'):
                self.controls[values['id']] = values
        # A textarea's attributes are UI; only its contents are user text.
        if tag in ('script', 'style', 'textarea', 'pre', 'code'):
            self.hidden.append(tag)

    def handle_endtag(self, tag):
        if self.hidden and tag == self.hidden[-1]:
            self.hidden.pop()

    def handle_data(self, value):
        if not self.hidden:
            self.text.append(value)


class EnglishUITests(unittest.TestCase):
    def setUp(self):
        fixture.AudioTests.setUp(self)
        self.client.delete_cookie('kilas_language')

    def test_default_english_navigation_active_pages_and_fresh_reload(self):
        pages = {}
        with patch.object(providers, '_openai', side_effect=AssertionError('no paid QA')):
            for path in ('/products/start', '/kilas-ai', '/kilas-ai/usage',
                         '/kilas-ai/library', '/kilas-translator?mode=voiceover',
                         '/kilas-translator/live', '/account'):
                for _ in range(2):
                    response = self.client.get(path, follow_redirects=True)
                    self.assertEqual(response.status_code, 200, path)
                    self.assertIn('<html lang="en">', response.text, path)
                    text = ' '.join(VisibleUI(response.text).text)
                    for leftover in ('Bahasa aplikasi', 'Terapkan', 'Pilih suara',
                                     'Naskah', 'Mendengarkan', 'Pilih dua bahasa',
                                     'Tambah Suara', 'Saldo Audio', 'Belum ada',
                                     'sedang dicadangkan', 'Terjemahkan naskah',
                                     'Tulis apa yang ingin diucapkan...'):
                        self.assertTrue(leftover not in text, (path, leftover))
                    self.assertNotIn('href="/kilas-learning', response.text)
                    pages[path] = response.text
        target = os.environ.get('KILAS_ENGLISH_UI_FIXTURE_PATH')
        if target:
            Path(target).write_text(json.dumps(pages), encoding='utf-8')

    def test_visible_ui_includes_textarea_attributes_but_excludes_its_content(self):
        page = VisibleUI('<textarea id="draft" placeholder="UI placeholder" aria-label="UI label">Private user text</textarea>')
        self.assertIn('UI placeholder', page.text)
        self.assertIn('UI label', page.text)
        self.assertNotIn('Private user text', page.text)

    def test_reported_home_library_voice_and_language_labels_roundtrip(self):
        for language in ('en', 'id', 'en'):
            self.client.set_cookie('kilas_language', language)
            home = self.client.get('/products/start').text
            visible = VisibleUI(home).text
            for expected in (('How can I Help you?', 'See all', 'Profile') if language=='en'
                             else ('Apa yang bisa saya bantu?', 'Lihat semua', 'Profil')):
                self.assertIn(expected, visible)
            library = self.client.get('/kilas-ai/library').text
            self.assertTrue(('<h1>My Library</h1>' if language=='en' else '<h1>Pustaka saya</h1>') in library)
            audio = self.client.get('/kilas-translator?mode=voiceover').text
            self.assertTrue(('>Generate Voice Over</button>' if language=='en' else '>Buat Voice Over</button>') in audio)
            self.assertTrue(('<h2>Recent</h2>' if language=='en' else '<h2>Terbaru</h2>') in audio)
            self.assertTrue(('>Auto Detect</option>' if language=='en' else '>Deteksi otomatis</option>') in audio)
            live = self.client.get('/kilas-translator/live').text
            options = re.search(r'<select name="language_a"[^>]*>(.*?)</select>',live,re.S)[1]
            self.assertTrue(re.search(r'value="id"[^>]*>'+('Indonesian' if language=='en' else 'Bahasa Indonesia')+r'</option>',options))
            self.assertTrue(re.search(r'value="en"[^>]*>'+('English' if language=='en' else 'Inggris')+r'</option>',options))
            self.assertTrue('value="id" selected' in options)

    def test_voiceover_script_placeholder_respects_locale_refresh_and_original_draft(self):
        source = 'Tulis apa yang ingin diucapkan...'
        history_fixture.AudioHistoryTests.seed(self, 5)
        for code, expected in ((None, 'Write what you want to say...'),
                               ('en', 'Write what you want to say...'), ('id', source),
                               ('en', 'Write what you want to say...'),
                               ('es', 'Escribe lo que quieres decir...'),
                               ('zh', '输入你想说的内容...'),
                               ('en', 'Write what you want to say...')):
            if code is None:
                self.client.delete_cookie('kilas_language')
            else:
                selected = self.client.post('/language', data={
                    'csrf_token':'audio-csrf', 'language':code,
                    'next':'/kilas-translator?mode=voiceover'})
                self.assertEqual(selected.status_code, 303)
            # Navigation and repeated GETs use the persisted application locale.
            home = self.client.get('/products/start')
            self.assertTrue('<html lang="'+(code or 'en')+'">' in home.text)
            for _ in range(2):
                response = self.client.get('/kilas-translator?mode=voiceover')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(VisibleUI(response.text).controls['audio-script']['placeholder'], expected)
            target = os.environ.get('KILAS_ENGLISH_UI_FIXTURE_PATH')
            if target and code in ('en', 'id'):
                path = Path(target)
                pages = json.loads(path.read_text()) if path.exists() else {}
                pages['voiceover-locale-'+code] = response.text
                pages['history-locale-'+code] = self.client.get(
                    '/kilas-translator/history?page=2&kind=voiceover').json
                pages['history-translate-locale-'+code] = self.client.get(
                    '/kilas-translator/history?page=1&kind=translate').json
                path.write_text(json.dumps(pages), encoding='utf-8')
            carried = self.client.post('/kilas-ai/home-task', data={
                'csrf_token':'audio-csrf', 'task':'voiceover', 'brief':source})
            self.assertEqual(carried.status_code, 200)
            self.assertEqual(VisibleUI(carried.text).controls['audio-script']['placeholder'], expected)
            value = re.search(r'<textarea\b[^>]*id="audio-script"[^>]*>(.*?)</textarea>', carried.text, re.S)
            self.assertIsNotNone(value)
            self.assertEqual(value[1], source)

    def test_default_ui_does_not_change_translator_language_or_voice_settings(self):
        with patch.object(audio_branded_voices, 'public_choices', return_value=[{'alias':'kilas-male','name':'Kilas Male','style':'Natural'}]):
            response = self.client.get('/kilas-translator/live')
        self.assertIn('First language', response.text)
        self.assertIn('Second language', response.text)
        self.assertIn('value="id" selected', response.text)
        self.assertIn('value="en" selected', response.text)
        self.assertIn('name="language_a"', response.text)
        self.assertIn('name="language_b"', response.text)
        self.assertIn('value="kilas-male" selected', response.text)
        self.assertIn('aria-label="End session"', response.text)

    def test_explicit_indonesian_and_other_preferences_survive_refresh(self):
        for code in ('id', 'es', 'zh'):
            self.client.set_cookie('kilas_language', code)
            for _ in range(2):
                response = self.client.get('/kilas-translator/live')
                self.assertIn('<html lang="'+code+'">', response.text)
                self.assertIn('value="'+code+'" selected', response.text)
            if code == 'id':
                self.assertIn('Pilih dua bahasa, lalu mulai percakapan.', response.text)
                self.assertNotIn('First language', response.text)

    def test_saved_voice_name_and_original_script_are_not_ui_translation_keys(self):
        fixture.f.db.execute("INSERT INTO kilas_audio_saved_voices(user_id,name,voice_id,operation_key,consent_at,updated_at) VALUES (?,?,?,?,?,?)",
                             (self.user, 'Hapus Suara', 'synthetic-private', 'locale-voice', '2026-10-15', '2026-10-15'))
        response = self.client.get('/kilas-translator?mode=voiceover')
        self.assertIn('>Hapus Suara</option>', response.text)
        self.assertIn('>Delete Voice</button>', response.text)
        with fixture.f.app.app.test_request_context('/kilas-translator'):
            from flask import render_template
            from ui_i18n import translate
            rendered = render_template('kilas_translator/_result.html',
                job={'status':'COMPLETED','mode':'voiceover','source_language':'id',
                     'target_language':'id','actual_ms':1000,'result_is_video':False,
                     'id':123,'has_original_script':True}, languages=audio_provider.LANGUAGES,
                seconds=lambda value: str(value)+'s', upload_translation_visible=False)
            self.assertIn('Voice Over complete', rendered)
            self.assertIn('Indonesian', rendered)
            self.assertEqual(translate('Hapus Suara'), 'Delete Voice')

    def test_content_project_and_script_text_are_preserved(self):
        content_schema.apply_release()
        with patch.object(content_projects, 'enabled', return_value=True):
            ident = content_projects.create(self.user, 'Pilih suara', 'Naskah asli bahasa Indonesia', 'locale-project-key-123456')
            content_projects.save_script(self.user, ident, 0, 'Pilih dua bahasa, lalu mulai percakapan.', 'locale-script-key-123456')
            response = self.client.get('/kilas-ai/content-projects/'+str(ident))
            self.assertEqual(response.status_code, 200)
            self.assertIn('Pilih suara', response.text)
            self.assertIn('Pilih dua bahasa, lalu mulai percakapan.', response.text)
            self.assertTrue('>Save script version</button>' in response.text)

    def test_history_fragment_localizes_paging_and_keeps_saved_titles(self):
        jobs = history_fixture.AudioHistoryTests.seed(self, 5)
        fixture.f.db.execute('UPDATE kilas_audio_jobs SET title=? WHERE id=?', ('Edit naskah', jobs[0]))
        first = self.client.get('/kilas-translator?mode=voiceover')
        second = self.client.get('/kilas-translator/history?page=2&kind=voiceover').json
        self.assertIn('Edit naskah', second['html'])
        self.assertTrue('Edit script' in second['html'])
        self.assertTrue('Halaman' not in second['html'])
        target = os.environ.get('KILAS_ENGLISH_UI_FIXTURE_PATH')
        if target:
            path = Path(target)
            pages = json.loads(path.read_text()) if path.exists() else {}
            pages['history-first'] = first.text
            pages['history-second'] = second
            path.write_text(json.dumps(pages), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
