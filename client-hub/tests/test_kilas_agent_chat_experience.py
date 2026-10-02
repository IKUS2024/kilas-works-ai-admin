"""Focused chat lifecycle, inference, owner isolation and unchanged execution boundaries."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(CLIENT_HUB_DB_PATH=tempfile.mktemp(suffix='.sqlite'), SECRET_KEY='chat-experience-qa',
                  KILAS_AI_ENABLED='true', KILAS_AI_AUTOMATION_ENABLED='true', KILAS_AI_AUTONOMOUS_ENABLED='true')
os.environ.pop('DATABASE_URL', None)
import app
import db
import repo
from kilas_ai import agent_store as chats, agent_intents as intents, agent_presentation as display
from kilas_ai import autonomous_store as jobs, autonomous_planner, autonomous_runner, providers
from kilas_ai import google_connection, agent_workers, connectors


class ChatTests(unittest.TestCase):
    def setUp(self):
        db.execute("UPDATE kilas_agent_jobs SET status='STOPPED',next_wake_at=NULL WHERE status NOT IN ('COMPLETED','FAILED','STOPPED')")
        self.owner = repo.create_user(self._testMethodName+'@chat.example.test', 'hash')
        self.other = repo.create_user(self._testMethodName+'@other.example.test', 'hash')
        self.conv = chats.new_conversation(self.owner)
        self.client = app.app.test_client()
        with self.client.session_transaction() as state:
            state.update(user_id=self.owner, role='CLIENT_OWNER', _csrf_token='chat-qa', agent_conversation_id=self.conv)
        app.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)

    def send(self, text, **extra):
        return self.client.post('/kilas-ai/agent/chat', data={'csrf_token':'chat-qa', 'message':text,
                               'conversation_id':self.conv, **extra})

    def only_job(self):
        rows=jobs.list_jobs(self.owner)
        self.assertEqual(len(rows),1)
        return rows[0]

    def test_new_chat_separate_history(self):
        chats.append(self.owner,'user','Old meaningful conversation',self.conv)
        result=self.client.post('/kilas-ai/agent/conversations',data={'csrf_token':'chat-qa'})
        self.assertEqual(result.status_code,303)
        with self.client.session_transaction() as state: new=state['agent_conversation_id']
        self.assertNotEqual(new,self.conv)
        self.assertEqual(chats.messages(self.owner,conversation_id=new),[])
        self.assertIn('Old meaningful',chats.messages(self.owner,conversation_id=self.conv)[0]['content'])

    def test_new_chat_preserves_job_and_lease(self):
        job=jobs.create(self.owner,'Riset sampai selesai',conversation_id=self.conv)
        claim=jobs.claim_due(1)[0]
        self.client.post('/kilas-ai/agent/conversations',data={'csrf_token':'chat-qa'})
        current=jobs.get(self.owner,job)
        self.assertEqual(current['lease_token'],claim[1])
        self.assertEqual(current['origin_conversation_id'],self.conv)
        with jobs.transaction() as conn: self.assertTrue(jobs.locked(conn,job,claim[1]))
        jobs.release(*claim)

    def test_browser_session_not_required_for_runner(self):
        job=jobs.create(self.owner,'Riset sampai selesai',conversation_id=self.conv)
        with self.client.session_transaction() as state: state.clear()
        claim=next(c for c in jobs.claim_due(3) if c[0]==job)
        with jobs.transaction() as conn: self.assertTrue(jobs.locked(conn,job,claim[1]))
        jobs.release(*claim)

    def test_foreign_chat_denied(self):
        foreign=chats.new_conversation(self.other)
        self.assertEqual(self.client.get('/kilas-ai/agent?conversation='+str(foreign)).status_code,404)
        self.assertEqual(self.send('hi',conversation_id=foreign).status_code,404)
        self.assertEqual(chats.messages(self.owner,conversation_id=foreign),[])

    def test_foreign_task_origin_denied(self):
        with self.assertRaises(ValueError): jobs.create(self.owner,'Work',conversation_id=chats.new_conversation(self.other))

    def test_cheap_title_and_rename(self):
        chats.append(self.owner,'user','Riset kompetitor lokal',self.conv)
        self.assertEqual(chats.conversation(self.owner,self.conv)['title'],'Riset kompetitor lokal')
        self.client.post(f'/kilas-ai/agent/conversations/{self.conv}/rename',data={'csrf_token':'chat-qa','title':'Riset baru'})
        self.assertEqual(chats.conversation(self.owner,self.conv)['title'],'Riset baru')

    def test_sidebar_bounded(self):
        for _ in range(25): chats.new_conversation(self.owner)
        self.assertEqual(len(chats.recent_conversations(self.owner)),20)

    def test_messages_pagination(self):
        for n in range(65): chats.append(self.owner,'user',str(n),self.conv)
        recent=chats.messages(self.owner,conversation_id=self.conv)
        self.assertEqual(len(recent),60)
        self.assertEqual(len(chats.messages(self.owner,conversation_id=self.conv,before=recent[0]['id'])),5)

    def test_normal_qa_stream_no_task(self):
        events=[{'type':'provider','provider':'openai','model':'gpt-6-luna'}, {'type':'delta','text':'Bitcoin adalah aset digital.'}, {'type':'usage','input_tokens':10,'output_tokens':8}, {'type':'finish','reason':'stop'}]
        with patch.object(providers,'stream',return_value=iter(events)) as stream:
            response=self.client.post('/kilas-ai/agent/chat',data={'csrf_token':'chat-qa','message':'Apa itu Bitcoin?','conversation_id':self.conv},headers={'X-Agent-Chat':'1'})
            self.assertIn('Bitcoin adalah',response.get_data(as_text=True))
        self.assertEqual(jobs.list_jobs(self.owner),[])
        self.assertEqual(stream.call_args.args[0],'FAST')
        self.assertEqual(chats.messages(self.owner,conversation_id=self.conv)[-1]['content'],'Bitcoin adalah aset digital.')

    def test_qa_with_schedule_word_not_task(self):
        with patch.object(providers,'stream',return_value=iter([{'type':'delta','text':'Jawaban'}])):
            self.send('Jelaskan apa yang perlu saya lakukan besok')
        self.assertEqual(jobs.list_jobs(self.owner),[])

    def test_provider_failure_honest(self):
        with patch.object(providers,'stream',side_effect=providers.ProviderError('unavailable')):
            self.send('Apa itu Bitcoin?')
        self.assertIn('belum bisa menjawab',chats.messages(self.owner,conversation_id=self.conv)[-1]['content'])

    def test_single_work_origin_link(self):
        self.send('Kerjain riset kompetitor ini sampai selesai')
        job=self.only_job()
        self.assertEqual(job['mode'],'ONE_SHOT')
        self.assertEqual(job['origin_conversation_id'],self.conv)
        page=self.client.get('/kilas-ai/agent').get_data(as_text=True)
        self.assertIn(f'data-job-id="{job["id"]}"',page)
        self.assertNotIn('Pekerjaan #',page)
        self.assertIn('Buka percakapan',self.client.get(f'/kilas-ai/agent/jobs/{job["id"]}').get_data(as_text=True))

    def test_condition_watch(self):
        self.send('Pantau Bitcoin sampai turun di bawah 900 juta')
        self.assertEqual(self.only_job()['mode'],'CONDITION_WATCH')
        self.assertIn('Data market real-time belum tersedia',chats.messages(self.owner,conversation_id=self.conv)[-1]['content'])

    def test_continuous_watch(self):
        self.send('Pantau Bitcoin terus sampai saya stop')
        self.assertEqual(self.only_job()['mode'],'CONTINUOUS')

    def test_continuous_work(self):
        self.send('Terus kerjain riset sampai saya bilang stop')
        self.assertEqual(self.only_job()['mode'],'CONTINUOUS')

    def test_until_complete_not_endless_cycle(self):
        self.assertEqual(intents.infer('Kerjain ini terus sampai selesai')['mode'],'ONE_SHOT')

    def test_recurring_clock_survives_cycle(self):
        schedule={'timezone':'Asia/Jakarta','schedule':{'kind':'daily','hour':8,'minute':0}}
        job_id=jobs.create(self.owner,'Riset setiap hari jam 8',mode='RECURRING',schedule=schedule)
        job=jobs.get(self.owner,job_id)
        claim=jobs.claim_due(1)[0]
        plan=autonomous_planner.validate({'objective':'Write result','mode':'RECURRING','stop_condition':'One cycle','next_action':'Write',
              'steps':[{'worker':'FILE','action':'create','instruction':'Create result','input_json':'{"name":"result.txt","format":"txt","content":"Verified"}',
                        'completion_criteria':'Result available','requires_approval':False}]},'RECURRING')
        jobs.install_plan(job,claim[1],plan);jobs.release(*claim)
        autonomous_runner.execute(*jobs.claim_due(1)[0])
        current=jobs.get(self.owner,job_id)
        self.assertEqual(current['status'],'PLANNING')
        wake=datetime.fromisoformat(current['next_wake_at'])
        self.assertEqual(wake.hour,1)
        self.assertEqual(wake.minute,0)
        self.assertGreater(wake,jobs.now())

    def test_missing_threshold_clarify_no_job(self):
        self.send('Pantau Bitcoin setiap 5 menit sampai turun di bawah target saya')
        self.assertEqual(jobs.list_jobs(self.owner),[])
        self.assertIn('Berapa target',chats.messages(self.owner,conversation_id=self.conv)[-1]['content'])
        self.send('di bawah 900 juta rupiah')
        self.assertEqual(self.only_job()['interval_seconds'],300)

    def test_missing_clock_clarify_no_invention(self):
        self.send('Setiap pagi riset berita AI')
        self.assertEqual(jobs.list_jobs(self.owner),[])
        self.send('jam 8 pagi')
        self.assertEqual(self.only_job()['mode'],'RECURRING')

    def test_recurring_wib(self):
        self.send('Setiap hari jam 8 pagi riset berita AI')
        job=self.only_job()
        self.assertEqual(job['mode'],'RECURRING')
        self.assertEqual(json.loads(job['schedule_json'])['timezone'],'Asia/Jakarta')
        self.assertEqual(datetime.fromisoformat(job['next_wake_at']).hour,1)

    def test_scheduled_wib(self):
        spec=intents.infer('Besok jam 10 pagi kerjakan laporan',now=datetime(2026,10,2,0,tzinfo=timezone.utc))
        self.assertEqual(spec['mode'],'SCHEDULED')
        self.assertEqual(spec['wake_at'],datetime(2026,10,3,3,tzinfo=timezone.utc))

    def test_explicit_timezone(self):
        spec=intents.infer('Besok jam 10 pagi kerjakan laporan WITA',now=datetime(2026,10,2,0,tzinfo=timezone.utc))
        self.assertEqual(spec['wake_at'].hour,2)

    def test_human_wib_date(self):
        self.assertEqual(display.time_label('2026-10-02T03:00:00+00:00'),'2 Oktober 2026, 10.00 WIB')

    def test_human_durations(self):
        for n,text in [(60,'1 menit'),(300,'5 menit'),(900,'15 menit'),(3600,'1 jam')]:
            self.assertEqual(display.duration(n),'Setiap '+text)

    def test_ui_advanced_collapsed_no_utc(self):
        page=self.client.get('/kilas-ai/agent').get_data(as_text=True)
        self.assertNotIn('UTC',page)
        self.assertNotIn('detik',page)
        self.assertIn('<details class="autonomous-options">',page)
        self.assertNotIn('autonomous-options" open',page)

    def test_submit_key_prevents_duplicate_task(self):
        key='unique_operation_123456'
        self.assertEqual(self.send('Kerjain riset sampai selesai',operation_key=key).status_code,303)
        self.assertEqual(self.send('Kerjain riset sampai selesai',operation_key=key).status_code,409)
        self.only_job()

    def test_controls_pause_resume_stop(self):
        job=jobs.create(self.owner,'Riset sampai selesai',conversation_id=self.conv)
        for text,status in [('jeda dulu','PAUSED'),('lanjut','PLANNING'),('stop','STOPPED')]:
            self.send(text)
            self.assertEqual(jobs.get(self.owner,job)['status'],status)

    def test_feedback_does_not_stop_immediately(self):
        job=jobs.create(self.owner,'Perbaiki bug',conversation_id=self.conv)
        self.send('stop setelah test pass')
        current=jobs.get(self.owner,job)
        self.assertEqual(current['status'],'PLANNING')
        self.assertIn('stop setelah test pass',current['constraints_json'])

    def test_multiple_tasks_clarify(self):
        for _ in range(2): jobs.create(self.owner,'Riset sampai selesai',conversation_id=self.conv)
        self.send('pause')
        self.assertTrue(all(j['status']=='PLANNING' for j in jobs.list_jobs(self.owner)))
        self.assertIn('beberapa pekerjaan',chats.messages(self.owner,conversation_id=self.conv)[-1]['content'])

    def test_focused_control(self):
        first=jobs.create(self.owner,'First',conversation_id=self.conv)
        second=jobs.create(self.owner,'Second',conversation_id=self.conv)
        self.client.get(f'/kilas-ai/agent/jobs/{second}')
        self.send('jeda')
        self.assertEqual(jobs.get(self.owner,first)['status'],'PLANNING')
        self.assertEqual(jobs.get(self.owner,second)['status'],'PAUSED')

    def test_task_card_status_progress(self):
        self.send('Perbaiki bug ini sampai semua test pass')
        page=self.client.get('/kilas-ai/agent').get_data(as_text=True)
        self.assertIn('Menyiapkan rencana',page)
        self.assertIn('Langkah sedang disiapkan',page)

    def test_market_continuous_no_model_or_quotes(self):
        job=jobs.create(self.owner,'Pantau Bitcoin terus sampai saya stop',mode='CONTINUOUS')
        with patch('requests.post',side_effect=AssertionError('No fabricated market plan')):
            plan=autonomous_planner.propose(jobs.get(self.owner,job),[])
        self.assertEqual(plan['steps'][0]['worker'],'UNAVAILABLE')
        self.assertEqual(plan['steps'][0]['input']['capability'],'market_data_provider')

    def test_market_aliases_block_web_substitute(self):
        for name in ['Bitcoin','BTCUSDT','XAUUSD']:
            self.assertTrue(agent_workers.market_request(name))
            with self.assertRaises(ValueError): agent_workers.validate_step({'worker':'WATCH','action':'observe','input':{'query':name,'operator':'lt','threshold':9}})

    def test_google_minimal_scopes_unchanged(self):
        self.assertEqual(set(google_connection.IDENTITY_SCOPES + connectors.GOOGLE_SCOPES['gmail']),{'openid','https://www.googleapis.com/auth/userinfo.email','https://www.googleapis.com/auth/gmail.send'})

    def test_reminder_and_connector_not_captured(self):
        for text in ['Setiap hari jam 8 ingatkan saya minum air','Kirim email ke a@example.test','Cek kalender besok']:
            self.assertIsNone(intents.infer(text))

    def test_task_origin_does_not_show_in_new_chat(self):
        self.send('Riset kompetitor sampai selesai')
        job=self.only_job()
        response=self.client.post('/kilas-ai/agent/conversations',data={'csrf_token':'chat-qa'},follow_redirects=True)
        self.assertNotIn(f'data-job-id="{job["id"]}"',response.get_data(as_text=True))
        self.assertIn(f'data-job-id="{job["id"]}"',self.client.get('/kilas-ai/agent?view=tasks').get_data(as_text=True))

    def test_bad_advanced_frequency_safe(self):
        self.assertEqual(self.send('Work',autonomous_mode='ONE_SHOT',interval_seconds='bad').status_code,303)
        self.assertEqual(jobs.list_jobs(self.owner),[])

    def test_history_migration_backfill(self):
        conn=sqlite3.connect(':memory:')
        conn.executescript("CREATE TABLE users(id INTEGER PRIMARY KEY); INSERT INTO users VALUES(1),(2); CREATE TABLE kilas_ai_agent_messages(id INTEGER PRIMARY KEY,user_id INTEGER,role TEXT,content TEXT); INSERT INTO kilas_ai_agent_messages VALUES(1,1,'user','old'),(2,1,'assistant','answer'),(3,2,'user','other'); CREATE TABLE kilas_agent_jobs(id INTEGER PRIMARY KEY,user_id INTEGER);")
        conn.executescript((Path(__file__).resolve().parents[1]/'migrations/0079_kilas_agent_conversations_sqlite.sql').read_text())
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM kilas_ai_agent_messages').fetchone()[0],3)
        self.assertEqual(conn.execute('SELECT COUNT(DISTINCT conversation_id) FROM kilas_ai_agent_messages').fetchone()[0],2)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM kilas_ai_agent_messages WHERE conversation_id IS NULL').fetchone()[0],0)
        conn.close()


if __name__=='__main__': unittest.main()
