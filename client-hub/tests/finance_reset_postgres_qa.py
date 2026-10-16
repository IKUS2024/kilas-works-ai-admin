"""Native PostgreSQL reset rehearsal; refuses every non-loopback/non-disposable target."""
import os,sys,json,hashlib,threading,unittest
from pathlib import Path
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

url=urlsplit(os.environ.get('DATABASE_URL',''))
if url.hostname not in ('127.0.0.1','localhost') or url.path!='/kilas_finance_qa' or os.environ.get('FINANCE_LOCAL_PG_QA')!='1':
    raise SystemExit('Dedicated loopback synthetic Finance PostgreSQL database required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db,repo,finance_service as f,finance_branches as branches,finance_schema,finance_reset as reset,finance_personal as personal
NAME='0101_finance_reset_requests'

class NativeResetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert db.BACKEND=='postgres'
        with patch.object(db,'MIGRATIONS',[pair for pair in db.MIGRATIONS if not pair[0].startswith('0101_')]):db.init_schema()
        cls.uid=repo.create_user('reset-native-synthetic@example.test','unused')
        cls.bid=repo.create_business(cls.uid,'Native reset synthetic')
        f.ensure_finance_defaults(cls.bid,actor_user_id=cls.uid)
        cls.branch=branches.list_branches(cls.bid,cls.uid)[0]['id']
        with patch.object(personal,'resolve_home',return_value=None),patch.object(personal,'bind_home',return_value=None):
            cls.personal=branches.ensure_personal(cls.bid,cls.uid)
            with branches.scope(cls.bid,cls.personal,cls.uid):
                f.ensure_finance_defaults(cls.bid,actor_user_id=cls.uid)
                cls.account=f.create_account(cls.bid,'BCA synthetic','BANK',opening_balance_minor=12345,actor_user_id=cls.uid)
                cls.dest=f.create_account(cls.bid,'Other bank synthetic','BANK',opening_balance_minor=888,actor_user_id=cls.uid)
                category=f.list_categories(cls.bid,'INCOME',actor_user_id=cls.uid)[0]['id']
                f.create_transaction(cls.bid,'INCOME',777,cls.account,category,'2026-09-10',description='Synthetic native income',actor_user_id=cls.uid)
                expense=f.list_categories(cls.bid,'EXPENSE',actor_user_id=cls.uid)[0]['id']
                f.set_monthly_budget(cls.bid,'2026-09',expense,5000,'IDR',actor_user_id=cls.uid)
                f.record_internal_transfer(cls.bid,cls.account,cls.dest,234,'2026-09-10',idempotency_key='c'*32,actor_user_id=cls.uid)
        cls.tables=[r['tablename'] for r in db.query_all("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE ? ORDER BY tablename",('finance_%',))]
        cls.before=cls.snapshot()

    @classmethod
    def snapshot(cls):
        return {table:hashlib.sha256(json.dumps(db.query_all('SELECT to_jsonb(t) AS row FROM '+table+' t ORDER BY to_jsonb(t)::text'),sort_keys=True,default=str).encode()).hexdigest() for table in cls.tables}

    def test_01_bad_release_rolls_back_all_ddl_and_preserves_finance_rows(self):
        original=Path.read_text
        def broken(path,*args,**kw):
            value=original(path,*args,**kw)
            return value+'\nSELECT missing_reset_release_function();' if str(path).endswith(NAME+'_postgres.sql') else value
        with patch.object(Path,'read_text',broken),self.assertRaises(Exception):finance_schema.apply_release(NAME)
        self.assertIsNone(db.query_one("SELECT to_regclass('finance_reset_requests') AS n")['n'])
        self.assertIsNone(db.query_one("SELECT to_regclass('finance_personal_homes') AS n")['n'])
        self.assertEqual(self.snapshot(),self.before)

    def test_02_release_and_retry_are_additive(self):
        self.assertEqual(finance_schema.apply_release(NAME),[NAME])
        self.assertEqual(finance_schema.apply_release(NAME),[])
        self.assertEqual(self.snapshot(),self.before)

    def test_03_parallel_final_confirmations_execute_once(self):
        with branches.scope(self.bid,self.personal,self.uid):
            key=reset.prepare(self.bid,self.personal,actor_user_id=self.uid)
        before=self.snapshot()
        barrier=threading.Barrier(4)
        def worker(_):
            try:
                barrier.wait()
                with branches.scope(self.bid,self.personal,self.uid):
                    return reset.complete(self.bid,self.personal,key,actor_user_id=self.uid,confirmation='RESET',acknowledged='yes')
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=4) as pool:result=list(pool.map(worker,range(4)))
        self.assertEqual(result,[key]*4)
        self.assertEqual(db.query_one("SELECT count(*) AS n FROM audit_log WHERE action='FINANCE_RESET_CONFIRMED'")['n'],1)
        with branches.scope(self.bid,self.personal,self.uid):
            self.assertTrue(all(row['balance_minor']==0 for row in f.get_account_balance_report(self.bid,'2026-09-30',self.uid)))
            self.assertEqual(f.list_monthly_budgets(self.bid,'2026-09',actor_user_id=self.uid),[])
        self.assertEqual(db.query_one('SELECT status FROM finance_internal_transfers')['status'],'VOID')

    def test_04_audit_failure_rolls_back_budget_transaction_balances_and_consumption(self):
        with branches.scope(self.bid,self.personal,self.uid):
            category=f.list_categories(self.bid,'INCOME',actor_user_id=self.uid)[0]['id']
            tx=f.create_transaction(self.bid,'INCOME',900,self.account,category,'2026-09-11',actor_user_id=self.uid)
            expense=f.list_categories(self.bid,'EXPENSE',actor_user_id=self.uid)[0]['id']
            f.set_monthly_budget(self.bid,'2026-09',expense,5000,'IDR',actor_user_id=self.uid)
            f.record_internal_transfer(self.bid,self.account,self.dest,123,'2026-09-11',idempotency_key='d'*32,actor_user_id=self.uid)
            key=reset.prepare(self.bid,self.personal,actor_user_id=self.uid)
            before=self.snapshot()
            original=f._audit
            def fail(bid,uid,action,*args):
                if action=='FINANCE_RESET_CONFIRMED':raise RuntimeError('late synthetic audit failure')
                return original(bid,uid,action,*args)
            with patch.object(f,'_audit',side_effect=fail),self.assertRaises(RuntimeError):
                reset.complete(self.bid,self.personal,key,actor_user_id=self.uid,confirmation='RESET',acknowledged='yes')
            self.assertEqual(self.snapshot(),before)
            self.assertIsNone(db.query_one('SELECT processed_at FROM finance_reset_requests WHERE request_key=?',(key,))['processed_at'])
            self.assertEqual(f.get_transaction(self.bid,tx,actor_user_id=self.uid)['status'],'POSTED')

    def test_05_business_reset_excludes_other_branches_and_preserves_personal(self):
        second=branches.create_branch(self.bid,'Native inactive business',self.uid)
        with branches.scope(self.bid,second,self.uid):
            account=f.list_accounts(self.bid,actor_user_id=self.uid)[0]['id']
            f.update_account_opening_balance(self.bid,account,123456,actor_user_id=self.uid)
        db.execute('UPDATE finance_branches SET is_active=FALSE WHERE id=?',(second,))
        personal_before=db.query_all('SELECT * FROM finance_accounts WHERE branch_id=? ORDER BY id',(self.personal,))
        personal_transactions=db.query_all('SELECT * FROM finance_transactions WHERE branch_id=? ORDER BY id',(self.personal,))
        with branches.scope(self.bid,self.branch,self.uid):
            key=reset.prepare(self.bid,self.branch,actor_user_id=self.uid)
            reset.complete(self.bid,self.branch,key,actor_user_id=self.uid,confirmation='RESET',acknowledged='yes')
        self.assertEqual(db.query_one('SELECT opening_balance_minor FROM finance_accounts WHERE id=?',(account,))['opening_balance_minor'],123456)
        self.assertEqual(personal_before,db.query_all('SELECT * FROM finance_accounts WHERE branch_id=? ORDER BY id',(self.personal,)))
        self.assertEqual(personal_transactions,db.query_all('SELECT * FROM finance_transactions WHERE branch_id=? ORDER BY id',(self.personal,)))

    def test_06_concurrent_personal_creation_across_businesses_has_one_home(self):
        owner=repo.create_user('native-canonical-owner@example.test','unused')
        bids=[repo.create_business(owner,'Canonical race '+str(n)) for n in range(2)]
        for bid in bids:f.ensure_finance_defaults(bid,actor_user_id=owner)
        barrier=threading.Barrier(2)
        def worker(bid):
            try:
                barrier.wait()
                try:return branches.ensure_personal(bid,owner)
                except f.FinanceError as error:return str(error)
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(worker,bids))
        self.assertEqual(sum(type(value) is int for value in results),1)
        self.assertEqual(sum(value=='personal_home_elsewhere' for value in results),1)
        self.assertEqual(db.query_one("SELECT count(*) AS n FROM finance_branch_workspaces WHERE workspace_type='PERSONAL' AND owner_user_id=?",(owner,))['n'],1)
        self.assertEqual(db.query_one('SELECT count(*) AS n FROM finance_personal_homes WHERE user_id=?',(owner,))['n'],1)

if __name__=='__main__':unittest.main(verbosity=2)
