"""Offline synthetic fixtures only; no credentials, microphone or provider IO."""
import base64
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from threading import Event
from time import monotonic
import unittest
from unittest.mock import patch
import wave
import zipfile

from kilas_ai import live_gemini_capture as capture


PCM = b'\x01\x00' * 2400


def provider_audio(pcm=PCM, **fields):
    return {'serverContent': {'modelTurn': {'parts': [{'inlineData': {
        'mimeType': 'audio/pcm;rate=24000', 'data': base64.b64encode(pcm).decode('ascii'),
    }}]}, **fields}}


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / 'captures'
        for patcher in (
            patch.object(capture, '_ROOT', self.root),
            patch.object(capture, 'start_cleanup'),
            patch.object(capture.db, 'query_one', return_value={'email': 'synthetic@example.test', 'role': 'CLIENT_OWNER'}),
            patch.dict(os.environ, {'KILAS_LIVE_GEMINI_QA_OWNER_ID': '9',
                                    'KILAS_LIVE_GEMINI_QA_OWNER_EMAIL': 'synthetic@example.test',
                                    'KILAS_LIVE_GEMINI_ENABLED': 'false'}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def full_input(self, selected):
        for index, offset in enumerate(range(0, len(selected.source_pcm), 16000)):
            self.assertTrue(selected.accept(index, selected.source_pcm[offset:offset + 16000]))
        self.assertTrue(selected.finish_input(30))

    def create(self, source='id', target='en', diagnostics=None):
        selected = capture.begin_fixture(9, source, target)
        self.full_input(selected)
        self.assertTrue(selected.observe(provider_audio()))
        ident = selected.finalize(diagnostics=diagnostics)
        self.assertIsNotNone(ident)
        return ident

    def timeline(self, ident):
        return json.loads(capture.export(9, ident, 'json')['data'])

    def assert_unavailable(self, callback):
        with self.assertRaises(capture.audio_store.AudioError) as raised:
            callback()
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(raised.exception.code, 'gemini_fixture_unavailable')
        self.assertNotIn('synthetic@example.test', str(raised.exception))

    def test_server_selects_only_two_immutable_fixed_format_fixtures(self):
        from kilas_ai import live_gemini_smoke as smoke
        for source, target in (('id', 'en'), ('en', 'id')):
            selected = capture.begin_fixture(9, source, target)
            self.assertEqual(len(selected.source_pcm), 480000)
            self.assertEqual(selected.source_pcm, smoke.fixture(source))
            self.assertEqual(capture.FIXTURES[source], smoke.FIXTURES[source])
        for source, target in (('../id', 'en'), ('id', 'id'), ('en', 'ar'), ('ID', 'en')):
            self.assert_unavailable(lambda: capture.begin_fixture(9, source, target))
        with patch.object(capture.Path, 'open', return_value=io.BytesIO(b'changed fixture')):
            self.assert_unavailable(lambda: capture.begin_fixture(9, 'id', 'en'))
        self.assertFalse(self.root.exists())

    def test_owner_configuration_email_and_live_database_role_fence_every_export(self):
        ident = self.create()
        self.assert_unavailable(lambda: capture.export(10, ident))
        self.assert_unavailable(lambda: capture.list_for_owner(10))
        self.assert_unavailable(lambda: capture.begin_fixture(True, 'id', 'en'))
        for extra in ({'KILAS_LIVE_GEMINI_QA_OWNER_ID': ''},
                      {'KILAS_LIVE_GEMINI_QA_OWNER_ID': '09'},
                      {'KILAS_LIVE_GEMINI_QA_OWNER_EMAIL': 'other@example.test'}):
            with patch.dict(os.environ, extra):
                self.assert_unavailable(lambda: capture.export(9, ident))
                self.assert_unavailable(lambda: capture.list_for_owner(9))
        for row in (None, {'email': 'synthetic@example.test', 'role': 'ADMIN'},
                    {'email': 'other@example.test', 'role': 'CLIENT_OWNER'}):
            with patch.object(capture.db, 'query_one', return_value=row):
                self.assert_unavailable(lambda: capture.export(9, ident))
        with patch.object(capture.db, 'query_one', side_effect=RuntimeError('private-database-error')):
            self.assert_unavailable(lambda: capture.export(9, ident))
        self.assertEqual(capture.list_for_owner(9)[0]['id'], ident)

    def test_normal_pcm_partial_reordered_replayed_and_extra_input_can_never_persist(self):
        def first(selected):
            return selected.source_pcm[:16000]
        invalid = (
            lambda selected: selected.accept(0, b'\x00' * 16000),
            lambda selected: selected.accept(1, first(selected)),
            lambda selected: selected.accept(False, first(selected)),
            lambda selected: selected.accept(0, first(selected)[:3200]),
            lambda selected: selected.finish_input(0),
            lambda selected: (selected.accept(0, first(selected)), selected.accept(0, first(selected))),
            lambda selected: (self.full_input(selected), selected.accept(30, first(selected))),
            lambda selected: (self.full_input(selected), selected.finish_input(30)),
        )
        for mutate in invalid:
            selected = capture.begin_fixture(9, 'id', 'en')
            selected.observe(provider_audio())
            mutate(selected)
            self.assertIsNone(selected.finalize())
            self.assertFalse(selected.output_pcm)
            self.assertEqual(selected.events, [])
        partial = capture.begin_fixture(9, 'id', 'en')
        partial.accept(0, first(partial))
        partial.observe(provider_audio())
        self.assertIsNone(partial.finalize())
        self.assertFalse(self.root.exists())

    def test_no_direct_constructor_no_form_capability_no_input_means_no_artifact(self):
        with self.assertRaises(capture.audio_store.AudioError):
            capture._FixtureCapture(object(), 9, 'binding', 'id', 'en', b'\0\0')
        self.assert_unavailable(lambda: capture.begin_fixture('9', 'id', 'en'))
        selected = capture.begin_fixture(9, 'id', 'en')
        selected.observe(provider_audio())
        self.assertIsNone(selected.finalize())
        empty = capture.begin_fixture(9, 'id', 'en')
        self.full_input(empty)
        self.assertIsNone(empty.finalize())
        self.assertFalse(self.root.exists())

    def test_private_bundle_has_correct_original_and_provider_wav_formats_even_while_off(self):
        ident = self.create()
        self.assertRegex(ident, r'^[a-f0-9]{48}$')
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.root / (ident + '.zip')).stat().st_mode), 0o600)
        bundle = capture.export(9, ident)
        self.assertEqual(bundle['mimetype'], 'application/zip')
        self.assertEqual(bundle['filename'], 'gemini-synthetic-fixture.zip')
        with zipfile.ZipFile(io.BytesIO(bundle['data'])) as archive:
            self.assertEqual(set(archive.namelist()), {'source.wav', 'output.wav', 'timeline.json'})
            for name, rate, pcm in (('source.wav', 16000, capture.fixture_pcm('id')), ('output.wav', 24000, PCM)):
                with wave.open(io.BytesIO(archive.read(name)), 'rb') as wav:
                    self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, rate))
                    self.assertEqual(wav.readframes(wav.getnframes()), pcm)
        for kind, expected_mime in (('json', 'application/json'), ('wav', 'audio/wav'), ('source.wav', 'audio/wav')):
            self.assertEqual(capture.export(9, ident, kind)['mimetype'], expected_mime)
        summary = capture.list_for_owner(9)
        self.assertEqual(summary[0]['input_ms'], 15000)
        self.assertEqual(summary[0]['output_ms'], 100)
        self.assertNotIn('source_text', str(summary))
        self.assertNotIn('owner_binding', str(summary))

    def test_private_bundle_is_readable_in_another_process_without_replaying_provider(self):
        ident = self.create()
        script = '''
import json, sys
from pathlib import Path
from unittest.mock import patch
from kilas_ai import live_gemini_capture as c
with patch.object(c, '_ROOT', Path(sys.argv[1])), patch.object(c, 'start_cleanup'), patch.object(c.db, 'query_one', return_value={'email':'synthetic@example.test','role':'CLIENT_OWNER'}):
    data = c.export(9, sys.argv[2], 'json')['data']
    value = json.loads(data)
    print(json.dumps({'input_ms':value['input_ms'],'output_ms':value['output_ms']}))
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.root), ident],
                                capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(json.loads(result.stdout), {'input_ms': 15000, 'output_ms': 100})

    def test_existing_smoke_instrumentation_exports_fixture_after_end_with_no_real_dispatch(self):
        from kilas_ai import live_gemini as native, live_gemini_smoke as smoke
        from kilas_ai import live_translator_store as sessions

        class Socket:
            def __init__(self):
                self.responses = iter([json.dumps({'setupComplete': {}}), json.dumps(provider_audio(
                    inputTranscription={'text': 'Water.'}, outputTranscription={'text': 'Air.'}, turnComplete=True))])

            def recv(self):
                return next(self.responses)

        class Relay:
            def __init__(self):
                self.finished = False
                self.completed = Event()
                self.accepted = self.expected = 0
                self.frames = [{'type': 'audio', 'pcm': base64.b64encode(PCM).decode('ascii')}]
                self.source_text, self.target_text = 'Water.', 'Air.'
                self.output_bytes = len(PCM)
                self.error = None
                self.first_output_at = self.first_input_at = monotonic()
                self.end_at = None
                self.tail_confirmed = True
                self.completion_kind = 'turn_complete'

            def accept(self, index, pcm):
                self.expected += 1
                self.accepted += len(pcm)

            def finish_input(self, count):
                self.end_at = monotonic()
                self.finished = True
                self.completed.set()

            def snapshot(self, after):
                return {'frames': self.frames[after:], 'next_index': len(self.frames)}

            def diagnostics(self):
                return {'tail_confirmed': True, 'completion_kind': 'turn_complete', 'input_sent_bytes': self.accepted}

        relay = Relay()

        def start(owner, ident, key):
            probe = native.connect()
            probe.recv()
            probe.recv()
            return relay

        def end(owner, ident):
            # This is the actual normal End privacy behavior: the RAM output is
            # removed, while only the verified synthetic artifact may survive.
            relay.frames.clear()
            relay.source_text = relay.target_text = ''

        with patch.object(native, 'connect', return_value=Socket()), patch.object(native, 'start', side_effect=start) as admission, \
                patch.object(native, 'cancel', side_effect=end), \
                patch.object(native, 'owned', side_effect=native.failure('gemini_output_expired', 409)), \
                patch.object(sessions, 'create', return_value='a' * 48), patch.object(sessions, 'end'), \
                patch.object(smoke.time, 'sleep'), patch.object(smoke, 'report'), \
                patch.object(native.budget, 'dispatch') as dispatch:
            result = smoke.session({'owner': 9}, 'en', 'id', capture.fixture_pcm('en'))
        self.assertEqual(admission.call_count, 1)
        dispatch.assert_not_called()
        self.assertTrue(result['backend_checks_passed'])
        self.assertEqual(result['post_end_frames'], 0)
        self.assertEqual(result['fixture_capture_status'], 'available')
        ident = result['fixture_capture_id']
        timeline = self.timeline(ident)
        self.assertEqual(timeline['source_text'], 'Water.')
        self.assertEqual(timeline['translated_text'], 'Air.')
        self.assertTrue(timeline['protocol']['tail_confirmed'])
        self.assertEqual(capture.export(9, ident, 'wav')['data'][44:], PCM)

    def test_transcripts_protocol_usage_and_interruptions_are_synthetic_bounded_allowlist(self):
        selected = capture.begin_fixture(9, 'en', 'id')
        selected.observe({'setupComplete': {'sessionId': 'private-session-id'},
                          'usageMetadata': {'promptTokenCount': 2, 'responseTokenCount': 4,
                                            'totalTokenCount': 6, 'secret': 'private-key'},
                          'error': {'code': 429, 'message': 'private-provider-error'}})
        selected.observe(provider_audio(inputTranscription={'text': 'Water.'}, outputTranscription={'text': 'Air.'}))
        selected.observe(provider_audio(b'\x02\x00' * 1200, interrupted=True, generationComplete=True,
                                        turnComplete=True, interactionStatus='IDLE'))
        self.full_input(selected)
        ident = selected.finalize(code='private-free-form-code', diagnostics={
            'tail_confirmed': False, 'completion_kind': 'bounded_drain', 'tail_code': 'gemini_tail_unconfirmed',
            'output_received_packets': 2, 'input_sent_bytes': 480000,
            'token': 'private-key', 'first_error_code': 'private-free-form-code',
        })
        timeline = self.timeline(ident)
        self.assertEqual(timeline['source_text'], 'Water.')
        self.assertEqual(timeline['translated_text'], 'Air.')
        self.assertFalse(timeline['audible_playback_verified'])
        self.assertFalse(timeline['semantic_translation_tail_verified'])
        self.assertEqual(timeline['protocol']['tail_code'], 'gemini_tail_unconfirmed')
        self.assertIn('interrupted_generations', timeline['output_semantics'])
        self.assertNotIn('private-', json.dumps(timeline))
        audio = [event for event in timeline['events'] if event['event'] == 'output_segment']
        self.assertEqual([event['generation'] for event in audio], [0, 1])
        self.assertEqual([event['output_offset'] for event in audio], [0, len(PCM)])
        interrupted = next(event for event in timeline['events'] if event['event'] == 'interrupted')
        self.assertEqual(interrupted['output_offset'], len(PCM))
        self.assertEqual(len(selected.output_pcm), 0)
        self.assertEqual(selected.source_text, '')
        self.assertIsNone(selected.finalize())

    def test_output_text_timeline_and_elapsed_limits_fail_closed_without_persistence(self):
        for event in (
            provider_audio(b'x'), provider_audio(b'\0\0' * (capture.MAX_OUTPUT_BYTES // 2 + 1)),
            {'serverContent': {'inputTranscription': {'text': 'x' * (capture.MAX_TEXT + 1)}}},
            {'serverContent': {'modelTurn': {'parts': [{'inlineData': {
                'mimeType': 'audio/pcm;rate=16000', 'data': 'AA=='}}]}}},
        ):
            selected = capture.begin_fixture(9, 'id', 'en')
            self.full_input(selected)
            self.assertFalse(selected.observe(event))
            self.assertIsNone(selected.finalize())
        selected = capture.begin_fixture(9, 'id', 'en')
        self.full_input(selected)
        with patch.object(capture, 'MAX_EVENTS', len(selected.events)):
            self.assertFalse(selected.observe(provider_audio()))
        self.assertIsNone(selected.finalize())
        selected = capture.begin_fixture(9, 'id', 'en')
        self.full_input(selected)
        with patch.object(capture, 'monotonic', return_value=selected.started + capture.MAX_SECONDS + 1):
            self.assertFalse(selected.observe(provider_audio()))
        self.assertIsNone(selected.finalize())
        self.assertFalse(self.root.exists())

    def test_max_90_second_output_is_accepted_and_next_segment_invalidates(self):
        selected = capture.begin_fixture(9, 'id', 'en')
        self.full_input(selected)
        selected.observe(provider_audio(b'\0' * capture.MAX_OUTPUT_BYTES))
        ident = selected.finalize()
        self.assertEqual(self.timeline(ident)['output_ms'], 90000)
        other = capture.begin_fixture(9, 'id', 'en')
        self.full_input(other)
        self.assertTrue(other.observe(provider_audio(b'\0' * capture.MAX_OUTPUT_BYTES)))
        self.assertFalse(other.observe(provider_audio(b'\0\0')))
        self.assertIsNone(other.finalize())

    def test_owner_revocation_between_capture_and_finalize_never_publishes(self):
        selected = capture.begin_fixture(9, 'id', 'en')
        self.full_input(selected)
        selected.observe(provider_audio())
        with patch.object(capture.db, 'query_one', return_value={'email': 'synthetic@example.test', 'role': 'ADMIN'}):
            self.assertIsNone(selected.finalize())
        self.assertFalse(self.root.exists())

    def test_store_full_does_not_evict_unexpired_outputs_and_ttl_cleans_private_files(self):
        identifiers = [self.create() for _ in range(capture.MAX_ENTRIES)]
        selected = capture.begin_fixture(9, 'id', 'en')
        self.full_input(selected)
        selected.observe(provider_audio())
        self.assertIsNone(selected.finalize())
        self.assertEqual(len(list(self.root.iterdir())), capture.MAX_ENTRIES)
        created = self.timeline(identifiers[0])['created_epoch']
        with patch.object(capture, 'time', return_value=created + capture.TTL_SECONDS + 1):
            capture.cleanup()
            self.assertEqual(capture.list_for_owner(9), [])
            self.assert_unavailable(lambda: capture.export(9, identifiers[0]))
        self.assertFalse(list(self.root.iterdir()))

    def test_cleanup_does_not_create_directory_and_worker_maintenance_starts_once(self):
        capture.cleanup()
        self.assertFalse(self.root.exists())
        # Call the real function rather than the per-test daemon suppressor.
        from importlib import import_module
        module = import_module(capture.__name__)
        real_start = self._real_start_cleanup
        with patch.object(module, '_maintenance_started', False), patch.object(module.Thread, 'start') as start:
            real_start()
            real_start()
            self.assertEqual(start.call_count, 1)
        self.assertFalse(self.root.exists())

    _real_start_cleanup = staticmethod(capture.start_cleanup)

    def test_path_symlink_unsafe_permissions_and_corruption_fail_closed(self):
        ident = self.create()
        for candidate in ('../' + ident, ident + '.zip', 'https://example.test/a', 'a' * 47, 'A' * 48):
            self.assert_unavailable(lambda: capture.export(9, candidate))
        self.assert_unavailable(lambda: capture.export(9, ident, '../source.wav'))
        path = self.root / (ident + '.zip')
        path.chmod(0o644)
        self.assert_unavailable(lambda: capture.export(9, ident))
        self.assertEqual(capture.list_for_owner(9), [])
        path.chmod(0o600)
        path.write_bytes(b'private-corrupt-bundle')
        self.assert_unavailable(lambda: capture.export(9, ident))
        self.assertEqual(capture.list_for_owner(9), [])
        path.unlink()
        outside = Path(self.folder.name) / 'outside'
        outside.write_bytes(b'outside-private-content')
        path.symlink_to(outside)
        self.assert_unavailable(lambda: capture.export(9, ident))
        self.assertEqual(outside.read_bytes(), b'outside-private-content')
        self.root.chmod(0o755)
        self.assert_unavailable(lambda: capture.list_for_owner(9))
        self.root.chmod(0o700)
        self.root.rmdir()
        self.root.symlink_to(self.folder.name, target_is_directory=True)
        self.assert_unavailable(lambda: capture.list_for_owner(9))

    def test_corrupt_json_and_wrong_owner_binding_are_never_returned_or_listed(self):
        ident = self.create()
        path = self.root / (ident + '.zip')
        for timeline in (b'{private-invalid-json', b'[]', b'{"owner_binding":"different-owner"}'):
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as archive:
                archive.writestr('source.wav', b'123')
                archive.writestr('output.wav', b'123')
                archive.writestr('timeline.json', timeline)
            self.assert_unavailable(lambda: capture.export(9, ident, 'json'))
            self.assertEqual(capture.list_for_owner(9), [])


if __name__ == '__main__':
    unittest.main()
