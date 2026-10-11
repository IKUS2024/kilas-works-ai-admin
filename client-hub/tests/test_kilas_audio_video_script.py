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
        import imageio_ffmpeg
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'a.wav').write_bytes(wav())
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i','color=c=white:s=32x32:d=2','-i',str(p/'a.wav'),'-shortest','-c:a','aac','-y',str(p/'v.mp4')],capture_output=True,check=True,timeout=20)
            cls.video=(p/'v.mp4').read_bytes()
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','lavfi','-i','color=c=white:s=32x32:d=2','-an','-y',str(p/'silent.mp4')],capture_output=True,check=True,timeout=20)
            cls.silent_video=(p/'silent.mp4').read_bytes()

    def funded(self,global_micro=90000,account_micro=60000):
        return patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic-only','KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'true','KILAS_VO_STT_CAMPAIGN':'synthetic-'+str(self.user),'KILAS_VO_STT_GLOBAL_BUDGET_MICRO_USD':str(global_micro),'KILAS_VO_STT_ACCOUNT_BUDGET_MICRO_USD':str(account_micro),'KILAS_VO_STT_EXPIRES_AT':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'KILAS_VO_STT_PRICE_VERSION':budget.PRICE_VERSION})

    def post(self,key='video-script-operation-1234',**fields):
        return self.client.post('/kilas-translator/voice-script/video',data={'csrf_token':'audio-csrf','operation_key':key,'consent':'yes','video':(io.BytesIO(self.video),'source.mp4','video/mp4'),**fields})

    def response(self,text='Ini ucapan asli, bukan terjemahan.',usage=None):
        response=Mock(status_code=200)
        response.iter_content.return_value=[json.dumps({'text':text,'usage':usage or {'type':'tokens','input_tokens':40,'output_tokens':20}}).encode()]
        context=Mock();context.__enter__=Mock(return_value=response);context.__exit__=Mock(return_value=False)
        return context

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
            args=paid.call_args;self.assertEqual(args.args[0],'https://api.openai.com/v1/audio/transcriptions');self.assertEqual(args.kwargs['data'],{'model':budget.MODEL,'response_format':'json'})
            self.assertEqual(args.kwargs['files']['file'][0],'recording.wav')
            self.assertEqual(self.post().json['status'],'COMPLETED');self.assertEqual(paid.call_count,1)
            self.assertEqual(self.client.get('/kilas-translator/voice-script/video?operation_key=video-script-operation-1234').json,{'status':'COMPLETED','operation_key':'video-script-operation-1234'})
        self.assertEqual(f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs')['n'],before)
        self.assertEqual(f.db.query_one('SELECT seconds FROM kilas_audio_balances WHERE user_id=?',(self.user,))['seconds'],60)
        row=f.db.query_one('SELECT * FROM kilas_vo_stt_operations WHERE user_id=?',(self.user,));self.assertEqual(row['charge_micro'],30000);self.assertEqual(row['actual_estimate_micro'],150);self.assertNotIn('text',row)

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
        self.assertEqual(f.db.query_one('SELECT charge_micro FROM kilas_vo_stt_operations WHERE user_id=?',(self.user,))['charge_micro'],30000)

    def test_capability_fingerprint_nonce_and_duplicate_dispatch(self):
        raw,ms=stt.normalize(wav());digest=hashlib.sha256(raw).hexdigest()
        with self.funded(),patch.object(stt.requests,'post') as paid:
            _,cap=budget.claim(self.user,'capability-operation-1234',digest,ms)
            for invalid in (None,budget.Reservation(self.other,cap.key,cap.lease),budget.Reservation(cap.owner,cap.key,'forged')):
                with self.assertRaises(budget.BudgetError):stt.transcribe(raw,invalid)
            paid.assert_not_called()
            budget.dispatch(cap,digest,ms)
            with self.assertRaises(budget.BudgetError):budget.dispatch(cap,digest,ms)
            with self.assertRaises(budget.BudgetError):budget.claim(self.user,cap.key,'a'*64,ms)

    def test_global_atomic_cap_and_parallel_same_key_claim(self):
        raw,ms=stt.normalize(wav());digest=hashlib.sha256(raw).hexdigest()
        with self.funded(global_micro=30000,account_micro=30000):
            def claim(owner):
                try:return budget.claim(owner,'parallel-claim-operation-1234',digest,ms)[1]
                except budget.BudgetError:return None
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(claim,(self.user,self.other)))
            self.assertEqual(sum(x is not None for x in results),1)
            cap=next(x for x in results if x is not None);self.assertIsNone(budget.claim(cap.owner,cap.key,digest,ms)[1])
            self.assertEqual(f.db.query_one('SELECT SUM(charge_micro) AS n FROM kilas_vo_stt_operations WHERE campaign=?',(budget.policy()['id'],))['n'],30000)

    def test_cancel_fences_before_dispatch_and_keeps_unknown_spend(self):
        raw,ms=stt.normalize(wav());digest=hashlib.sha256(raw).hexdigest()
        with self.funded():
            budget.cancel(self.user,'cancel-before-operation-1234')
            self.assertIsNone(budget.claim(self.user,'cancel-before-operation-1234',digest,ms)[1])
            _,cap=budget.claim(self.user,'cancel-after-operation-1234',digest,ms);budget.dispatch(cap,digest,ms)
            budget.cancel(self.user,cap.key);self.assertFalse(budget.finish(cap,True,{'type':'tokens','input_tokens':50,'output_tokens':20}))
            row=f.db.query_one('SELECT * FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(self.user,cap.key));self.assertEqual(row['status'],'CANCELLED');self.assertEqual(row['charge_micro'],30000)

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
                row=f.db.query_one('SELECT charge_micro,actual_estimate_micro FROM kilas_vo_stt_operations WHERE user_id=?',(case.user,));self.assertEqual(row['charge_micro'],30000);self.assertIsNone(row['actual_estimate_micro'])
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

    def test_off_inflight_finish_and_full_overrun_record_persistent_halt(self):
        raw,ms=stt.normalize(wav());digest=hashlib.sha256(raw).hexdigest()
        with self.funded():
            _,cap=budget.claim(self.user,'inflight-operation-1234',digest,ms);budget.dispatch(cap,digest,ms)
            with patch.dict(os.environ,{'KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'false'}):self.assertTrue(budget.finish(cap,True))
            _,cap=budget.claim(self.user,'overrun-operation-1234',digest,ms);budget.dispatch(cap,digest,ms)
            self.assertFalse(budget.finish(cap,True,{'type':'tokens','input_tokens':20000,'output_tokens':3000}))
            row=f.db.query_one('SELECT * FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(self.user,cap.key));self.assertEqual(row['actual_estimate_micro'],40000);self.assertEqual(row['charge_micro'],40000);self.assertEqual(row['status'],'UNKNOWN')
            self.assertEqual(f.db.query_one('SELECT blocked FROM kilas_vo_stt_campaigns WHERE id=?',(budget.policy()['id'],))['blocked'],1)
            with self.assertRaises(budget.BudgetError):budget.claim(self.other,'overrun-next-operation-1234',digest,ms)


if __name__=='__main__':unittest.main()
