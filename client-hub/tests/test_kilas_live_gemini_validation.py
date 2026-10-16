"""Fixed parser diagnostics and the completion boundary; no sockets or DB IO."""
import base64
import json
import unittest
from threading import Event, Thread
from unittest.mock import patch

from kilas_ai import audio_store, live_gemini as native, live_gemini_pair as pair


PRIVATE = 'private-provider-content-token-never-log'
PCM = b'\x01\x00' * 24


def packet(**content):
    return json.dumps({'serverContent':content})


def audio(data=None, mime='audio/pcm;rate=24000'):
    return packet(modelTurn={'parts':[{'inlineData':{
        'mimeType':mime, 'data':base64.b64encode(PCM).decode('ascii') if data is None else data}}]})


class ValidationTests(unittest.TestCase):
    def relay(self, paired=False):
        info = {'language_a':'en', 'language_b':'id',
                'voice_alias':pair.VOICE if paired else native.VOICE}
        parent = (pair.Pair if paired else native.Relay)(9, 'synthetic-session', 'synthetic-operation', info, None, None)
        check = patch.object(parent, 'check')
        check.start()
        self.addCleanup(check.stop)
        return parent.streams['en'] if paired else parent

    def invalid(self, call, reason):
        with self.assertRaises(audio_store.AudioError) as caught:
            call()
        error = caught.exception
        self.assertEqual(error.code, 'gemini_response_invalid')
        self.assertEqual(error.status, 503)
        self.assertEqual(str(error), str(native.failure('gemini_response_invalid')))
        self.assertEqual(native.validation_reason(error), reason)
        self.assertIn(reason, native.VALIDATION_REASONS)
        for value in (str(error), repr(error), repr(vars(error))):
            self.assertNotIn(PRIVATE, value)
        return error

    def test_message_reasons_are_fixed_and_preserve_public_error(self):
        cases = ((None, 'message_type'), (PRIVATE+'{', 'message_json'),
                 (b'\xff'+PRIVATE.encode(), 'message_json'),
                 (json.dumps([PRIVATE]), 'message_object'))
        for raw, reason in cases:
            with self.subTest(reason=reason, raw_type=type(raw).__name__):
                self.invalid(lambda:native.message(raw), reason)
        with patch.object(native, 'MAX_MESSAGE', 3):
            self.invalid(lambda:native.message(PRIVATE), 'message_size')

    def test_envelope_and_content_shape_reasons(self):
        for raw, reason in ((json.dumps({'error':{'message':PRIVATE}}), 'provider_error'),
                            (json.dumps({'toolCall':PRIVATE}), 'unexpected_tool_call'),
                            (json.dumps({'goAway':PRIVATE}), 'provider_go_away'),
                            (packet.__name__+PRIVATE, 'message_json'),
                            (json.dumps({'serverContent':PRIVATE}), 'content_shape')):
            with self.subTest(reason=reason):
                self.invalid(lambda:self.relay().receive(raw), reason)

    def test_provider_error_keeps_only_bounded_integer_status_and_fixed_reason(self):
        for code, expected in ((429, 429), (503, 503), (100, 100), (599, 599),
                               (99, None), (600, None), ('429', None), (True, None),
                               ({'secret':PRIVATE}, None)):
            with self.subTest(code_type=type(code).__name__):
                relay = self.relay()
                raw = json.dumps({'error':{'code':code, 'message':PRIVATE, 'details':[PRIVATE]}})
                error = self.invalid(lambda:relay.receive(raw), 'provider_error')
                self.assertEqual(native.provider_status(error), expected)
                self.assertEqual(relay.provider_status, expected)
                self.assertNotIn(PRIVATE, repr(vars(relay)))
        for status in (PRIVATE, True, 99, 600, [429]):
            error = native.invalid_response('provider_error')
            error.provider_status = status
            self.assertIsNone(native.provider_status(error))

    def test_transcription_shape_language_and_text_limit_reasons(self):
        for content, reason in (({'inputTranscription':PRIVATE}, 'transcript_shape'),
                                ({'outputTranscription':{'text':[PRIVATE]}}, 'transcript_shape'),
                                ({'inputTranscription':{'text':PRIVATE,'languageCode':'ja'}}, 'input_language'),
                                ({'outputTranscription':{'text':PRIVATE,'languageCode':'ja'}}, 'output_language')):
            with self.subTest(reason=reason):
                self.invalid(lambda:self.relay().receive(packet(**content)), reason)
        with patch.object(native, 'MAX_TEXT', 3):
            self.invalid(lambda:self.relay().receive(packet(inputTranscription={'text':PRIVATE})), 'text_limit')

    def test_turn_part_and_audio_shape_reasons(self):
        cases = (({'modelTurn':PRIVATE}, 'turn_shape'),
                 ({'modelTurn':{'parts':PRIVATE}}, 'turn_shape'),
                 ({'modelTurn':{'parts':[PRIVATE]}}, 'part_shape'),
                 ({'modelTurn':{'parts':[{'inlineData':PRIVATE}]}}, 'audio_shape'),
                 ({'modelTurn':{'parts':[{'inlineData':{'data':[PRIVATE]}}]}}, 'audio_shape'))
        for content, reason in cases:
            with self.subTest(reason=reason):
                self.invalid(lambda:self.relay().receive(packet(**content)), reason)

    def test_audio_mime_base64_and_length_reasons(self):
        self.invalid(lambda:self.relay().receive(audio(mime=PRIVATE)), 'audio_mime')
        self.invalid(lambda:self.relay().receive(audio(data=PRIVATE)), 'audio_base64')
        self.invalid(lambda:self.relay().receive(audio(data='')), 'audio_length')
        self.invalid(lambda:self.relay().receive(audio(data=base64.b64encode(b'1').decode())), 'audio_length')

    def test_frame_limit_and_closed_stream_reasons_preserve_caps(self):
        relay = self.relay()
        relay.frames = [{'type':'reset','generation':0}] * 2000
        self.invalid(lambda:relay.receive(packet(interrupted=True)), 'frame_limit')
        stream = self.relay(paired=True)
        stream.stopped = True
        self.invalid(lambda:stream.receive(audio()), 'closed_stream')
        self.assertEqual(stream.output_bytes, 0)
        self.assertEqual(stream.pair.output_bytes, 0)

    def test_active_pair_wrong_target_is_rejected_with_internal_reason(self):
        stream = self.relay(paired=True)
        raw = packet(outputTranscription={'text':PRIVATE,'languageCode':'id'})
        self.invalid(lambda:stream.receive(raw), 'output_language')
        self.assertEqual(stream.validation_reason, 'output_language')
        self.assertEqual(stream.target_text, '')
        self.assertEqual(stream.frames, [])

    def test_completed_packet_is_ignored_before_json_envelope_and_target_validation(self):
        for paired in (False, True):
            relay = self.relay(paired)
            relay.completed.set()
            for raw in (PRIVATE+'{', json.dumps({'error':{'message':PRIVATE}}),
                        packet(outputTranscription={'text':PRIVATE,'languageCode':'id'}),
                        audio()):
                with self.subTest(paired=paired, raw_type=type(raw).__name__):
                    relay.receive(raw)
            self.assertIsNone(relay.validation_reason)
            self.assertEqual(relay.target_text, '')
            self.assertEqual(relay.frames, [])
            self.assertEqual(relay.output_bytes, 0)

    def test_completion_between_check_and_parser_lock_ignores_late_invalid_packet(self):
        for raw in (PRIVATE+'{', packet(outputTranscription={'text':PRIVATE,'languageCode':'id'})):
            with self.subTest(packet_type='json' if raw.startswith('{') else 'malformed'):
                stream = self.relay(paired=True)
                checked, errors = Event(), []
                def check():
                    checked.set()
                def receive():
                    try:
                        stream.receive(raw)
                    except Exception as error:
                        errors.append(error)
                with patch.object(stream.pair, 'check', side_effect=check):
                    with stream.lock:
                        worker = Thread(target=receive)
                        worker.start()
                        self.assertTrue(checked.wait(1))
                        stream.completed.set()
                    worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertIsNone(stream.validation_reason)

    def test_cancellation_and_authorization_still_apply_to_completed_streams(self):
        stream = self.relay(paired=True)
        stream.completed.set()
        denied = native.failure('gemini_unavailable', 404)
        with patch.object(stream.pair, 'check', side_effect=denied):
            with self.assertRaises(audio_store.AudioError) as caught:
                stream.receive(PRIVATE+'{')
        self.assertIs(caught.exception, denied)
        stream.cancelled.set()
        stream.pair.error = native.failure('session_ended', 409)
        with self.assertRaises(audio_store.AudioError) as caught:
            stream.receive(PRIVATE+'{')
        self.assertEqual(caught.exception.code, 'session_ended')
        self.assertIsNone(stream.validation_reason)

    def test_valid_binary_text_pcm_and_terminal_marker_are_unchanged(self):
        for paired in (False, True):
            relay = self.relay(paired)
            raw = packet(inputTranscription={'text':'source','languageCode':'id-ID'},
                         outputTranscription={'text':'target','languageCode':'en-US'})
            relay.receive(raw.encode('utf-8'))
            relay.receive(audio())
            relay.end_sent.set()
            relay.receive(packet(turnComplete=True))
            self.assertEqual(relay.source_text, 'source')
            self.assertEqual(relay.target_text, 'target')
            self.assertEqual(base64.b64decode(relay.frames[0]['pcm']), PCM)
            self.assertTrue(relay.completed.is_set())
            self.assertTrue(relay.tail_confirmed)
            self.assertEqual(relay.completion_kind, 'turn_complete')
            self.assertIsNone(relay.validation_reason)

    def test_diagnostics_only_accept_allowlisted_reasons_and_keep_first(self):
        error = native.invalid_response(PRIVATE)
        self.assertEqual(native.validation_reason(error), 'unknown')
        for raw in (PRIVATE, [PRIVATE], {'reason':PRIVATE}):
            error.validation_reason = raw
            self.assertIsNone(native.validation_reason(error))
        other = native.failure()
        other.validation_reason = 'output_language'
        self.assertIsNone(native.validation_reason(other))
        relay = self.relay()
        self.invalid(lambda:relay.receive(audio(mime=PRIVATE)), 'audio_mime')
        self.invalid(lambda:relay.receive(audio(data=PRIVATE)), 'audio_base64')
        self.assertEqual(relay.validation_reason, 'audio_mime')


if __name__ == '__main__':
    unittest.main()
