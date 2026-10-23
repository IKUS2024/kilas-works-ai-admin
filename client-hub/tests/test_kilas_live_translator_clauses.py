"""Offline committed stream, real SQLite reservations and cancellation fences."""
import json,time,unittest,os
from threading import Event,Thread
from unittest.mock import patch
import test_kilas_live_translator as fixture
import test_kilas_audio as audio
from kilas_ai import live_translator_clauses as clauses,live_translator as live
from kilas_ai import live_translator_store as sessions,live_translator_output as output
from kilas_ai import audio_branded_voices as voices,providers,live_translator_segments as segments
from kilas_ai import live_translator_realtime as realtime,live_translator_realtime_budget as budget
from test_kilas_live_translator_realtime import Socket

class ClauseTests(unittest.TestCase):
    setUp=fixture.LiveTranslatorTests.setUp
    funded=fixture.LiveTranslatorTests.funded
    on=fixture.LiveTranslatorTests.on
    credit=fixture.LiveTranslatorTests.credit
    session=fixture.LiveTranslatorTests.session
    key=fixture.LiveTranslatorTests.key
    stream=fixture.LiveTranslatorTests.stream
    @classmethod
    def setUpClass(cls):cls.audio=audio.mp3()

    def wait(self,check):
        deadline=time.monotonic()+5
        while not check() and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue(check())

    def make(self):
        self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key)
        stream=clauses.create(self.user,ident,key,info)
        self.addCleanup(stream.cancel)
        self.addCleanup(lambda:stream.worker.join(2))
        return stream

    def test_stable_clauses_are_billed_once_before_input_ends_and_ack_is_idempotent(self):
        with self.funded(),self.on(),patch.object(voices,'resolve',return_value=fixture.VOICE),patch.object(providers,'_openai',side_effect=self.stream) as translation,patch.object(segments,'speech',return_value=self.audio) as speech:
            stream=self.make()
            stream.offer('Kalimat belum lengkap')
            time.sleep(.05);translation.assert_not_called()
            stream.offer('selesai.')
            self.wait(lambda:stream.entries and sessions.result(self.user,stream.ident,stream.entries[0]['key'])['status']=='COMPLETED')
            self.assertEqual(sessions.result(self.user,stream.ident,stream.key)['status'],'PROCESSING')
            entry=stream.snapshot()['clauses'][0];key=entry['key']
            before=dict(audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE operation_key=?',(stream.key+'-audio',)))
            self.assertEqual(before['status'],'PROCESSING');self.assertEqual(before['content_origin'],'live_session');self.assertIsNone(before['result_content'])
            stream.audio.settle(key,999999);stream.ack(0);stream.ack(0);self.assertIsNone(output.get(self.user,stream.ident,key))
            self.assertEqual(dict(audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE operation_key=?',(stream.key+'-audio',))),before)
            stream.offer('Kalimat berikutnya.',final=True);stream.worker.join(3)
            self.assertTrue(stream.done);self.assertEqual(translation.call_count,2);self.assertEqual(speech.call_count,2)
            self.assertEqual(len(stream.entries),1);stream.ack(1)
            self.assertEqual(stream.snapshot()['clauses'],[])
            after=dict(audio.f.db.query_one('SELECT * FROM kilas_audio_jobs WHERE operation_key=?',(stream.key+'-audio',)))
            self.assertEqual(after['status'],'COMPLETED');self.assertGreater(after['actual_ms'],before['actual_ms'])
            self.assertEqual(after['id'],before['id']);self.assertEqual(after['reserved_seconds'],0)

    def test_relay_commits_during_uninterrupted_pcm_and_publishes_progress_before_final_input(self):
        gate=Event();entered=Event();socket=Socket(['Kalimat pertama.','Kalimat kedua.'])
        def speech(text,voice,check,on_first_byte,**kwargs):
            on_first_byte();kwargs['on_chunk'](self.audio[:200]);entered.set()
            while not gate.wait(.01):check()
            check();return self.audio
        with self.funded(),self.on(),patch.object(realtime,'connect',return_value=socket),patch.object(voices,'resolve',return_value=fixture.VOICE),patch.object(providers,'_openai',side_effect=self.stream),patch.object(segments,'speech',side_effect=speech):
            self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key);cap=budget.claim(self.user,ident,key)
            self.assertTrue(realtime._slots.acquire(blocking=False))
            relay=realtime.Relay(self.user,ident,key,info,cap,clauses=True)
            worker=Thread(target=relay.run);worker.start()
            try:
                for n in range(4):relay.accept(n,b'\x01\x00'*16000)
                self.assertTrue(entered.wait(4));self.assertFalse(relay.final);self.assertFalse(socket.closed)
                child=relay.clauses.snapshot()['clauses'][0]['key']
                self.assertEqual(output.progress_read(self.user,ident,child,0)[0],self.audio[:200])
                for n in range(4,6):relay.accept(n,b'\x01\x00'*16000)
                self.assertEqual(relay.accepted,6*32000)
                gate.set();self.wait(lambda:sessions.result(self.user,ident,child)['status']=='COMPLETED');relay.clauses.ack(0)
                relay.commit(6);worker.join(4);relay.clauses.worker.join(4)
                self.assertTrue(relay.finished);self.assertTrue(relay.clauses.done)
            finally:
                gate.set();relay.close(realtime.failure('turn_cancelled'));worker.join(3);relay.clauses.cancel()

    def test_end_cancels_inflight_and_queued_clauses_without_next_paid_dispatch(self):
        entered=Event();gate=Event()
        def translate(*args,**kwargs):
            entered.set()
            while not gate.wait(.01):pass
            yield from self.stream(*args,**kwargs)
        with self.funded(),self.on(),patch.object(voices,'resolve',return_value=fixture.VOICE),patch.object(providers,'_openai',side_effect=translate) as translation,patch.object(segments,'speech') as speech:
            stream=self.make();stream.offer('Pertama.');self.assertTrue(entered.wait(3));stream.offer('Kedua.')
            sessions.end(self.user,stream.ident);clauses.cancel(self.user,stream.ident);gate.set();stream.worker.join(3)
            self.assertFalse(stream.worker.is_alive());self.assertEqual(translation.call_count,1);speech.assert_not_called()
            self.assertIsNone(output.get(self.user,stream.ident,stream.key))

    def test_natural_pause_commits_before_four_seconds_without_closing_socket(self):
        socket=Socket(['Do not send the payment today',''])
        with self.funded(),self.on(),patch.object(realtime,'connect',return_value=socket) as connect,patch.object(voices,'resolve',return_value=fixture.VOICE),patch.object(providers,'_openai',side_effect=self.stream) as translation,patch.object(segments,'speech',return_value=self.audio):
            self.credit(300);ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key);cap=budget.claim(self.user,ident,key)
            self.assertTrue(realtime._slots.acquire(blocking=False))
            relay=realtime.Relay(self.user,ident,key,info,cap,clauses=True)
            worker=Thread(target=relay.run);worker.start()
            try:
                relay.accept(0,b'\x00\x20'*16000)
                relay.accept(1,b'\x00\x00'*16000)
                self.wait(lambda:relay.clauses.entries and sessions.result(self.user,ident,relay.clauses.entries[0]['key'])['status']=='COMPLETED')
                self.assertFalse(relay.final);self.assertFalse(socket.closed)
                self.assertEqual(socket.commits,1);self.assertEqual(translation.call_count,1)
                self.assertEqual(relay.early_commits,1);connect.assert_called_once()
                relay.clauses.ack(0);relay.commit(2);worker.join(4);relay.clauses.worker.join(4)
                self.assertTrue(relay.finished);self.assertTrue(relay.clauses.done)
            finally:
                relay.close(realtime.failure('turn_cancelled'));worker.join(3);relay.clauses.cancel()

    def test_backpressure_and_foreign_owner_fail_before_extra_work(self):
        ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key)
        stream=clauses.Stream(self.user,ident,key,info)
        stream.offer('Satu.');stream.offer('Dua.')
        with self.assertRaises(audio.store.AudioError):stream.offer('Tiga.')
        with self.assertRaises(audio.store.AudioError):clauses.owned(self.other,ident,key)
        self.assertEqual(stream.next_index,0)

    def test_disconnected_reader_stops_queue_without_new_dispatch(self):
        with self.funded(),self.on(),patch.object(providers,'_openai') as translation:
            stream=self.make();stream.last_read-=16;stream.worker.join(3)
            self.assertFalse(stream.worker.is_alive());translation.assert_not_called();self.assertTrue(stream.cancelled)

    def test_thirty_acknowledged_clauses_have_no_count_cutoff_or_accumulating_audio(self):
        with self.funded(),self.on(),patch.object(live.usage,'_qa_quota_exempt',return_value=True),patch.dict(os.environ,{'KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS':'600'}),patch.object(voices,'resolve',return_value=fixture.VOICE),patch.object(providers,'_openai',side_effect=self.stream) as translation,patch.object(segments,'speech',return_value=self.audio) as speech:
            stream=self.make()
            for index in range(30):
                stream.offer('Kalimat lengkap.')
                self.wait(lambda:stream.entries and sessions.result(self.user,stream.ident,stream.entries[0]['key'])['status']=='COMPLETED')
                self.assertEqual(len(stream.entries),1);stream.snapshot();stream.ack(index)
                self.assertLessEqual(len([a for a in output._items if a[:2]==(self.user,stream.ident)]),1)
            self.assertEqual(translation.call_count,30);self.assertEqual(speech.call_count,30)
            self.assertEqual(sessions.result(self.user,stream.ident,stream.key)['status'],'PROCESSING')
            stream.offer('',final=True);stream.worker.join(3);self.assertTrue(stream.done)

    def test_empty_balance_blocks_translation_before_dispatch(self):
        with self.funded(),self.on(),patch.object(voices,'resolve',return_value=fixture.VOICE),patch.object(providers,'_openai') as translation,patch.object(segments,'speech') as speech:
            stream=self.make()
            audio.f.db.execute('UPDATE kilas_audio_balances SET seconds=0 WHERE user_id=?',(self.user,))
            stream.offer('Kalimat lengkap.',final=True);stream.worker.join(3)
            self.assertTrue(stream.cancelled);translation.assert_not_called();speech.assert_not_called()
            self.assertEqual(stream.error.code,'zero_balance')

    def test_cancel_discards_completed_but_unplayed_audio(self):
        with self.funded(),self.on(),patch.object(voices,'resolve',return_value=fixture.VOICE),patch.object(providers,'_openai',side_effect=self.stream),patch.object(segments,'speech',return_value=self.audio):
            stream=self.make();stream.offer('Kalimat lengkap.')
            self.wait(lambda:stream.entries and sessions.result(self.user,stream.ident,stream.entries[0]['key'])['status']=='COMPLETED')
            key=stream.entries[0]['key'];self.assertIsNotNone(output.get(self.user,stream.ident,key))
            stream.cancel();stream.worker.join(3)
            self.assertIsNone(output.get(self.user,stream.ident,key))

    def test_common_title_is_not_spoken_as_a_complete_sentence(self):
        ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key)
        stream=clauses.Stream(self.user,ident,key,info);stream.offer('Dr.')
        self.assertEqual(stream.pending,[]);stream.offer('Rina is here.')
        self.assertEqual(stream.pending,['Dr. Rina is here.'])

    def test_pause_flushes_committed_tail_without_punctuation_but_fixed_commit_does_not(self):
        ident=self.session();key=self.key();info=sessions.claim(self.user,ident,key)
        stream=clauses.Stream(self.user,ident,key,info)
        stream.offer('Do not send');self.assertEqual(stream.pending,[])
        stream.offer('the payment today',phrase_end=True)
        self.assertEqual(stream.pending,['Do not send the payment today'])
        self.assertEqual(stream.tail,'');self.assertFalse(stream.final)

    def test_pause_detection_requires_speech_and_survives_fixed_duration_commit(self):
        relay=object.__new__(realtime.Relay)
        relay.clauses=True;relay.final=False;relay.quiet_bytes=0;relay.phrase_voice_bytes=0
        relay.observe_audio(b'\x00\x00'*16000);self.assertFalse(relay.early_boundary())
        relay.observe_audio(b'\x00\x20'*6400)
        # A fixed-duration commit resets its own byte window, not phrase speech.
        relay.since_commit=0;relay.quiet_bytes=0
        relay.observe_audio(b'\x00\x00'*9600);self.assertFalse(relay.early_boundary())
        relay.observe_audio(b'\x00\x00'*3200);self.assertTrue(relay.early_boundary())
        relay.final=True;self.assertFalse(relay.early_boundary())

if __name__=='__main__':unittest.main()
