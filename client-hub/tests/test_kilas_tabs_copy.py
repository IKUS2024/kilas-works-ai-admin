"""Static feature-tab copy only, synthetic owners and forbidden external transport."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import test_kilas_video as video_fixture
fixture=video_fixture.fixture
from kilas_ai import audio_provider,content_projects,content_schema,agent_store,store


class TabsCopyTests(unittest.TestCase):
    def setUp(self):
        self.base=video_fixture.VideoTests('test_create_and_reopen_owner_history');self.base.id=lambda:self.id();self.base.setUp()
        self.owner=self.base.owner;self.client=self.base.client
        self.flags=patch.dict(os.environ,{'KILAS_AI_AUTOMATION_ENABLED':'true','KILAS_CONTENT_PROJECTS_ENABLED':'true','KILAS_LIVE_ASSIST_ENABLED':'true','KILAS_LIVE_ASSIST_QA_ENABLED':'false','KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'false','KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'false'})
        self.flags.start();self.addCleanup(self.flags.stop)
        self.voices=patch.object(audio_provider,'voices',return_value=[]);self.voices.start();self.addCleanup(self.voices.stop)
        self.transport=patch('requests.sessions.Session.request',side_effect=AssertionError('External IO forbidden'));self.transport.start();self.addCleanup(self.transport.stop)
        response,_=self.base.make();self.assertEqual(response.status_code,200,response.text);self.video=response.json['url']
        self.thread=store.create_thread(self.owner);store.append_user_once(self.owner,self.thread,'Keep this user description verbatim.','SMART','tabs-copy-user-123456')
        store.append_assistant(self.owner,self.thread,'Keep this AI description verbatim.','SMART','fixture','fixture','tabs-copy-user-123456',{})
        self.conversation=agent_store.new_conversation(self.owner)
        agent_store.append(self.owner,'user','Keep this agent user description verbatim.',conversation_id=self.conversation)
        content_schema.apply_disposable_sqlite(Path(fixture.db.SQLITE_PATH).parent)
        self.project=content_projects.create(self.owner,'Synthetic project','Keep this project brief description verbatim.','tabs-copy-project-123456')
        self.paths={'home':'/products/start','legacy_chat':'/kilas-ai/threads/'+str(self.thread),'agent_chat':'/kilas-ai/agent?conversation='+str(self.conversation),'video_new':'/kilas-ai/video','video_result':self.video,'voiceover':'/kilas-translator?mode=voiceover','work_tasks':'/kilas-ai/agent?view=tasks','work_history':'/kilas-ai/agent?view=history','work_notifications':'/kilas-ai/agent?view=notifications','reminders':'/kilas-ai/automation','reminder_new':'/kilas-ai/automation/new','projects':'/kilas-ai/content-projects','project':f'/kilas-ai/content-projects/{self.project}','live_assist':'/kilas-ai/live-assist'}

    def test_feature_routes_keep_inputs_user_content_and_essential_notices(self):
        responses={key:self.client.get(path) for key,path in self.paths.items()}
        for key,response in responses.items():self.assertEqual(response.status_code,200,(key,response.status_code))
        removed={'home':['Mulai dari ide, pertanyaan, atau pekerjaanmu.'],'agent_chat':['Mulai dari ide, pertanyaan, atau pekerjaanmu.'],'video_new':['Ubah ide sederhana menjadi rencana video yang siap diproduksi.','Dari ide ke arahan produksi'],'voiceover':['Audio kamu tersimpan di sini.'],'reminders':['Jadwalkan pengingat, riset, dan pemantauan.'],'projects':['Simpan brief, naskah, rencana visual dan hasil audio dalam satu proyek.']}
        for key,phrases in removed.items():
            for phrase in phrases:self.assertNotIn(phrase,responses[key].text)
        for text in ('Keep this user description verbatim.','Keep this AI description verbatim.'):self.assertIn(text,responses['legacy_chat'].text)
        self.assertIn('Keep this agent user description verbatim.',responses['agent_chat'].text)
        self.assertIn('Keep this project brief description verbatim.',responses['project'].text)
        self.assertIn('Demonstrasi pemakaian dengan kemasan tetap sama.',responses['video_result'].text)
        for key,ids in {'home':['ai-input','ai-files','ai-send','ai-stop'],'video_new':['video-idea','video-submit','video-clip-strategy','video-status','video-error'],'voiceover':['audio-script','voice-assist-generate','voice-translate-toggle','dictation-start','voice-generate'],'live_assist':['live-consent','live-provider','live-start','live-stop','live-status']}.items():
            for ident in ids:self.assertIn('id="'+ident+'"',responses[key].text)
        self.assertIn('Jawaban AI dapat keliru.',responses['home'].text)
        self.assertIn('Video akhir dibuat di tool pilihanmu.',responses['video_new'].text)
        for key in ('home','legacy_chat','agent_chat','voiceover','live_assist'):
            self.assertNotIn('ElevenLabs',responses[key].text)
            self.assertNotIn('OpenAI',responses[key].text)
        self.assertNotIn('href="/privacy#audio-processing"',responses['voiceover'].text)
        self.assertIn('ElevenLabs memakai logging bawaan',self.client.get('/privacy').text)
        self.assertIn('Caption, terjemahan dan saran jawaban belum tersedia.',responses['live_assist'].text)
        policy=self.client.get('/privacy').text
        for text in ('id="audio-processing"','ElevenLabs','OpenAI','Hasil audio tersimpan di akun pemilik','permintaan provider yang sudah dikirim dapat tetap diproses dan memakai biaya','kapasitas AI dan audio','Transkripsi audio di proyek chat mengirim audio ke OpenAI'):
            self.assertIn(text,policy)
        self.assertIn('Hubungan versi naskah tidak memverifikasi kecocokan isi audio.',responses['project'].text)

    def test_primary_feature_templates_keep_provider_disclosures_in_privacy_destination(self):
        root=Path(__file__).resolve().parents[1]/'templates'
        for name in ('kilas_translator/live.html','kilas_translator/home.html','kilas_ai/home.html','kilas_ai/_home_workspace.html','kilas_ai/_agent_home_chat.html','finance_assistant.html','_finance_home_dashboard.html','kilas_content/_transcription.html','kilas_content/live_assist.html'):
            with self.subTest(template=name):self.assertNotRegex((root/name).read_text(),r'ElevenLabs|OpenAI')
        for name in ('kilas_translator/live.html','kilas_content/_transcription.html','kilas_content/live_assist.html'):
            self.assertIn("url_for('privacy_policy')",(root/name).read_text())
        self.assertNotIn("url_for('privacy_policy')",(root/'kilas_translator/home.html').read_text())

    def test_translate_rollback_mode_keeps_form_and_validation(self):
        with patch.dict(os.environ,{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'true'}):html=self.client.get('/kilas-translator?mode=translate').text
        for text in ('Terjemahkan suara atau buat voice over tanpa ribet.','Suara yang sama. Bahasa baru.'):self.assertNotIn(text,html)
        for ident in ('translate-panel','audio-file','audio-duration','voiceover-panel','audio-script'):self.assertIn('id="'+ident+'"',html)
        self.assertIn('MP4 maks. 250 MB',html);self.assertIn('required aria-describedby="audio-duration"',html)


if __name__=='__main__':unittest.main()
