"""Focused Audio prepaid/provider/security tests; all paid provider IO mocked."""
import io
import math
import os
import subprocess
import tempfile
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch, Mock

import test_kilas_autonomous_agent as f
from kilas_ai import audio_store as store, audio_billing as billing, audio_service as service, audio_provider as provider, audio_media as media, video_entitlement, video_director, usage


def wav(seconds=2):
    out=io.BytesIO()
    with wave.open(out,'wb') as a:
        a.setnchannels(1);a.setsampwidth(2);a.setframerate(16000);a.writeframes(b'\0\0'*int(seconds*16000))
    return out.getvalue()


def mp3(seconds=2):
    import imageio_ffmpeg
    with tempfile.TemporaryDirectory() as folder:
        p=Path(folder);(p/'a.wav').write_bytes(wav(seconds))
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(p/'a.wav'),'-y',str(p/'a.mp3')],check=True,capture_output=True,timeout=20)
        return (p/'a.mp3').read_bytes()


class AudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.audio=mp3(2.4)

    def setUp(self):
        f.app.app.config.update(TESTING=True,CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        self.user=f.repo.create_user(self.id()+'@example.test','hash')
        self.other=f.repo.create_user(self.id()+'-other@example.test','hash')
        self.client=f.app.app.test_client()
        with self.client.session_transaction() as s:s.update(user_id=self.user,role='CLIENT_OWNER',_csrf_token='audio-csrf')
        self.voices=[{'id':'actualVoice123','name':'QA Calm','style':'Female · Calm'}]
        self.env=patch.dict(os.environ,{'ELEVENLABS_API_KEY':'synthetic-only'});self.env.start();self.addCleanup(self.env.stop)
        self.transport=patch.object(provider.requests,'request',side_effect=provider.requests.ConnectionError('offline provider mock'))
        self.transport.start();self.addCleanup(self.transport.stop)

    def credit(self,seconds=60):
        f.db.execute('INSERT INTO kilas_audio_balances(user_id,seconds) VALUES (?,?)',(self.user,seconds))

    def create(self,mode='voiceover',key='audio-key-1234567890',**data):
        body={'csrf_token':'audio-csrf','operation_key':key,'mode':mode,'language':'en','voice':'actualVoice123','script':'Hello. This is a safe synthetic audio test.',**data}
        with patch.object(provider,'voices',return_value=self.voices),patch.object(provider,'speech',return_value=(self.audio,'request-1')) as speech,patch.object(provider,'dub',return_value='dubbing123') as dub:
            r=self.client.post('/kilas-translator/jobs',data=body,content_type='multipart/form-data')
        return r,speech,dub

    def test_auth_csrf_and_role(self):
        self.assertEqual(f.app.app.test_client().get('/kilas-translator').status_code,302)
        self.assertEqual(self.client.get('/kilas-translator').status_code,200)
        self.assertEqual(self.client.post('/kilas-translator/jobs',data={'operation_key':'audio-key-1234567890'}).status_code,400)
        f.db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(self.user,))
        self.assertEqual(self.client.get('/kilas-translator').status_code,404)

    def test_zero_no_provider_or_decode(self):
        with patch.object(provider,'request') as paid,patch.object(media,'upload') as decode:
            r,call,dub=self.create();self.assertEqual(r.status_code,402);call.assert_not_called();dub.assert_not_called()
            self.client.get('/kilas-translator');paid.assert_not_called();decode.assert_not_called()

    def test_finance_session_can_open_translator_without_bypassing_gates(self):
        with self.client.session_transaction() as state:
            state['active_product'] = 'finance'
        page = self.client.get('/kilas-translator')
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="voiceover-tab"', page.text)
        self.assertEqual(self.client.get('/products/finance').status_code, 200)
        with self.client.session_transaction() as state:
            self.assertEqual(state['active_product'], 'finance')
        response, speech, dub = self.create()
        self.assertEqual(response.status_code, 402)
        speech.assert_not_called(); dub.assert_not_called()
        self.assertEqual(self.client.post('/kilas-translator/personal-voice',
            data={'consent':'yes','operation_key':'navigation-operation-1234','csrf_token':'wrong'}).status_code, 400)

    def test_insufficient_does_not_submit(self):
        self.credit(1);r,speech,_=self.create();self.assertEqual(r.status_code,402);speech.assert_not_called()

    def test_translator_large_upload_cap_is_scoped_and_enforced(self):
        self.credit()
        # Valid short WAV above the old cap; duration remains the only charge basis.
        # A valid RIFF padding chunk, rather than trailing zeros interpreted as audio.
        import struct
        raw=wav(3)+b'JUNK'+struct.pack('<I',26*1024*1024)+b'\0'*(26*1024*1024)
        raw=raw[:4]+struct.pack('<I',len(raw)-8)+raw[8:]
        with patch.object(provider,'dub',return_value='large-dubbing') as dub:
            inspected=self.client.post('/kilas-translator/inspect',data={'csrf_token':'audio-csrf','file':(io.BytesIO(raw),'large.wav','audio/wav')})
            self.assertEqual(inspected.status_code,200,inspected.text)
            self.assertEqual(inspected.json['required_seconds'],3)
            dub.assert_not_called()
            r,_,submitted=self.create('translate',file=(io.BytesIO(raw),'large.wav','audio/wav'))
            self.assertEqual(r.status_code,201,r.text);submitted.assert_called_once()
        # Per-file cap still applies, and unrelated endpoints keep their original cap.
        oversized=wav()+b'\0'*(100*1024*1024)
        r=self.client.post('/kilas-translator/inspect',data={'csrf_token':'audio-csrf','file':(io.BytesIO(oversized),'large.wav','audio/wav')})
        self.assertEqual(r.status_code,400);self.assertIn('100 MB',r.json['error'])
        r=self.client.post('/register',data={'csrf_token':'audio-csrf','file':(io.BytesIO(raw),'large.wav','audio/wav')})
        self.assertEqual(r.status_code,413)
        self.assertEqual(f.app.app.config['MAX_CONTENT_LENGTH'],12*1024*1024)

    def test_estimate_fits_but_headroom_does_not_blocks_provider(self):
        self.credit(10);r,speech,_=self.create(script='Hello world')
        self.assertEqual(r.status_code,402);speech.assert_not_called()

    def test_stranded_reservation_expires_without_paid_retry(self):
        self.credit()
        ident,_=store.create(self.user,'expired-key-123456789','translate','QA','auto','en','','','',2000,wav(),2,2)
        old=(usage._now()-timedelta(minutes=4)).isoformat();f.db.execute('UPDATE kilas_audio_jobs SET created_at=? WHERE id=?',(old,ident))
        with patch.object(provider,'request') as paid:self.assertEqual(store.balance(self.user)['available'],60);paid.assert_not_called()
        self.assertEqual(store.get(self.user,ident)['status'],'FAILED')

    def test_wav_provider_result_is_real_mp3(self):
        converted,ms=media.ensure_mp3(wav());self.assertFalse(converted.startswith(b'RIFF'));self.assertGreater(ms,0)

    def test_shared_balance_actual_seconds(self):
        self.credit();r,speech,_=self.create();self.assertEqual(r.status_code,201,r.text);speech.assert_called_once()
        job=store.get(self.user,r.json['id']);self.assertEqual(job['status'],'COMPLETED');self.assertEqual(job['seconds_charged'],math.ceil(media.mp3_duration(self.audio)/1000))
        remaining=store.balance(self.user)['seconds']
        r,_,dub=self.create('translate',key='second-audio-key-123456',file=(io.BytesIO(wav(3)),'qa.wav','audio/wav'))
        self.assertEqual(r.status_code,201,r.text);dub.assert_called_once()
        ident=r.json['id'];self.assertEqual(store.balance(self.user)['reserved'],3)
        with patch.object(provider,'dub_status',return_value={'status':'dubbed','source_language':'id'}),patch.object(provider,'dub_result',return_value=self.audio):service.refresh(self.user,ident)
        self.assertEqual(store.balance(self.user)['seconds'],remaining-3)
        self.assertEqual(store.get(self.user,ident)['seconds_charged'],3)
        self.assertEqual(store.get(self.user,ident)['source_language'],'id')

    def test_duplicate_does_not_submit_or_deduct(self):
        self.credit();r,_,_=self.create();first=store.balance(self.user)['seconds']
        repeat,speech,_=self.create();self.assertEqual(repeat.json['id'],r.json['id']);speech.assert_not_called();self.assertEqual(store.balance(self.user)['seconds'],first)

    def test_failed_generation_releases(self):
        self.credit()
        with patch.object(provider,'voices',return_value=self.voices),patch.object(provider,'speech',side_effect=provider.ProviderError()):
            r=self.client.post('/kilas-translator/jobs',data={'csrf_token':'audio-csrf','operation_key':'failed-audio-key-12345','mode':'voiceover','language':'en','voice':'actualVoice123','script':'Hello world'})
        self.assertEqual(store.get(self.user,r.json['id'])['status'],'FAILED');self.assertEqual(store.balance(self.user)['seconds'],60);self.assertEqual(store.balance(self.user)['reserved'],0)

    def test_reconciliation_above_reservation_withholds_output(self):
        self.credit(5)
        ident,_=store.create(self.user,'bound-key-1234567890','voiceover','QA','en','en','voice','QA','hello',0,None,1,5);store.start(self.user,ident)
        with self.assertRaises(store.AudioError):store.finish(self.user,ident,self.audio,6000)
        store.fail(self.user,ident,'output_exceeds_reservation');self.assertEqual(store.balance(self.user)['seconds'],5)
        self.assertEqual(self.client.get(f'/kilas-translator/jobs/{ident}/result').status_code,404)

    def test_concurrent_reservation_single_provider_job(self):
        self.credit()
        def create(i):
            try:return store.create(self.user,'concurrent-audio-key-'+str(i),'translate','QA','auto','en','','','',30000,wav(),30,30)[0]
            except store.AudioError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(create,[1,2]))
        self.assertEqual(sum(x is not None for x in results),1);self.assertEqual(store.balance(self.user)['reserved'],30)

    def test_internal_qa_no_charge_without_balance(self):
        f.db.execute('UPDATE users SET email=? WHERE id=?',('qa-internal-audio@example.test',self.user))
        with patch.dict(os.environ,{'KILAS_AI_INTERNAL_QA_EMAILS':'qa-internal-audio@example.test'}):
            r,_,_=self.create();self.assertEqual(r.status_code,201,r.text);self.assertEqual(store.get(self.user,r.json['id'])['seconds_charged'],0);self.assertTrue(video_entitlement.state(self.user)['allowed'])

    def test_internal_qa_translate_completion_without_balance(self):
        f.db.execute('UPDATE users SET email=? WHERE id=?',('qa-internal-translate@example.test',self.user))
        with patch.dict(os.environ,{'KILAS_AI_INTERNAL_QA_EMAILS':'qa-internal-translate@example.test'}):
            r,_,_=self.create('translate',source_language='id',file=(io.BytesIO(wav()),'qa.wav','audio/wav'))
            self.assertEqual(r.status_code,201,r.text)
            with patch.object(provider,'dub_status',return_value={'status':'dubbed'}),patch.object(provider,'dub_result',return_value=self.audio):service.refresh(self.user,r.json['id'])
            self.assertEqual(store.get(self.user,r.json['id'])['status'],'COMPLETED')
            self.assertEqual(store.get(self.user,r.json['id'])['seconds_charged'],0)
            self.assertEqual(store.balance(self.user)['reserved'],0)

    def test_private_job_result_and_history(self):
        self.credit();r,_,_=self.create();ident=r.json['id']
        self.assertEqual(self.client.get(r.json['url']).status_code,200)
        result=self.client.get(f'/kilas-translator/jobs/{ident}/result?download=1');self.assertEqual(result.status_code,200);self.assertEqual(result.mimetype,'audio/mpeg');self.assertEqual(result.data,self.audio)
        with self.client.session_transaction() as s:s['user_id']=self.other
        for path in (r.json['url'],f'/kilas-translator/jobs/{ident}/result',f'/kilas-translator/jobs/{ident}/status'):self.assertEqual(self.client.get(path).status_code,404)
        self.assertNotIn('safe synthetic audio test',self.client.get('/kilas-translator').text)

    def test_supported_wav_duration_and_invalid_extension_mime(self):
        from werkzeug.datastructures import FileStorage
        for name,mime,raw in [('audio.wav','audio/wav',wav(2.25)),('audio.mp3','audio/mpeg',self.audio)]:
            _,ms,pcm=media.upload(FileStorage(io.BytesIO(raw),filename=name,content_type=mime));self.assertGreater(ms,2000);self.assertTrue(pcm.startswith(b'RIFF'))
        for name,mime,raw in [('file.wav','audio/wav',b'not audio'),('file.exe','audio/mpeg',self.audio),('file.mp3','text/html',self.audio)]:
            with self.assertRaises(media.MediaError):media.upload(FileStorage(io.BytesIO(raw),filename=name,content_type=mime))

    def test_video_audio_track_only(self):
        import imageio_ffmpeg
        from werkzeug.datastructures import FileStorage
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'source.wav').write_bytes(wav())
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i','color=c=white:s=32x32:d=2','-i',str(p/'source.wav'),'-shortest','-c:a','aac','-y',str(p/'source.mp4')],capture_output=True,check=True,timeout=20)
            _,ms,pcm=media.upload(FileStorage(io.BytesIO((p/'source.mp4').read_bytes()),filename='source.mp4',content_type='video/mp4'))
            self.assertLessEqual(ms,2100);self.assertTrue(pcm.startswith(b'RIFF'))

    def test_estimation_uses_actual_finalization(self):
        expected,ceiling=service.estimate('This script is only an estimate.');self.assertGreaterEqual(ceiling,expected)
        self.credit();r,_,_=self.create();job=store.get(self.user,r.json['id']);self.assertNotEqual(job['estimated_seconds'],job['seconds_charged'])

    def test_invalid_script_voice_language_no_paid_calls(self):
        self.credit()
        for data in ({'script':' '},{'voice':'randomInvalid'},{'language':'xx'}):
            r,speech,_=self.create(**data);self.assertGreaterEqual(r.status_code,400);speech.assert_not_called()

    def test_provider_v2_payload_and_personal_v4_no_fallback(self):
        with patch.object(provider,'request',return_value={'project_id':'proj_verified123'}) as call:
            self.assertEqual(provider.dub(wav(),'id','en',1),'proj_verified123')
            args=call.call_args;self.assertEqual(args.args,('POST','/dubbing/project'))
            self.assertEqual(args.kwargs['data'],{'target_language':'en','source_language':'id','reference':'Kilas audio 1','model_id':'dubbing_v2'})
            self.assertEqual(args.kwargs['files']['file'][0],'audio.wav');self.assertEqual(call.call_count,1)
        with patch.object(provider,'request',return_value=(self.audio,'req')) as call:
            provider.speech('Hello','actualVoice123','en');self.assertEqual(call.call_args.kwargs['json']['model_id'],'eleven_multilingual_v2')
            for language in ('id','en'):
                provider.speech('Safe script','ownPrivateVoice123',language,personal=True)
                self.assertEqual(call.call_args.args,('POST','/text-to-speech/ownPrivateVoice123'))
                self.assertEqual(call.call_args.kwargs['json'],{'text':'Safe script','model_id':'eleven_v4','language_code':language,'voice_settings':{'stability':0.5,'similarity_boost':0.75}})
        with patch.object(provider,'request',side_effect=provider.ProviderError()) as call:
            with self.assertRaises(provider.ProviderError):provider.speech('Safe','ownPrivateVoice123','id',personal=True)
            self.assertEqual(call.call_count,1)

    def test_provider_400_safe_diagnostics_and_no_retry(self):
        response=Mock(status_code=400)
        response.iter_content.return_value=[b'{"detail":{"status":"watermark_required","message":"Use watermark. sk_secret user@example.test"}}']
        transport=Mock();transport.__enter__=Mock(return_value=response);transport.__exit__=Mock(return_value=False)
        with patch.object(provider.requests,'request',return_value=transport) as call, self.assertLogs(provider.__name__,level='WARNING') as logs:
            with self.assertRaises(provider.ProviderError) as error:provider.request('POST','/dubbing')
        self.assertEqual(error.exception.code,'provider_http_400');self.assertEqual(call.call_count,1)
        self.assertIn('watermark_required',logs.output[0]);self.assertNotIn('sk_secret',logs.output[0]);self.assertNotIn('user@example.test',logs.output[0])

    def test_v2_ignores_obsolete_watermark_and_detects_language(self):
        with patch.dict(os.environ,{'ELEVENLABS_DUBBING_WATERMARK':'true'}),patch.object(provider,'request',return_value={'project_id':'proj_auto'}) as call:
            provider.dub(wav(),'auto','en',1)
            self.assertNotIn('watermark',call.call_args.kwargs['data']);self.assertNotIn('source_language',call.call_args.kwargs['data'])
            self.assertEqual(call.call_count,1)

    def test_v2_async_and_voice_substitution_warning(self):
        with patch.object(provider,'request',return_value={'status':'preparing'}) as call:
            self.assertEqual(provider.dub_status('proj_test','en')['status'],'preparing');self.assertEqual(call.call_count,1)
        for status in ('queued','processing','failed','completed'):
            with patch.object(provider,'request',side_effect=[{'status':'ready','source_language':'id'},{'languages':[{'target_language':'en','status':status,'outputs':{'lossless_audio':'https://storage.googleapis.com/test'}}]}]):
                self.assertEqual(provider.dub_status('proj_test','en')['status'],status)
        with patch.object(provider,'request',side_effect=[{'status':'ready'},{'languages':[{'target_language':'en','status':'completed','warnings':[{'type':'voices_not_permitted'}]}]}]):
            with self.assertRaises(provider.ProviderError) as caught:provider.dub_status('proj_test','en')
            self.assertEqual(caught.exception.code,'voice_preservation_unavailable')
        with patch.object(provider.requests,'get') as transport:
            for url in ('http://storage.googleapis.com/test','https://evil.example/test','https://storage.googleapis.com@evil.example/test'):
                with self.assertRaises(provider.ProviderError):provider.dub_result('proj_test','en',{'lossless_audio':url})
            transport.assert_not_called()

    def test_v2_warning_keeps_source_history_and_releases_reservation(self):
        self.credit();source=b'\x00\x00\x00\x18ftyp'+b'synthetic'
        ident,_=store.create(self.user,'warning-dub-key-123456','translate','safe.mp4','id','en','','','',2000,source,2,2)
        with patch.object(provider,'dub',return_value='proj_warning'):service.submit(self.user,ident)
        with patch.object(provider,'dub_status',side_effect=provider.ProviderError('voice_preservation_unavailable')),patch.object(provider,'dub_result') as download:
            service.refresh(self.user,ident);download.assert_not_called()
        self.assertEqual(store.get(self.user,ident)['status'],'FAILED')
        self.assertEqual(bytes(store.payload(self.user,ident)['source_content']),source)
        self.assertEqual(store.balance(self.user)['seconds'],60);self.assertEqual(store.balance(self.user)['reserved'],0)
        self.assertEqual(store.history(self.user)[0]['id'],ident)

    def test_v2_flac_audio_and_signed_download_without_credentials(self):
        import imageio_ffmpeg
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'a.wav').write_bytes(wav())
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(p/'a.wav'),'-y',str(p/'a.flac')],check=True,capture_output=True,timeout=20)
            flac=(p/'a.flac').read_bytes()
        output,ms=media.ensure_mp3(flac);self.assertGreater(ms,1900);self.assertGreater(media.mp3_duration(output),1900)
        response=Mock(status_code=200);response.iter_content.return_value=[flac]
        response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        with patch.object(provider.requests,'get',return_value=response) as get:
            self.assertEqual(provider.dub_result('proj_safe','en',{'lossless_audio':'https://storage.googleapis.com/safe?signature=synthetic'}),flac)
            self.assertNotIn('headers',get.call_args.kwargs);self.assertFalse(get.call_args.kwargs['allow_redirects']);self.assertEqual(get.call_count,1)

    def test_v2_video_persists_until_mux_then_private_mp4_and_idempotence(self):
        import imageio_ffmpeg
        self.credit()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'a.wav').write_bytes(wav())
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i','color=c=white:s=32x32:d=2','-i',str(p/'a.wav'),'-shortest','-c:a','aac','-y',str(p/'v.mp4')],check=True,capture_output=True,timeout=20)
            original=(p/'v.mp4').read_bytes()
        with patch.object(provider,'dub',return_value='proj_video') as paid:
            r=self.client.post('/kilas-translator/jobs',data={'csrf_token':'audio-csrf','operation_key':'video-dub-key-123456','mode':'translate','source_language':'id','language':'en','file':(io.BytesIO(original),'qa.mp4','video/mp4')})
            self.assertEqual(r.status_code,201,r.text);paid.assert_called_once()
        ident=r.json['id'];self.assertEqual(bytes(store.payload(self.user,ident)['source_content']),original)
        with patch.object(provider,'dub_status',return_value={'status':'completed','source_language':'id','outputs':{'lossless_audio':'safe'}}),patch.object(provider,'dub_result',return_value=wav()) as result,patch.object(provider,'dub') as paid:
            service.refresh(self.user,ident);service.refresh(self.user,ident);paid.assert_not_called();result.assert_called_once()
        job=store.get(self.user,ident);self.assertEqual(job['status'],'COMPLETED');self.assertTrue(job['result_is_video'])
        self.assertIsNone(store.payload(self.user,ident)['source_content'])
        self.assertEqual(job['seconds_charged'],math.ceil(job['source_ms']/1000))
        page=self.client.get(f'/kilas-translator/jobs/{ident}');self.assertIn('<video controls',page.text);self.assertIn('Download MP4',page.text)
        downloaded=self.client.get(f'/kilas-translator/jobs/{ident}/result?download=1')
        self.assertEqual(downloaded.mimetype,'video/mp4');self.assertEqual(downloaded.data[4:8],b'ftyp')
        self.assertIn('.mp4',downloaded.headers['Content-Disposition'])
        with self.client.session_transaction() as state:state['user_id']=self.other
        self.assertEqual(self.client.get(f'/kilas-translator/jobs/{ident}/result').status_code,404)

    def test_multipart_translator_files_are_disk_backed(self):
        from flask import request
        with f.app.app.test_request_context('/kilas-translator/inspect',method='POST',data={'file':(io.BytesIO(wav()),'qa.wav','audio/wav')}):
            uploaded=request.files['file']
            self.assertNotIsInstance(uploaded.stream,io.BytesIO)
            self.assertGreaterEqual(uploaded.stream.fileno(),0)

    def test_ambiguous_translate_never_posts_again_and_releases_balance(self):
        self.credit()
        with patch.object(provider,'dub',side_effect=provider.ProviderError('provider_transport')) as paid:
            data={'csrf_token':'audio-csrf','operation_key':'ambiguous-translate-key-123','mode':'translate','source_language':'id','language':'en'}
            r=self.client.post('/kilas-translator/jobs',data={**data,'file':(io.BytesIO(wav()),'qa.wav','audio/wav')})
            ident=r.json['id']
            repeat=self.client.post('/kilas-translator/jobs',data={**data,'file':(io.BytesIO(wav()),'qa.wav','audio/wav')})
            self.assertEqual(repeat.json['id'],ident)
            self.client.get(f'/kilas-translator/jobs/{ident}/status');paid.assert_called_once()
        job=store.get(self.user,ident);self.assertEqual(job['seconds_charged'],0)
        self.assertEqual(store.balance(self.user)['reserved'],0);self.assertEqual(store.balance(self.user)['seconds'],60)

    def test_translate_persists_same_project_and_completed_download_after_refresh(self):
        self.credit()
        r,_,_=self.create('translate',source_language='id',file=(io.BytesIO(wav()),'qa.wav','audio/wav'))
        ident=r.json['id'];job=store.get(self.user,ident)
        self.assertEqual(job['provider_id'],'dubbing123');self.assertIsNone(store.payload(self.user,ident)['source_content'])
        with patch.object(provider,'dub_status',return_value={'status':'dubbed','source_language':'id'}) as poll,patch.object(provider,'dub_result',return_value=wav()) as result,patch.object(provider,'dub') as paid:
            self.client.get(f'/kilas-translator/jobs/{ident}/status')
            poll.assert_called_once_with('dubbing123');result.assert_called_once_with('dubbing123','en');paid.assert_not_called()
        self.assertEqual(store.get(self.user,ident)['source_language'],'id')
        self.assertIn('Translation complete',self.client.get(r.json['url']).text)
        output=self.client.get(f'/kilas-translator/jobs/{ident}/result?download=1')
        self.assertEqual(output.mimetype,'audio/mpeg');self.assertIn('attachment',output.headers['Content-Disposition'])
        self.assertGreater(media.mp3_duration(output.data),0)

    def test_streamed_mp4_above_25mb_cleanup_and_bounded_db_audio(self):
        import imageio_ffmpeg
        from werkzeug.datastructures import FileStorage
        class BoundedReader:
            def __init__(self,stream):self.stream=stream
            def read(self,n):
                self.assert_size(n)
                return self.stream.read(n)
            def assert_size(self,n):
                if not 0<n<=65536:raise AssertionError('unbounded source read')
        directories=[];original=media.tempfile.TemporaryDirectory
        def tracked(**kwargs):
            context=original(**kwargs);directories.append(Path(context.name));return context
        self.credit()
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'audio.wav').write_bytes(wav())
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i','color=c=white:s=32x32:d=2','-i',str(p/'audio.wav'),'-shortest','-c:a','aac','-y',str(p/'video.mp4')],capture_output=True,check=True,timeout=20)
            with (p/'video.mp4').open('ab') as output:
                for _ in range(26):output.write(b'\0'*(1024*1024))
            with (p/'video.mp4').open('rb') as source,patch.object(media.tempfile,'TemporaryDirectory',side_effect=tracked):
                name,ms,pcm=media.upload(FileStorage(BoundedReader(source),filename='../../outside/video.mp4',content_type='video/mp4'))
            self.assertFalse(any(path.exists() for path in directories));self.assertNotIn('/',name)
            self.assertLess(len(pcm),100000);self.assertLessEqual(ms,2100)
            ident,_=store.create(self.user,'bounded-source-key-12345','translate','QA','id','en','','name','',ms,pcm,3,3)
            self.assertLess(len(store.payload(self.user,ident)['source_content']),100000)

    def test_size_limits_streamed_cleanup_on_rejection(self):
        from werkzeug.datastructures import FileStorage
        class SizedSource:
            def __init__(self,size,head):self.left=size;self.head=head
            def read(self,n):
                if not 0<n<=65536:raise AssertionError('unbounded upload read')
                take=min(n,self.left);self.left-=take
                if not take:return b''
                head=self.head;self.head=b''
                return head+b'\0'*(take-len(head))
        for ext,mime,limit,head in [('mp4','video/mp4',250,b'\0\0\0\x18ftypisom'),('wav','audio/wav',100,b'RIFF0000WAVE')]:
            self.assertEqual(media.file_limit(ext),limit*1024*1024)
            for extra in [0,1]:
                with patch.object(media,'_decode_source',return_value=(2000,wav())) as decoded:
                    item=FileStorage(SizedSource(limit*1024*1024+extra,head),filename='limit.'+ext,content_type=mime)
                    if extra:
                        with self.assertRaises(media.MediaError):media.upload(item)
                        decoded.assert_not_called()
                    else:media.upload(item);decoded.assert_called_once()
        self.assertEqual(media.duration_limit(),600)

    def test_m4a_supported_and_ten_minute_duration_enforced(self):
        import imageio_ffmpeg
        from werkzeug.datastructures import FileStorage
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'audio.wav').write_bytes(wav())
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(p/'audio.wav'),'-c:a','aac','-y',str(p/'audio.m4a')],capture_output=True,check=True,timeout=20)
            with (p/'audio.m4a').open('rb') as source:
                _,ms,_=media.upload(FileStorage(source,filename='audio.m4a',content_type='audio/mp4'));self.assertGreater(ms,1900)
        with self.assertRaises(media.MediaError):media.decode(wav(601),'wav')
        self.assertEqual(media.decode(wav(600),'wav')[0],600000)
        with self.assertRaises(media.MediaError):media.decode(wav(),'../../arbitrary')

    def test_curated_actual_available_voice_ids_stable(self):
        raw={'voices':[{'voice_id':'valid'+str(i),'name':'Voice '+str(i),'labels':{'gender':'female','description':'calm'}} for i in range(8)]}
        with patch.object(provider,'_voices',None),patch.object(provider,'request',return_value=raw):
            one=provider.voices();two=provider.voices();self.assertEqual(one,two);self.assertEqual(len(one),4);self.assertTrue(all(v['id'].startswith('valid') for v in one))

    def test_packs_exact_verified_credit_idempotent_independent_ai(self):
        admin=f.repo.create_user(self.id()+'admin@example.test','hash',role='KILAS_ADMIN')
        from PIL import Image
        from werkzeug.datastructures import FileStorage
        for pack,(seconds,price) in store.PACKS.items():
            ident=billing.create(self.user,pack);self.assertEqual(billing.create(self.user,pack),ident)
            raw=io.BytesIO();Image.new('RGB',(30,30),'white').save(raw,'PNG')
            billing.proof(self.user,ident,FileStorage(io.BytesIO(raw.getvalue()),filename='proof.png',content_type='image/png'))
            before=store.balance(self.user)['seconds'];billing.review(ident,admin,'VERIFIED');billing.review(ident,admin,'VERIFIED')
            self.assertEqual(store.balance(self.user)['seconds']-before,seconds);self.assertEqual(billing.order(self.user,ident)['amount_idr'],price)
        self.assertEqual(store.balance(self.user)['seconds'],960);self.assertEqual(usage.effective_plan(self.user)['plan'],'FREE')

    def test_payment_privilege_and_foreign_invoice(self):
        ident=billing.create(self.user,'MINUTE')
        with self.assertRaises(store.AudioError):billing.review(ident,self.user,'VERIFIED')
        self.assertEqual(store.balance(self.user)['seconds'],0)
        with self.client.session_transaction() as s:s['user_id']=self.other
        self.assertEqual(self.client.get(f'/kilas-translator/orders/{ident}').status_code,404)

    def test_poll_failure_then_success_without_second_submission(self):
        self.credit();r,_,_=self.create('translate',file=(io.BytesIO(wav()),'qa.wav','audio/wav'));ident=r.json['id']
        with patch.object(provider,'dub_status',side_effect=provider.ProviderError()),patch.object(provider,'dub') as paid:service.refresh(self.user,ident);paid.assert_not_called()
        self.assertEqual(store.get(self.user,ident)['status'],'PROCESSING');self.assertEqual(store.balance(self.user)['reserved'],2)
        f.db.execute('UPDATE kilas_audio_jobs SET poll_until=NULL WHERE id=?',(ident,))
        with patch.object(provider,'dub_status',return_value={'status':'failed'}):service.refresh(self.user,ident)
        self.assertEqual(store.balance(self.user)['reserved'],0);self.assertEqual(store.balance(self.user)['seconds'],60)

    def test_missing_key_safe_state(self):
        self.credit()
        with patch.dict(os.environ,{'ELEVENLABS_API_KEY':''}):
            r,speech,_=self.create();self.assertEqual(r.status_code,503);speech.assert_not_called();self.assertEqual(store.balance(self.user)['seconds'],60)

    def test_video_zero_quota_before_model_or_new_project(self):
        self.assertFalse(video_entitlement.state(self.user)['allowed'])
        with patch.object(video_director.requests,'post') as paid:
            r=self.client.post('/kilas-ai/video/plan',data={'csrf_token':'audio-csrf','operation_key':'video-gate-key-1234567','idea':'coffee storyboard'})
            self.assertEqual(r.status_code,402);self.assertIn('Kuota Kilas Video belum tersedia',r.text);paid.assert_not_called()
        self.assertEqual(f.db.query_one('SELECT COUNT(*) AS n FROM kilas_video_projects WHERE user_id=?',(self.user,))['n'],0)
        self.assertIn('Lihat Paket',self.client.get('/kilas-ai/video').text)

    def test_video_active_and_exhausted_capacity(self):
        now=usage._now();f.db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?)",(self.user,now.isoformat(),(now+timedelta(days=30)).isoformat()))
        self.assertTrue(video_entitlement.state(self.user)['allowed'])
        with patch('kilas_ai.capacity.spent',return_value=100):
            gate=video_entitlement.state(self.user);self.assertFalse(gate['allowed']);self.assertEqual(gate['reason'],'exhausted')


if __name__=='__main__':unittest.main()
