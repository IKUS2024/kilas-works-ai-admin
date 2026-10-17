"""Remote execution contracts only. No model request or real sandbox is created."""
import base64
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import test_kilas_chat_models as fixture
import db
from kilas_ai import autonomous_store as jobs,autonomous_runner as runner,workspace_execution as execution
from kilas_ai import workspace_execution_worker as worker,workspace_files,work_artifacts,workspace_guest as guest
from kilas_ai.agent_workers import code_worker

SOURCE={'README.md':'# Synthetic\nPython standard library only.','main.py':'print(6 * 7)\n'}


class Stream(io.BytesIO):
    def __iter__(self):
        while True:
            part=self.read(8192)
            if not part:return
            yield part


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        db.execute('DELETE FROM kilas_workspace_executions')  # Isolated synthetic test database only.
        fixture.RouteTests.setUp(self)
    client=fixture.RouteTests.client
    submit=fixture.RouteTests.submit

    def claimed(self):
        ident=jobs.create(self.owner,'Run Python main.py',conversation_id=self.conversation)
        ident,token=jobs.claim_due(1)[0]
        db.execute("UPDATE kilas_agent_jobs SET status='RUNNING' WHERE id=?",(ident,))
        return jobs.get(self.owner,ident),{'idempotency_key':'synthetic-run-'+str(ident)}

    def sandbox(self,report=None):
        if report is None:report={'exit_code':0,'stdout':'42\n','stderr':'','timed_out':False,'outputs':{'answer.txt':base64.b64encode(b'42\n').decode()}}
        sandbox=Mock(sandbox_id='synthetic-private-vm')
        sandbox.get_info.return_value=SimpleNamespace(cpu_count=2,memory_mb=4096,allow_internet_access=False,
            network={'allow_public_traffic':False},lifecycle={'on_timeout':'kill','auto_resume':False})
        sandbox.commands.run.return_value=SimpleNamespace(stdout='ready')
        sandbox.files.read.side_effect=lambda *a,**kw:Stream(json.dumps(report).encode())
        return sandbox

    def enabled(self,sandbox):
        from contextlib import ExitStack
        stack=ExitStack();self.addCleanup(stack.close)
        from datetime import timedelta
        now=jobs.now()
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?)",(self.owner,jobs.stamp(now-timedelta(days=1)),jobs.stamp(now+timedelta(days=29))))
        stack.enter_context(patch.object(execution,'accepted',return_value=True))  # Synthetic acceptance only.
        stack.enter_context(patch.dict(os.environ,{'KILAS_EXECUTION_APPROVAL':execution.POLICY,'KILAS_EXECUTION_ALLOWED_USERS':str(self.owner),'E2B_API_KEY':'synthetic-secret','DATABASE_URL':'must-not-reach-vm'}))
        create=stack.enter_context(patch('e2b.Sandbox.create',return_value=sandbox))
        return create

    def test_disabled_before_dispatch_and_no_local_execution(self):
        job,step=self.claimed()
        with patch.dict(os.environ,{'KILAS_EXECUTION_APPROVAL':'','E2B_API_KEY':''}),patch('e2b.Sandbox.create') as create,patch('subprocess.Popen',side_effect=AssertionError('host process forbidden')):
            self.assertFalse(execution.capability()['available'])
            with self.assertRaisesRegex(ValueError,'not_configured'):execution.execute(job,step,SOURCE)
            result=worker.run(job,step,{'request':'Run Python main.py'})
            self.assertEqual(result.status,'WAITING_CAPABILITY');self.assertFalse(result.verified)
            self.assertIsNone(code_worker.test_command(Path('/tmp')));create.assert_not_called()
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_workspace_executions')['n'],0)

    def test_configured_key_does_not_grant_other_tenants_execution(self):
        job,step=self.claimed();sandbox=self.sandbox();create=self.enabled(sandbox)
        other={**job,'user_id':self.other}
        with self.assertRaisesRegex(ValueError,'not_configured'):execution.execute(other,step,SOURCE)
        create.assert_not_called();self.assertFalse(execution.capability(self.other)['available'])

    def test_general_execution_requires_durable_actual_proof_not_only_flags(self):
        job,step=self.claimed();create=self.enabled(self.sandbox())
        with patch.object(execution,'accepted',return_value=False):
            self.assertFalse(execution.capability(self.owner)['available'])
            with self.assertRaisesRegex(ValueError,'not_configured'):execution.execute(job,step,SOURCE)
        create.assert_not_called()

    def test_proof_is_off_and_cannot_accept_generated_source(self):
        from kilas_ai import workspace_execution_proof as proof
        job,step=self.claimed();create=self.enabled(self.sandbox())
        with patch.dict(os.environ,{'KILAS_EXECUTION_PROOF_APPROVAL':''}),patch.object(proof.threading,'Thread') as thread:
            proof.maybe_start(None);thread.assert_not_called()
            with self.assertRaisesRegex(ValueError,'proof_not_authorized'):execution.execute(job,step,SOURCE,_proof=True)
        with patch.dict(os.environ,{'KILAS_EXECUTION_PROOF_APPROVAL':execution.POLICY}):
            with self.assertRaisesRegex(ValueError,'proof_not_authorized'):execution.execute({**job,'user_id':9},{'idempotency_key':proof.key()},SOURCE,_proof=True)
        create.assert_not_called()

    def test_fixed_proof_mock_contract_is_durable_once_and_gates_general_execution(self):
        from kilas_ai import workspace_execution_proof as proof
        import app
        real_accepted=execution.accepted
        report={'exit_code':0,'stdout':'KILAS_PROOF_OK\n','stderr':'','timed_out':False,
                'outputs':{'proof.json':base64.b64encode(json.dumps({'answer':42,'checks':proof.CHECKS}).encode()).decode()}}
        create=self.enabled(self.sandbox(report))
        with patch.object(proof,'OWNER_ID',self.owner),patch.object(execution,'accepted',side_effect=real_accepted),patch.dict(os.environ,{'KILAS_EXECUTION_PROOF_APPROVAL':execution.POLICY}):
            self.assertFalse(execution.capability(self.owner)['available'])
            proof.run(app.app)
            self.assertTrue(execution.capability(self.owner)['available'])
            proof.run(app.app)
        self.assertEqual(create.call_count,1)
        row=db.query_one('SELECT outcome_json,cleanup_confirmed FROM kilas_workspace_executions')
        self.assertTrue(json.loads(row['outcome_json'])['proof_passed']);self.assertEqual(row['cleanup_confirmed'],1)

    def test_trusted_guest_early_failure_reports_bounded_safe_diagnostic(self):
        # Pure report handling only: no subprocess or generated code is run here.
        with patch.dict(os.environ,{'KILAS_REMOTE_GUEST':'e2b-ephemeral-v1'}),patch.object(guest.os,'getuid',return_value=0),patch.object(guest,'main',side_effect=RuntimeError('sandbox_disk_limit_unverified')),patch.object(guest.Path,'write_text') as write:
            guest.run()
        report=json.loads(write.call_args.args[0])
        self.assertEqual(report,{'exit_code':1,'stdout':'','stderr':'KILAS_GUEST_FAILURE:sandbox_disk_limit_unverified','timed_out':False,'outputs':{}})
        with patch.dict(os.environ,{'KILAS_REMOTE_GUEST':'e2b-ephemeral-v1'}),patch.object(guest.os,'getuid',return_value=0),patch.object(guest,'main',side_effect=RuntimeError('sensitive source or environment')),patch.object(guest.Path,'write_text') as write:
            guest.run()
        self.assertNotIn('sensitive',write.call_args.args[0])
        self.assertIn('guest_runner_error',write.call_args.args[0])

    def test_failed_fixed_proof_retains_diagnostics_and_cannot_dispatch_again(self):
        from kilas_ai import workspace_execution_proof as proof
        import app
        report={'exit_code':1,'stdout':'','stderr':'KILAS_GUEST_FAILURE:sandbox_disk_limit_unverified','timed_out':False,'outputs':{}}
        real_accepted=execution.accepted;create=self.enabled(self.sandbox(report))
        with patch.object(proof,'OWNER_ID',self.owner),patch.object(execution,'accepted',side_effect=real_accepted),patch.dict(os.environ,{'KILAS_EXECUTION_PROOF_APPROVAL':execution.POLICY}):
            proof.run(app.app);proof.run(app.app)
            self.assertFalse(execution.capability(self.owner)['available'])
        create.assert_called_once()
        row=db.query_one('SELECT outcome_json,cleanup_confirmed,state FROM kilas_workspace_executions')
        outcome=json.loads(row['outcome_json'])
        self.assertFalse(outcome['proof_passed']);self.assertEqual(outcome['guest_failure'],'sandbox_disk_limit_unverified')
        self.assertEqual(row['state'],'FAILED');self.assertEqual(row['cleanup_confirmed'],1)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_agent_artifacts WHERE name='execution-result.json'")['n'],1)

    def test_success_exact_remote_boundary_and_bounded_artifact_download(self):
        job,step=self.claimed();sandbox=self.sandbox();create=self.enabled(sandbox)
        with patch('subprocess.Popen',side_effect=AssertionError('host process forbidden')):
            outcome=execution.execute(job,step,SOURCE)
        self.assertEqual(outcome['stdout'],'42\n');self.assertFalse(outcome['tests_asserted'])
        kwargs=create.call_args.kwargs
        self.assertEqual(kwargs['envs'],{});self.assertFalse(kwargs['allow_internet_access'])
        self.assertFalse(kwargs['network']['allow_public_traffic']);self.assertEqual(kwargs['network']['deny_out'],['0.0.0.0/0'])
        self.assertEqual(kwargs['timeout'],60);self.assertEqual(kwargs['retries'],0)
        self.assertEqual(kwargs['lifecycle'],{'on_timeout':'kill','auto_resume':False})
        self.assertNotIn('must-not-reach-vm',str(sandbox.files.write.call_args_list))
        self.assertEqual(sandbox.files.read.call_args.kwargs['format'],'stream');sandbox.kill.assert_called_once()
        row=db.query_one('SELECT * FROM kilas_workspace_executions WHERE job_id=?',(job['id'],))
        self.assertEqual(row['state'],'SUCCEEDED');self.assertEqual(row['cleanup_confirmed'],1)
        self.assertEqual(row['reserved_micro_usd'],8880)
        result=worker.result(outcome)
        for artifact in result.artifacts:work_artifacts.validate(artifact['binary_file'])
        self.assertEqual(workspace_files.read_archive(result.artifacts[1]['binary_file']['content']),{'answer.txt':'42\n'})
        with self.assertRaisesRegex(ValueError,'already_dispatched'):execution.execute(job,step,SOURCE)
        self.assertEqual(create.call_count,1)

    def test_create_ambiguity_has_no_retry_or_new_reservation(self):
        job,step=self.claimed();create=self.enabled(self.sandbox());create.side_effect=TimeoutError('ambiguous')
        with self.assertRaisesRegex(ValueError,'remote_execution_error'):execution.execute(job,step,SOURCE)
        self.assertEqual(db.query_one('SELECT state FROM kilas_workspace_executions')['state'],'UNKNOWN')
        with self.assertRaisesRegex(ValueError,'already_dispatched'):execution.execute(job,step,SOURCE)
        self.assertEqual(create.call_count,1)

    def test_cancellation_after_create_destroys_vm_and_does_not_publish(self):
        job,step=self.claimed();sandbox=self.sandbox();create=self.enabled(sandbox)
        def created(**kwargs):jobs.control(self.owner,job['id'],'stop');return sandbox
        create.side_effect=created
        with self.assertRaisesRegex(ValueError,'execution_cancelled'):execution.execute(job,step,SOURCE)
        sandbox.kill.assert_called_once();sandbox.files.write.assert_not_called()
        self.assertEqual(db.query_one('SELECT state FROM kilas_workspace_executions')['state'],'CANCELLED')
        self.assertEqual(work_artifacts.listing(self.owner,job_id=job['id']),[])
        self.assertEqual(db.query_one("SELECT status FROM kilas_ai_usage WHERE user_id=? AND operation_type='CODE_EXECUTION'",(self.owner,))['status'],'FAILED')

    def test_runtime_boundary_rejects_network_or_resources_before_source_upload(self):
        job,step=self.claimed();sandbox=self.sandbox();self.enabled(sandbox)
        sandbox.get_info.return_value.allow_internet_access=True
        with self.assertRaisesRegex(ValueError,'boundary_unverified'):execution.execute(job,step,SOURCE)
        sandbox.files.write.assert_not_called();sandbox.kill.assert_called_once()

    def test_output_stream_is_closed_and_aborted_at_limit(self):
        sandbox=self.sandbox();stream=Stream(b'x'*(execution.MAX_REPORT+8192));sandbox.files.read.side_effect=None;sandbox.files.read.return_value=stream
        with self.assertRaisesRegex(ValueError,'output_limit'):execution.bounded_read(sandbox,'/root/kilas-done.json')
        self.assertTrue(stream.closed)

    def test_reject_malicious_source_before_create(self):
        job,step=self.claimed();create=self.enabled(self.sandbox())
        for files,entry in (({'../escape.py':'print(1)'},'../escape.py'),({'.env':'secret'},'.env'),(SOURCE,'main.py; curl bad'),(SOURCE,'unittest')):
            with self.subTest(entry=entry),self.assertRaises(ValueError):execution.execute(job,step,files,entry)
        create.assert_not_called()

    def test_untrusted_output_path_rejected_and_vm_destroyed(self):
        job,step=self.claimed();sandbox=self.sandbox({'exit_code':0,'stdout':'','stderr':'','timed_out':False,'outputs':{'../escape.txt':'eA=='}});self.enabled(sandbox)
        with self.assertRaises(ValueError):execution.execute(job,step,SOURCE)
        sandbox.kill.assert_called_once();self.assertEqual(work_artifacts.listing(self.owner),[])

    def test_budget_concurrency_and_daily_limits_are_durable(self):
        job,step=self.claimed();execution.reserve(job,'first')
        with self.assertRaisesRegex(ValueError,'capacity_limit'):execution.reserve(job,'second')
        db.execute("UPDATE kilas_workspace_executions SET state='SUCCEEDED'")
        for index in range(9):
            run=execution.reserve(job,'run'+str(index));execution.update(run,state='SUCCEEDED')
        with self.assertRaisesRegex(ValueError,'capacity_limit'):execution.reserve(job,'eleventh')
        db.execute('UPDATE kilas_workspace_executions SET reserved_micro_usd=1000000')
        with self.assertRaisesRegex(ValueError,'capacity_limit'):execution.reserve(job,'over-monthly')

    def test_cleanup_failure_keeps_explicit_ttl_and_cleanup_state(self):
        job,step=self.claimed();sandbox=self.sandbox();self.enabled(sandbox);sandbox.kill.side_effect=TimeoutError()
        execution.execute(job,step,SOURCE)
        row=db.query_one('SELECT state,cleanup_confirmed,expires_at FROM kilas_workspace_executions')
        self.assertEqual(row['state'],'CLEANUP_REQUIRED');self.assertEqual(row['cleanup_confirmed'],0);self.assertGreater(row['expires_at'],jobs.stamp())
        from decimal import Decimal
        self.assertEqual(Decimal(db.query_one("SELECT estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_type='CODE_EXECUTION'",(self.owner,))['estimated_cost_usd']),Decimal('.008880'))

    def test_guest_resource_contract_without_launching_source(self):
        calls=[]
        with patch.object(guest.os,'setgroups') as groups,patch.object(guest.os,'setgid') as gid,patch.object(guest.os,'setuid') as uid,patch.object(guest.ctypes,'CDLL',return_value=SimpleNamespace(prctl=lambda *args:0)),patch.object(guest.resource,'setrlimit',side_effect=lambda key,value:calls.append((key,value))):
            guest.child_limits()
        groups.assert_called_once_with([]);uid.assert_called_once_with(65534);gid.assert_called_once_with(65534)
        self.assertIn((guest.resource.RLIMIT_AS,(268435456,268435456)),calls)
        self.assertIn((guest.resource.RLIMIT_FSIZE,(65536,65536)),calls)
        self.assertIn((guest.resource.RLIMIT_NPROC,(16,16)),calls)

    def test_actual_job_routes_to_disabled_execution_without_model_or_host_call(self):
        with patch.dict(os.environ,{'KILAS_EXECUTION_APPROVAL':'','E2B_API_KEY':''}),patch('e2b.Sandbox.create') as create,patch('kilas_ai.providers.stream',side_effect=AssertionError('model forbidden')),patch('subprocess.Popen',side_effect=AssertionError('host forbidden')):
            self.assertEqual(self.submit(text='Run Python main.py in this project ZIP').status_code,303)
            job=jobs.list_jobs(self.owner)[0]
            runner.execute(*jobs.claim_due(1)[0]);runner.execute(*jobs.claim_due(1)[0])
            current=jobs.get(self.owner,job['id']);self.assertEqual(current['status'],'WAITING')
            self.assertEqual(current['last_error'],'isolated_execution_not_configured');create.assert_not_called()

    def test_artifact_source_is_owner_and_conversation_scoped(self):
        job,step=self.claimed()
        with self.assertRaisesRegex(ValueError,'source_not_owned'):worker.source(job,{'request':'Run Python artifact #999999'})
        self.assertEqual(worker.entrypoint(SOURCE,'Run main.py'),'main.py')
        self.assertEqual(worker.entrypoint({'tests/test_main.py':'pass'},'Run Python tests'),'unittest')

    def test_full_job_mocked_remote_execution_persists_real_owned_artifacts(self):
        ident=jobs.create(self.owner,'Run Python main.py',conversation_id=self.conversation)
        sandbox=self.sandbox();create=self.enabled(sandbox)
        runner.execute(*jobs.claim_due(1)[0])
        with patch.object(worker,'source',return_value=SOURCE):runner.execute(*jobs.claim_due(1)[0])
        self.assertEqual(jobs.get(self.owner,ident)['status'],'COMPLETED');self.assertEqual(create.call_count,1)
        artifacts=work_artifacts.listing(self.owner,job_id=ident);self.assertEqual(len(artifacts),2)
        result=next(a for a in artifacts if a['name']=='execution-result.json')
        url=f'/kilas-ai/agent/jobs/{ident}/artifacts/{result["id"]}?download=1'
        downloaded=self.client().get(url);self.assertEqual(downloaded.status_code,200)
        self.assertEqual(json.loads(downloaded.data)['stdout'],'42\n')
        self.assertEqual(self.client(self.other).get(url).status_code,404)

    def test_remote_timeout_kills_without_retry_or_output_download(self):
        job,step=self.claimed();sandbox=self.sandbox();create=self.enabled(sandbox)
        with patch.object(execution.time,'monotonic',side_effect=[0,100,101]):
            with self.assertRaisesRegex(ValueError,'execution_timeout'):execution.execute(job,step,SOURCE)
        create.assert_called_once();sandbox.kill.assert_called_once();sandbox.files.read.assert_not_called()

    def test_budget_reservation_survives_job_deletion(self):
        job,step=self.claimed();run=execution.reserve(job,'durable-budget')
        db.execute('DELETE FROM kilas_agent_jobs WHERE id=?',(job['id'],))
        saved=db.query_one('SELECT job_id,reserved_micro_usd FROM kilas_workspace_executions WHERE id=?',(run,))
        self.assertIsNone(saved['job_id']);self.assertEqual(saved['reserved_micro_usd'],execution.RESERVE_MICRO_USD)

    def test_untrusted_csv_formula_cannot_be_published(self):
        job,step=self.claimed();sandbox=self.sandbox({'exit_code':0,'stdout':'','stderr':'','timed_out':False,'outputs':{'data.csv':base64.b64encode(b'Name,Value\nattack,=WEBSERVICE("https://bad")').decode()}});self.enabled(sandbox)
        with self.assertRaisesRegex(ValueError,'unsafe_csv_output'):execution.execute(job,step,SOURCE)
        sandbox.kill.assert_called_once();self.assertEqual(work_artifacts.listing(self.owner),[])

    def test_zero_customer_capacity_blocks_before_sdk_and_reservation(self):
        from decimal import Decimal
        from kilas_ai import capacity,usage
        job,step=self.claimed();create=self.enabled(self.sandbox())
        with patch.object(capacity,'allowance',return_value=Decimal(0)):
            with self.assertRaises(usage.UsageLimit):execution.execute(job,step,SOURCE)
        create.assert_not_called()
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_workspace_executions')['n'],0)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE user_id=? AND operation_type='CODE_EXECUTION'",(self.owner,))['n'],0)

    def test_customer_success_settles_once_without_refunding_global_exposure(self):
        job,step=self.claimed();create=self.enabled(self.sandbox())
        execution.execute(job,step,SOURCE)
        row=dict(db.query_one("SELECT * FROM kilas_ai_usage WHERE user_id=? AND operation_type='CODE_EXECUTION'",(self.owner,)))
        self.assertEqual(row['status'],'COMPLETE');self.assertEqual(row['provider'],'e2b');self.assertIsNone(row['model'])
        from decimal import Decimal
        self.assertLessEqual(Decimal(row['estimated_cost_usd']),Decimal('.008880'))
        self.assertEqual(db.query_one('SELECT reserved_micro_usd FROM kilas_workspace_executions')['reserved_micro_usd'],8880)
        with self.assertRaisesRegex(ValueError,'already_dispatched'):execution.execute(job,step,SOURCE)
        self.assertEqual(dict(db.query_one('SELECT * FROM kilas_ai_usage WHERE id=?',(row['id'],))),row);self.assertEqual(create.call_count,1)

    def test_topup_maximum_reserved_before_create_and_charged_once(self):
        from decimal import Decimal
        from datetime import timedelta
        from kilas_ai import capacity,topups
        job,step=self.claimed();sandbox=self.sandbox();create=self.enabled(sandbox)
        order=topups.create_order(self.owner,'MINI')
        db.execute('INSERT INTO kilas_ai_topup_credits(order_id,user_id,total_micro,expires_at) VALUES (?,?,?,?)',(order,self.owner,1000000,jobs.stamp(jobs.now()+timedelta(days=1))))
        def created(**kwargs):
            row=db.query_one('SELECT reserved_micro,status FROM kilas_ai_topup_debits WHERE user_id=?',(self.owner,))
            self.assertEqual(row['reserved_micro'],8880);self.assertEqual(row['status'],'PENDING');return sandbox
        create.side_effect=created
        with patch.object(capacity,'allowance',return_value=Decimal(0)):execution.execute(job,step,SOURCE)
        row=dict(db.query_one('SELECT * FROM kilas_ai_topup_debits WHERE user_id=?',(self.owner,)))
        self.assertEqual(row['status'],'COMPLETE');self.assertGreater(row['charged_micro'],0);self.assertLessEqual(row['charged_micro'],8880)
        with self.assertRaisesRegex(ValueError,'already_dispatched'):execution.execute(job,step,SOURCE)
        self.assertEqual(dict(db.query_one('SELECT * FROM kilas_ai_topup_debits WHERE id=?',(row['id'],))),row)

    def test_ambiguous_failure_retains_full_customer_reservation(self):
        job,step=self.claimed();create=self.enabled(self.sandbox());create.side_effect=TimeoutError()
        with self.assertRaises(ValueError):execution.execute(job,step,SOURCE)
        row=db.query_one("SELECT status,estimated_cost_usd FROM kilas_ai_usage WHERE user_id=? AND operation_type='CODE_EXECUTION'",(self.owner,))
        from decimal import Decimal
        self.assertEqual(row['status'],'FAILED');self.assertEqual(Decimal(row['estimated_cost_usd']),Decimal('.008880'))

    def test_expired_pending_customer_exposure_cannot_vanish_after_ten_minutes(self):
        from datetime import timedelta
        from decimal import Decimal
        from kilas_ai import capacity,usage
        job,step=self.claimed();self.enabled(self.sandbox())
        run=execution.reserve(job,'crashed-customer',customer=True)
        old=jobs.now()-timedelta(hours=2)
        db.execute("UPDATE kilas_ai_usage SET created_at=? WHERE operation_key='crashed-customer'",(jobs.stamp(old),))
        db.execute('UPDATE kilas_workspace_executions SET expires_at=? WHERE id=?',(jobs.stamp(old),run))
        with jobs.transaction() as conn:self.assertEqual(capacity.spent(conn,self.owner,old-timedelta(days=1),jobs.now()),Decimal('.008880'))
        execution.reserve(job,'next-customer',customer=True)
        row=db.query_one("SELECT status,estimated_cost_usd FROM kilas_ai_usage WHERE operation_key='crashed-customer'")
        self.assertEqual(row['status'],'FAILED');self.assertEqual(Decimal(row['estimated_cost_usd']),Decimal('.008880'))

    def test_global_five_dollar_window_includes_previous_month_other_tenant(self):
        from datetime import timedelta
        job,step=self.claimed();seed=execution.reserve(job,'prior-period')
        execution.update(seed,state='SUCCEEDED')
        db.execute('UPDATE kilas_workspace_executions SET reserved_micro_usd=?,created_at=? WHERE id=?',(5000000-8880,jobs.stamp(jobs.now()-timedelta(days=32)),seed))
        ident=jobs.create(self.other,'Run Python main.py');claim=jobs.claim_due(1)[0]
        db.execute("UPDATE kilas_agent_jobs SET status='RUNNING' WHERE id=?",(ident,));other=jobs.get(self.other,ident)
        final=execution.reserve(other,'other-tenant-last');execution.update(final,state='SUCCEEDED')
        with self.assertRaisesRegex(ValueError,'capacity_limit'):execution.reserve(job,'over-five')
        self.assertEqual(db.query_one('SELECT SUM(reserved_micro_usd) AS n FROM kilas_workspace_executions')['n'],5000000)

    def test_concurrent_tenants_share_one_global_reservation(self):
        from concurrent.futures import ThreadPoolExecutor
        job,step=self.claimed();ident=jobs.create(self.other,'Run Python main.py');jobs.claim_due(1)
        db.execute("UPDATE kilas_agent_jobs SET status='RUNNING' WHERE id=?",(ident,));other=jobs.get(self.other,ident)
        def reserve(item):
            try:execution.reserve(item,'parallel-'+str(item['id']));return 'reserved'
            except ValueError as error:return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,[job,other]))
        self.assertEqual(results.count('reserved'),1);self.assertIn('execution_capacity_limit',results)

    def test_old_one_dollar_activation_token_is_rejected_and_proof_key_unchanged(self):
        from kilas_ai import workspace_execution_proof as proof
        job,step=self.claimed();create=self.enabled(self.sandbox())
        with patch.dict(os.environ,{'KILAS_EXECUTION_APPROVAL':'e2b-hobby-60s-1usd-v1','KILAS_EXECUTION_PROOF_APPROVAL':'e2b-hobby-60s-1usd-v1'}):
            self.assertFalse(execution.capability(self.owner)['available']);self.assertFalse(proof.authorized())
        self.assertEqual(proof.key(),'initial-proof-v1');create.assert_not_called()

    def test_project_author_and_execution_have_distinct_single_usage_entries(self):
        from kilas_ai import workspace_model_tools as native
        self.enabled(self.sandbox())
        self.submit(text='Create a Python project ZIP with README and main.py and run Python')
        job=jobs.list_jobs(self.owner)[0];runner.execute(*jobs.claim_due(1)[0])
        authored={'calls':[{'id':'publish','name':'publish_project','arguments':{'files':[{'name':n,'content':v} for n,v in SOURCE.items()]}}],
                  'usage':{'input_tokens':100,'output_tokens':100},'model_provenance':{'requested_model':'gpt-6.1-sol','returned_model':'gpt-6.1-sol','provider':'openai'}}
        with patch.object(native,'turn',return_value=authored):runner.execute(*jobs.claim_due(1)[0])
        self.assertEqual(jobs.get(self.owner,job['id'])['status'],'COMPLETED')
        rows=db.query_all('SELECT operation_type,operation_key,status FROM kilas_ai_usage WHERE user_id=?',(self.owner,))
        self.assertEqual(len(rows),2);self.assertEqual(sum(r['operation_type']=='CODE_EXECUTION' for r in rows),1)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_workspace_executions')['n'],1)


if __name__=='__main__':unittest.main()
