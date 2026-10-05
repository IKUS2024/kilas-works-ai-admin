"""Focused personal-voice consent, persistence, isolation and replacement regressions."""
import io
import unittest
from unittest.mock import patch,Mock
from werkzeug.datastructures import FileStorage
import test_kilas_audio as audio
from test_kilas_audio import f, wav, provider, store, media
from kilas_ai import audio_personal_voice as personal


class PersonalVoiceTests(unittest.TestCase):
    setUpClass=classmethod(audio.AudioTests.setUpClass.__func__)
    setUp=audio.AudioTests.setUp
    credit=audio.AudioTests.credit
    create=audio.AudioTests.create

    def clone(self,key='personal-operation-1234',**values):
        data={'csrf_token':'audio-csrf','operation_key':key,'consent':'yes','recording':(io.BytesIO(wav()),'recording','audio/wav'),**values}
        return self.client.post('/kilas-translator/personal-voice',data=data,content_type='multipart/form-data')

    def test_consent_csrf_and_balance_before_provider(self):
        with patch.object(provider,'clone_voice') as clone:
            self.assertEqual(self.clone(consent='no').status_code,400)
            self.assertEqual(self.clone(csrf_token='bad').status_code,400)
            self.assertEqual(self.clone().status_code,402)
            clone.assert_not_called()

    def test_create_persist_retry_no_public_identifier(self):
        self.credit()
        with patch.object(provider,'clone_voice',return_value='ownPrivateVoice123') as clone:
            self.assertEqual(self.clone().json,{'ready':True})
            self.assertEqual(self.clone().status_code,200);clone.assert_called_once()
        self.assertEqual(personal.get(self.user),'ownPrivateVoice123')
        page=self.client.get('/kilas-translator').text
        self.assertIn('Siap digunakan',page);self.assertNotIn('ownPrivateVoice123',page)
        row=f.db.query_one('SELECT * FROM kilas_audio_personal_voices WHERE user_id=?',(self.user,))
        self.assertTrue(row['consent_at']);self.assertEqual(row['claim_token'],'')
        self.assertNotIn('recording',row)

    def test_same_voice_indonesian_english_original_text(self):
        self.credit(300)
        with patch.object(provider,'clone_voice',return_value='ownPrivateVoice123'):self.clone()
        for i,text in enumerate(('Selamat datang di Kilas Works.','Welcome to Kilas Works. Today we are building something new.')):
            r,speech,_=self.create(key='personal-generation-'+str(i),voice='personal',language='auto',script=text)
            self.assertEqual(r.status_code,201,r.text)
            speech.assert_called_once_with(text,'ownPrivateVoice123','auto')
            self.assertEqual(store.get(self.user,r.json['id'])['status'],'COMPLETED')
            self.assertEqual(self.client.get(r.json['url']).status_code,200)
            result=self.client.get('/kilas-translator/jobs/'+str(r.json['id'])+'/result?download=1')
            self.assertEqual(result.data,self.audio);self.assertIn('.mp3',result.headers['Content-Disposition'])

    def test_replace_confirmation_failure_and_success(self):
        self.credit()
        with patch.object(provider,'clone_voice',return_value='oldPrivate123'):self.clone()
        with patch.object(provider,'clone_voice',side_effect=provider.ProviderError()) as clone,patch.object(provider,'delete_voice') as delete:
            self.assertEqual(self.clone(key='replace-operation-1234').status_code,409);clone.assert_not_called()
            self.assertEqual(self.clone(key='replace-operation-1234',replace='yes').status_code,503)
            self.assertEqual(personal.get(self.user),'oldPrivate123');delete.assert_not_called()
        with patch.object(provider,'clone_voice',return_value='newPrivate123'),patch.object(provider,'delete_voice') as delete:
            self.assertEqual(self.clone(key='replace-operation-1234',replace='yes').status_code,200)
            self.assertEqual(personal.get(self.user),'newPrivate123');delete.assert_called_once_with('oldPrivate123')

    def test_user_cannot_select_foreign_clone(self):
        self.credit()
        with patch.object(provider,'clone_voice',return_value='foreignPrivate123'):self.clone()
        self.user=self.other;self.credit()
        with self.client.session_transaction() as s:s['user_id']=self.other
        self.assertFalse(personal.get(self.other))
        for choice in ('personal','foreignPrivate123'):
            r,speech,_=self.create(voice=choice);self.assertEqual(r.status_code,503);speech.assert_not_called()
        self.assertNotIn('foreignPrivate123',self.client.get('/kilas-translator').text)

    def test_curated_library_excludes_all_personal_clones(self):
        voices=[{'voice_id':'sharedStock123','category':'premade','name':'Rachel','labels':{'gender':'female'}},
                {'voice_id':'secretOther123','category':'cloned','labels':{'gender':'female'}},
                {'voice_id':'secretPvc123','category':'professional','labels':{'gender':'male'}},
                {'voice_id':'secretLabel123','labels':{'gender':'male','kilas_personal':'true'}}]
        with patch.object(provider,'_voices',None),patch.object(provider,'request',return_value={'voices':voices}):
            self.assertEqual([v['id'] for v in provider.voices()],['sharedStock123'])

    def test_clone_adapter_private_and_verification_not_ready(self):
        with patch.object(provider,'request',return_value={'voice_id':'clone123','requires_verification':False}) as call:
            self.assertEqual(provider.clone_voice(b'sample'),'clone123')
            self.assertEqual(call.call_args.args,('POST','/voices/add'));self.assertTrue(call.call_args.kwargs['private'])
            self.assertEqual(call.call_args.kwargs['files'][0][0],'files')
        with patch.object(provider,'request',return_value={'voice_id':'clone123','requires_verification':True}),patch.object(provider,'delete_voice') as delete:
            with self.assertRaises(provider.ProviderError):provider.clone_voice(b'sample')
            delete.assert_called_once_with('clone123')

    def test_busy_blocks_parallel_clone_and_personal_generation(self):
        self.credit()
        with patch.object(provider,'clone_voice',return_value='oldPrivate123'):self.clone()
        with patch.object(provider,'clone_voice') as paid:
            from datetime import timedelta
            from kilas_ai import usage
            f.db.execute('UPDATE kilas_audio_personal_voices SET claim_until=? WHERE user_id=?',((usage._now()+timedelta(minutes=2)).isoformat(),self.user))
            self.assertEqual(self.clone(key='parallel-operation-1234',replace='yes').status_code,409);paid.assert_not_called()
            r,speech,_=self.create(voice='personal');self.assertEqual(r.status_code,409);speech.assert_not_called()

    def test_recording_validation_short_sample_and_cleanup(self):
        self.assertTrue(media.voice_sample(FileStorage(io.BytesIO(wav(.5)),filename='recording',content_type='audio/wav')).startswith(b'RIFF'))
        for mime,raw in [('text/html',b'<html>'),('audio/webm',b'invalid')]:
            with self.assertRaises(media.MediaError):media.voice_sample(FileStorage(io.BytesIO(raw),filename='recording',content_type=mime))
        with patch.object(media,'_decode_source') as decode:
            with self.assertRaises(media.MediaError):media.voice_sample(FileStorage(io.BytesIO(b'#EXTM3U\nfile:///private.wav'),filename='recording',content_type='audio/webm'))
            decode.assert_not_called()


if __name__=='__main__':unittest.main()
