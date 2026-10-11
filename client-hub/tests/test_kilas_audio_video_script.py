"""VO video -> original-language text, finite independent cost admission; no paid IO."""
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, Mock
import test_kilas_audio as audio_fixture
from test_kilas_audio import f, wav
from kilas_ai import audio_transcription_budget as budget, audio_transcription_provider as stt, transcription_provider as old_stt


class VideoScriptTests(unittest.TestCase):
    setUp=audio_fixture.AudioTests.setUp
    credit=audio_fixture.AudioTests.credit

    @classmethod
    def setUpClass(cls):
        cls.legacy_audio=audio_fixture.mp3(2.4)
        import imageio_ffmpeg
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'a.wav').write_bytes(wav())
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i','color=c=white:s=32x32:d=2','-i',str(p/'a.wav'),'-shortest','-c:a','aac','-y',str(p/'v.mp4')],capture_output=True,check=True,timeout=20)
            cls.video=(p/'v.mp4').read_bytes()
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i','color=c=white:s=32x32:d=2','-an','-y',str(p/'silent.mp4')],capture_output=True,check=True,timeout=20)
            cls.silent_video=(p/'silent.mp4').read_bytes()

    def funded(self,global_micro=90000,account_micro=60000):
        return patch.dict(os.environ,{'ELEVENLABS_API_KEY':'synthetic-only','KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'true','KILAS_VO_STT_CAMPAIGN':'synthetic-'+str(self.user),'KILAS_VO_STT_GLOBAL_BUDGET_MICRO_USD':str(global_micro),'KILAS_VO_STT_ACCOUNT_BUDGET_MICRO_USD':str(account_micro),'KILAS_VO_STT_EXPIRES_AT':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'KILAS_VO_STT_PRICE_VERSION':budget.PRICE_VERSION})

    def post(self,key='video-script-operation-1234',**fields):
        return self.client.post('/kilas-translator/voice-script/video',data={'csrf_token':'audio-csrf','operation_key':key,'consent':'yes','video':(io.BytesIO(self.video),'source.mp4','video/mp4'),**fields})

    def response(self,text='Ini ucapan asli, bukan terjemahan.',usage=None):
        response=Mock(status_code=200)
        response.iter_content.return_value=[json.dumps({'text':text,'language_code':'id','language_probability':0.99,'words':[],**({'usage':usage} if usage is not None else {})}).encode()]
        context=Mock();context.__enter__=Mock(return_value=response);context.__exit__=Mock(return_value=False)
        return context

    def legacy_job(self,owner=None,mode='voiceover',status='COMPLETED',original=None,raw=None):
        owner=self.user if owner is None else owner
        f.db.execute("INSERT INTO kilas_audio_jobs(user_id,operation_key,fingerprint,mode,title,source_language,target_language,estimated_seconds,reserved_seconds,actual_ms,seconds_charged,status,original_script,result_content,created_at,updated_at) VALUES (?,?,?,?,?,'id','en',3,0,2400,3,?,?,?,?,?)",(owner,'legacy-'+os.urandom(8).hex(),'unchanged-fingerprint',mode,'Legacy output',status,original,self.legacy_audio if raw is None else raw,'2026-01-01','2026-01-01'))
        return f.db.query_one('SELECT MAX(id) AS id FROM kilas_audio_jobs WHERE user_id=?',(owner,))['id']

    def reconstruct(self,ident,**fields):
        return self.client.post('/kilas-translator/jobs/'+str(ident)+'/reconstruct-script',data={'csrf_token':'audio-csrf','consent':'yes','operation_key':'legacy-'+str(ident)+'-synthetic-operation-1234',**fields})

    def test_legacy_reconstruction_preserves_entire_job_and_never_restores_original(self):
        ident=self.legacy_job();before=f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(ident,))
        with self.funded(),patch.object(stt.requests,'post',return_value=self.response('Spoken English output.')) as paid,patch('requests.sessions.Session.request',side_effect=AssertionError('No other external transport')):
            result=self.reconstruct(ident);self.assertEqual(result.status_code,200);self.assertEqual(result.json['text'],'Spoken English output.')
            self.assertEqual(result.json['source_kind'],'audio_reconstruction');self.assertEqual(result.json['job_id'],ident);self.assertIn('no-store',result.headers['Cache-Control'])
            self.assertEqual(self.reconstruct(ident).json['status'],'COMPLETED');self.assertEqual(paid.call_count,1)
        self.assertEqual(f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE id=?',(ident,)),before)
        self.assertIsNone(f.db.query_one('SELECT seconds FROM kilas_audio_balances WHERE user_id=?',(self.user,)))

    def test_legacy_original_first_no_cost_and_cancellation_after_original_appears(self):
        ident=self.legacy_job(original='Exact archived original.')
        with patch.dict(os.environ,{'KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'false'}),patch.object(stt.requests,'post') as paid,patch('kilas_ai.audio_media.decode') as decode:
            response=self.reconstruct(ident,consent='no');self.assertEqual(response.json['text'],'Exact archived original.');self.assertEqual(response.json['source_kind'],'original_script');paid.assert_not_called();decode.assert_not_called()
        old=self.legacy_job();key='legacy-'+str(old)+'-synthetic-operation-1234';raw,ms=stt.normalize(wav());digest=hashlib.sha256(raw).hexdigest()
        with self.funded():
            _,cap=budget.claim(self.user,key,digest,ms);budget.dispatch(cap,digest,ms)
            f.db.execute('UPDATE kilas_audio_jobs SET original_script=? WHERE id=?',('Original arrived later.',old))
            self.assertEqual(self.reconstruct(old,action='cancel').json['status'],'CANCELLED');self.assertFalse(budget.finish(cap,True))
            status=self.client.get('/kilas-translator/jobs/'+str(old)+'/reconstruct-script?operation_key='+key)
            self.assertEqual(status.json['status'],'CANCELLED');self.assertNotIn('text',status.json)

    def test_legacy_guard_ownership_mode_status_media_csrf_consent_and_off(self):
        good=self.legacy_job();invalid=[self.legacy_job(owner=self.other),self.legacy_job(mode='translate'),self.legacy_job(status='FAILED'),self.legacy_job(status='QUEUED')]
        with self.funded(),patch.object(stt.requests,'post') as paid,patch('kilas_ai.audio_media.decode') as decode:
            for ident in invalid:self.assertEqual(self.reconstruct(ident).status_code,404)
            self.assertEqual(self.reconstruct(good,csrf_token='wrong').status_code,400)
            self.assertEqual(self.reconstruct(good,consent='no').status_code,400)
            self.assertEqual(self.reconstruct(good,operation_key='legacy-wrong-operation-1234').status_code,400)
            for raw in (b'',b'not MP3',b'ID3'+b'x'*(20*1024*1024)):
                f.db.execute('UPDATE kilas_audio_jobs SET result_content=? WHERE id=?',(raw,good));self.assertEqual(self.reconstruct(good).status_code,400)
            with patch.dict(os.environ,{'KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'false'}):
                response=self.reconstruct(good);self.assertEqual(response.status_code,503);self.assertIn('belum diaktifkan',response.json['error'])
            paid.assert_not_called();decode.assert_not_called()

    def test_default_unavailable_keeps_old_stt_guard_and_no_decode_or_provider(self):
        with patch.dict(os.environ,{'KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'false'}),patch.object(stt.requests,'post') as paid,patch('kilas_ai.audio_media.upload') as decode:
            self.assertFalse(budget.ready());self.assertFalse(old_stt.budget_ready())
            response=self.post();self.assertEqual(response.status_code,503);self.assertEqual(response.json['code'],'budget_unavailable');paid.assert_not_called();decode.assert_not_called()
            html=self.client.get('/kilas-translator?mode=voiceover').text
            self.assertIn('data-ready="false"',html);self.assertIn('Batas biaya transkripsi belum diaktifkan',html)
            title=html.split('<title>',1)[1].split('</title>',1)[0];self.assertNotIn('<script',title)
            self.assertEqual(html.count('id="audio-script"'),1)

    def test_real_mp4_decode_original_text_only_no_tts_job_or_credit_debit(self):
        self.credit(60);before=f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs')['n']
        with self.funded(),patch.object(stt.requests,'post',return_value=self.response()) as paid,patch('requests.sessions.Session.request',side_effect=AssertionError('External transport forbidden')):
            response=self.post();self.assertEqual(response.status_code,200);self.assertEqual(response.json['text'],'Ini ucapan asli, bukan terjemahan.')
            self.assertEqual(response.json['status'],'COMPLETED');self.assertIn('no-store',response.headers['Cache-Control'])
            args=paid.call_args;self.assertEqual(args.args[0],'https://api.elevenlabs.io/v1/speech-to-text');self.assertEqual(args.kwargs['data']['model_id'],'scribe_v2')
            self.assertEqual(args.kwargs['headers'],{'xi-api-key':'synthetic-only'});self.assertEqual(args.kwargs['params'],{'enable_logging':'true'})
            self.assertFalse(args.kwargs['allow_redirects']);self.assertTrue(args.kwargs['stream'])
            for flag in ('tag_audio_events','diarize','webhook','use_multi_channel','use_speaker_library','detect_speaker_roles','no_verbatim'):self.assertEqual(args.kwargs['data'][flag],'false')
            for absent in ('language_code','transcript_edit','keyterms','source_url','cloud_storage_url','entity_detection','entity_redaction'):self.assertNotIn(absent,args.kwargs['data'])
            self.assertEqual(args.kwargs['files']['file'][0],'recording.wav')
            self.assertEqual(self.post().json['status'],'COMPLETED');self.assertEqual(paid.call_count,1)
            self.assertEqual(self.client.get('/kilas-translator/voice-script/video?operation_key=video-script-operation-1234').json,{'status':'COMPLETED','operation_key':'video-script-operation-1234'})
        self.assertEqual(f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs')['n'],before)
        self.assertEqual(f.db.query_one('SELECT seconds FROM kilas_audio_balances WHERE user_id=?',(self.user,))['seconds'],60)
        row=f.db.query_one('SELECT * FROM kilas_vo_stt_operations WHERE user_id=?',(self.user,));self.assertEqual(row['charge_micro'],budget.reserve_micro(row['duration_ms']));self.assertIsNone(row['actual_estimate_micro']);self.assertIsNone(row['input_tokens']);self.assertIsNone(row['output_tokens']);self.assertNotIn('text',row)

    def test_consent_csrf_auth_mime_size_and_missing_audio_before_provider(self):
        with self.funded(),patch.object(stt.requests,'post') as paid:
            self.assertEqual(self.post(consent='no').status_code,400)
            self.assertEqual(self.post(csrf_token='wrong').status_code,400)
            self.assertEqual(self.post(video=(io.BytesIO(wav()),'spoof.mp4','video/mp4')).status_code,400)
            self.assertEqual(self.post(video=(io.BytesIO(self.video),'source.mp4','text/plain')).status_code,400)
            self.assertEqual(self.post(video=(io.BytesIO(wav()),'source.wav','audio/wav')).status_code,400)
            paid.assert_not_called()
        other=f.app.app.test_client()
        with other.session_transaction() as s:s.update(user_id=self.other,role='CLIENT_OWNER')
        self.assertEqual(other.get('/kilas-translator/voice-script/video?operation_key=video-script-operation-1234').status_code,404)
        self.assertEqual(f.app.app.test_client().get('/kilas-translator/voice-script/video?operation_key=video-script-operation-1234').status_code,302)

    def test_output_over_limit_is_not_truncated_and_failure_spend_not_retried(self):
        with self.funded(),patch.object(stt.requests,'post',return_value=self.response('x'*4001)) as paid:
            response=self.post();self.assertEqual(response.status_code,422);self.assertEqual(response.json['code'],'script_too_long')
            self.assertEqual(self.post().json['status'],'FAILED');self.assertEqual(paid.call_count,1)
        row=f.db.query_one('SELECT charge_micro,duration_ms FROM kilas_vo_stt_operations WHERE user_id=?',(self.user,));self.assertEqual(row['charge_micro'],budget.reserve_micro(row['duration_ms']))

    def test_capability_fingerprint_nonce_and_duplicate_dispatch(self):
        raw,ms=stt.normalize(wav());digest=hashlib.sha256(raw).hexdigest()
        with self.funded(),patch.object(stt.requests,'post') as paid:
            _,cap=budget.claim(self.user,'capability-operation-1234',digest,ms)
            for invalid in (None,budget.Reservation(self.other,cap.key,cap.lease),budget.Reservation(cap.owner,cap.key,'forged')):
                with self.assertRaises(budget.BudgetError):stt.transcribe(raw,invalid)
            paid.assert_not_called()
            f.db.execute('UPDATE kilas_vo_stt_operations SET charge_micro=0 WHERE user_id=? AND operation_key=?',(self.user,cap.key))
            with self.assertRaises(budget.BudgetError):stt.transcribe(raw,cap)
            paid.assert_not_called()
            f.db.execute('UPDATE kilas_vo_stt_operations SET charge_micro=? WHERE user_id=? AND operation_key=?',(budget.reserve_micro(ms),self.user,cap.key))
            budget.dispatch(cap,digest,ms)
            with self.assertRaises(budget.BudgetError):budget.dispatch(cap,digest,ms)
            with self.assertRaises(budget.BudgetError):budget.claim(self.user,cap.key,'a'*64,ms)

    def test_global_atomic_cap_and_parallel_same_key_claim(self):
        raw,ms=stt.normalize(wav());digest=hashlib.sha256(raw).hexdigest()
        with self.funded(global_micro=budget.reserve_micro(ms),account_micro=budget.reserve_micro(ms)):
            def claim(owner):
                try:return budget.claim(owner,'parallel-claim-operation-1234',digest,ms)[1]
                except budget.BudgetError:return None
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(claim,(self.user,self.other)))
            self.assertEqual(sum(x is not None for x in results),1)
            cap=next(x for x in results if x is not None);self.assertIsNone(budget.claim(cap.owner,cap.key,digest,ms)[1])
            self.assertEqual(f.db.query_one('SELECT SUM(charge_micro) AS n FROM kilas_vo_stt_operations WHERE campaign=?',(budget.policy()['id'],))['n'],budget.reserve_micro(ms))

    def test_cancel_fences_before_dispatch_and_keeps_unknown_spend(self):
        raw,ms=stt.normalize(wav());digest=hashlib.sha256(raw).hexdigest()
        with self.funded():
            budget.cancel(self.user,'cancel-before-operation-1234')
            self.assertIsNone(budget.claim(self.user,'cancel-before-operation-1234',digest,ms)[1])
            _,cap=budget.claim(self.user,'cancel-after-operation-1234',digest,ms);budget.dispatch(cap,digest,ms)
            budget.cancel(self.user,cap.key);self.assertFalse(budget.finish(cap,True))
            row=f.db.query_one('SELECT * FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(self.user,cap.key));self.assertEqual(row['status'],'CANCELLED');self.assertEqual(row['charge_micro'],budget.reserve_micro(row['duration_ms']))

    def test_missing_invalid_expired_policy_is_failclosed(self):
        raw,ms=stt.normalize(wav());digest=hashlib.sha256(raw).hexdigest()
        for field,value in (('KILAS_VO_STT_GLOBAL_BUDGET_MICRO_USD',''),('KILAS_VO_STT_ACCOUNT_BUDGET_MICRO_USD','0'),('KILAS_VO_STT_EXPIRES_AT','2000-01-01T00:00:00Z'),('KILAS_VO_STT_EXPIRES_AT','2099-01-01'),('KILAS_VO_STT_PRICE_VERSION','unknown'),('KILAS_VO_STT_CAMPAIGN','../bad')):
            with self.subTest(field=field),self.funded(),patch.dict(os.environ,{field:value}),patch.object(stt.requests,'post') as paid:
                self.assertFalse(budget.ready())
                with self.assertRaises(budget.BudgetError):budget.claim(self.user,'invalid-policy-operation-1234',digest,ms)
                paid.assert_not_called()

    def test_invalid_timeout_and_missing_usage_keep_full_reservation(self):
        # Synthetic failures only; no retry and no customer Audio debit.
        for index,kind in enumerate(('timeout','malformed','missing_usage')):
            case=VideoScriptTests('test_default_unavailable_keeps_old_stt_guard_and_no_decode_or_provider');case.id=lambda:'failure-fixture-'+kind;case.setUp()
            try:
                response=case.response(); response.__enter__.return_value.iter_content.return_value=[b'{'] if kind=='malformed' else [b'{"text":"Original text"}']
                with case.funded(),patch.object(stt.requests,'post',side_effect=stt.requests.Timeout() if kind=='timeout' else None,return_value=response) as paid:
                    result=case.post();self.assertEqual(result.status_code,200 if kind=='missing_usage' else 503)
                    self.assertEqual(case.post().json['status'],'COMPLETED' if kind=='missing_usage' else 'FAILED');self.assertEqual(paid.call_count,1)
                row=f.db.query_one('SELECT charge_micro,actual_estimate_micro,duration_ms FROM kilas_vo_stt_operations WHERE user_id=?',(case.user,));self.assertEqual(row['charge_micro'],budget.reserve_micro(row['duration_ms']));self.assertIsNone(row['actual_estimate_micro'])
            finally:case.doCleanups()

    def test_oversize_duration_no_audio_reject_and_delete_private_temps(self):
        from kilas_ai import audio_media
        real_temp=audio_media.tempfile.TemporaryDirectory;folders=[]
        def tracked(*args,**kwargs):
            result=real_temp(*args,**kwargs);folders.append(Path(result.name));return result
        with self.funded(),patch.object(stt.requests,'post') as paid,patch.object(audio_media.tempfile,'TemporaryDirectory',side_effect=tracked):
            self.assertEqual(self.post(video=(io.BytesIO(self.silent_video),'silent.mp4','video/mp4')).status_code,400)
            with patch.object(audio_media,'duration_limit',return_value=1):self.assertEqual(self.post().status_code,400)
            with patch.object(audio_media,'file_limit',return_value=100):self.assertEqual(self.post().status_code,400)
            paid.assert_not_called()
        self.assertTrue(folders);self.assertTrue(all(not folder.exists() for folder in folders))

    def test_minimum_audio_and_slow_stream_failure_hold_allowance(self):
        import wave
        def pcm(frames):
            raw=io.BytesIO()
            with wave.open(raw,'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0'*(frames*2))
            return raw.getvalue()
        with self.funded(),patch.object(stt.requests,'post') as paid:
            for frames in (1,1599):
                with self.assertRaises(budget.BudgetError):stt.normalize(pcm(frames))
            self.assertEqual(stt.normalize(pcm(1600))[1],100);paid.assert_not_called()
        with self.funded(),patch.object(stt.requests,'post',return_value=self.response()) as paid,patch.object(stt,'monotonic',side_effect=(0,61)):
            response=self.post();self.assertEqual(response.status_code,503);self.assertEqual(response.json['code'],'transcription_failed');self.assertNotIn('text',response.json)
            self.assertEqual(self.post().json['status'],'FAILED');self.assertEqual(paid.call_count,1)
        row=f.db.query_one('SELECT * FROM kilas_vo_stt_operations WHERE user_id=?',(self.user,))
        self.assertEqual(row['status'],'FAILED');self.assertEqual(row['charge_micro'],budget.reserve_micro(row['duration_ms']))

    def test_duration_ceiling_and_off_inflight_finish_without_invoice_claim(self):
        for ms,expected in ((1,1),(1000,62),(1001,62),(60000,3667),(600000,36667)):
            self.assertEqual(budget.reserve_micro(ms),expected)
        for invalid in (True,0,-1,600001,1.5):
            with self.assertRaises(budget.BudgetError):budget.reserve_micro(invalid)
        raw,ms=stt.normalize(wav());digest=hashlib.sha256(raw).hexdigest()
        with self.funded():
            _,cap=budget.claim(self.user,'inflight-operation-1234',digest,ms);budget.dispatch(cap,digest,ms)
            with patch.dict(os.environ,{'KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'false'}):self.assertTrue(budget.finish(cap,True))
            row=f.db.query_one('SELECT * FROM kilas_vo_stt_operations WHERE user_id=?',(self.user,))
            self.assertEqual(row['charge_micro'],budget.reserve_micro(ms));self.assertIsNone(row['actual_estimate_micro'])

    def test_ten_minute_reservation_enforces_full_duration_cap(self):
        with self.funded(global_micro=36666,account_micro=36666):
            with self.assertRaises(budget.BudgetError) as denied:budget.claim(self.user,'ten-minute-operation-1234','a'*64,600000)
            self.assertEqual(denied.exception.code,'budget_limit')
        with self.funded(global_micro=36667,account_micro=36667),patch.dict(os.environ,{'KILAS_VO_STT_CAMPAIGN':'ten-minute-funded'}):
            budget.claim(self.user,'ten-minute-operation-1234','a'*64,600000)
            row=f.db.query_one('SELECT charge_micro FROM kilas_vo_stt_operations WHERE user_id=?',(self.user,))
            self.assertEqual(row['charge_micro'],36667)

    def test_old_price_version_cannot_admit_or_settle_as_new_provider(self):
        raw,ms=stt.normalize(wav());digest=hashlib.sha256(raw).hexdigest()
        with self.funded(),patch.object(stt.requests,'post') as paid:
            _,cap=budget.claim(self.user,'old-price-operation-1234',digest,ms)
            f.db.execute("UPDATE kilas_vo_stt_campaigns SET price_version='openai-mini-transcribe-20261011-standard' WHERE id=?",(budget.policy()['id'],))
            with self.assertRaises(budget.BudgetError):stt.transcribe(raw,cap)
            paid.assert_not_called()
            f.db.execute("UPDATE kilas_vo_stt_operations SET status='DISPATCHED' WHERE user_id=?",(self.user,))
            self.assertFalse(budget.finish(cap,True))
            self.assertEqual(f.db.query_one('SELECT status FROM kilas_vo_stt_operations WHERE user_id=?',(self.user,))['status'],'UNKNOWN')
            self.assertEqual(f.db.query_one('SELECT blocked FROM kilas_vo_stt_campaigns WHERE id=?',(budget.policy()['id'],))['blocked'],1)

    def test_access_denied_redirect_and_unknown_token_usage_do_not_change_allowance(self):
        for kind in ('access_denied','redirect','oversized','fake_tokens'):
            case=VideoScriptTests('test_default_unavailable_keeps_old_stt_guard_and_no_decode_or_provider');case.id=lambda:'protocol-'+kind;case.setUp()
            try:
                response=case.response(usage={'type':'tokens','input_tokens':99999999,'output_tokens':99999999})
                response.__enter__.return_value.status_code={'access_denied':403,'redirect':302,'oversized':200,'fake_tokens':200}[kind]
                if kind=='oversized':response.__enter__.return_value.iter_content.return_value=[b'x'*65537]
                with case.funded(),patch.object(stt.requests,'post',return_value=response) as paid:
                    result=case.post();self.assertEqual(result.status_code,200 if kind=='fake_tokens' else 503);self.assertEqual(paid.call_count,1)
                    if kind!='fake_tokens':self.assertEqual(result.json['code'],'transcription_failed')
                row=f.db.query_one('SELECT * FROM kilas_vo_stt_operations WHERE user_id=?',(case.user,))
                self.assertEqual(row['charge_micro'],budget.reserve_micro(row['duration_ms']));self.assertIsNone(row['actual_estimate_micro']);self.assertIsNone(row['input_tokens']);self.assertIsNone(row['output_tokens'])
            finally:case.doCleanups()


if __name__=='__main__':unittest.main()
