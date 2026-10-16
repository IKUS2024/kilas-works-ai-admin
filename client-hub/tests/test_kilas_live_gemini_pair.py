"""Two native streams, one synthetic capture/reservation; offline SQLite only."""
import base64
import io
import json
import unittest
from contextlib import redirect_stdout
from queue import Empty, Queue
from threading import Event, Thread
from unittest.mock import patch

import test_kilas_live_gemini as fixture
from kilas_ai import audio_store, live_gemini as native, live_gemini_budget as budget
from kilas_ai import live_gemini_pair as pair, live_translator_store as sessions


PCM = b'\x01\x00' * 2400


def audio(pcm=PCM, **content):
    content['modelTurn'] = {'parts':[{'inlineData':{
        'mimeType':'audio/pcm;rate=24000', 'data':base64.b64encode(pcm).decode('ascii')}}]}
    return json.dumps({'serverContent':content})


class Socket:
    def __init__(self, terminal=True):
        self.incoming = Queue()
        self.incoming.put('{"setupComplete":{}}')
        self.sent = []
        self.closed = Event()
        self.configured = Event()
        self.terminal = terminal

    def settimeout(self, value):
        pass

    def send(self, raw):
        value = json.loads(raw)
        self.sent.append(value)
        if 'setup' in value:
            self.configured.set()
        if value.get('realtimeInput', {}).get('audioStreamEnd') and self.terminal:
            self.incoming.put('{"serverContent":{"turnComplete":true}}')

    def recv(self):
        import websocket
        try:
            value = self.incoming.get(timeout=.02)
        except Empty:
            raise websocket.WebSocketTimeoutException() from None
        if value is None:
            raise OSError('synthetic socket stop')
        return value

    def shutdown(self):
        if not self.closed.is_set():
            self.closed.set()
            self.incoming.put(None)


class PairTests(unittest.TestCase):
    setUp = fixture.GeminiTests.setUp
    config = fixture.GeminiTests.config
    credit = fixture.GeminiTests.credit
    key = fixture.GeminiTests.key
    wait = fixture.GeminiTests.wait

    def make(self):
        self.credit(300)
        ident = sessions.create(self.user, 'en', 'id', pair.VOICE)
        with patch.object(pair.Thread, 'start'):
            relay = pair.start(self.user, ident, self.key())
        self.addCleanup(lambda:native.cancel(self.user, ident))
        self.addCleanup(lambda: [native._slots.release() for _ in range(2)] if not relay.finished else None)
        return relay

    def ledger(self):
        return fixture.audio.f.db.query_one(
            'SELECT COUNT(*) AS n,MIN(status) AS first,MAX(status) AS last,SUM(charge_micro) AS charge '
            'FROM kilas_vo_stt_operations WHERE user_id=?', (self.user,))

    def run_pair(self, relay, sockets, action=None):
        with patch.object(native, 'connect', side_effect=sockets) as connect, redirect_stdout(io.StringIO()):
            runner = Thread(target=relay.run)
            runner.start()
            try:
                if action:
                    action(runner)
                runner.join(3)
            finally:
                if runner.is_alive():
                    relay.stop(native.failure('synthetic_test_timeout'))
                    runner.join(3)
        self.assertFalse(runner.is_alive())
        return connect

    def test_two_fixed_targets_share_capture_then_publish_contiguous_runs_after_both_settle(self):
        with self.config():
            relay = self.make()
            en, indonesian = Socket(), Socket()
            def interact(runner):
                self.assertTrue(en.configured.wait(2) and indonesian.configured.wait(2))
                relay.accept(0, b'\x02\x00' * 1600)
                for socket, pcm, expected in ((en, PCM, 1), (indonesian, b'\x02\x00'*2400, 2),
                                              (en, b'\x03\x00'*2400, 3), (indonesian, b'\x04\x00'*2400, 4)):
                    socket.incoming.put(audio(pcm))
                    self.wait(lambda:relay.output_bytes == expected*len(PCM))
                before = relay.snapshot(0)
                self.assertEqual(before['frames'], [])
                self.assertFalse(before['output_closed'])
                self.assertEqual(before['input_mode'], pair.INPUT_MODE)
                relay.finish_input(1)
            connect = self.run_pair(relay, [en, indonesian], interact)
            final = relay.snapshot(0)
            self.assertEqual(final['status'], 'COMPLETED')
            self.assertTrue(final['output_closed'])
            self.assertTrue(final['tail_confirmed'])
            self.assertEqual(final['completion_kind'], 'turn_complete')
            self.assertEqual(final['output_order'], 'stream_runs_after_close')
            self.assertEqual([frame['stream_id'] for frame in final['frames']], ['en','en','id','id'])
            self.assertEqual([frame['index'] for frame in final['frames']], [0,1,2,3])
            expected = [PCM,b'\x03\x00'*2400,b'\x02\x00'*2400,b'\x04\x00'*2400]
            self.assertEqual([base64.b64decode(frame['pcm']) for frame in final['frames']], expected)
            self.assertEqual(final['total_frames'], 4)
            self.assertTrue(all(stream['output_closed'] for stream in final['streams'].values()))
            self.assertEqual(connect.call_count, 2)
            for target, socket in (('en',en), ('id',indonesian)):
                self.assertEqual(socket.sent[0], native.setup(target))
                self.assertFalse(socket.sent[0]['setup']['generationConfig']['translationConfig']['echoTargetLanguage'])
                self.assertTrue(socket.closed.is_set())
            packets = lambda socket:[value for value in socket.sent if value.get('realtimeInput',{}).get('audio')]
            self.assertEqual(packets(en), packets(indonesian))
            self.assertEqual(len(packets(en)), 1)
            self.assertEqual(relay.sent_bytes, 3200)
            self.assertEqual(relay.streams['en'].sent_bytes, 3200)
            self.assertEqual(dict(self.ledger()), {'n':2,'first':'COMPLETED','last':'COMPLETED','charge':2000})
            self.assertEqual(audio_store.get(self.user, relay.job)['actual_ms'], 400)
            with patch.object(budget, 'finish') as settle, patch.object(native, 'connect') as reconnect:
                relay.run()
            settle.assert_not_called()
            reconnect.assert_not_called()

    def test_independent_bounded_tails_never_claim_semantic_confirmation(self):
        with self.config(), patch.object(native, 'TAIL_GRACE_SECONDS', .04), \
             patch.object(native, 'TAIL_MAX_SECONDS', .06), patch.object(native, 'TAIL_QUIET_SECONDS', .015):
            relay = self.make()
            sockets = [Socket(terminal=False), Socket(terminal=False)]
            relay.accept(0, b'\0\0'*1600)
            relay.finish_input(1)
            self.run_pair(relay, sockets)
            final = relay.snapshot(0)
            self.assertEqual(final['status'], 'COMPLETED')
            self.assertEqual(final['completion_kind'], 'bounded_drain')
            self.assertFalse(final['tail_confirmed'])
            self.assertEqual(final['tail_code'], 'gemini_tail_unconfirmed')
            self.assertEqual(final['total_frames'], 0)
            self.assertEqual(set(final['streams']), {'en','id'})
            self.assertTrue(all(stream['completion_kind'] == 'bounded_drain'
                                for stream in final['streams'].values()))

    def test_one_explicit_tail_does_not_close_or_confirm_the_whole_pair(self):
        with self.config(), patch.object(native, 'TAIL_GRACE_SECONDS', .2), \
             patch.object(native, 'TAIL_MAX_SECONDS', .3), patch.object(native, 'TAIL_QUIET_SECONDS', .05):
            relay = self.make()
            sockets = [Socket(), Socket(terminal=False)]
            relay.accept(0, b'\0\0'*1600)
            relay.finish_input(1)
            def first_done(runner):
                self.wait(lambda:relay.streams['en'].stopped)
                self.assertFalse(relay.finished)
                self.assertEqual(relay.snapshot(0)['frames'], [])
            self.run_pair(relay, sockets, first_done)
            final = relay.snapshot(0)
            self.assertEqual(final['status'], 'COMPLETED')
            self.assertEqual(final['completion_kind'], 'bounded_drain')
            self.assertFalse(final['tail_confirmed'])
            self.assertTrue(final['streams']['en']['tail_confirmed'])
            self.assertFalse(final['streams']['id']['tail_confirmed'])

    def test_second_handshake_failure_closes_first_and_keeps_full_pair_charge(self):
        with self.config():
            relay = self.make()
            first = Socket()
            with patch.object(native, 'connect', side_effect=[first, OSError('synthetic private key')]) as connect, \
                 redirect_stdout(io.StringIO()):
                relay.run()
            self.assertEqual(connect.call_count, 2)
            self.assertTrue(first.closed.is_set())
            self.assertEqual(relay.error.code, 'gemini_transport')
            self.assertNotIn('private', str(relay.error))
            self.assertEqual(dict(self.ledger()), {'n':2,'first':'UNKNOWN','last':'UNKNOWN','charge':2000})
            self.assertEqual(relay.snapshot(0)['status'], 'FAILED')
            self.assertEqual(relay.snapshot(0)['total_frames'], 0)

    def test_one_leg_failure_stops_both_and_keeps_accepted_audio_for_final_drain(self):
        with self.config():
            relay = self.make()
            sockets = [Socket(), Socket()]
            def interact(runner):
                self.assertTrue(sockets[1].configured.wait(2))
                relay.accept(0, b'\0\0'*1600)
                sockets[0].incoming.put(audio())
                self.wait(lambda:relay.output_bytes == len(PCM))
                sockets[1].incoming.put('')
            self.run_pair(relay, sockets, interact)
            final = relay.snapshot(0)
            self.assertEqual(final['status'], 'FAILED')
            self.assertEqual(final['code'], 'gemini_transport')
            self.assertEqual(final['total_frames'], 1)
            self.assertEqual(final['frames'][0]['stream_id'], 'en')
            self.assertTrue(all(socket.closed.is_set() for socket in sockets))
            self.assertEqual(audio_store.get(self.user, relay.job)['actual_ms'], 100)
            self.assertEqual(self.ledger()['charge'], 2000)

    def test_aggregate_output_admission_is_atomic_across_both_parsers(self):
        with self.config(), patch.object(native, 'OUTPUT_BYTES', len(PCM)):
            relay = self.make()
            results = []
            def receive(stream):
                try:
                    stream.receive(audio())
                    results.append('accepted')
                except audio_store.AudioError as error:
                    results.append(error.code)
                finally:
                    native.db._discard_cached_connection()
            threads = [Thread(target=receive, args=(stream,)) for stream in relay.streams.values()]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(2)
            self.assertCountEqual(results, ['accepted','gemini_output_limit'])
            self.assertEqual(relay.output_bytes, len(PCM))
            self.assertEqual(relay.rejected_output_bytes, len(PCM))
            self.assertEqual(sum(len(stream.frames) for stream in relay.streams.values()), 1)
            budget.finish(relay.capability, False)
            audio_store.fail(self.user, relay.job, 'synthetic')

    def test_per_stream_interruptions_and_target_metadata_stay_isolated(self):
        with self.config():
            relay = self.make()
            en, indonesian = relay.streams['en'], relay.streams['id']
            en.receive(audio())
            indonesian.receive(audio())
            en.receive(audio(interrupted=True))
            indonesian.receive(audio())
            self.assertEqual(en.generation, 1)
            self.assertEqual(indonesian.generation, 0)
            self.assertEqual([frame['generation'] for frame in en.frames], [0,1,1])
            self.assertEqual([frame['generation'] for frame in indonesian.frames], [0,0])
            with self.assertRaises(audio_store.AudioError) as caught:
                en.receive(audio(outputTranscription={'text':'wrong target','languageCode':'id'}))
            self.assertEqual(caught.exception.code, 'gemini_response_invalid')
            en.receive(audio(outputTranscription={'text':'right target','languageCode':'en-US'}))
            with self.assertRaises(audio_store.AudioError):
                en.receive(audio(inputTranscription={'text':'outside pair','languageCode':'ja'}))
            budget.finish(relay.capability, False)
            audio_store.fail(self.user, relay.job, 'synthetic')

    def test_parent_failure_between_child_check_and_parser_lock_is_not_explicit_end(self):
        with self.config():
            relay = self.make()
            stream = relay.streams['en']
            stream.receive(audio())
            def fail_after_check():
                relay.stop(native.failure('gemini_transport'))
            with patch.object(relay, 'check', side_effect=fail_after_check):
                with self.assertRaises(audio_store.AudioError) as caught:
                    stream.receive(audio())
            self.assertEqual(caught.exception.code, 'gemini_transport')
            self.assertEqual(relay.first_error.code, 'gemini_transport')
            self.assertFalse(relay.discarded)
            self.assertEqual(len(stream.frames), 1)
            budget.finish(relay.capability, False)
            audio_store.fail(self.user, relay.job, 'synthetic')

    def test_end_cancels_both_immediately_and_never_republishes_after_first_failure(self):
        with self.config():
            relay = self.make()
            sockets = [Socket(), Socket()]
            def interact(runner):
                self.assertTrue(sockets[1].configured.wait(2))
                relay.accept(0, b'\0\0'*1600)
                sockets[0].incoming.put(audio())
                self.wait(lambda:relay.output_bytes == len(PCM))
                relay.stop(native.failure('gemini_transport'))
                sessions.end(self.user, relay.ident)
                native.cancel(self.user, relay.ident)
            self.run_pair(relay, sockets, interact)
            self.assertEqual(relay.error.code, 'gemini_transport')
            self.assertTrue(relay.discarded)
            self.assertEqual(relay.frames, [])
            self.assertTrue(all(stream.frames == [] for stream in relay.streams.values()))
            self.assertTrue(all(socket.closed.is_set() for socket in sockets))
            self.assertEqual(audio_store.get(self.user, relay.job)['actual_ms'], 100)
            with self.assertRaises(audio_store.AudioError):
                relay.snapshot(0)

    def test_end_between_final_frame_copy_and_publication_cannot_reveal_buffered_pcm(self):
        with self.config():
            relay = self.make()
            sockets = [Socket(), Socket()]
            copied, release = Event(), Event()
            original_publish = relay.publish
            def pause_publication(frames):
                self.assertEqual(len(frames), 1)
                copied.set()
                if not release.wait(3):
                    raise RuntimeError('synthetic publication gate timeout')
                original_publish(frames)
            with patch.object(native, 'connect', side_effect=sockets), \
                 patch.object(relay, 'publish', side_effect=pause_publication), redirect_stdout(io.StringIO()):
                runner = Thread(target=relay.run)
                runner.start()
                try:
                    self.assertTrue(sockets[1].configured.wait(2))
                    relay.accept(0, b'\0\0'*1600)
                    sockets[0].incoming.put(audio())
                    self.wait(lambda:relay.output_bytes == len(PCM))
                    relay.stop(native.failure('gemini_transport'))
                    self.assertTrue(copied.wait(2))
                    sessions.end(self.user, relay.ident)
                    native.cancel(self.user, relay.ident)
                finally:
                    release.set()
                    runner.join(3)
            self.assertFalse(runner.is_alive())
            self.assertTrue(relay.finished)
            self.assertTrue(relay.discarded)
            self.assertEqual(relay.error.code, 'gemini_transport')
            self.assertEqual(relay.frames, [])
            self.assertTrue(all(stream.frames == [] for stream in relay.streams.values()))

    def test_failed_pair_keeps_multi_page_cursor_and_charge_without_retry(self):
        with self.config():
            relay = self.make()
            sockets = [Socket(), Socket()]
            def interact(runner):
                self.assertTrue(sockets[1].configured.wait(2))
                relay.accept(0, b'\0\0'*1600)
                for _ in range(14):
                    sockets[0].incoming.put(audio())
                self.wait(lambda:relay.output_bytes == 14*len(PCM))
                sockets[1].incoming.put('{"error":{}}')
            self.run_pair(relay, sockets, interact)
            first = relay.snapshot(0)
            last = relay.snapshot(first['next_index'])
            self.assertEqual(first['status'], 'FAILED')
            self.assertEqual(first['code'], 'gemini_response_invalid')
            self.assertEqual(first['total_frames'], 14)
            self.assertEqual(first['frames'], relay.snapshot(0)['frames'])
            self.assertEqual([frame['index'] for frame in first['frames']+last['frames']], list(range(14)))
            self.assertEqual(audio_store.get(self.user, relay.job)['actual_ms'], 1400)
            self.assertEqual(self.ledger()['charge'], 2000)

    def test_end_during_dispatch_never_connects_and_relinquishes_both_units(self):
        with self.config():
            relay = self.make()
            original = budget.dispatch
            def end(capability):
                original(capability)
                sessions.end(self.user, relay.ident)
                native.cancel(self.user, relay.ident)
            with patch.object(budget, 'dispatch', side_effect=end), \
                 patch.object(native, 'connect') as connect, redirect_stdout(io.StringIO()):
                relay.run()
            connect.assert_not_called()
            self.assertEqual(relay.error.code, 'turn_cancelled')
            self.assertEqual(dict(self.ledger()), {'n':2,'first':'UNKNOWN','last':'UNKNOWN','charge':2000})

    def test_legacy_session_and_legacy_relay_cannot_be_upgraded_by_pair_api(self):
        with self.config():
            self.credit(300)
            ident = sessions.create(self.user, 'en', 'id', native.VOICE)
            self.addCleanup(lambda:sessions.end(self.user, ident))
            with patch.object(native, 'connect') as connect:
                with self.assertRaises(audio_store.AudioError) as caught:
                    pair.start(self.user, ident, self.key())
            self.assertEqual(caught.exception.code, 'gemini_session_changed')
            connect.assert_not_called()
            fake = native.Relay(self.user, ident, self.key(), {'language_a':'en','language_b':'id'}, None, None)
            with patch.object(native, 'owned', return_value=fake):
                with self.assertRaises(audio_store.AudioError):
                    pair.owned(self.user, ident, self.key())

    def test_landing_requires_pair_allowance_but_active_checks_do_not_use_availability(self):
        with patch.object(native, 'ready', return_value=True), \
             patch.object(budget, 'status', return_value={'available':False}) as status:
            self.assertFalse(pair.ready(9))
            status.assert_called_once_with(9, streams=2)
        with self.config():
            relay = self.make()
            with patch.object(budget, 'status', side_effect=AssertionError('active availability read')):
                relay.check()
            budget.finish(relay.capability, False)
            audio_store.fail(self.user, relay.job, 'synthetic')


if __name__ == '__main__':
    unittest.main()
