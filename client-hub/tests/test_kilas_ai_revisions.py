"""Owner UI revisions and ElevenLabs dictation. All provider calls synthetic."""
import hashlib
import io
import os
import unittest
from unittest.mock import patch
from pathlib import Path
import test_kilas_audio as audio
import test_kilas_audio_video_script as video_fixture
from kilas_ai import audio_branded_voices as branded, audio_transcription_budget as budget
from kilas_ai import audio_transcription_provider as stt, audio_media as media, audio_provider as provider
from kilas_ai import chat_video_planning, unified_runtime, store


class RevisionTests(unittest.TestCase):
    setUp=audio.AudioTests.setUp
    funded=video_fixture.VideoScriptTests.funded
    response=video_fixture.VideoScriptTests.response
    credit=audio.AudioTests.credit

    def post(self,key='dictate-synthetic-operation-1234',**fields):
        return self.client.post('/kilas-translator/voice-script/dictate',data={'csrf_token':'audio-csrf','consent':'yes','operation_key':key,'recording':(io.BytesIO(audio.wav()),'recording.wav','audio/wav'),**fields})

    def test_navigation_profile_and_private_library(self):
        ident=store.create_thread(self.user);store.rename_thread(self.user,ident,'Old conversation retained')
        other=store.create_thread(self.other);store.rename_thread(self.other,other,'Foreign conversation')
        html=self.client.get('/products/start').text
        self.assertIn('Old conversation retained',html);self.assertNotIn('Foreign conversation',html)
        self.assertIn('New Chat',html);self.assertIn('My Library',html);self.assertIn('How can I Help you?',html)
        self.assertEqual(html.count('name="product" value="finance"'),1)
        choices=html.split('class="home-task-choices"',1)[1].split('</div>',1)[0]
        self.assertLess(choices.index('AI Chat'),choices.index('Translator'))
        self.assertLess(choices.index('Translator'),choices.index('Voice Over'))
        self.assertLess(choices.index('Voice Over'),choices.index('Finance'))
        self.assertNotIn('data-home-task="video"',html);self.assertNotIn('data-home-task="translate"',html)
        profile=html.split('class="kilas-profile-options"',1)[1].split('</div>',1)[0]
        self.assertLess(profile.index('Account'),profile.index('Subscription'))
        self.assertLess(profile.index('Subscription'),profile.index('App Language'))
        self.assertLess(profile.index('App Language'),profile.index('Logout'))
        self.assertIn(self.id().lower()+'@example.test',profile)
        self.assertEqual(self.client.get('/kilas-ai/library').status_code,200)
        voice=self.client.get('/kilas-translator?mode=voiceover').text
        self.assertNotIn('data-chat-sidebar',voice);self.assertNotIn('id="premium-sidebar"',voice)
        self.assertIn('kilas-feature-navigation',voice);self.assertNotIn('voice-video-script',voice)
        self.assertNotIn('class="audio-balance"',voice)

    def test_branded_aliases_exact_records_no_new_clone_or_personal_change(self):
        now='2026-10-11'
        for name,ident in [('irvan Voice','existingMaleID'),('putri voice','existingFemaleID')]:
            audio.f.db.execute('INSERT INTO kilas_audio_saved_voices(user_id,name,voice_id,operation_key,consent_at,updated_at) VALUES (?,?,?,?,?,?)',(self.user,name,ident,'voice-'+ident,now,now))
        rows=audio.f.db.query_all('SELECT * FROM kilas_audio_saved_voices WHERE user_id=? ORDER BY id',(self.user,))
        sources=tuple((alias,self.user,row['id'],label) for alias,label,row in zip(('kilas-male','kilas-female'),('Kilas Male','Kilas Female'),rows))
        audio.f.db.execute('INSERT INTO kilas_audio_personal_voices(user_id,voice_id) VALUES (?,?)',(self.user,'existingMaleID'))
        self.credit(120)
        with patch.object(branded,'SOURCES',sources),patch.object(provider,'clone_voice') as clone,patch.object(provider,'speech',return_value=(audio.mp3(),2000)) as tts:
            self.assertEqual([v['name'] for v in branded.choices()],['Kilas Male','Kilas Female'])
            self.assertEqual(branded.resolve('kilas-male')['id'],'existingMaleID')
            html=self.client.get('/kilas-translator?mode=voiceover').text
            self.assertIn('value="kilas-male"',html);self.assertIn('value="kilas" checked',html)
            self.assertNotIn('existingMaleID',html);self.assertNotIn('existingFemaleID',html)
            result=self.client.post('/kilas-translator/jobs',data={'csrf_token':'audio-csrf','operation_key':'branded-synthetic-operation','mode':'voiceover','voice':'kilas-male','language':'auto','script':'Ini naskah uji sintetis.'})
            self.assertEqual(result.status_code,201);self.assertEqual(tts.call_args.args[1],'existingMaleID');clone.assert_not_called()
        self.assertEqual(audio.f.db.query_all('SELECT * FROM kilas_audio_saved_voices WHERE user_id=? ORDER BY id',(self.user,)),rows)
        with patch.object(branded,'SOURCES',(('kilas-male',self.other,rows[0]['id'],'Kilas Male'),)):
            self.assertEqual(branded.choices(),[])

    def test_dictation_off_consent_csrf_fail_closed_before_decode_or_provider(self):
        with patch.dict(os.environ,{'KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'false'}),patch.object(media,'voice_sample') as decode,patch.object(stt.requests,'post') as paid:
            self.assertEqual(self.post().json['code'],'budget_unavailable')
            self.assertEqual(self.post(consent='no').status_code,400)
            self.assertEqual(self.post(csrf_token='wrong').status_code,400)
            decode.assert_not_called();paid.assert_not_called()

    def test_dictation_decodes_real_synthetic_wav_and_never_generates_tts(self):
        before=audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs')['n']
        with self.funded(),patch.object(stt.requests,'post',return_value=self.response('Ini hasil dikte sintetis.')) as paid,patch.object(provider,'speech') as tts,patch.object(provider,'clone_voice') as clone:
            result=self.post();self.assertEqual(result.status_code,200,result.json)
            self.assertEqual(result.json['text'],'Ini hasil dikte sintetis.')
            self.assertIn('no-store',result.headers['Cache-Control'])
            self.assertEqual(self.post().json['status'],'COMPLETED');self.assertEqual(paid.call_count,1)
            self.assertEqual(paid.call_args.kwargs['data']['model_id'],'scribe_v2')
            tts.assert_not_called();clone.assert_not_called()
        self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs')['n'],before)
        self.assertIsNone(audio.f.db.query_one('SELECT seconds FROM kilas_audio_balances WHERE user_id=?',(self.user,)))

    def test_cancel_fences_pending_dictation_and_retains_unknown_cost(self):
        key='dictate-cancel-synthetic-1234';raw,ms=stt.normalize(audio.wav());digest=hashlib.sha256(raw).hexdigest()
        with self.funded():
            _,cap=budget.claim(self.user,key,digest,ms);budget.dispatch(cap,digest,ms)
            response=self.post(key,action='cancel');self.assertEqual(response.json['status'],'CANCELLED')
            self.assertFalse(budget.finish(cap,True))
            row=audio.f.db.query_one('SELECT charge_micro FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(self.user,key))
            self.assertGreater(row['charge_micro'],0)

    def test_video_planning_reuses_director_without_rendering_or_jobs(self):
        prompt='Buatkan konsep video kopi dan storyboard 15 detik'
        self.assertEqual(unified_runtime.intent(prompt),'CHAT')
        guide=chat_video_planning.instruction([{'role':'user','content':prompt}])
        self.assertIn('NEVER invent brand/product benefits',guide)
        self.assertIn('timed scene table',guide);self.assertIn('English production prompts',guide)
        self.assertEqual(chat_video_planning.instruction([{'role':'user','content':'halo'}]),'')
        self.assertIn('latest corrections',chat_video_planning.instruction([{'role':'user','content':prompt},{'role':'assistant','content':'Plan'},{'role':'user','content':'ganti adegan kedua'}]))


if __name__=='__main__':unittest.main()
