"""Authenticated synthetic-export routes; disposable SQLite, no network/audio IO."""
import base64
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile
import test_kilas_audio as audio
from auth_test_helpers import authenticate
from kilas_ai import live_gemini as native, live_gemini_capture as capture


class FixtureExportRoutes(unittest.TestCase):
    setUp = audio.AudioTests.setUp

    def config(self):
        email=audio.f.db.query_one('SELECT email FROM users WHERE id=?',(self.user,))['email']
        return patch.dict(os.environ,{'KILAS_LIVE_GEMINI_ENABLED':'false',
                                     'KILAS_LIVE_GEMINI_QA_OWNER_ID':str(self.user),
                                     'KILAS_LIVE_GEMINI_QA_OWNER_EMAIL':email})

    def artifact(self):
        cap=capture.begin_fixture(self.user,'id','en')
        for index,offset in enumerate(range(0,len(cap.source_pcm),16000)):
            self.assertTrue(cap.accept(index,cap.source_pcm[offset:offset+16000]))
        self.assertTrue(cap.finish_input(30))
        pcm=b'\x01\x00'*2400
        self.assertTrue(cap.observe({'serverContent':{'outputTranscription':{'text':'Synthetic final water.'},
            'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000',
                                                'data':base64.b64encode(pcm).decode()}}]}}}))
        return cap.finalize(diagnostics={'tail_confirmed':False,'completion_kind':'bounded_drain'})

    def test_off_owner_can_download_exact_fixture_artifacts_without_dispatch_or_history(self):
        with tempfile.TemporaryDirectory() as directory,self.config(),patch.object(capture,'_ROOT',Path(directory)/'captures'),patch.object(capture,'start_cleanup'),patch.object(native,'connect') as connect:
            ident=self.artifact()
            index=self.client.get('/kilas-translator/live/gemini/fixtures')
            self.assertEqual(index.status_code,200)
            self.assertEqual(index.json['fixtures'][0]['id'],ident)
            for kind in ('zip','json','wav','source.wav'):
                response=self.client.get('/kilas-translator/live/gemini/fixtures/'+ident+'/'+kind)
                self.assertEqual(response.status_code,200,kind)
                self.assertEqual(response.headers['Cache-Control'],'private, no-store')
                self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
                self.assertTrue(response.headers['Content-Disposition'].startswith('attachment;'))
                if kind=='zip':
                    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                        self.assertEqual(set(archive.namelist()),{'source.wav','output.wav','timeline.json'})
                if kind=='json':
                    timeline=json.loads(response.data)
                    self.assertEqual(timeline['scope'],'canonical_synthetic_fixture_only')
                if kind in ('wav','source.wav'):
                    with wave.open(io.BytesIO(response.data)) as wav:
                        self.assertEqual(wav.getframerate(),24000 if kind=='wav' else 16000)
            self.assertEqual(self.client.post('/kilas-translator/live/gemini/fixtures',data={'csrf_token':'audio-csrf'}).status_code,405)
            self.assertEqual(audio.f.db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE user_id=?',(self.user,))['n'],0)
            connect.assert_not_called()

    def test_cross_owner_anonymous_wrong_binding_and_unknown_artifacts_are_denied(self):
        with tempfile.TemporaryDirectory() as directory,self.config(),patch.object(capture,'_ROOT',Path(directory)/'captures'),patch.object(capture,'start_cleanup'):
            ident=self.artifact();path='/kilas-translator/live/gemini/fixtures/'+ident+'/zip'
            stranger=audio.f.app.app.test_client()
            self.assertEqual(stranger.get(path).status_code,302)
            authenticate(stranger,audio.f.repo.get_user_by_id(self.other),_csrf_token='audio-csrf')
            self.assertEqual(stranger.get(path).status_code,404)
            self.assertEqual(stranger.get('/kilas-translator/live/gemini/fixtures').status_code,404)
            for suffix in ('x'*48+'/zip',ident+'/unknown','a'*48+'/zip'):
                self.assertEqual(self.client.get('/kilas-translator/live/gemini/fixtures/'+suffix).status_code,404)
            with patch.dict(os.environ,{'KILAS_LIVE_GEMINI_QA_OWNER_EMAIL':'other@example.test'}):
                self.assertEqual(self.client.get(path).status_code,404)


if __name__=='__main__':
    unittest.main()
