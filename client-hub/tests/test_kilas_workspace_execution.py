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
        with patch.object(execution.time,'monotonic',side_effect=[0,100]):
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


if __name__=='__main__':unittest.main()
