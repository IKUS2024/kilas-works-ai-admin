"""Offline synthetic audio upload, clone safeguards and pre-hydration regressions."""
import io
from contextlib import contextmanager
import os
import subprocess
import tempfile
import unittest
import wave
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from werkzeug.datastructures import FileStorage
import test_kilas_audio as audio
from test_kilas_audio import f, media, provider, wav
from kilas_ai import audio_personal_voice as personal


class Tags(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.ids = {}; self.feed(html)
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if 'id' in values: self.ids[values['id']] = values


class VoiceUploadTests(unittest.TestCase):
    setUp = audio.AudioTests.setUp
    credit = audio.AudioTests.credit

    @classmethod
    def setUpClass(cls):
        # Silence only, encoded locally. No human voice or external transport.
        cls.samples = {'wav': wav(.6)}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); source = root / 'source.wav'; source.write_bytes(cls.samples['wav'])
            for suffix, codec in [('mp3', 'libmp3lame'), ('m4a', 'aac'), ('ogg', 'libopus'), ('webm', 'libopus')]:
                output = root / ('sample.' + suffix)
                subprocess.run([media.imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error', '-i', str(source), '-c:a', codec, '-y', str(output)], check=True, capture_output=True, timeout=15)
                cls.samples[suffix] = output.read_bytes()

    def post_sample(self, path='/personal-voice/inspect', raw=None, filename='sample.mp3', mime='audio/mpeg', **values):
        data = {'csrf_token': 'audio-csrf', 'recording': (io.BytesIO(self.samples['mp3'] if raw is None else raw), filename, mime), **values}
        return self.client.post('/kilas-translator' + path, data=data, content_type='multipart/form-data')

    def test_all_advertised_formats_decode_to_existing_provider_wav(self):
        self.credit()
        for suffix, mime in [('mp3', 'audio/mpeg'), ('wav', 'audio/wav'), ('m4a', 'audio/mp4'), ('ogg', 'audio/ogg'), ('webm', 'audio/webm')]:
            with self.subTest(suffix=suffix):
                ms, pcm = media.voice_sample(FileStorage(io.BytesIO(self.samples[suffix]), filename='sample.'+suffix, content_type=mime), with_duration=True)
                self.assertTrue(500 <= ms <= 900)
                with wave.open(io.BytesIO(pcm)) as decoded:
                    self.assertEqual(decoded.getframerate(), 44100); self.assertEqual(decoded.getnchannels(), 1)
                with patch.object(provider, 'clone_voice') as clone, patch.object(provider, 'request') as request:
                    result = self.post_sample(raw=self.samples[suffix], filename='sample.'+suffix, mime=mime)
                    self.assertEqual(result.status_code, 200, result.text); self.assertTrue(500 <= result.json['duration_ms'] <= 900)
                    self.assertEqual(result.headers['Cache-Control'], 'private, no-store'); clone.assert_not_called(); request.assert_not_called()
        self.assertEqual(f.db.query_one('SELECT seconds FROM kilas_audio_balances WHERE user_id=?', (self.user,))['seconds'], 60)
        self.assertIsNone(f.db.query_one('SELECT * FROM kilas_audio_saved_voices WHERE user_id=?', (self.user,)))

    def test_picker_mime_aliases_and_unknown_mime_require_known_extension(self):
        for suffix, mime in [('mp3','audio/mp3'), ('wav','audio/x-wav'), ('wav','audio/vnd.wave'), ('m4a','audio/x-m4a'), ('mp3','application/octet-stream'), ('wav','')]:
            with self.subTest(suffix=suffix,mime=mime):
                self.assertTrue(media.voice_sample(FileStorage(io.BytesIO(self.samples[suffix]), filename='sample.'+suffix, content_type=mime)).startswith(b'RIFF'))
        with self.assertRaises(media.MediaError):
            media.voice_sample(FileStorage(io.BytesIO(self.samples['mp3']),filename='sample.txt',content_type='application/octet-stream'))

    def test_invalid_mime_bytes_empty_and_size_never_reach_decoder_or_clone(self):
        self.credit()
        invalid = [(self.samples['wav'],'audio/mpeg'), (self.samples['mp3'],'audio/wav'), (self.samples['wav'],'text/html'), (b'','audio/mpeg'), (b'ID3'+b'0'*(10*1024*1024),'audio/mpeg'), (b'#EXTM3U\nfile:///private.wav','audio/mpeg')]
        with patch.object(media,'_decode_source') as decode, patch.object(provider,'clone_voice') as clone:
            for raw,mime in invalid:
                with self.subTest(mime=mime,size=len(raw)):
                    self.assertEqual(self.post_sample(raw=raw,mime=mime).status_code,400)
                    self.assertEqual(self.post_sample('/personal-voice',raw=raw,mime=mime,consent='yes',name='Synthetic',operation_key='bad-audio-operation-1234').status_code,400)
            decode.assert_not_called(); clone.assert_not_called()

    def test_corruption_and_duration_bounds_use_real_local_decoder(self):
        self.credit()
        with patch.object(provider,'clone_voice') as clone:
            for raw,mime,filename in [(b'ID3invalid','audio/mpeg','bad.mp3'), (wav(181),'audio/wav','long.wav'), (wav(0),'audio/wav','empty.wav')]:
                with self.subTest(filename=filename):
                    result=self.post_sample(raw=raw,mime=mime,filename=filename)
                    self.assertEqual(result.status_code,400,result.text)
            clone.assert_not_called()
        created=[]; original=tempfile.TemporaryDirectory
        @contextmanager
        def capture_directory(*args,**kwargs):
            with original(*args,**kwargs) as directory:
                created.append(directory); yield directory
        with patch.object(media.tempfile,'TemporaryDirectory',side_effect=capture_directory):
            media.voice_sample(FileStorage(io.BytesIO(self.samples['mp3']),filename='sample.mp3',content_type='audio/mpeg'))
            with self.assertRaises(media.MediaError):
                media.voice_sample(FileStorage(io.BytesIO(b'ID3invalid'),filename='bad.mp3',content_type='audio/mpeg'))
        self.assertEqual(len(created),2)
        self.assertTrue(all(not Path(directory).exists() for directory in created))

    def test_inspection_keeps_owner_auth_csrf_and_balance_gate(self):
        with patch.object(media,'voice_sample') as decode, patch.object(provider,'request') as paid:
            self.assertEqual(self.post_sample(csrf_token='wrong').status_code,400)
            self.assertEqual(self.post_sample().status_code,402)
            anonymous=f.app.app.test_client()
            with anonymous.session_transaction() as state:state['_csrf_token']='audio-csrf'
            self.assertEqual(anonymous.post('/kilas-translator/personal-voice/inspect',data={'csrf_token':'audio-csrf'}).status_code,302)
            decode.assert_not_called(); paid.assert_not_called()

    def test_mp3_clone_reuses_named_voice_consent_preview_idempotency(self):
        self.credit()
        values={'consent':'yes','name':'Synthetic upload','operation_key':'mp3-upload-operation-1234'}
        with patch.object(provider,'clone_voice',return_value='syntheticPrivateUpload') as clone:
            first=self.post_sample('/personal-voice',**values)
            self.assertEqual(first.status_code,200,first.text)
            self.assertEqual(self.post_sample('/personal-voice',**values).json,first.json)
            clone.assert_called_once(); self.assertTrue(clone.call_args.args[0].startswith(b'RIFF'))
        ident=first.json['id']; row=personal.saved(self.user,ident)
        self.assertEqual(row['name'],'Synthetic upload')
        preview=self.client.get('/kilas-translator/personal-voices/'+str(ident)+'/preview')
        self.assertEqual(preview.status_code,200); self.assertEqual(preview.mimetype,'audio/mpeg'); self.assertLess(media.mp3_duration(preview.data),1000)
        with self.client.session_transaction() as state:state['user_id']=self.other
        self.assertEqual(self.client.get('/kilas-translator/personal-voices/'+str(ident)+'/preview').status_code,404)

    def test_uploaded_replacement_keeps_saved_voice_until_success(self):
        self.credit()
        with patch.object(provider,'clone_voice',return_value='syntheticOriginal'):
            first=self.post_sample('/personal-voice',consent='yes',name='Original',operation_key='original-upload-key-1234').json
        ident=first['id']; before=personal.saved_preview(self.user,ident)
        values={'consent':'yes','name':'Replacement','operation_key':'replace-upload-key-1234','saved_voice_id':str(ident)}
        with patch.object(provider,'clone_voice',side_effect=provider.ProviderError()),patch.object(provider,'delete_voice') as delete:
            self.assertEqual(self.post_sample('/personal-voice',**values).status_code,503); delete.assert_not_called()
        self.assertEqual(personal.saved(self.user,ident)['voice_id'],'syntheticOriginal'); self.assertEqual(personal.saved_preview(self.user,ident),before)
        with patch.object(provider,'clone_voice',return_value='syntheticReplacement'),patch.object(provider,'delete_voice') as delete:
            self.assertEqual(self.post_sample('/personal-voice',**values).json['id'],ident);delete.assert_called_once_with('syntheticOriginal')
        self.assertEqual(personal.saved(self.user,ident)['voice_id'],'syntheticReplacement')

    def test_no_consent_foreign_replacement_and_zero_balance_cannot_clone_upload(self):
        with patch.object(provider,'clone_voice') as clone:
            self.assertEqual(self.post_sample('/personal-voice',name='Upload',operation_key='denied-upload-key-1234',consent='yes').status_code,402)
            self.credit()
            self.assertEqual(self.post_sample('/personal-voice',name='Upload',operation_key='denied-upload-key-1234',consent='no').status_code,400)
            self.assertEqual(self.post_sample('/personal-voice',name='Upload',operation_key='denied-upload-key-1234',consent='yes',saved_voice_id='999999').status_code,404)
            clone.assert_not_called()

    def test_server_render_is_voiceover_before_javascript_and_styles_load_in_head(self):
        for visible in ('true','false'):
            with self.subTest(visible=visible),patch.dict(os.environ,{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':visible}):
                html=self.client.get('/kilas-translator?mode=voiceover&page=2').text;ids=Tags(html).ids
                self.assertEqual(ids['audio-studio']['data-active-mode'],'voiceover')
                self.assertNotIn('hidden',ids['voiceover-panel']);self.assertIn('hidden',ids['personal-voice-setup']);self.assertNotIn('hidden',ids['kilas-voice-options'])
                self.assertIn('<h1>Voice Over</h1>',html);self.assertIn('<title>Voice Over · Kilas Works',html)
                self.assertLess(html.index('kilas_audio.css'),html.index('</head>'));self.assertEqual(html.count('kilas_audio.css'),1)
                self.assertIn('mode=voiceover',html); self.assertIn('id="voice-sample-file"',html)
                if visible=='true':self.assertIn('hidden',ids['translate-panel'])
        with patch.dict(os.environ,{'KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE':'true'}):
            html=self.client.get('/kilas-translator?mode=translate').text;ids=Tags(html).ids
            self.assertNotIn('hidden',ids['translate-panel']);self.assertIn('hidden',ids['voiceover-panel']);self.assertIn('<h1>Kilas Translator</h1>',html)


if __name__=='__main__':unittest.main()
