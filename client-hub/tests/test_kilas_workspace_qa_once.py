"""Offline one-job QA budget proof. Every provider/VM request is mocked."""
import base64
from contextlib import ExitStack
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING
import io
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import test_kilas_thread_projects as fixture
from kilas_ai import autonomous_store as jobs, usage, selected_author
from kilas_ai import workspace_qa_once as qa, workspace_model_tools as native
from kilas_ai import workspace_execution as execution


SOURCE = {'README.md': '# Budget calculator\nRun main.py once. Expected balance: 50000.\n',
          'main.py': 'from pathlib import Path\nassert 100000-35000-15000==50000\n'
                     'Path("output").mkdir(exist_ok=True)\nPath("output/hasil.txt").write_text("sisa=50000\\n")\nprint("TEST_OK")\n'}


def provider(name='list_files'):
    arguments = {'files': [{'name': n, 'content': value} for n, value in SOURCE.items()]} if name == 'publish_project' else {}
    return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
        'model': qa.MODEL, 'status': 'completed', 'output': [{'type': 'function_call', 'call_id': name,
        'name': name, 'arguments': json.dumps(arguments)}], 'usage': {'input_tokens': 20, 'output_tokens': 30}})


class OnceTests(unittest.TestCase):
    client = fixture.ThreadProjects.client
    sandbox = fixture.ThreadProjects.sandbox
    enabled = fixture.ThreadProjects.enabled

    def setUp(self):
        fixture.ThreadProjects.setUp(self)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(qa, 'OWNER_ID', self.owner))
        self.stack.enter_context(patch.object(qa, 'EXPIRES_AT', jobs.now() + timedelta(hours=1)))
        self.stack.enter_context(patch.dict(os.environ, {'RENDER_SERVICE_ID': qa.SERVICE_ID}))
        self.dispatch = self.stack.enter_context(patch.object(native.requests, 'post', side_effect=AssertionError('Real provider forbidden')))
        self.create = self.enabled(self.sandbox())
        # The prior attempt must be a proven zero-dispatch quota denial.
        with patch.object(qa, 'claim'), patch.object(qa, 'audit_rearm'):
            self.assertEqual(self.post('qa_prior_request_00000000').status_code, 200)
        prior = self.job()
        self.stack.enter_context(patch.object(qa, 'PREVIOUS_JOB_ID', prior['id']))
        diagnostic = {'execution': 'not_run', 'reason': 'execution_quota_exhausted',
                      'execution_diagnostic': {'code': 'execution_quota_exhausted', 'phase': 'customer_reservation'}}
        fixture.db.execute("UPDATE kilas_agent_jobs SET status='FAILED' WHERE id=?", (prior['id'],))
        fixture.db.execute("UPDATE kilas_agent_steps SET status='FAILED',idempotency_key=?,output_json=? WHERE job_id=?", (qa.OLD_KEY,json.dumps(diagnostic),prior['id']))


    def post(self, key='qa_budget_request_00000001', model='gpt-6-luna', prompt=None):
        return self.client().post(f'/kilas-ai/threads/{self.thread}/send', data={
            'content': qa.PROMPT if prompt is None else prompt, 'operation_key': key,
            'selected_model': model, 'csrf_token': 'work-csrf'})

    def start(self, job):
        return self.client().post(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}/start',
                                  json={}, headers={'X-CSRF-Token': 'work-csrf'})

    def job(self):
        return jobs.list_jobs(self.owner)[0]

    def test_bound_includes_context_cache_write_output_regional_and_single_vm(self):
        worst = qa.MAX_CALLS * (Decimal(qa.MAX_CONTEXT)*Decimal('.25') +
                               Decimal(qa.MAX_OUTPUT)*Decimal('.75')) * Decimal('1.10') + qa.SANDBOX_RESERVE
        self.assertEqual(worst, Decimal('915680.400'))
        self.assertEqual(int(worst.to_integral_value(rounding=ROUND_CEILING)), qa.TOTAL_BOUND_MICRO_USD)
        self.assertLess(qa.TOTAL_BOUND_MICRO_USD, 1000000)
        self.assertEqual(execution.MAX_SECONDS, 60)
        self.assertEqual(execution.RESERVE_MICRO_USD, qa.SANDBOX_RESERVE)

    def test_exact_scope_and_durable_duplicate_claim_precede_provider(self):
        self.assertEqual(qa.request_key(self.owner, qa.MODEL, qa.PROMPT, []), qa.KEY)
        self.assertIsNone(qa.request_key(self.other, qa.MODEL, qa.PROMPT, []))
        self.assertIsNone(qa.request_key(self.owner, qa.MODEL, 'Ordinary unrelated request', []))
        with self.assertRaises(ValueError):
            qa.request_key(self.owner, 'gpt-6.1-sol', qa.PROMPT, [])
        with self.assertRaises(ValueError):
            qa.request_key(self.owner, qa.MODEL, qa.PROMPT, [{}])
        self.assertEqual(self.post().status_code, 200)
        job = self.job()
        self.assertEqual((job['max_steps'], job['max_attempts']), (1, 1))
        self.assertEqual(jobs.steps(job['id'])[0]['idempotency_key'], qa.KEY)
        self.assertEqual(self.post().status_code, 200)  # Same browser operation reuses existing job.
        self.assertEqual(self.post('qa_budget_duplicate_0000002').status_code, 429)
        self.assertEqual(len(jobs.list_jobs(self.owner)), 2)
        self.dispatch.assert_not_called()

    def test_fourth_turn_stops_before_provider_and_quota_and_cannot_restart(self):
        self.assertEqual(self.post().status_code, 200)
        job = self.job()
        self.dispatch.side_effect = [provider(), provider(), provider()]
        with patch('e2b.Sandbox.create', side_effect=AssertionError('VM forbidden')) as vm:
            self.start(job)
            self.assertEqual(jobs.get(self.owner, job['id'])['status'], 'FAILED')
            self.assertEqual(self.dispatch.call_count, 3)
            for call in self.dispatch.call_args_list:
                self.assertEqual(call.kwargs['json']['service_tier'], 'default')
                self.assertLessEqual(call.kwargs['json']['max_output_tokens'], qa.MAX_OUTPUT)
            rows = fixture.db.query_all("SELECT operation_key FROM kilas_ai_usage WHERE user_id=? AND operation_type='CHAT'", (self.owner,))
            self.assertEqual(len(rows), 0)
            self.assertEqual(len(fixture.db.query_all("SELECT id FROM kilas_agent_events WHERE job_id=? AND kind='QA_MODEL_RESERVED'", (job['id'],))), 3)
            self.start(job)
            self.assertEqual(self.dispatch.call_count, 3)
            vm.assert_not_called()

    def test_third_turn_can_publish_source_run_once_and_retain_downloadable_zip(self):
        contents = fixture.frames({'hasil.txt': b'sisa=50000\n'})
        report = {'exit_code': 0, 'stdout': 'TEST_OK\n', 'stderr': '', 'timed_out': False,
                  'outputs': {name: base64.b64encode(value.encode()).decode() for name, value in contents.items()}}
        vm = self.sandbox(report)
        self.create.return_value = vm
        create = self.create
        self.dispatch.side_effect = [provider(), provider(), provider('publish_project')]
        self.assertEqual(self.post().status_code, 200)
        job = self.job()
        self.start(job)
        self.assertEqual(jobs.get(self.owner, job['id'])['status'], 'COMPLETED')
        self.assertEqual(self.dispatch.call_count, 3)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(create.call_args.kwargs['timeout'], 60)
        self.assertEqual(create.call_args.kwargs['retries'], 0)
        vm.kill.assert_called_once()
        files = self.client().get(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}').json['files']
        source = next(file for file in files if file['filename'] == 'source-project.zip')
        response = self.client().get(source['url'])
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.read('main.py').decode(), SOURCE['main.py'])
        self.assertEqual(self.client(self.other).get(source['url']).status_code, 404)
        self.assertIn('hasil.txt', [file['filename'] for file in files])
        self.start(job)
        self.assertEqual(create.call_count, 1)

    def test_prior_charged_unknown_or_artifact_attempt_cannot_rearm(self):
        prior = jobs.get(self.owner, qa.PREVIOUS_JOB_ID)
        fixture.db.execute("UPDATE kilas_agent_steps SET status='RUNNING' WHERE job_id=?", (prior['id'],))
        self.assertEqual(self.post().status_code, 429)
        self.dispatch.assert_not_called();self.create.assert_not_called()

    def test_server_funding_leaves_customer_ledger_and_old_failure_untouched(self):
        from kilas_ai import workspace_execution_credits as credits, capacity
        # Exhaust real customer allowance; ordinary execution still refuses it.
        fixture.db.execute("INSERT INTO kilas_ai_usage(user_id,operation_key,operation_type,mode,status,quota_source,estimated_cost_usd,created_at) VALUES (?,?,'CHAT','SMART','COMPLETE','BASE','100',?)", (self.owner,'synthetic_exhausted',jobs.stamp()))
        conn=usage._connect()
        try:
            with self.assertRaises(usage.UsageLimit):credits.reserve(conn,self.owner,'ordinary_execution',8880)
        finally:conn.rollback();conn.close()
        baseline=fixture.db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=?',(self.owner,))
        self.dispatch.side_effect=[provider('publish_project')]
        contents=fixture.frames({'hasil.txt':b'sisa=50000\n'})
        report={'exit_code':0,'stdout':'TEST_OK\n','stderr':'','timed_out':False,'outputs':{n:base64.b64encode(v.encode()).decode() for n,v in contents.items()}}
        self.create.return_value=self.sandbox(report)
        self.assertEqual(self.post().status_code,200);job=self.job();self.start(job)
        self.assertEqual(jobs.get(self.owner,job['id'])['status'],'COMPLETED')
        self.assertEqual(fixture.db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=?',(self.owner,)),baseline)
        self.assertEqual(jobs.get(self.owner,qa.PREVIOUS_JOB_ID)['status'],'FAILED')
        self.assertEqual(len(fixture.db.query_all("SELECT id FROM kilas_agent_events WHERE job_id=? AND kind='QA_REARMED'",(job['id'],))),1)
        run=fixture.db.query_one('SELECT outcome_json FROM kilas_workspace_executions WHERE job_id=?',(job['id'],))
        outcome=json.loads(run['outcome_json']);self.assertFalse(outcome['customer_metered']);self.assertEqual(outcome['funding'],'SERVER_QA')
        self.start(job);self.assertEqual(self.create.call_count,1)

    def test_prior_usage_and_execution_rows_block_rearm(self):
        fixture.db.execute("INSERT INTO kilas_ai_usage(user_id,operation_key,operation_type,mode,status,quota_source,estimated_cost_usd,created_at) VALUES (?,?,'CHAT','FAST','FAILED','BASE','0.001',?)", (self.owner,qa.OLD_KEY+'-tools-0',jobs.stamp()))
        self.assertEqual(self.post().status_code,429)
        self.dispatch.assert_not_called();self.create.assert_not_called()
        fixture.db.execute('DELETE FROM kilas_ai_usage WHERE user_id=? AND operation_key=?', (self.owner,qa.OLD_KEY+'-tools-0'))

    def test_vm_unknown_is_consumed_and_global_capacity_still_blocks(self):
        self.dispatch.side_effect=[provider('publish_project')]
        self.create.side_effect=RuntimeError('synthetic transport unknown')
        self.assertEqual(self.post().status_code,200);job=self.job();self.start(job)
        self.assertEqual(jobs.get(self.owner,job['id'])['status'],'FAILED')
        self.assertEqual(self.create.call_count,1)
        self.start(job);self.assertEqual(self.create.call_count,1);self.assertEqual(self.dispatch.call_count,1)
        self.assertEqual(self.post('qa_no_second_retry_000001').status_code,429)

    def test_global_vm_budget_and_owner_burst_remain_enforced(self):
        # The funded adapter still calls the original locked global reservation.
        fixture.db.execute("INSERT INTO kilas_workspace_executions(user_id,job_id,operation_key,state,reserved_micro_usd,created_at,expires_at) VALUES (?,?,?,'SUCCEEDED',5000000,?,?)", (self.owner,qa.PREVIOUS_JOB_ID,'synthetic_global_cap',jobs.stamp(),jobs.stamp()))
        self.dispatch.side_effect=[provider('publish_project')]
        self.assertEqual(self.post().status_code,200);job=self.job();self.start(job)
        self.assertEqual(jobs.get(self.owner,job['id'])['status'],'FAILED')
        self.create.assert_not_called();self.assertEqual(self.dispatch.call_count,1)
        with jobs.transaction() as conn, patch.dict(os.environ, {'KILAS_AI_BURST_PER_MINUTE':'1'}):
            with self.assertRaises(usage.UsageLimit):qa.resource_check(conn,self.owner)

    def test_qa_adapter_retains_original_guest_isolation_and_cleanup_body(self):
        import inspect
        from kilas_ai import workspace_qa_execution as adapter
        original=inspect.getsource(execution.execute)
        adapted=inspect.getsource(adapter.execute)
        # Only admission/funding differs; VM, network, guest, report validation,
        # cancellation, deadlines, cleanup and conservative settlement are exact.
        original=original[original.index('    if not active(job):'):]
        adapted=adapted[adapted.index('    if not active(job):'):]
        original=original.replace('customer=not _proof','customer=False').replace("outcome['customer_metered']=not _proof", "outcome['customer_metered']=False\n        outcome['funding']='SERVER_QA'\n        outcome['qa_rearm_of']=qa.PREVIOUS_JOB_ID")
        self.assertEqual(adapted,original)
        self.assertIs(adapter.reserve,execution.reserve)
        self.assertIs(adapter.RUNNER_COMMAND,execution.RUNNER_COMMAND)

    def test_expiry_runtime_drift_and_tampered_scope_fail_closed(self):
        for target, value in [('EXPIRES_AT', jobs.now()-timedelta(seconds=1))]:
            with patch.object(qa, target, value), self.assertRaises(ValueError):
                qa.request_key(self.owner, qa.MODEL, qa.PROMPT, [])
        with patch.object(execution, 'MAX_SECONDS', 61), self.assertRaises(ValueError):
            qa.request_key(self.owner, qa.MODEL, qa.PROMPT, [])
        self.assertEqual(self.post().status_code, 200)
        job = self.job(); step = jobs.steps(job['id'])[0]
        with qa.for_job(job, step):
            with self.assertRaises(ValueError):
                qa.before_send(qa.MODEL, {'model': qa.MODEL, 'max_output_tokens': qa.MAX_OUTPUT+1})
            with self.assertRaises(ValueError):
                qa.before_send('gpt-6.1-sol', {'model': 'gpt-6.1-sol', 'max_output_tokens': 1})
            with self.assertRaises(ValueError):
                qa.before_send(qa.MODEL, {'model': qa.MODEL, 'max_output_tokens': 1, 'tools': [{'type': 'web_search'}]})
            for _ in range(3):
                qa.before_send(qa.MODEL, {'model': qa.MODEL, 'max_output_tokens': 1, 'tools': []})
            with self.assertRaisesRegex(ValueError, 'qa_model_call_limit'):
                selected_author.Author(qa.MODEL, 'no fourth reservation', '')
        ordinary = {'model': 'gpt-6.1-sol', 'max_output_tokens': 24576, 'service_tier': 'priority'}
        qa.before_send('gpt-6.1-sol', ordinary)
        self.assertEqual(ordinary['service_tier'], 'priority')
        self.dispatch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
