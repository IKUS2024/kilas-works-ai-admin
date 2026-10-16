"""Native PostgreSQL release rehearsal, loopback disposable database only."""
import os,sys,json,hashlib,threading
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import unittest

url=urlsplit(os.environ.get('DATABASE_URL',''))
if url.hostname not in ('127.0.0.1','localhost') or url.path!='/kilas_finance_qa' or os.environ.get('FINANCE_LOCAL_PG_QA')!='1':
    raise SystemExit('Dedicated loopback synthetic Finance PostgreSQL database required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db,repo,finance_service as f,finance_branches as branches,finance_schema

class NativeFinanceRelease(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert db.BACKEND=='postgres'
        with patch.object(db,'MIGRATIONS',[pair for pair in db.MIGRATIONS if not pair[0].startswith('0100_')]):db.init_schema()
        cls.uid=repo.create_user('native-synthetic@example.test','unused');cls.bid=repo.create_business(cls.uid,'Native synthetic Finance')
        f.ensure_finance_defaults(cls.bid,actor_user_id=cls.uid)
        cls.branch=branches.list_branches(cls.bid,cls.uid)[0]['id'];cls.account=f.list_accounts(cls.bid,actor_user_id=cls.uid)[0]['id']
        cat=f.list_categories(cls.bid,'INCOME',actor_user_id=cls.uid)[0]['id']
        now=repo._now()
        db.execute("INSERT INTO finance_transactions(business_id,branch_id,direction,amount_minor,currency,account_id,category_id,occurred_on,description,created_by_user_id,created_at,updated_at) VALUES (?,?,'INCOME',12345,'IDR',?,?,?,'Legacy synthetic row',?,?,?)",(cls.bid,cls.branch,cls.account,cat,'2026-09-10',cls.uid,now,now))
        cls.tables=[r['tablename'] for r in db.query_all("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE ? ORDER BY tablename", ('finance_%',))]
        cls.before=cls.snapshot()

    @classmethod
    def snapshot(cls):
        result={}
        for name in cls.tables:
            rows=db.query_all('SELECT to_jsonb(t)-\'notes\' AS row FROM '+name+' t ORDER BY (to_jsonb(t)-\'notes\')::text')
            result[name]=hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest()
        return result

    def test_01_late_schema_failure_rolls_back_every_change(self):
        original=Path.read_text
        def broken(path,*args,**kwargs):
            data=original(path,*args,**kwargs)
            return data+'\nSELECT missing_synthetic_release_function();' if str(path).endswith('0100_finance_approved_revisions_postgres.sql') else data
        with patch.object(Path,'read_text',broken),self.assertRaises(Exception):finance_schema.apply_release()
        self.assertIsNone(db.query_one("SELECT to_regclass('finance_internal_transfers') AS n")['n'])
        self.assertEqual(db.query_one("SELECT count(*) AS n FROM information_schema.columns WHERE table_name='finance_transactions' AND column_name='notes'")['n'],0)
        self.assertEqual(self.before,self.snapshot())

    def test_02_success_retry_preserves_all_legacy_rows(self):
        self.assertEqual(finance_schema.apply_release(),[finance_schema.NAME])
        self.assertEqual(finance_schema.apply_release(),[])
        self.assertEqual(self.before,self.snapshot())
        self.assertEqual(db.query_one("SELECT count(*) AS n FROM finance_release_migrations")['n'],1)

    def test_03_parallel_retries_debit_credit_once_and_reject_cross_currency(self):
        dest=f.create_account(self.bid,'Native reserve','BANK',actor_user_id=self.uid)
        barrier=threading.Barrier(4)
        def worker(_):
            try:
                barrier.wait()
                with branches.scope(self.bid,self.branch,self.uid):
                    return f.record_internal_transfer(self.bid,self.account,dest,999,'2026-09-10',idempotency_key='e'*32,actor_user_id=self.uid)
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(worker,range(4)))
        self.assertEqual(len(set(results)),1)
        with branches.scope(self.bid,self.branch,self.uid):
            balances={r['id']:r for r in f.get_account_balance_report(self.bid,'2026-09-30',self.uid)}
            self.assertEqual(balances[self.account]['balance_minor'],12345-999)
            self.assertEqual(balances[dest]['balance_minor'],999)
            self.assertEqual(sum(r['balance_minor'] for r in balances.values()),12345)
            self.assertEqual(f.get_finance_summary(self.bid,'2026-09-01','2026-09-30',actor_user_id=self.uid)['total_income_minor'],12345)
            usd=f.create_account(self.bid,'USD','BANK','USD',actor_user_id=self.uid)
            with self.assertRaisesRegex(f.FinanceError,'transfer_currency_mismatch'):
                f.record_internal_transfer(self.bid,self.account,usd,99,'2026-09-10',idempotency_key='f'*32,actor_user_id=self.uid)
        self.assertEqual(db.query_one('SELECT count(*) AS n FROM finance_internal_transfers')['n'],1)

    def test_04_audit_failure_leaves_no_partial_transfer(self):
        with branches.scope(self.bid,self.branch,self.uid):
            dest=f.list_accounts(self.bid,actor_user_id=self.uid)[1]['id']
            before=f.get_account_balance_report(self.bid,'2026-09-30',self.uid)
            with patch.object(f,'_audit',side_effect=RuntimeError('late synthetic failure')),self.assertRaises(RuntimeError):
                f.record_internal_transfer(self.bid,self.account,dest,200,'2026-09-10',idempotency_key='b'*32,actor_user_id=self.uid)
            self.assertEqual(before,f.get_account_balance_report(self.bid,'2026-09-30',self.uid))
        self.assertEqual(db.query_one('SELECT count(*) AS n FROM finance_internal_transfers')['n'],1)

if __name__=='__main__':unittest.main(verbosity=2)
