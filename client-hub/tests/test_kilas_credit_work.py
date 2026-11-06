"""Durable job consent and exactly-once dispatch, synthetic models and balances."""
import json
import os
import unittest
from pathlib import Path
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import db
from kilas_ai import credit_work as work, credit_policy as policy, credit_wallet as wallet, usage, autonomous_store as store
from kilas_ai.agent_workers.image_worker import contract
from test_kilas_credit_wallet import WalletTests


class WorkCreditTests(unittest.TestCase):
    setUp=WalletTests.setUp
    tearDown=WalletTests.tearDown
    fund=WalletTests.fund
    proof=WalletTests.proof

    def setup_job(self):
        self.fund()
        flags=patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'yes','KILAS_AI_OPENAI_IMAGE_MODEL':'synthetic-model',
            'KILAS_CREDIT_TARIFFS_JSON':json.dumps({'version':'customer-credit-v1','rates':{'IMAGE':{'milli':1000,'units':1}}})})
        flags.start();self.addCleanup(flags.stop)
        conn=usage._connect()
        try:
            sql=(Path(__file__).parents[1]/'migrations'/('0078_kilas_autonomous_agent_'+db.BACKEND+'.sql')).read_text()
            if db.BACKEND=='sqlite':conn.executescript(sql)
            else:
                with conn.cursor() as cursor:cursor.execute(sql)
            usage._query(conn,'ALTER TABLE kilas_agent_jobs ADD COLUMN origin_conversation_id BIGINT')
            conn.commit()
        finally:conn.close()
        db.execute("INSERT INTO kilas_agent_jobs(user_id,title,instruction,mode,status,lease_token,lease_until,plan_json) VALUES (1,'Test','Create image','ONE_SHOT','RUNNING','lease',?,'{\"steps\":1}')",((usage._now()+timedelta(minutes=10)).isoformat(),))
        self.job_id=db.query_one('SELECT MAX(id) AS id FROM kilas_agent_jobs')['id']
        db.execute("INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,status,input_json,idempotency_key,attempts) VALUES (?,1,'IMAGE','generate','Create','RUNNING',?,'work-image',1)",(self.job_id,json.dumps({'prompt':'Synthetic request'})))
        self.job,self.step=self.current()
        policy.admit(1,'used-free-image','IMAGE',1,'a'*64);policy.finish(1,'used-free-image',1,success=True)
        self.spec=contract(self.job,self.step,json.loads(self.step['input_json']))
        with self.assertRaises(policy.ConsentRequired) as caught:self.admit()
        self.assertTrue(work.park(self.job,'lease',self.step,caught.exception))
        self.token=work.waiting(1,self.job_id)['token']

    def current(self):
        return dict(db.query_one('SELECT * FROM kilas_agent_jobs WHERE id=?',(self.job_id,))),dict(db.query_one('SELECT * FROM kilas_agent_steps WHERE job_id=?',(self.job_id,)))

    def admit(self):return policy.admit(1,'work-image','IMAGE',1,self.spec['profile']['credit_fingerprint'])

    def test_exact_resume_once_completed_steps_preserved_and_no_direct_provider(self):
        self.setup_job()
        self.assertEqual(self.current()[0]['status'],'NEEDS_APPROVAL')
        self.assertEqual(self.current()[1]['attempts'],0)
        with self.assertRaisesRegex(ValueError,'credit_consent'):store.control(1,self.job_id,'resume')
        with self.assertRaises(wallet.WalletError):work.decide(2,self.token,True)
        self.assertEqual(work.decide(1,self.token,True),'APPROVED')
        self.assertEqual(work.decide(1,self.token,True),'APPROVED')
        self.assertEqual(self.current()[0]['revision'],1)
        self.assertEqual(self.current()[1]['status'],'PENDING')
        job,_=self.current();step=store.begin_step(job,'lease')
        self.assertTrue(self.admit()['dispatch'])
        work.dispatch(job,step,self.spec)
        with self.assertRaisesRegex(wallet.WalletError,'dispatch_closed'):work.dispatch(job,step,self.spec)
        policy.finish(1,'work-image',1,success=True)
        self.assertFalse(self.admit()['dispatch'])
        self.assertEqual(wallet.balance(1)['balance_milli'],1999000)
        self.assertEqual(db.query_one('SELECT state FROM kilas_credit_work_waits')['state'],'CONSUMED')

    def test_concurrent_resume_schedules_one_revision_and_one_dispatch(self):
        self.setup_job()
        with ThreadPoolExecutor(max_workers=4) as pool:result=list(pool.map(lambda _:work.decide(1,self.token,True),range(8)))
        self.assertEqual(result,['APPROVED']*8)
        job,_=self.current();step=store.begin_step(job,'lease');self.admit()
        def dispatch(_):
            try:work.dispatch(job,step,self.spec);return True
            except wallet.WalletError:return False
        with ThreadPoolExecutor(max_workers=4) as pool:result=list(pool.map(dispatch,range(8)))
        self.assertEqual(sum(result),1)
        self.assertEqual(self.current()[0]['revision'],1)

    def test_decline_expiry_changed_input_model_tariff_and_cancellation_never_dispatch(self):
        self.setup_job()
        with patch.dict(os.environ,{'KILAS_AI_OPENAI_IMAGE_MODEL':'changed-model'}):
            with self.assertRaisesRegex(wallet.WalletError,'work_changed'):work.decide(1,self.token,True)
        original=self.step['input_json'];db.execute("UPDATE kilas_agent_steps SET input_json='{}' WHERE job_id=?",(self.job_id,))
        with self.assertRaises(wallet.WalletError):work.decide(1,self.token,True)
        db.execute('UPDATE kilas_agent_steps SET input_json=? WHERE job_id=?',(original,self.job_id))
        with patch.dict(os.environ,{'KILAS_CREDIT_TARIFFS_JSON':json.dumps({'version':'customer-credit-v1','rates':{'IMAGE':{'milli':1001,'units':1}}})}):
            with self.assertRaisesRegex(wallet.WalletError,'quote_changed'):work.decide(1,self.token,True)
        old=db.query_one('SELECT expires_at FROM kilas_credit_consents')['expires_at']
        db.execute('UPDATE kilas_credit_consents SET expires_at=?',((usage._now()-timedelta(seconds=1)).isoformat(),))
        with self.assertRaisesRegex(wallet.WalletError,'expired'):work.decide(1,self.token,True)
        db.execute('UPDATE kilas_credit_consents SET expires_at=?',(old,))
        self.assertEqual(work.decide(1,self.token,False),'DECLINED')
        self.assertEqual(self.current()[0]['status'],'PAUSED')
        with self.assertRaises(wallet.WalletError):work.decide(1,self.token,True)
        self.assertEqual(wallet.balance(1)['reserved_milli'],0)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_work_operations')['n'],0)

    def test_cancelled_or_insufficient_resume_and_pending_old_worker_are_fenced(self):
        self.setup_job();store.control(1,self.job_id,'stop')
        with self.assertRaisesRegex(wallet.WalletError,'work_changed'):work.decide(1,self.token,True)
        with self.assertRaises(wallet.WalletError):work.dispatch(self.job,self.step,self.spec)
        self.assertEqual(wallet.balance(1)['reserved_milli'],0)

    def test_rollback_cannot_reprice_waiting_work_as_legacy_or_skip_dispatch_fence(self):
        self.setup_job();work.decide(1,self.token,True)
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}):
            with self.assertRaisesRegex(wallet.WalletError,'disabled'):work.guard_mode(self.job,self.step)
        job,_=self.current();step=store.begin_step(job,'lease');self.admit()
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}):
            work.dispatch(job,step,self.spec)
            with self.assertRaisesRegex(wallet.WalletError,'closed'):work.dispatch(job,step,self.spec)
        self.assertEqual(wallet.balance(1)['reserved_milli'],1000)

    def test_balance_change_after_consent_cannot_dispatch(self):
        self.setup_job();work.decide(1,self.token,True)
        wallet.reserve(1,'other',2000000,fingerprint='b'*64)
        with self.assertRaisesRegex(wallet.WalletError,'insufficient'):self.admit()
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_work_operations')['n'],0)


if __name__=='__main__':unittest.main()
