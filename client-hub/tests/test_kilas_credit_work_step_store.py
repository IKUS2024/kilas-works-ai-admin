"""Work root concurrency/retry/cancellation on SQLite or isolated PostgreSQL."""
import json
import os
import unittest
from pathlib import Path
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import db
from kilas_ai import credit_policy as policy,credit_wallet as wallet,credit_work_steps as steps,usage
from kilas_ai.agent_workers import Result
from test_kilas_credit_wallet import WalletTests


class WorkStoreTests(unittest.TestCase):
    setUp=WalletTests.setUp
    tearDown=WalletTests.tearDown
    fund=WalletTests.fund
    proof=WalletTests.proof

    def fixture(self):
        self.fund()
        conn=usage._connect()
        try:
            sql=(Path(__file__).parents[1]/'migrations'/('0078_kilas_autonomous_agent_'+db.BACKEND+'.sql')).read_text()
            if db.BACKEND=='sqlite':conn.executescript(sql)
            else:
                with conn.cursor() as cursor:cursor.execute(sql)
            usage._query(conn,'ALTER TABLE kilas_agent_jobs ADD COLUMN origin_conversation_id BIGINT')
            usage._query(conn,'CREATE TABLE kilas_ai_subscriptions(user_id BIGINT,plan TEXT,status TEXT,period_start TEXT,period_end TEXT)')
            conn.commit()
        finally:conn.close()
        terms={'version':'customer-credit-v1','work_allocation':'per_successful_logical_step','rates':{'WORK_TEXT':{'milli':1000,'units':1}},'limits':{'WORK_TEXT':{'operations':{'text':{'models':['synthetic'],'max_calls':1,'input_bytes':1000,'output_tokens':100}}}}}
        flags=patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'yes','KILAS_CREDIT_TARIFFS_JSON':json.dumps(terms)})
        flags.start();self.addCleanup(flags.stop)
        db.execute("INSERT INTO kilas_agent_jobs(user_id,title,instruction,mode,status,lease_token,lease_until) VALUES (1,'Test','Create a note','ONE_SHOT','RUNNING','lease',?)",((usage._now()+timedelta(minutes=5)).isoformat(),))
        self.job=dict(db.query_one('SELECT * FROM kilas_agent_jobs'))
        db.execute("INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,status,input_json,idempotency_key,attempts) VALUES (?,1,'AI_TEXT','write','Write','RUNNING','{\"prompt\":\"Synthetic\"}','logical-root',1)",(self.job['id'],))
        self.step=dict(db.query_one('SELECT * FROM kilas_agent_steps'))
        with self.assertRaises(policy.ConsentRequired) as caught:steps.execute(self.job,self.step,lambda:None)
        token=policy.persist_consent(caught.exception);policy.consent(1,token,True)

    def provider(self):
        steps.before_provider('text','synthetic',{'prompt':'Synthetic'},100);steps.provider_done()
        return Result('SUCCEEDED','Synthetic',{'text':'Useful result'},verified=True)

    def test_simultaneous_root_admission_has_one_dispatch_and_settlement(self):
        self.fixture()
        def execute(_):
            try:return steps.execute(self.job,self.step,self.provider)
            except wallet.WalletError:return None
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(execute,range(16)))
        self.assertEqual(sum(item is not None for item in results),1)
        result=next(item for item in results if item)
        with self.assertRaisesRegex(wallet.WalletError,'still_active'):policy.reconcile(1,'logical-root',3,'NOT_DELIVERED',0,'synthetic reviewed evidence')
        db.execute("UPDATE kilas_agent_jobs SET status='PAUSED'")
        with self.assertRaisesRegex(wallet.WalletError,'still_active'):policy.reconcile(1,'logical-root',3,'NOT_DELIVERED',0,'synthetic reviewed evidence')
        db.execute("UPDATE kilas_agent_jobs SET status='RUNNING'")
        for _ in range(2):
            with wallet._locked(1) as conn:steps.finish_in(conn,self.job,result)
        self.assertEqual(wallet.balance(1)['balance_milli'],1999000)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_work_calls')['n'],1)
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_credit_events WHERE event_key='capture:logical-root'")['n'],1)

    def test_cancellation_before_supplier_releases_and_terminal_retry_never_calls_provider(self):
        self.fixture();count=[]
        def cancelled():
            db.execute("UPDATE kilas_agent_jobs SET status='STOPPED',revision=revision+1")
            steps.before_provider('text','synthetic',{'prompt':'Synthetic'},100);count.append(1)
        with self.assertRaisesRegex(wallet.WalletError,'cancelled'):steps.execute(self.job,self.step,cancelled)
        self.assertEqual(count,[]);self.assertEqual(wallet.balance(1)['reserved_milli'],0)
        with self.assertRaises(wallet.WalletError):steps.execute(self.job,self.step,self.provider)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_work_calls')['n'],0)

    def test_unknown_supplier_delivery_retains_hold_across_restart_and_no_redispatch(self):
        self.fixture()
        def interrupted():
            steps.before_provider('text','synthetic',{'prompt':'Synthetic'},100)
            raise OSError('synthetic transport interruption')
        with self.assertRaises(OSError):steps.execute(self.job,self.step,interrupted)
        db._discard_cached_connection()
        with self.assertRaises(wallet.WalletError):steps.execute(self.job,self.step,self.provider)
        self.assertEqual(wallet.balance(1)['reserved_milli'],1000)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_work_calls')['n'],1)

    def test_accepted_work_settles_after_rollback_without_reverting_to_chat_funding(self):
        self.fixture()
        def accepted():
            with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}):
                with wallet._locked(1) as conn:self.assertTrue(steps.supplier_only_in(conn,1))
                return self.provider()
        result=steps.execute(self.job,self.step,accepted)
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}):
            with wallet._locked(1) as conn:steps.finish_in(conn,self.job,result)
            with self.assertRaises(wallet.WalletError):steps.execute(self.job,self.step,self.provider)
        self.assertEqual(wallet.balance(1)['balance_milli'],1999000)


if __name__=='__main__':unittest.main()
