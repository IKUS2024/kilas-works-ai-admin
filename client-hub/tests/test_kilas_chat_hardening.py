"""Seven audit regressions. Synthetic users, streams and files; no paid calls."""
import io
import re
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
import test_kilas_chat_models as fixture
from kilas_ai import store, attachments, conversation_context, chat_transport, providers
from kilas_ai import thread_context_checkpoint, autonomous_store as jobs, usage
import app, db


class HardeningTests(unittest.TestCase):
    setUp = fixture.RouteTests.setUp
    client = fixture.RouteTests.client
    submit = fixture.RouteTests.submit

    def test_legacy_replay_is_payload_bound_and_does_not_redispatch(self):
        key='hardening_retry_000000001'
        with patch.object(providers,'stream',side_effect=fixture.answer) as provider:
            first=self.submit(agent=False,text='Jelaskan API.',key=key)
            second=self.submit(agent=False,text='Jelaskan API.',key=key)
            conflict=self.submit(agent=False,text='Jelaskan SQL.',key=key)
        self.assertIn('event: done',first.text);self.assertIn('event: done',second.text)
        self.assertEqual(provider.call_count,1)
        self.assertEqual(conflict.status_code,409);self.assertEqual(conflict.json['code'],'operation_payload_conflict')
        self.assertEqual(len(store.messages(self.owner,self.thread)),2)
        rows=db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=? AND operation_key=?',(self.owner,key))
        self.assertEqual(len(rows),1)

    def test_payload_binding_concurrent_and_owner_thread_scoped(self):
        barrier=threading.Barrier(2);key='hardening_parallel_00001'
        def claim(text):
            barrier.wait()
            try:store.bind_request(self.owner,self.thread,key,MultiDict({'content':text}),[],text);return 'bound'
            except ValueError:return 'conflict'
        with ThreadPoolExecutor(2) as pool:
            results=[pool.submit(claim,t) for t in ('A','B')]
            self.assertCountEqual([f.result() for f in results],['bound','conflict'])
        foreign=store.create_thread(self.other)
        store.bind_request(self.other,foreign,key,MultiDict({'content':'C'}),[],'C')
        with self.assertRaises(ValueError):store.bind_request(self.owner,store.create_thread(self.owner),key,MultiDict({'content':'C'}),[],'C')

    def test_upload_http_and_component_limits_agree(self):
        limits=attachments.limits('FREE')
        self.assertEqual(limits['max_image_bytes'],8*1024**2)
        self.assertEqual(limits['max_file_bytes'],2*1024**2)
        self.assertEqual(limits['max_total_bytes'],10*1024**2)
        with patch.object(providers,'stream',side_effect=AssertionError('No dispatch for rejected input')) as provider:
            response=self.client().post(f'/kilas-ai/threads/{self.thread}/send',data={
                'csrf_token':'work-csrf','content':'Baca gambar.','operation_key':'hardening_oversize_00001',
                'attachments':(io.BytesIO(b'x'*(13*1024**2)),'photo.jpg','image/jpeg')})
            self.assertEqual(response.status_code,413);self.assertEqual(response.json['code'],'attachment_request_too_large')
            provider.assert_not_called()
        with self.assertRaises(attachments.AttachmentError):
            attachments.validate_total([{'source_byte_size':6*1024**2,'byte_size':100}]*2)
        page=self.client().get(f'/kilas-ai/threads/{self.thread}').text
        self.assertIn('data-max-image-bytes="8388608"',page)
        self.assertIn('data-max-total-bytes="10485760"',page)

    def test_legacy_early_fact_late_correction_pagination_and_isolation(self):
        with jobs.transaction() as conn:
            for i in range(250):
                text='Ingat kode produk ORCHID-73 dan budget 100.' if i==0 else 'Conversación '+str(i)
                if i==211:text='Corrección: el presupuesto ahora es 50, no 100.'
                usage._query(conn,"INSERT INTO kilas_ai_messages(thread_id,role,content,mode) VALUES (?,'user',?,'FAST')",(self.thread,text))
        context=str(store.context(self.owner,self.thread,selected_model='gpt-6.1-sol'))
        self.assertIn('ORCHID-73',context);self.assertIn('ahora es 50',context)
        self.assertLess(context.index('budget 100'),context.index('ahora es 50'))
        latest=store.messages(self.owner,self.thread);earlier=store.messages(self.owner,self.thread,before=latest[0]['id'])
        self.assertEqual(len(latest),100);self.assertEqual(len(earlier),100)
        self.assertLess(earlier[-1]['id'],latest[0]['id'])
        page=self.client().get(f'/kilas-ai/threads/{self.thread}').text
        self.assertIn('before='+str(latest[0]['id']),page)
        self.assertIsNone(store.messages(self.other,self.thread))
        self.assertEqual(thread_context_checkpoint.before(self.other,self.thread,2**62),'')
        state=db.query_one('SELECT * FROM kilas_thread_context_checkpoints WHERE user_id=? AND thread_id=?',(self.owner,self.thread))
        self.assertLessEqual(len(state['summary']),3000)

    def test_checkpoint_catchup_is_bounded_and_retains_data(self):
        with jobs.transaction() as conn:
            for i in range(1100):
                usage._query(conn,"INSERT INTO kilas_ai_messages(thread_id,role,content,mode) VALUES (?,'user',?,'FAST')",(self.thread,'Always keep EARLY_UNIQUE.' if i==0 else 'Small talk '+str(i)))
        first=thread_context_checkpoint.before(self.owner,self.thread,2**62)
        self.assertIn('not yet indexed',first);self.assertIn('EARLY_UNIQUE',first)
        second=thread_context_checkpoint.before(self.owner,self.thread,2**62)
        self.assertNotIn('not yet indexed',second)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_messages WHERE thread_id=?',(self.thread,))['n'],1100)

    def test_latest_original_quote_is_retained_without_language_keywords(self):
        for correction in ('Corrección: mi presupuesto es 50.', '更正：预算改为50。', 'تصحيح: الميزانية الآن 50.', '訂正：予算は50です。', 'Bajet saya kini 50 sahaja.'):
            rows=[{'role':'user','content':f'Always retain constraint {i}: budget is 100.'} for i in range(100)]
            rows.append({'role':'user','content':correction})
            result=conversation_context.summary(rows,3000)
            self.assertIn(correction,result);self.assertLessEqual(len(result),3000)
            self.assertLess(result.index('100'),result.index(correction))

    def test_expired_session_returns_login_recovery_without_provider(self):
        client=app.app.test_client()
        result=client.post(f'/kilas-ai/threads/{self.thread}/send',headers={'X-Chat-Request':'1'},json={})
        self.assertEqual(result.status_code,401);self.assertEqual(result.json['code'],'session_expired')
        self.assertEqual(result.json['login_url'],'/login')
        self.assertEqual(client.get(f'/kilas-ai/threads/{self.thread}').status_code,302)
        logged=self.client()
        self.assertEqual(logged.post(f'/kilas-ai/threads/{self.thread}/send',json={},headers={'X-CSRF-Token':'invalid'}).status_code,400)

    def test_four_locale_chat_keys_have_real_catalog_coverage(self):
        from ui_i18n import CATALOG,LANGUAGES
        expected={'id':'Periksa jawaban AI.','en':'Check AI answers.','es':'Revisa las respuestas de la IA.','zh':'请核对 AI 的回答。'}
        client=self.client()
        for locale in LANGUAGES:
            client.set_cookie('kilas_language',locale)
            html=client.get(f'/kilas-ai/threads/{self.thread}').text
            self.assertIn(expected[locale],html)
        root=Path(__file__).resolve().parents[1]
        keys=set()
        for name in ('kilas_ai.js','kilas_ai_agent_chat.js','kilas_chat_operation.js','kilas_chat_models.js'):
            keys.update(m[1] for m in re.findall(r"\bt\(\s*(['\"])(.*?)\1",(root/'static'/name).read_text()))
        # Dynamic provider labels are separately tested; these are authored literals.
        for key in keys:
            if not key:continue
            self.assertIn(key,CATALOG,key)
            for locale in LANGUAGES:self.assertTrue(CATALOG[key].get(locale),(key,locale))


class TransportTests(unittest.TestCase):
    def test_first_text_timeout_never_retries_or_frees_stuck_slot_early(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def source(control):
            calls.append(1);yield {'type':'provider','provider':'openai','model':'synthetic'}
            entered.set();release.wait(3)
            control.check();yield {'type':'delta','text':'late'}
        try:
            with patch.object(chat_transport,'_slots',threading.BoundedSemaphore(1)),patch.object(chat_transport,'FIRST_TEXT_SECONDS',.1):
                start=time.monotonic()
                with self.assertRaisesRegex(providers.ProviderError,'chat_timeout'):list(chat_transport.bounded(source))
                self.assertLess(time.monotonic()-start,.6);self.assertTrue(entered.is_set())
                with self.assertRaisesRegex(providers.ProviderError,'chat_capacity'):list(chat_transport.bounded(source))
                self.assertEqual(calls,[1])
                release.set();time.sleep(.05)
        finally:release.set()

    def test_total_deadline_applies_to_trickling_text(self):
        def source(control):
            while True:
                time.sleep(.02);yield {'type':'delta','text':'x'}
        with patch.object(chat_transport,'TOTAL_SECONDS',.15):
            start=time.monotonic()
            with self.assertRaisesRegex(providers.ProviderError,'chat_timeout'):list(chat_transport.bounded(source))
            self.assertLess(time.monotonic()-start,.7)

    def test_cancel_interrupts_silent_consumer_and_closes_source(self):
        release=threading.Event();closed=threading.Event();cancel=threading.Event()
        def source(control):
            try:
                yield {'type':'provider','provider':'openai','model':'synthetic'}
                release.wait(3);control.check()
            finally:closed.set()
        try:
            with chat_transport.cancellation(cancel.is_set):
                result=chat_transport.bounded(source);next(result);cancel.set()
                with self.assertRaisesRegex(providers.ProviderError,'chat_cancelled'):next(result)
            release.set();self.assertTrue(closed.wait(1))
        finally:release.set()
