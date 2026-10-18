"""Package admission and exact proof compatibility; mock SDK only, no VM/model."""
import hashlib
import json
import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch
import test_kilas_workspace_execution as f
import db
from kilas_ai import workspace_execution as execution,workspace_execution_access as access
from kilas_ai import workspace_execution_rollout as rollout,workspace_execution_proof as proof
from kilas_ai import autonomous_store as jobs,usage,capacity,free_test


class EntitledExecutionTests(unittest.TestCase):
    setUp=f.ExecutionTests.setUp
    claimed=f.ExecutionTests.claimed
    sandbox=f.ExecutionTests.sandbox
    enabled=f.ExecutionTests.enabled
    def policy(self):
        digest=hashlib.sha256(Path(rollout.__file__).read_bytes()).hexdigest()
        return patch.dict(os.environ,{'KILAS_EXECUTION_AUDIENCE':'entitled','KILAS_EXECUTION_APPROVAL':execution.POLICY,
            'KILAS_EXECUTION_PROOF_APPROVAL':'','KILAS_EXECUTION_COMPATIBILITY_SHA256':digest,'E2B_API_KEY':'synthetic-only',
            'KILAS_APP_FREE_TEST_ENABLED':'false'})
    def paid(self,user):
        now=usage._now()
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PLUS','ACTIVE',?,?)",(user,jobs.stamp(now-timedelta(days=1)),jobs.stamp(now+timedelta(days=2))))
    def other_job(self):
        ident=jobs.create(self.other,'Run Python main.py');jobs.claim_due(1)
        db.execute("UPDATE kilas_agent_jobs SET status='RUNNING' WHERE id=?",(ident,))
        return jobs.get(self.other,ident),{'idempotency_key':'entitled-'+str(ident)}
    def actual_proof_row(self):
        job,step=self.claimed()
        run=execution.reserve(job,'execution:'+proof.key(),customer=False)
        outcome={'proof_passed':True,'proof_fingerprint':rollout.ORIGINAL_PROOF_FINGERPRINT}
        execution.update(run,state='SUCCEEDED',cleanup_confirmed=1,outcome_json=json.dumps(outcome))
        db.execute("UPDATE kilas_agent_jobs SET status='COMPLETED' WHERE id=?",(job['id'],))
        return run

    def test_nonowner_paid_not_allowlisted_executes_and_settles_once(self):
        self.paid(self.other);job,step=self.other_job();create=self.enabled(self.sandbox())
        with self.policy():
            self.assertNotEqual(str(self.other),os.environ['KILAS_EXECUTION_ALLOWED_USERS'])
            self.assertTrue(execution.capability(self.other)['available'])
            outcome=execution.execute(job,step,f.SOURCE)
            self.assertTrue(outcome['customer_metered'])
            with self.assertRaisesRegex(ValueError,'already_dispatched'):execution.execute(job,step,f.SOURCE)
        create.assert_called_once()
        rows=db.query_all("SELECT user_id,status FROM kilas_ai_usage WHERE operation_type='CODE_EXECUTION' AND user_id=?",(self.other,))
        self.assertEqual([(r['user_id'],r['status']) for r in rows],[(self.other,'COMPLETE')])
        self.assertEqual(db.query_one('SELECT reserved_micro_usd FROM kilas_workspace_executions')['reserved_micro_usd'],8880)

    def test_existing_sponsored_trial_uses_finite_capacity_not_owner_allowlist(self):
        job,step=self.other_job();create=self.enabled(self.sandbox())
        with self.policy(),patch.dict(os.environ,{'KILAS_APP_FREE_TEST_ENABLED':'true','KILAS_APP_FREE_TEST_END_AT':free_test.END_AT.isoformat()}):
            self.assertEqual(usage.effective_plan(self.other)['plan'],'FREE')
            self.assertTrue(access.entitled(self.other));self.assertTrue(execution.capability(self.other)['available'])
            execution.execute(job,step,f.SOURCE)
        create.assert_called_once()
        row=db.query_one("SELECT quota_source,status FROM kilas_ai_usage WHERE user_id=? AND operation_type='CODE_EXECUTION'",(self.other,))
        self.assertEqual((row['quota_source'],row['status']),('BASE','COMPLETE'))

    def test_sponsored_trial_exhaustion_denies_before_sdk_or_global_reserve(self):
        job,step=self.other_job();create=self.enabled(self.sandbox())
        with self.policy(),patch.dict(os.environ,{'KILAS_APP_FREE_TEST_ENABLED':'true','KILAS_APP_FREE_TEST_END_AT':free_test.END_AT.isoformat()}),patch.object(capacity,'allowance',return_value=Decimal(0)):
            with self.assertRaises(usage.UsageLimit):execution.execute(job,step,f.SOURCE)
        create.assert_not_called();self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_workspace_executions')['n'],0)

    def test_unentitled_invalid_unknown_audience_and_expired_trial_deny(self):
        job,step=self.other_job();create=self.enabled(self.sandbox())
        with self.policy():
            for user in (None,True,'9',-1,self.other,99999999):self.assertFalse(access.entitled(user))
            self.assertFalse(execution.capability(self.other)['available'])
            with self.assertRaisesRegex(ValueError,'not_configured'):execution.execute(job,step,f.SOURCE)
            with patch.dict(os.environ,{'KILAS_EXECUTION_AUDIENCE':'*'}):self.assertFalse(execution.capability(self.owner)['available'])
            with patch.dict(os.environ,{'KILAS_APP_FREE_TEST_ENABLED':'true','KILAS_APP_FREE_TEST_END_AT':'2020-01-01T00:00:00+00:00'}):self.assertFalse(access.entitled(self.other))
        create.assert_not_called()

    def test_exact_compatibility_accepts_completed_original_without_rewriting_record(self):
        run=self.actual_proof_row();before=dict(db.query_one('SELECT * FROM kilas_workspace_executions WHERE id=?',(run,)))
        with self.policy(),patch('e2b.Sandbox.create') as create:
            self.assertTrue(execution.accepted());self.assertFalse(proof.authorized())
            self.assertNotEqual(proof.fingerprint(),rollout.ORIGINAL_PROOF_FINGERPRINT)
        self.assertEqual(dict(db.query_one('SELECT * FROM kilas_workspace_executions WHERE id=?',(run,))),before);create.assert_not_called()

    def test_missing_wrong_pin_noncomplete_failed_or_uncleaned_never_accepted(self):
        run=self.actual_proof_row()
        with self.policy():
            for digest in ('','0'*64):
                with patch.dict(os.environ,{'KILAS_EXECUTION_COMPATIBILITY_SHA256':digest}):self.assertFalse(execution.accepted())
            for sql,args in [("UPDATE kilas_agent_jobs SET status='FAILED' WHERE id=(SELECT job_id FROM kilas_workspace_executions WHERE id=?)",(run,)),("UPDATE kilas_workspace_executions SET cleanup_confirmed=0 WHERE id=?",(run,))]:
                db.execute(sql,args);self.assertFalse(execution.accepted())

    def test_any_reviewed_runtime_function_or_fixture_edit_rejects(self):
        self.actual_proof_row();original=Path.read_bytes
        mutations=[('workspace_execution.py',b'def accepted():',b'def accepted():\n    # changed acceptance gate'),
                   ('workspace_execution.py',b'def capability(user_id=None):',b'def capability(user_id=None):\n    # changed audience gate'),
                   ('workspace_execution.py',b'allow_internet_access=False',b'allow_internet_access=True'),
                   ('workspace_execution.py',b'MAX_SECONDS=60',b'MAX_SECONDS=61'),
                   ('workspace_execution.py',b'cleaned=True',b'cleaned=False'),
                   ('workspace_execution.py',b'def reserve(',b'def reserve_changed('),
                   ('workspace_guest.py',b'67108864',b'67108865'),
                   ('workspace_acceptance_fixture.py',b'BYTES=67108864',b'BYTES=67108865'),
                   ('workspace_execution_access.py',b"audience=='entitled'",b"audience=='all'"),
                   ('workspace_execution_credits.py',b'capacity.allowance()',b'capacity.allowance()+1')]
        for name,old,new in mutations:
            raw=original(Path(execution.__file__).parent/name);self.assertIn(old,raw)
            def read(path,name=name,old=old,new=new):
                data=original(path);return data.replace(old,new,1) if path.name==name else data
            with self.subTest(file=name,change=old),self.policy(),patch.object(Path,'read_bytes',read):self.assertFalse(execution.accepted())

    def test_compatibility_source_and_each_constant_mutation_rejects(self):
        self.actual_proof_row();original=Path.read_bytes
        with self.policy():
            with patch.object(Path,'read_bytes',lambda path:original(path)+b'\n# changed verifier' if path.name=='workspace_execution_rollout.py' else original(path)):self.assertFalse(execution.accepted())
            for name,value in [('ORIGINAL_PROOF_FINGERPRINT','0'*64),('BOUNDARY_SOURCE_SHA256','0'*64),('REVIEWED_FILES',{**rollout.REVIEWED_FILES,'workspace_execution.py':'0'*64})]:
                with self.subTest(constant=name),patch.object(rollout,name,value):self.assertFalse(execution.accepted())

    def test_expired_paid_package_without_sponsorship_is_not_entitled(self):
        self.paid(self.other)
        db.execute("UPDATE kilas_ai_subscriptions SET period_end=? WHERE user_id=?",(jobs.stamp(usage._now()-timedelta(seconds=1)),self.other))
        with self.policy(),patch('e2b.Sandbox.create') as create:
            self.assertFalse(access.entitled(self.other));self.assertFalse(execution.capability(self.other)['available'])
        create.assert_not_called()

    def test_real_compatibility_gate_reports_nonowner_on_without_sdk(self):
        self.actual_proof_row();self.paid(self.other)
        with self.policy(),patch('e2b.Sandbox.create') as create:
            self.assertTrue(execution.capability(self.other)['available'])
            self.assertTrue(access.log_readiness())
            self.assertFalse(execution.capability(None)['available'])
            self.assertFalse(proof.authorized())
        create.assert_not_called()
