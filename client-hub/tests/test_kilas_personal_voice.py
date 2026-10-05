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

    def test_named_library_add_select_rename_and_delete(self):
        self.credit(300)
        with patch.object(provider,'clone_voice',side_effect=['privateNamedA','privateNamedB']) as clone:
            first=self.clone(name='Suara Irvan').json
            self.assertEqual(self.clone(name='Suara Irvan').json,first)
            second=self.clone(key='named-second-key-1234',name='Suara Presentasi').json
            self.assertEqual(clone.call_count,2)
        self.assertEqual(len(personal.saved_voices(self.user)),2)
        self.assertNotIn('privateNamedA',self.client.get('/kilas-translator').text)
        r,tts,_=self.create(voice='personal:'+str(second['id']))
        self.assertEqual(r.status_code,201);self.assertEqual(tts.call_args.args[1],'privateNamedB');self.assertTrue(tts.call_args.kwargs['personal'])
        job=r.json['id']
        url='/kilas-translator/personal-voices/'+str(second['id'])
        self.assertEqual(self.client.post(url+'/rename',data={'csrf_token':'audio-csrf','name':'Narasi Inggris'}).status_code,200)
        self.assertEqual(personal.saved(self.user,second['id'])['name'],'Narasi Inggris')
        self.assertEqual(self.client.get(url+'/preview').status_code,200)
        with patch.object(provider,'request',return_value={}) as delete:
            self.assertEqual(self.client.post(url+'/delete',data={'csrf_token':'audio-csrf'}).status_code,200)
            delete.assert_called_once_with('DELETE','/voices/privateNamedB',private=True)
        self.assertIsNone(personal.saved(self.user,second['id']))
        self.assertEqual(self.client.get('/kilas-translator/jobs/'+str(job)+'/result').status_code,200)
        self.assertEqual(len(personal.saved_voices(self.user)),1)

    def test_named_library_preserves_legacy_and_owner_isolation(self):
        self.credit()
        f.db.execute('INSERT INTO kilas_audio_personal_voices(user_id,voice_id) VALUES (?,?)',(self.user,'legacySavedPrivate'))
        rows=personal.saved_voices(self.user);ident=rows[0]['id']
        self.assertEqual(len(personal.saved_voices(self.user)),1)
        self.assertEqual(personal.saved(self.user,ident)['voice_id'],'legacySavedPrivate')
        self.assertIsNone(personal.saved(self.other,ident))
        with self.client.session_transaction() as session:session['user_id']=self.other
        for action in ('rename','delete'):
            with patch.object(provider,'request') as call:
                self.assertEqual(self.client.post('/kilas-translator/personal-voices/'+str(ident)+'/'+action,data={'csrf_token':'audio-csrf','name':'Other'}).status_code,404)
                call.assert_not_called()
        self.assertEqual(self.client.get('/kilas-translator/personal-voices/'+str(ident)+'/preview').status_code,404)

    def test_named_library_failed_replace_or_delete_keeps_voice(self):
        self.credit()
        with patch.object(provider,'clone_voice',return_value='savedBeforeFailure'):
            first=self.clone(name='Asli').json
        before=personal.saved_preview(self.user,first['id'])
        with patch.object(provider,'clone_voice',side_effect=provider.ProviderError()):
            self.assertEqual(self.clone(key='named-failed-key-1234',name='Baru',saved_voice_id=str(first['id'])).status_code,503)
        self.assertEqual(personal.saved(self.user,first['id'])['name'],'Asli')
        self.assertEqual(personal.saved_preview(self.user,first['id']),before)
        with patch.object(provider,'request',side_effect=provider.ProviderError()):
            self.assertEqual(self.client.post('/kilas-translator/personal-voices/'+str(first['id'])+'/delete',data={'csrf_token':'audio-csrf'}).status_code,503)
        self.assertIsNotNone(personal.saved(self.user,first['id']))

    def test_named_library_validation_and_csrf(self):
        self.credit()
        with patch.object(provider,'clone_voice') as call:
            self.assertEqual(self.clone(name=' ').status_code,400)
            self.assertEqual(self.clone(name='x'*61).status_code,400)
            self.assertEqual(self.clone(name='Valid',saved_voice_id='999999').status_code,404)
            call.assert_not_called()
        with patch.object(provider,'clone_voice',return_value='csrfSavedPrivate'):
            first=self.clone(name='CSRF').json
        self.assertEqual(self.client.post('/kilas-translator/personal-voices/'+str(first['id'])+'/delete',data={'csrf_token':'bad'}).status_code,400)

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

    def test_private_original_preview_and_legacy_clone(self):
        self.credit()
        f.db.execute("INSERT INTO kilas_audio_personal_voices(user_id,voice_id) VALUES (?,?)",(self.user,'legacyPrivate123'))
        page=self.client.get('/kilas-translator').text
        self.assertIn('Contoh rekaman belum tersedia',page);self.assertEqual(self.client.get('/kilas-translator/personal-voice/preview').status_code,404)
        with patch.object(provider,'clone_voice',return_value='newPrivate123'),patch.object(provider,'delete_voice'):
            self.assertEqual(self.clone(replace='yes').status_code,200)
        preview=self.client.get('/kilas-translator/personal-voice/preview')
        self.assertEqual(preview.status_code,200);self.assertEqual(preview.mimetype,'audio/mpeg')
        self.assertEqual(preview.headers['Cache-Control'],'private, no-store');self.assertLess(media.mp3_duration(preview.data),16000)
        self.assertEqual(preview.data,personal.preview(self.user));self.assertNotIn('newPrivate123',self.client.get('/kilas-translator').text)
        with self.client.session_transaction() as state:state['user_id']=self.other
        self.assertEqual(self.client.get('/kilas-translator/personal-voice/preview').status_code,404)
        self.assertEqual(f.app.app.test_client().get('/kilas-translator/personal-voice/preview').status_code,302)

    def test_failed_replacement_preserves_private_preview(self):
        self.credit()
        with patch.object(provider,'clone_voice',return_value='oldPrivate123'):self.clone()
        before=personal.preview(self.user)
        with patch.object(provider,'clone_voice',side_effect=provider.ProviderError()),patch.object(provider,'delete_voice') as delete:
            self.assertEqual(self.clone(key='failed-replacement-123',replace='yes').status_code,503)
            delete.assert_not_called()
        self.assertEqual(personal.preview(self.user),before);self.assertEqual(personal.get(self.user),'oldPrivate123')

    def test_voice_translation_preview_never_tts_and_edited_text_wins(self):
        from kilas_ai import audio_voice_script as script
        self.credit(300)
        with patch.object(provider,'clone_voice',return_value='ownPrivateVoice123'):self.clone()
        with patch.object(script,'translate',return_value={'text':'Hello, today I am in Bali.','source_language':'id'}) as translate,patch.object(provider,'speech') as tts,patch.object(provider,'dub') as dub:
            r=self.client.post('/kilas-translator/voice-script/translate',data={'csrf_token':'audio-csrf','script':'Halo, hari ini saya berada di Bali.','language':'en'})
            self.assertEqual(r.status_code,200);self.assertEqual(r.json['source_language'],'id');translate.assert_called_once()
            tts.assert_not_called();dub.assert_not_called()
        edited='Hello, today I am enjoying Bali.'
        r,tts,_=self.create(voice='personal',script='Halo, hari ini saya berada di Bali.',translated_script=edited,translate_script='yes',translation_source='id',language='en')
        self.assertEqual(r.status_code,201,r.text);tts.assert_called_once_with(edited,'ownPrivateVoice123','en',personal=True)
        job=store.get(self.user,r.json['id']);self.assertEqual(job['source_language'],'id');self.assertEqual(job['target_language'],'en')
        repeat,tts,_=self.create(voice='personal',script='original',translated_script=edited,translate_script='yes',translation_source='id',language='en')
        self.assertEqual(repeat.json['id'],r.json['id']);tts.assert_not_called()
        off,tts,_=self.create(key='translation-off-key-123',voice='personal',script='Selamat pagi.',translated_script='Ignored translation',language='auto')
        self.assertEqual(off.status_code,201);tts.assert_called_once_with('Selamat pagi.','ownPrivateVoice123','auto',personal=True)

    def test_translation_validation_csrf_balance_and_safe_failure(self):
        from kilas_ai import audio_voice_script as script
        with patch.object(script,'translate') as translate:
            self.assertEqual(self.client.post('/kilas-translator/voice-script/translate',data={'csrf_token':'wrong'}).status_code,400)
            self.assertEqual(self.client.post('/kilas-translator/voice-script/translate',data={'csrf_token':'audio-csrf'}).status_code,402)
            self.credit()
            for text,language in [('', 'en'),('test','bad'),('a'*4001,'en')]:
                self.assertEqual(self.client.post('/kilas-translator/voice-script/translate',data={'csrf_token':'audio-csrf','script':text,'language':language}).status_code,400)
            translate.assert_not_called()
        events=[{'type':'delta','text':'{"text":"Hello.","source_language":"id"}'},{'type':'finish','reason':'stop'}]
        with patch.dict(__import__('os').environ,{'OPENAI_API_KEY':'synthetic'}),patch.object(script.providers,'_openai',return_value=iter(events)) as ai:
            self.assertEqual(script.translate('Halo.','en'),{'text':'Hello.','source_language':'id'})
            self.assertEqual(ai.call_args.args[2],[{'role':'user','content':'Halo.'}])
        with patch.dict(__import__('os').environ,{'OPENAI_API_KEY':'synthetic'}),patch.object(script.providers,'_openai',side_effect=script.providers.ProviderError()):
            with self.assertRaises(store.AudioError):script.translate('Halo.','en')

    def test_same_voice_indonesian_english_original_text(self):
        self.credit(300)
        with patch.object(provider,'clone_voice',return_value='ownPrivateVoice123'):self.clone()
        for i,text in enumerate(('Selamat datang di Kilas Works.','Welcome to Kilas Works. Today we are building something new.')):
            r,speech,_=self.create(key='personal-generation-'+str(i),voice='personal',language='auto',script=text)
            self.assertEqual(r.status_code,201,r.text)
            speech.assert_called_once_with(text,'ownPrivateVoice123','auto',personal=True)
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
