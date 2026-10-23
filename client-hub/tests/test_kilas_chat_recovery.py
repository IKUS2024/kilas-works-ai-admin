"""Six Chat recovery regressions. Synthetic owners, files and provider streams only."""
import base64
import io
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from PIL import Image
from flask import session
from werkzeug.exceptions import TooManyRequests
import test_kilas_chat_models as fixture
from kilas_ai import store, providers, agent_store, agent_chat, attachments, workspace_streams, pdf_vision
from kilas_ai import autonomous_store as jobs, agent_context_checkpoint as checkpoint, usage
import app, db


class RecoveryTests(unittest.TestCase):
    setUp=fixture.RouteTests.setUp
    client=fixture.RouteTests.client
    submit=fixture.RouteTests.submit

    def image(self):
        out=io.BytesIO();Image.new('RGB',(12,8),'green').save(out,'PNG');return out.getvalue()

    def capture(self,seen,incomplete=False):
        def answer(mode,messages,**kwargs):
            seen.append(messages)
            yield {'type':'provider','provider':'openai','model':'gpt-6.1-sol'}
            yield {'type':'delta','text':'Jawaban sintetis tersimpan.'}
            yield {'type':'usage','input_tokens':100,'output_tokens':10}
            if not incomplete:yield {'type':'finish','reason':'stop'}
        return answer

    def test_changed_payload_conflict_and_explicit_new_key_after_failure(self):
        key='recovery_failure_0000001'
        with patch.object(providers,'stream',side_effect=providers.ProviderError('synthetic_failure')) as provider:
            self.assertEqual(self.submit(text='Jelaskan konsep A.',key=key).status_code,200)
            self.assertEqual(self.submit(text='Jelaskan konsep A.',key=key).status_code,409)
            changed=self.submit(text='Jelaskan konsep B.',key=key)
            self.assertEqual(changed.status_code,409);self.assertEqual(changed.json['code'],'operation_payload_conflict')
            self.assertEqual(provider.call_count,1)
        with patch.object(providers,'stream',side_effect=self.capture([])) as provider:
            self.assertEqual(self.submit(text='Jelaskan konsep B.',key='recovery_new_key_0000001').status_code,200)
            self.assertEqual(provider.call_count,1)
        self.assertEqual([m['content'] for m in agent_store.messages(self.owner,conversation_id=self.conversation) if m['role']=='user'],['Jelaskan konsep A.','Jelaskan konsep B.'])

    def test_concurrent_claims_are_once_and_payload_bound(self):
        barrier=threading.Barrier(2)
        def claim(fingerprint):
            barrier.wait()
            try:return agent_store.claim_request(self.owner,self.conversation,'concurrent_claim_0000001',fingerprint)
            except agent_store.RequestConflict:return 'conflict'
        with ThreadPoolExecutor(2) as pool:
            futures=[pool.submit(claim,'a'*64) for _ in range(2)]
            self.assertCountEqual([f.result() for f in futures],[True,False])
        with self.assertRaises(agent_store.RequestConflict):agent_store.claim_request(self.owner,self.conversation,'concurrent_claim_0000001','b'*64)
        other=agent_store.new_conversation(self.owner)
        with self.assertRaises(agent_store.RequestConflict):agent_store.claim_request(self.owner,other,'concurrent_claim_0000001','a'*64)
        self.assertTrue(agent_store.claim_request(self.other,agent_store.new_conversation(self.other),'concurrent_claim_0000001','b'*64))

    def stream_row(self,owner,conversation,key,age=20):
        old=jobs.stamp(jobs.now()-timedelta(minutes=age))
        return db.query_one('INSERT INTO kilas_workspace_streams(user_id,conversation_id,operation_key,created_at,updated_at) VALUES (?,?,?,?,?) RETURNING id',
            (owner,conversation,key,old,old))['id']

    def test_orphan_owner_recovery_allows_new_chat_and_preserves_foreign_owner(self):
        stale=self.stream_row(self.owner,self.conversation,'recovery_orphan_00000001')
        foreign=self.stream_row(self.other,agent_store.new_conversation(self.other),'recovery_foreign_0000001')
        new=agent_store.new_conversation(self.owner)
        calls=[]
        def output():calls.append(1);yield {'type':'delta','text':'New synthetic answer'}
        class Inline:
            def __init__(self,target,args,**kwargs):self.target,self.args=target,args
            def start(self):self.target(*self.args)
        with app.app.test_request_context('/kilas-ai/agent/chat'):
            session['user_id']=self.owner
            with patch.object(workspace_streams.threading,'Thread',Inline):
                result=workspace_streams.start(self.owner,new,'recovery_new_stream_0001',output());result.close()
        self.assertEqual(calls,[1])
        self.assertEqual(db.query_one('SELECT state FROM kilas_workspace_streams WHERE id=?',(stale,))['state'],'INTERRUPTED')
        self.assertEqual(db.query_one('SELECT state FROM kilas_workspace_streams WHERE id=?',(foreign,))['state'],'RUNNING')

    def test_heartbeat_keeps_silent_active_stream_and_admission_is_serialized(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def output():
            calls.append(1);entered.set();yield {'type':'activity','label':'Synthetic'}
            release.wait(5);yield {'type':'delta','text':'Finished'}
        barrier=threading.Barrier(2)
        def start(index):
            with app.app.test_request_context('/kilas-ai/agent/chat'):
                session['user_id']=self.owner;barrier.wait()
                try:
                    response=workspace_streams.start(self.owner,self.conversation,'concurrent_stream_'+str(index).zfill(8),output());response.close();return 200
                except TooManyRequests:return 429
        try:
            with patch.object(workspace_streams,'HEARTBEAT_SECONDS',.01),ThreadPoolExecutor(2) as pool:
                futures=[pool.submit(start,i) for i in range(2)]
                self.assertCountEqual([f.result() for f in futures],[200,429]);self.assertTrue(entered.wait(2))
                ident=db.query_one("SELECT id FROM kilas_workspace_streams WHERE user_id=? AND state='RUNNING'",(self.owner,))['id']
                tick=threading.Event();original=db.execute
                def watch(sql,params=()):
                    result=original(sql,params)
                    if 'UPDATE kilas_workspace_streams SET updated_at=' in sql:tick.set()
                    return result
                with patch.object(db,'execute',side_effect=watch):self.assertTrue(tick.wait(2))
                workspace_streams.recover(self.owner,self.conversation)
                self.assertEqual(db.query_one('SELECT state FROM kilas_workspace_streams WHERE id=?',(ident,))['state'],'RUNNING')
                self.assertEqual(calls,[1])
        finally:release.set()

    def test_scan_pages_survive_first_send_and_stored_regeneration(self):
        raw=b'%PDF synthetic owned scan';page={'mime_type':'image/png','content':self.image()}
        scan={'filename':'scan.pdf','mime_type':'application/pdf','byte_size':len(raw),'content':raw,
              'extracted_text':'PDF scan: hanya 1 halaman pertama disertakan sebagai gambar.', 'vision_pages':[page]}
        seen=[]
        with patch.object(attachments,'prepare_many',return_value=[scan]),patch.object(providers,'stream',side_effect=self.capture(seen)),patch.object(pdf_vision,'render',side_effect=AssertionError('Prepared pages already available')):
            result=self.client().post(f'/kilas-ai/threads/{self.thread}/send',data={'csrf_token':'work-csrf','content':'Baca lampiran ini.',
                'operation_key':'recovery_scan_0000000001','selected_model':'gpt-6.1-sol','attachments':(io.BytesIO(raw),'scan.pdf','application/pdf')})
            self.assertIn('event: done',result.text)
        image=seen[0][-1]['content'][1]['image_url']['url'];self.assertEqual(base64.b64decode(image.split(',',1)[1]),page['content'])
        with patch.object(pdf_vision,'render',return_value=[page]) as render,patch.object(providers,'stream',side_effect=self.capture(seen)),patch('kilas_ai.capabilities.current',return_value={'uploaded_image_understanding':True}):
            result=self.client().post(f'/kilas-ai/threads/{self.thread}/regenerate',json={'operation_key':'recovery_regen_000000001','selected_model':'gpt-6.1-sol'},headers={'X-CSRF-Token':'work-csrf'})
            self.assertIn('event: done',result.text);self.assertTrue(render.called)
            self.assertTrue(all(call.args==(raw,) for call in render.call_args_list))
        self.assertEqual(base64.b64decode(seen[-1][-1]['content'][1]['image_url']['url'].split(',',1)[1]),page['content'])
        self.assertIsNone(store.context(self.other,self.thread))

    def test_pdf_reconstruction_bounds_and_honest_render_failure(self):
        item={'filename':'scan.pdf','mime_type':'application/pdf','content':b'x'*(attachments.MAX_FILE_BYTES+1),'extracted_text':'PDF scan: source'}
        with patch.object(pdf_vision,'render',side_effect=AssertionError('Oversized input must not render')) as render,patch('kilas_ai.capabilities.current',return_value={'uploaded_image_understanding':True}):
            result=attachments.restore_visuals([item]);render.assert_not_called()
        self.assertNotIn('vision_pages',result[0]);self.assertIn('Jangan menebak',result[0]['extracted_text'])

    def test_visual_followup_reuses_owned_image_but_unrelated_question_does_not(self):
        raw=self.image();ident,_=store.append_user_once(self.owner,self.thread,'Apa isi gambar ini?','FAST','recovery_image_00000001')
        store.save_attachments(self.owner,self.thread,ident,[{'filename':'photo.png','mime_type':'image/png','byte_size':len(raw),'content':raw,'extracted_text':None}])
        store.append_assistant(self.owner,self.thread,'Ada objek berwarna.','FAST',None,None,'recovery_image_00000001',{'status':'complete'})
        seen=[]
        with patch.object(providers,'stream',side_effect=self.capture(seen)):
            self.assertIn('event: done',self.submit(text='Apa tulisan di sudut kanan gambar itu?',agent=False).text)
            self.assertIn('event: done',self.submit(text='Jelaskan definisi API.',agent=False).text)
        self.assertEqual(base64.b64decode(seen[0][-1]['content'][1]['image_url']['url'].split(',',1)[1]),raw)
        self.assertIsInstance(seen[1][-1]['content'],str)
        self.assertEqual(store.latest_visual_attachments(self.other,self.thread,999999),[])

    def test_early_constraint_and_late_correction_survive_over_100_turns(self):
        agent_store.append(self.owner,'user','Ingat wajib nama kode KETENTUAN_AWAL_UNIK. Budget 200 juta.',self.conversation)
        for i in range(110):agent_store.append(self.owner,'user',f'Percakapan biasa {i}.',self.conversation)
        agent_store.append(self.owner,'user','Koreksi budget menjadi 150 juta.',self.conversation)
        for i in range(40):agent_store.append(self.owner,'assistant',f'Jawaban biasa {i}.',self.conversation)
        with app.app.test_request_context('/kilas-ai/agent/chat'):
            context=agent_chat.context(self.owner,self.conversation)
        joined=str(context);self.assertIn('KETENTUAN_AWAL_UNIK',joined);self.assertLess(joined.index('200 juta'),joined.index('150 juta'))
        state=db.query_one('SELECT * FROM kilas_chat_context_checkpoints WHERE user_id=? AND conversation_id=?',(self.owner,self.conversation))
        self.assertLessEqual(len(state['summary']),checkpoint.SUMMARY_LIMIT)
        self.assertEqual(checkpoint.before(self.other,self.conversation,999999),'')

    def test_historical_backfill_is_bounded_and_resumes_without_invented_text(self):
        with jobs.transaction() as conn:
            for i in range(checkpoint.BATCH_SIZE*checkpoint.MAX_BATCHES+40):
                usage._query(conn,"INSERT INTO kilas_ai_agent_messages(user_id,conversation_id,role,content) VALUES (?,?,'user',?)",(self.owner,self.conversation,'Ingat awal unik.' if i==0 else f'Obrolan {i}'))
        first=checkpoint.before(self.owner,self.conversation,999999)
        self.assertIn('Ingat awal unik.',first);self.assertIn('not yet indexed',first)
        second=checkpoint.before(self.owner,self.conversation,999999)
        self.assertIn('Ingat awal unik.',second);self.assertNotIn('not yet indexed',second)

    def test_instructions_in_middle_of_long_early_turn_and_later_correction(self):
        middle='Gunakan bahasa Indonesia untuk semua jawaban dan jangan menyarankan pinjaman.'
        original='Contoh latar biasa. '*90+middle+' '+'Catatan tambahan biasa. '*90
        agent_store.append(self.owner,'user',original,self.conversation)
        for i in range(120):agent_store.append(self.owner,'user',f'Obrolan umum {i}.',self.conversation)
        correction='Koreksi: pinjaman boleh dibahas, tetapi wajib tanpa agunan.'
        agent_store.append(self.owner,'user',correction,self.conversation)
        for i in range(40):agent_store.append(self.owner,'assistant',f'Tanggapan {i}.',self.conversation)
        with app.app.test_request_context('/kilas-ai/agent/chat'):context=agent_chat.context(self.owner,self.conversation)
        text=str(context)
        self.assertIn(middle,text);self.assertIn(correction,text);self.assertLess(text.index(middle),text.index(correction))
        self.assertIn('not full conversation recall',text)

    def test_interrupted_send_and_regenerate_replay_incomplete_without_dispatch(self):
        for endpoint in ('send','regenerate'):
            key='recovery_partial_'+endpoint+'0000001'
            with patch.object(providers,'stream',side_effect=self.capture([],True)):
                if endpoint=='send':initial=self.submit(text='Jelaskan konsep sederhana ini.',agent=False,key=key)
                else:initial=self.client().post(f'/kilas-ai/threads/{self.thread}/regenerate',json={'operation_key':key,'selected_model':'gpt-6.1-sol'},headers={'X-CSRF-Token':'work-csrf'})
                self.assertIn('event: error',initial.text)
            with patch.object(providers,'stream',side_effect=AssertionError('Replay must not dispatch')):
                if endpoint=='send':replay=self.submit(text='Jelaskan konsep sederhana ini.',agent=False,key=key)
                else:replay=self.client().post(f'/kilas-ai/threads/{self.thread}/regenerate',json={'operation_key':key,'selected_model':'gpt-6.1-sol'},headers={'X-CSRF-Token':'work-csrf'})
                self.assertIn('event: incomplete',replay.text);self.assertNotIn('event: done',replay.text)
        html=self.client().get(f'/kilas-ai/threads/{self.thread}').text;self.assertIn('ai-result-status',html)


if __name__=='__main__':unittest.main()
