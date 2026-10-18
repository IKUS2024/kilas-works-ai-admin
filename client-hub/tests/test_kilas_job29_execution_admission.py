"""Saved synthetic job 29 source; no generated Python, model or VM is executed."""
import base64
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_kilas_thread_projects as thread
import db
from kilas_ai import workspace_execution as execution,workspace_execution_credits as credits
from kilas_ai import workspace_execution_admission as admission,workspace_execution_worker as worker
from kilas_ai import workspace_artifact_transport as transport,workspace_files,workspace_model_tools as native
from kilas_ai import autonomous_store as jobs,store,usage,capacity,free_test

ARCHIVE=Path(__file__).with_name('fixtures')/'kilas-job29'/'source-project.zip'
SOURCES=workspace_files.read_archive(ARCHIVE.read_bytes())


class Job29AdmissionTests(unittest.TestCase):
    setUp=thread.ThreadProjects.setUp
    client=thread.ThreadProjects.client
    post=thread.ThreadProjects.post
    sandbox=thread.ThreadProjects.sandbox
    enabled=thread.ThreadProjects.enabled

    def provider(self):
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'model':'gpt-6-luna','status':'completed',
            'output':[{'type':'function_call','call_id':'publish','name':'publish_project','arguments':json.dumps({'files':[{'name':n,'content':v} for n,v in SOURCES.items()]})}],
            'usage':{'input_tokens':630,'output_tokens':2471}})

    def start(self,job):
        return self.client().post(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}/start',json={},headers={'X-CSRF-Token':'work-csrf'})

    def test_saved_archive_exact_hash_and_static_admission_no_host_execution(self):
        self.assertEqual(hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),'60a128b314eb730745f868dd547f0ef3272dd97f05d392698b59f62c900d2360')
        self.assertEqual(hashlib.sha256(SOURCES['main.py'].encode()).hexdigest(),'60abd233c918f30b280e21d5a60bca6949ff4186d17afac307ef9145adc8d024')
        with patch('subprocess.Popen',side_effect=AssertionError('host code execution forbidden')):
            entry=worker.entrypoint(SOURCES,thread.JOB28_PROMPT)
            prepared,target=transport.prepare(SOURCES,entry)
            execution.checked(prepared,target)
        self.assertEqual(entry,'main.py');self.assertEqual(prepared['main.py'],SOURCES['main.py'])

    def test_actual_customer_function_reproduces_job29_funding_shape_and_blocks_before_model(self):
        create=self.enabled(self.sandbox())
        db.execute('DELETE FROM kilas_ai_subscriptions WHERE user_id=?',(self.owner,))
        # Read-only production snapshot at dispatch: FREE, zero top-up lots,
        # $12.511476 counted premium history. A synthetic aggregate row preserves
        # that exact numerical exposure without copying unrelated usage records.
        db.execute("INSERT INTO kilas_ai_usage(user_id,operation_key,operation_type,mode,status,quota_source,estimated_cost_usd,created_at) VALUES (?,'historical-snapshot','AI_CALL','SMART','COMPLETE','BASE','12.511476',?)",(self.owner,jobs.stamp()))
        with patch.object(free_test,'active',return_value=True),patch.object(capacity,'allowance',return_value=Decimal(35000)/Decimal(17000)):
            conn=usage._connect()
            try:
                self.assertEqual(capacity.spent(conn,self.owner,usage._now().replace(day=1),usage._now()),Decimal('12.511476'))
                with self.assertRaisesRegex(usage.UsageLimit,'Kapasitas Premium belum cukup'):
                    credits.reserve(conn,self.owner,'execution:snapshot',8880)
            finally:conn.rollback();conn.close()
            self.post(thread.JOB28_PROMPT);job=jobs.list_jobs(self.owner)[0]
            with patch.object(native.requests,'post') as model:self.start(job)
            model.assert_not_called();create.assert_not_called()
        step=jobs.steps(job['id'])[0];output=json.loads(step['output_json'])
        self.assertEqual(output['reason'],'execution_quota_exhausted')
        self.assertEqual(output['execution_diagnostic'],{'phase':'customer_reservation','code':'execution_quota_exhausted'})
        self.assertEqual(step['error'],'execution_quota_exhausted')
        self.assertEqual(jobs.get(self.owner,job['id'])['last_error'],'execution_quota_exhausted')
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_workspace_executions')['n'],0)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE operation_type='CODE_EXECUTION'")['n'],0)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_usage')['n'],1)
        from ui_i18n import CATALOG
        answer=store.operation(self.owner,self.thread,json.loads(job['checkpoint_json'])['thread_operation_key']+':assistant')['content']
        self.assertIn(answer,CATALOG)
        for locale in ('id','en','es','zh'):
            client=self.client();client.set_cookie('kilas_language',locale)
            state=client.get(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}').json
            self.assertEqual(state['state'],'FAILED');self.assertFalse(state['files'])
            self.assertNotIn('percobaan dibatasi',state['text'])

    def test_funded_nonowner_saved_project_real_post_mock_sdk_download_once(self):
        previous=self.owner;self.owner=self.other;self.other=previous;self.thread=store.create_thread(self.owner)
        outputs=thread.frames({'report.html':thread.HTML,'sales.csv':thread.CSV})
        report={'exit_code':0,'stdout':'410000 226000 184000\n','stderr':'','timed_out':False,'outputs':{n:base64.b64encode(v.encode()).decode() for n,v in outputs.items()}}
        sandbox=self.sandbox(report);create=self.enabled(sandbox)
        with patch.object(native.requests,'post',return_value=self.provider()) as model,patch.object(execution,'checked',wraps=execution.checked) as check:
            self.post(thread.JOB28_PROMPT);job=jobs.list_jobs(self.owner)[0];self.start(job)
            self.assertEqual(jobs.get(self.owner,job['id'])['status'],'COMPLETED')
            self.assertEqual(check.call_args.args[0]['main.py'],SOURCES['main.py'])
            self.assertEqual(model.call_count,1);self.assertEqual(create.call_count,1)
            status=self.client().get(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}').json
            for item in status['files']:
                self.assertEqual(self.client(self.other).get(item['url']).status_code,404)
                if item['filename']=='report.html':self.assertEqual(self.client().get(item['url']).data,thread.HTML)
            self.start(job);self.assertEqual(create.call_count,1)
        sandbox.kill.assert_called_once()
        rows=db.query_all("SELECT status FROM kilas_ai_usage WHERE user_id=? AND operation_type='CODE_EXECUTION'",(self.owner,))
        self.assertEqual([r['status'] for r in rows],['COMPLETE'])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_workspace_executions')['n'],1)

    def test_successful_preflight_is_rolled_back_and_arbitrary_error_is_sanitized(self):
        self.enabled(self.sandbox())
        before=[dict(row) for row in db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=?',(self.owner,))]
        admission.preflight(self.owner,{'idempotency_key':'dry-run-test'})
        self.assertIsNone(db.query_one("SELECT id FROM kilas_ai_usage WHERE user_id=? AND operation_key='execution:dry-run-test'",(self.owner,)))
        self.assertEqual(before,[dict(row) for row in db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=?',(self.owner,))])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_topup_debits WHERE user_id=?',(self.owner,))['n'],0)
        value=admission.diagnostic({'id':1},{'id':2},'export_preparation',ValueError('PRIVATE_SOURCE_OR_KEY'))
        self.assertEqual(value,{'phase':'export_preparation','code':'execution_failed'})

    def test_topup_preflight_rolls_back_all_debit_writes_and_preserves_credit_balance(self):
        self.enabled(self.sandbox())
        from datetime import timedelta
        order=db.insert_returning_id("INSERT INTO kilas_ai_topup_orders(user_id,invoice_number,pack,amount_idr,status) VALUES (?,'synthetic-rollback','MINI',25000,'VERIFIED')",(self.owner,))
        db.execute('INSERT INTO kilas_ai_topup_credits(order_id,user_id,total_micro,expires_at) VALUES (?,?,10000,?)',(order,self.owner,jobs.stamp(usage._now()+timedelta(days=1))))
        before=dict(db.query_one('SELECT * FROM kilas_ai_topup_credits WHERE order_id=?',(order,)))
        with patch.object(capacity,'spent',return_value=Decimal('20')):
            admission.preflight(self.owner,{'idempotency_key':'dry-run-topup'})
        self.assertEqual(dict(db.query_one('SELECT * FROM kilas_ai_topup_credits WHERE order_id=?',(order,))),before)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_topup_debits WHERE user_id=?',(self.owner,))['n'],0)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE user_id=? AND operation_type='CODE_EXECUTION'",(self.owner,))['n'],0)

    def test_funding_race_after_authoring_preserves_durable_reason_and_source_only(self):
        create=self.enabled(self.sandbox());original=credits.reserve;calls=[]
        def reserve(*args,**kwargs):
            calls.append(True)
            if len(calls)>1:raise usage.UsageLimit(next(iter(admission.QUOTA_MESSAGES)))
            return original(*args,**kwargs)
        with patch.object(credits,'reserve',side_effect=reserve),patch.object(native.requests,'post',return_value=self.provider()):
            self.post(thread.JOB28_PROMPT);job=jobs.list_jobs(self.owner)[0];self.start(job)
        create.assert_not_called();step=jobs.steps(job['id'])[0];output=json.loads(step['output_json'])
        self.assertEqual(output['reason'],'execution_quota_exhausted');self.assertEqual(output['execution_diagnostic']['phase'],'execution_dispatch')
        self.assertEqual(step['error'],'execution_quota_exhausted')
        state=self.client().get(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}').json
        self.assertEqual(state['state'],'FAILED');self.assertEqual({f['filename'] for f in state['files']},{'source-project.zip','main.py'})
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_workspace_executions')['n'],0)

    def test_unexpected_preflight_failure_is_durable_sanitized_and_never_dispatches(self):
        create=self.enabled(self.sandbox())
        with patch.object(admission,'preflight',side_effect=RuntimeError('PRIVATE_NOT_RETAINED')),patch.object(native.requests,'post') as model:
            self.post(thread.JOB28_PROMPT);job=jobs.list_jobs(self.owner)[0];self.start(job)
        model.assert_not_called();create.assert_not_called()
        output=json.loads(jobs.steps(job['id'])[0]['output_json'])
        self.assertEqual(output['execution_diagnostic'],{'phase':'customer_reservation','code':'execution_preflight_failed'})
        self.assertNotIn('PRIVATE_NOT_RETAINED',str(output))


if __name__=='__main__':unittest.main()
