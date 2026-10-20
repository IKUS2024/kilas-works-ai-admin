"""Exact spoken editor snapshots; synthetic audio/provider boundaries only."""
import unittest
from unittest.mock import patch
import test_kilas_audio as base
from test_kilas_audio import f,provider,store
from kilas_ai import audio_branded_voices as branded


class VoiceEditTests(unittest.TestCase):
    setUpClass=classmethod(base.AudioTests.setUpClass.__func__)
    setUp=base.AudioTests.setUp
    credit=base.AudioTests.credit
    create=base.AudioTests.create

    def source(self,**kw):
        self.credit(300)
        response,_,_=self.create(**kw)
        self.assertEqual(response.status_code,201,response.text)
        return response.json['id']

    def test_exact_translated_snapshot_survives_reload_alternate_and_regeneration(self):
        original='  Selamat datang.\nIni naskah Indonesia.  '
        spoken='Welcome. This is the English script.'
        ident=self.source(script=original,translate_script='yes',translated_script=spoken,language='en',translation_source='id')
        with patch.object(branded,'choices',return_value=[{'alias':'kilas-female','id':'actualVoice123','name':'Kilas Female','style':'Natural'}]):
            for _ in range(2):
                self.assertIn('data-audio-edit=',self.client.get(f'/kilas-translator/jobs/{ident}').text)
                self.assertIn('data-audio-edit=',self.client.get('/kilas-translator/history?mode=voiceover').text)
                payload=self.client.get(f'/kilas-translator/jobs/{ident}/script').json
                self.assertEqual(payload,{'script':spoken,'language':'en','voice':'kilas-female','source_kind':'spoken_script'})
            with patch.object(provider,'speech',return_value=(self.audio,'alternate')):
                response=self.client.post(f'/kilas-translator/jobs/{ident}/alternate',data={'csrf_token':'audio-csrf','operation_key':'edit-alternate-123456'})
            alternate=response.json['id']
            self.assertEqual(self.client.get(f'/kilas-translator/jobs/{alternate}/script').json,payload)
            with patch.object(provider,'speech',return_value=(self.audio,'edited')) as speech:
                response=self.client.post('/kilas-translator/jobs',data={'csrf_token':'audio-csrf','operation_key':'edit-regenerate-123456','mode':'voiceover','voice':payload['voice'],'language':payload['language'],'script':payload['script']+' Updated.'})
            self.assertEqual(response.status_code,201,response.text)
            speech.assert_called_once_with(spoken+' Updated.','actualVoice123','en')
        row=f.db.query_one('SELECT original_script,spoken_script,source_language,target_language FROM kilas_audio_jobs WHERE id=?',(ident,))
        self.assertEqual(tuple(row[key] for key in ('original_script','spoken_script','source_language','target_language')),(original,spoken,'id','en'))
        self.assertEqual(store.edit_script(self.user,ident),original)

    def test_selected_job_uses_its_own_last_translation_language(self):
        ident=self.source(script='Naskah pertama.',translate_script='yes',translated_script='こんにちは。',language='ja',translation_source='id')
        later,_,_=self.create(key='later-spanish-123456',script='Naskah kedua.',translate_script='yes',translated_script='Buenos días.',language='es',translation_source='id')
        self.assertEqual(later.status_code,201)
        for job,text,language in ((later.json['id'],'Buenos días.','es'),(ident,'こんにちは。','ja')):
            payload=self.client.get(f'/kilas-translator/jobs/{job}/script').json
            self.assertEqual((payload['script'],payload['language']),(text,language))
        response,speech,_=self.create(key='edit-japanese-123456',script='こんにちは。編集しました。',language='ja')
        self.assertEqual(response.status_code,201)
        speech.assert_called_once_with('こんにちは。編集しました。','actualVoice123','ja')

    def test_plain_auto_personal_missing_voice_and_legacy(self):
        ident=self.source(script='  Plain script.\n',language='auto')
        payload=self.client.get(f'/kilas-translator/jobs/{ident}/script').json
        self.assertEqual(payload['script'],'Plain script.');self.assertEqual(payload['language'],'auto');self.assertIsNone(payload['voice'])
        now='2026-10-20T00:00:00+00:00'
        f.db.execute("INSERT INTO kilas_audio_saved_voices(user_id,name,voice_id,operation_key,consent_at,updated_at) VALUES (?,?,?,?,?,?)",(self.user,'My saved voice','actualVoice123','saved-edit-123456',now,now))
        saved=f.db.query_one('SELECT id FROM kilas_audio_saved_voices WHERE user_id=?',(self.user,))['id']
        f.db.execute('UPDATE kilas_audio_jobs SET voice_is_personal=1 WHERE id=?',(ident,))
        self.assertEqual(self.client.get(f'/kilas-translator/jobs/{ident}/script').json['voice'],f'personal:{saved}')
        f.db.execute('DELETE FROM kilas_audio_saved_voices WHERE user_id=?',(self.user,))
        self.assertIsNone(self.client.get(f'/kilas-translator/jobs/{ident}/script').json['voice'])
        f.db.execute('UPDATE kilas_audio_jobs SET spoken_script=NULL WHERE id=?',(ident,))
        self.assertEqual(self.client.get(f'/kilas-translator/jobs/{ident}/script').status_code,409)
        self.assertFalse(store.get(self.user,ident)['has_edit_script'])
        self.assertNotIn('data-audio-edit=',self.client.get(f'/kilas-translator/jobs/{ident}').text)
        self.assertEqual(store.edit_script(self.user,ident),'  Plain script.\n')

    def test_terminal_owner_scope_and_session_denial(self):
        ident=self.source(script='English exact text.')
        f.db.execute('UPDATE kilas_audio_jobs SET user_id=? WHERE id=?',(self.other,ident))
        self.assertIsNone(store.spoken_edit_script(self.user,ident));self.assertEqual(self.client.get(f'/kilas-translator/jobs/{ident}/script').status_code,404)
        f.db.execute("UPDATE kilas_audio_jobs SET user_id=?,status='PROCESSING' WHERE id=?",(self.user,ident))
        self.assertIsNone(store.spoken_edit_script(self.user,ident));self.assertEqual(self.client.get(f'/kilas-translator/jobs/{ident}/script').status_code,409)
        f.db.execute("UPDATE kilas_audio_jobs SET status='FAILED' WHERE id=?",(ident,))
        self.assertEqual(self.client.get(f'/kilas-translator/jobs/{ident}/script').json['script'],'English exact text.')
        f.db.execute("UPDATE kilas_audio_jobs SET content_origin='live_session' WHERE id=?",(ident,))
        self.assertIsNone(store.spoken_edit_script(self.user,ident));self.assertEqual(self.client.get(f'/kilas-translator/jobs/{ident}/script').status_code,404)
