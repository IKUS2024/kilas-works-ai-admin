"""Bounded native completion using disposable SQLite and synthetic sockets only."""
import base64
import io
import json
import time
import unittest
from contextlib import redirect_stdout
from queue import Empty, Queue
from threading import BoundedSemaphore, Event, Thread
from unittest.mock import patch

import test_kilas_live_gemini as fixture
from kilas_ai import audio_store, live_gemini as native, live_gemini_budget as budget
from kilas_ai import live_translator_store as sessions


PCM = b'\x01\x00' * 2400


def output(parts=1, **content):
    content['modelTurn'] = {'parts':[{'inlineData':{
        'mimeType':'audio/pcm;rate=24000', 'data':base64.b64encode(PCM).decode('ascii')
    }} for _ in range(parts)]}
    return json.dumps({'serverContent':content})


class ContinuousSocket:
    """No EOF or turn marker unless explicitly requested by a test."""
    def __init__(self, terminal=None, post_end_audio=True):
        self.incoming = Queue()
        self.incoming.put('{"setupComplete":{}}')
        self.terminal = terminal
        self.post_end_audio = post_end_audio
        self.sent = []
        self.closed = Event()
        self.timeout = .02

    def settimeout(self, value):
        self.timeout = min(value, .02)

    def send(self, raw):
        value = json.loads(raw)
        self.sent.append(value)
        realtime = value.get('realtimeInput', {})
        if realtime.get('audio'):
            self.incoming.put(output(outputTranscription={'text':'First. '}))
        if realtime.get('audioStreamEnd'):
            if self.post_end_audio:
                self.incoming.put(output(outputTranscription={'text':'Tail.'}, generationComplete=True))
            if self.terminal is not None:
                self.incoming.put(self.terminal)

    def recv(self):
        import websocket
        try:
            value = self.incoming.get(timeout=self.timeout)
        except Empty:
            raise websocket.WebSocketTimeoutException() from None
        if value is None:
            raise OSError('synthetic local socket stop')
        return value

    def shutdown(self):
        if not self.closed.is_set():
            self.closed.set()
            self.incoming.put(None)


class CompletionTests(unittest.TestCase):
    setUp = fixture.GeminiTests.setUp
    config = fixture.GeminiTests.config
    make = fixture.GeminiTests.make
    credit = fixture.GeminiTests.credit
    key = fixture.GeminiTests.key
    row = fixture.GeminiTests.row
    wait = fixture.GeminiTests.wait

    def run_socket(self, socket):
        relay = self.make()
        relay.accept(0, b'\x01\x00' * 1600)
        relay.finish_input(1)
        with patch.object(native, 'connect', return_value=socket), \
             patch.object(native, 'TAIL_GRACE_SECONDS', .06), redirect_stdout(io.StringIO()):
            relay.run()
        return relay

    def test_continuous_stream_locally_finishes_and_retains_unconfirmed_tail(self):
        with self.config():
            socket = ContinuousSocket()
            relay = self.run_socket(socket)
            final = relay.snapshot(0)
            self.assertTrue(relay.completed.is_set())
            self.assertTrue(socket.closed.is_set())
            self.assertEqual(final['status'], 'COMPLETED')
            self.assertEqual(final['completion_kind'], 'bounded_drain')
            self.assertFalse(final['tail_confirmed'])
            self.assertEqual(final['tail_code'], 'gemini_tail_unconfirmed')
            self.assertIsNone(final['code'])
            self.assertEqual(final['translated_text'], 'First. Tail.')
            self.assertTrue(final['output_closed'])
            self.assertEqual(final['total_frames'], 2)
            self.assertEqual(len(final['frames']), 2)
            self.assertEqual(relay.diagnostics()['turn_complete_count'], 0)
            self.assertEqual(relay.diagnostics()['generation_complete_after_end'], 1)
            self.assertEqual(self.row()['status'], 'COMPLETED')
            self.assertEqual(audio_store.get(self.user, relay.job)['actual_ms'], 200)
            self.assertFalse(sessions.status(self.user, relay.ident)['processing'])
            # A new physical operation may claim the same active logical session.
            next_key = 'live-' + 'd' * 32
            info = sessions.claim(self.user, relay.ident, next_key)
            self.assertEqual(info['voice_alias'], native.VOICE)
            sessions.cancel_turn(self.user, relay.ident, next_key)

    def test_silence_and_usage_are_unconfirmed_after_bounded_window(self):
        with self.config():
            socket = ContinuousSocket(post_end_audio=False)
            socket.incoming.put('{"usageMetadata":{"totalTokenCount":1}}')
            relay = self.run_socket(socket)
            self.assertEqual(relay.completion_kind, 'bounded_drain')
            self.assertFalse(relay.tail_confirmed)
            self.assertIsNone(relay.error)
            self.assertEqual(relay.snapshot(0)['total_frames'], 1)

    def test_explicit_terminal_marker_is_distinct_from_local_stop(self):
        with self.config():
            relay = self.run_socket(ContinuousSocket('{"serverContent":{"turnComplete":true}}'))
            final = relay.snapshot(0)
            self.assertEqual(final['completion_kind'], 'turn_complete')
            self.assertTrue(final['tail_confirmed'])
            self.assertIsNone(final['tail_code'])
            self.assertTrue(relay.diagnostics()['tail_confirmed'])
            self.assertEqual(final['total_frames'], 2)

    def test_eof_before_local_bound_is_failure_but_keeps_all_accepted_pcm(self):
        with self.config():
            relay = self.run_socket(ContinuousSocket(b''))
            final = relay.snapshot(0)
            self.assertEqual(final['status'], 'FAILED')
            self.assertEqual(final['code'], 'gemini_tail_unconfirmed')
            self.assertIsNone(final['completion_kind'])
            self.assertFalse(final['tail_confirmed'])
            self.assertEqual(final['total_frames'], 2)
            self.assertEqual(len(final['frames']), 2)
            self.assertTrue(final['output_closed'])
            self.assertEqual(self.row()['status'], 'UNKNOWN')
            self.assertEqual(audio_store.get(self.user, relay.job)['actual_ms'], 200)

    def test_validation_failure_keeps_multi_page_frames_and_settles_once(self):
        with self.config():
            socket = ContinuousSocket('{"serverContent":{"modelTurn":{"parts":[null]}}}')
            # More than one snapshot page, all accepted before protocol failure.
            socket.incoming.put(output(18))
            relay = self.run_socket(socket)
            first = relay.snapshot(0)
            last = relay.snapshot(first['next_index'])
            self.assertEqual(first['status'], 'FAILED')
            self.assertEqual(first['code'], 'gemini_response_invalid')
            self.assertEqual(first['next_index'], 12)
            self.assertEqual(first['total_frames'], 20)
            self.assertEqual(last['next_index'], 20)
            self.assertEqual([frame['index'] for frame in first['frames'] + last['frames']], list(range(20)))
            self.assertEqual(relay.output_bytes, 20 * len(PCM))
            job = audio_store.get(self.user, relay.job)
            self.assertEqual(job['actual_ms'], 2000)
            self.assertEqual(job['seconds_charged'], 2)
            with patch.object(native, 'connect') as connect, \
                 patch.object(audio_store, 'finish') as settle, patch.object(budget, 'finish') as finish_budget:
                relay.run()
            connect.assert_not_called()
            settle.assert_not_called()
            finish_budget.assert_not_called()
            self.assertEqual(relay.diagnostics()['first_error_code'], 'gemini_response_invalid')

    def test_snapshot_cannot_mix_old_processing_status_with_finished_publication(self):
        with self.config():
            relay = self.make()
            socket = ContinuousSocket('{"serverContent":{"turnComplete":true}}')
            audio_settling, release_audio = Event(), Event()
            status_read, release_status, durable_terminal = Event(), Event(), Event()
            original_audio_finish = audio_store.finish
            original_result, original_session_finish = sessions.result, sessions.finish
            snapshots, errors = [], []
            def pause_audio_settlement(*args, **kwargs):
                audio_settling.set()
                if not release_audio.wait(3):
                    raise RuntimeError('synthetic settlement gate timed out')
                return original_audio_finish(*args, **kwargs)
            def pause_status_read(*args):
                state = original_result(*args)
                status_read.set()
                if not release_status.wait(3):
                    raise RuntimeError('synthetic snapshot gate timed out')
                return state
            def publish_durable_terminal(*args, **kwargs):
                result = original_session_finish(*args, **kwargs)
                durable_terminal.set()
                return result
            def read_snapshot():
                try:
                    snapshots.append(relay.snapshot(0))
                except Exception as error:
                    errors.append(error)
                finally:
                    native.db._discard_cached_connection()
            reader = None
            with patch.object(native, 'connect', return_value=socket), \
                 patch.object(audio_store, 'finish', side_effect=pause_audio_settlement), \
                 patch.object(sessions, 'result', side_effect=pause_status_read), \
                 patch.object(sessions, 'finish', side_effect=publish_durable_terminal), \
                 redirect_stdout(io.StringIO()):
                runner = Thread(target=relay.run)
                runner.start()
                try:
                    relay.accept(0, b'\x01\x00' * 1600)
                    relay.finish_input(1)
                    self.assertTrue(audio_settling.wait(3))
                    reader = Thread(target=read_snapshot)
                    reader.start()
                    self.assertTrue(status_read.wait(3))
                    # The paused PROCESSING read owns the publication lock.
                    # A real concurrent finalizer may commit its durable state,
                    # but cannot publish output_closed until that read returns.
                    lock_available = relay.lock.acquire(blocking=False)
                    if lock_available:
                        relay.lock.release()
                    release_audio.set()
                    self.assertTrue(durable_terminal.wait(3))
                    finished_during_read = relay.finished
                finally:
                    release_audio.set()
                    release_status.set()
                    if reader is not None:
                        reader.join(3)
                    runner.join(3)
            self.assertFalse(lock_available)
            self.assertFalse(finished_during_read)
            self.assertFalse(runner.is_alive())
            self.assertFalse(reader.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(snapshots[0]['status'], 'PROCESSING')
            self.assertFalse(snapshots[0]['output_closed'])
            self.assertIsNone(snapshots[0]['total_frames'])
            final = relay.snapshot(0)
            self.assertEqual(final['status'], 'COMPLETED')
            self.assertTrue(final['output_closed'])
            self.assertEqual(final['total_frames'], 2)

    def test_continuous_audio_does_not_extend_fixed_post_eos_window(self):
        with self.config():
            relay = self.make()
            base = relay.started
            relay.end_at = base + 15
            relay.end_sent.set()
            relay.input_closed = True
            with patch.object(native, 'monotonic', return_value=base + 18.999):
                # A large accepted burst must remain readable without prolonging
                # the final socket window by its30s PCM duration.
                for _ in range(3):
                    relay.receive(output(100))
                self.assertFalse(relay.finish_drain())
            self.assertEqual(relay.drain_deadline(), base + 19)
            with patch.object(native, 'monotonic', return_value=base + 19):
                self.assertTrue(relay.finish_drain())
            self.assertFalse(relay.tail_confirmed)
            self.assertEqual(len(relay.frames), 300)
            budget.finish(relay.capability, False)
            audio_store.fail(self.user, relay.job, 'synthetic')

    def test_hard_lease_still_fails_before_incomplete_drain_can_renew(self):
        with self.config():
            relay = self.make()
            relay.end_at = relay.started + 89
            relay.end_sent.set()
            relay.input_closed = True
            with patch.object(native, 'monotonic', return_value=relay.started + 90), \
                 patch.object(relay.cancelled, 'wait', return_value=False):
                relay.watch()
            self.assertEqual(relay.error.code, 'gemini_deadline')
            self.assertFalse(relay.completed.is_set())
            self.assertFalse(relay.tail_confirmed)
            budget.finish(relay.capability, False)
            audio_store.fail(self.user, relay.job, 'synthetic')

    def test_admission_delay_consumes_lease_and_never_gets_a_fresh_socket(self):
        with self.config():
            clock = [time.monotonic()]
            began = clock[0]
            original_claim = budget.claim
            def delayed_claim(*args):
                capability = original_claim(*args)
                clock[0] += 91
                return capability
            with patch.object(native, 'monotonic', side_effect=lambda:clock[0]), \
                 patch.object(budget, 'claim', side_effect=delayed_claim):
                relay = self.make()
                self.assertEqual(relay.started, began)
                self.assertEqual(relay.last_input, began + 91)
                with patch.object(native, 'connect') as connect, \
                     patch.object(native, 'Timer') as timer, redirect_stdout(io.StringIO()):
                    relay.run()
                connect.assert_not_called()
                self.assertEqual(timer.call_args.args[0], 0)
            self.assertEqual(relay.error.code, 'gemini_deadline')
            self.assertEqual(self.row()['status'], 'CANCELLED')
            self.assertEqual(self.row()['charge_micro'], 0)

    def test_end_while_dispatch_waits_never_opens_provider_socket(self):
        with self.config():
            relay = self.make()
            original_dispatch = budget.dispatch
            def end_after_dispatch(capability):
                original_dispatch(capability)
                sessions.end(self.user, relay.ident)
                native.cancel(self.user, relay.ident)
            with patch.object(budget, 'dispatch', side_effect=end_after_dispatch), \
                 patch.object(native, 'connect') as connect, redirect_stdout(io.StringIO()):
                relay.run()
            connect.assert_not_called()
            self.assertEqual(relay.error.code, 'turn_cancelled')
            self.assertEqual(self.row()['status'], 'UNKNOWN')
            self.assertEqual(relay.frames, [])

    def test_failed_admission_settlement_still_releases_slot_and_session_turn(self):
        with self.config():
            self.credit(300)
            ident = sessions.create(self.user, 'id', 'en', native.VOICE)
            self.addCleanup(lambda:sessions.end(self.user, ident))
            slots = BoundedSemaphore(1)
            with patch.object(native, '_slots', slots), \
                 patch.object(audio_store, 'create', side_effect=native.failure('synthetic_admission')), \
                 patch.object(budget, 'finish', side_effect=OSError('synthetic private DB failure')), \
                 patch.object(native, 'connect') as connect:
                with self.assertRaises(audio_store.AudioError) as caught:
                    native.start(self.user, ident, self.key())
            self.assertEqual(caught.exception.code, 'gemini_settlement_failed')
            self.assertNotIn('private', str(caught.exception))
            connect.assert_not_called()
            self.assertFalse(sessions.status(self.user, ident)['processing'])
            self.assertTrue(slots.acquire(blocking=False))
            slots.release()

    def test_first_failure_is_not_reclassified_as_bounded_completion(self):
        with self.config():
            relay = self.make()
            relay.end_at = relay.started
            relay.end_sent.set()
            relay.stop(native.failure('gemini_output_limit', 429))
            with patch.object(native, 'monotonic', return_value=relay.started + 5):
                self.assertFalse(relay.finish_drain())
            self.assertEqual(relay.error.code, 'gemini_output_limit')
            self.assertIsNone(relay.completion_kind)
            self.assertFalse(relay.completed.is_set())
            budget.finish(relay.capability, False)
            audio_store.fail(self.user, relay.job, 'synthetic')

    def test_end_during_bounded_receive_cancels_immediately_and_hides_frames(self):
        with self.config():
            socket = ContinuousSocket()
            relay = self.make()
            with patch.object(native, 'connect', return_value=socket), redirect_stdout(io.StringIO()):
                runner = Thread(target=relay.run)
                runner.start()
                relay.accept(0, b'\x01\x00' * 1600)
                relay.finish_input(1)
                self.wait(lambda:relay.end_sent.is_set() and len(relay.frames) == 2)
                before = time.monotonic()
                sessions.end(self.user, relay.ident)
                native.cancel(self.user, relay.ident)
                runner.join(1)
            self.assertFalse(runner.is_alive())
            self.assertLess(time.monotonic() - before, 1)
            self.assertTrue(socket.closed.is_set())
            self.assertEqual(relay.error.code, 'turn_cancelled')
            self.assertEqual(relay.frames, [])
            self.assertEqual(audio_store.get(self.user, relay.job)['actual_ms'], 200)
            with self.assertRaises(audio_store.AudioError):
                relay.snapshot(0)


if __name__ == '__main__':
    unittest.main()
