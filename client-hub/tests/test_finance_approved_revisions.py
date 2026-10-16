"""Approved October Finance contract. Disposable local fixtures; all external IO forbidden."""
import io
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from flask import template_rendered
from PIL import Image
import test_finance_phase2a as prior
import db, repo, finance_service as f, finance_branches as branches

app = prior.app

class ApprovedFinanceTests(unittest.TestCase):
    def setUp(self):
        prior.ReceivablesTests.setUp(self)
        self.client.set_cookie('kilas_language','id')
        self.branch = branches.list_branches(self.b,self.uid)[0]['id']
        self.personal = branches.ensure_personal(self.b,self.uid)
        with branches.scope(self.b,self.personal,self.uid):
            f.ensure_finance_defaults(self.b,actor_user_id=self.uid)
            self.pa = f.list_accounts(self.b,actor_user_id=self.uid)[0]['id']
        self.dest = f.create_account(self.b,'Synthetic reserve','BANK',opening_balance_minor=20000,actor_user_id=self.uid)
        self.fx = patch('finance_fx.snapshot',return_value={'rates':{'IDR':'1','USD':'15000'},'source':'synthetic','date':'2026-09-10','stale':False})
        self.fx.start();self.addCleanup(self.fx.stop)

    def page(self, branch=None, **query):
        contexts=[]
        def capture(sender,template,context,**extra):contexts.append(context)
        with template_rendered.connected_to(capture,app):
            response=self.client.get(self.url,query_string=dict(branch_id=branch or self.branch,month='2026-09',**query))
        self.assertEqual(response.status_code,200)
        return response.text,contexts[-1]

    def transfer(self, **values):
        data=dict(business_id=self.b,from_account_id=self.a,to_account_id=self.dest,
                  amount_minor=12345,occurred_on='2026-09-10',idempotency_key='a'*32,actor_user_id=self.uid)
        data.update(values)
        with branches.scope(self.b,self.branch,self.uid):return f.record_internal_transfer(**data)

    def balances(self, as_of='2026-09-30'):
        with branches.scope(self.b,self.branch,self.uid):
            return {r['id']:r for r in f.get_account_balance_report(self.b,as_of,self.uid)}

    def test_equal_debit_credit_conserves_native_total_and_excludes_cashflow(self):
        before=self.balances()
        original=f.get_finance_summaries(self.b,'2026-09-01','2026-09-30',actor_user_id=self.uid)
        self.transfer();after=self.balances()
        self.assertEqual(after[self.a]['balance_minor'],before[self.a]['balance_minor']-12345)
        self.assertEqual(after[self.dest]['balance_minor'],before[self.dest]['balance_minor']+12345)
        self.assertEqual(sum(r['balance_minor'] for r in before.values()),sum(r['balance_minor'] for r in after.values()))
        self.assertEqual(original,f.get_finance_summaries(self.b,'2026-09-01','2026-09-30',actor_user_id=self.uid))
        self.assertEqual(before,self.balances('2026-09-09'))
        self.assertEqual(f.count_transactions(self.b,actor_user_id=self.uid),0)

    def test_transfer_retry_and_conflicting_payload(self):
        first=self.transfer();before=self.balances()
        self.assertEqual(self.transfer(),first);self.assertEqual(self.balances(),before)
        with self.assertRaisesRegex(f.FinanceError,'transfer_key_conflict'):self.transfer(amount_minor=100)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_internal_transfers')['n'],1)

    def test_concurrent_submissions_have_one_atomic_result(self):
        barrier=threading.Barrier(2)
        def worker(_):
            try:
                barrier.wait();return self.transfer()
            finally:
                if getattr(db._local,'conn',None):db._local.conn.close();db._local.conn=None
        with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(worker,range(2)))
        self.assertEqual(result[0],result[1])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_internal_transfers')['n'],1)

    def test_invalid_transfer_values_and_scope_never_write(self):
        foreign=f.list_accounts(self.other)[0]['id']
        usd=f.create_account(self.b,'USD fixture','BANK','USD',actor_user_id=self.uid)
        for params in (dict(to_account_id=self.a),dict(to_account_id=usd),dict(to_account_id=foreign),
                       dict(to_account_id=self.pa),dict(amount_minor=0),dict(amount_minor=-1),
                       dict(amount_minor=1.5),dict(amount_minor=True),dict(amount_minor=2**63),
                       dict(occurred_on='2999-01-01'),dict(idempotency_key='bad')):
            with self.subTest(params=params),self.assertRaises(f.FinanceError):self.transfer(**params)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_internal_transfers')['n'],0)
        with self.assertRaises(f.FinanceError):self.transfer(actor_user_id=self.other_uid)
        with self.assertRaises(f.FinanceError):f.record_internal_transfer(self.b,self.a,self.dest,1,'2026-09-10',idempotency_key='a'*32,actor_user_id=self.uid)

    def test_inactive_account_and_other_personal_owner_denied(self):
        db.execute('UPDATE finance_accounts SET is_active=FALSE WHERE id=?',(self.dest,))
        with self.assertRaises(f.FinanceError):self.transfer()
        db.execute("INSERT INTO business_memberships(business_id,user_id,role_in_business) VALUES (?,?,'OWNER')",(self.b,self.other_uid))
        other_personal=branches.ensure_personal(self.b,self.other_uid)
        with self.assertRaises(f.FinanceError):
            with branches.scope(self.b,other_personal,self.uid):f.list_internal_transfers(self.b,actor_user_id=self.uid)

    def test_late_audit_failure_rolls_back_transfer_and_both_balances(self):
        before=self.balances()
        with patch.object(f,'_audit',side_effect=RuntimeError('synthetic failure')),self.assertRaises(RuntimeError):self.transfer()
        self.assertEqual(before,self.balances())
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_internal_transfers')['n'],0)

    def test_void_preserves_history_and_retry_does_not_restore_money(self):
        before=self.balances();tid=self.transfer()
        with branches.scope(self.b,self.branch,self.uid):
            f.void_internal_transfer(self.b,tid,actor_user_id=self.uid)
            f.void_internal_transfer(self.b,tid,actor_user_id=self.uid)
            history=f.list_internal_transfers(self.b,actor_user_id=self.uid)
        self.assertEqual(history[0]['status'],'VOID');self.assertEqual(self.balances(),before)
        self.assertEqual(self.transfer(),tid);self.assertEqual(self.balances(),before)

    def test_transfer_linked_account_cannot_move_workspace(self):
        self.transfer()
        with branches.scope(self.b,self.branch,self.uid),self.assertRaisesRegex(f.FinanceError,'workspace_move_fx_linked'):
            f.move_account_workspace(self.b,self.a,self.personal,actor_user_id=self.uid)

    def test_personal_income_description_notes_and_legacy_category_preserved(self):
        with branches.scope(self.b,self.personal,self.uid):
            old_categories=f.list_categories(self.b,'INCOME',include_inactive=True,actor_user_id=self.uid)
        response=self.client.post(self.url+'/transactions',data=dict(branch_id=self.personal,direction='INCOME',
            description='Synthetic consulting',occurred_on='2026-09-10',amount='123.45',account_id=self.pa,notes='Optional separate note',
            return_view='transactions',return_direction='INCOME',return_period_mode='range',return_range_start='2026-08',return_range_end='2026-09',return_account_id=self.pa,return_search='consulting',return_display_currency='IDR'))
        self.assertEqual(response.status_code,303)
        for preserved in ('period_mode=range','range_start=2026-08','search=consulting','account_id=','direction=INCOME'):self.assertIn(preserved,response.location)
        html,ctx=self.page(self.personal,view='transactions',direction='INCOME')
        self.assertEqual([(r['name'],r['amount_minor']) for r in ctx['ledger_category_rows']],[('Synthetic consulting',12345)])
        self.assertIn('Optional separate note',html)
        row=f.get_transaction(self.b,ctx['transactions'][0]['id'],actor_user_id=self.uid)
        self.assertEqual((row['description'],row['notes']),('Synthetic consulting','Optional separate note'))
        with branches.scope(self.b,self.personal,self.uid):
            new=f.list_categories(self.b,'INCOME',include_inactive=True,actor_user_id=self.uid)
        self.assertTrue(all(row in new for row in old_categories))

    def test_missing_personal_description_and_invalid_notes_leave_no_rows(self):
        for description,notes in (('',None),('Valid','x'*4001)):
            self.client.post(self.url+'/transactions',data=dict(branch_id=self.personal,direction='INCOME',description=description,
                notes=notes or '',occurred_on='2026-09-10',amount='10',account_id=self.pa))
        self.assertEqual(f.count_transactions(self.b,actor_user_id=self.uid),0)
        with branches.scope(self.b,self.personal,self.uid):
            self.assertNotIn('Pemasukan',[r['name'] for r in f.list_categories(self.b,'INCOME',actor_user_id=self.uid)])

    def test_summaries_only_saved_categories_and_current_filters(self):
        html,ctx=self.page(view='transactions',direction='EXPENSE')
        self.assertEqual(ctx['ledger_category_rows'],[])
        self.assertNotIn('class="card finance-ledger-category-card"',html)
        category=f.list_categories(self.b,'EXPENSE',actor_user_id=self.uid)[0]['id']
        for account,amount,description in ((self.a,100,'First'),(self.dest,250,'Second')):
            f.create_transaction(self.b,'EXPENSE',amount,account,category,'2026-09-10',description=description,actor_user_id=self.uid)
        _,ctx=self.page(view='transactions',direction='EXPENSE',account_id=self.dest,search='Second')
        self.assertEqual(len(ctx['ledger_category_rows']),1)
        self.assertEqual(ctx['ledger_category_rows'][0]['amount_minor'],250)
        self.assertEqual(ctx['period_expense_display'],'Rp2,50')
        _,ctx=self.page(view='transactions',direction='EXPENSE',search='missing')
        self.assertEqual(ctx['ledger_category_rows'],[]);self.assertEqual(ctx['period_expense_display'],'Rp0,00')

    def test_personal_income_edit_keeps_original_category_and_notes(self):
        with branches.scope(self.b,self.personal,self.uid):
            cat=f.list_categories(self.b,'INCOME',actor_user_id=self.uid)[0]['id']
            tx=f.create_transaction(self.b,'INCOME',100,self.pa,cat,'2026-09-10',description='Legacy source',actor_user_id=self.uid)
        self.client.post(self.url+f'/transactions/{tx}/edit',data=dict(branch_id=self.personal,description='Edited source',notes='Edited note',amount='2.50',occurred_on='2026-09-10',account_id=self.pa))
        row=f.get_transaction(self.b,tx,actor_user_id=self.uid)
        self.assertEqual((row['category_id'],row['description'],row['notes'],row['amount_minor']),(cat,'Edited source','Edited note',250))

    def test_header_identity_persists_and_upload_is_protected(self):
        image=io.BytesIO();Image.new('RGB',(12,12),'green').save(image,format='PNG')
        data=dict(branch_id=str(self.branch),name='Synthetic renamed business',photo=(io.BytesIO(image.getvalue()),'logo.png'))
        self.assertEqual(self.client.post(self.url+'/identity',data=data).status_code,303)
        html,ctx=self.page();self.assertEqual(ctx['finance_ui']['identity_name'],'Synthetic renamed business')
        self.assertIsNotNone(ctx['finance_ui']['identity_photo'])
        response=self.client.get(f'/account/business/{self.b}/photo')
        self.assertEqual(response.status_code,200);self.assertEqual(response.data,image.getvalue())
        self.assertEqual(self.client.get(f'/account/business/{self.other}/photo').status_code,404)
        self.client.post(self.url+'/identity',data=dict(branch_id=self.personal,name='Synthetic personal name',photo=(io.BytesIO(image.getvalue()),'personal.png')))
        self.assertEqual(self.client.get('/account/photo').data,image.getvalue())
        _,ctx=self.page(self.personal);self.assertEqual(ctx['finance_ui']['identity_name'],'Synthetic personal name')
        _,ctx=self.page();self.assertEqual(ctx['finance_ui']['identity_name'],'Synthetic renamed business')

    def test_invalid_image_and_staff_identity_write_denied(self):
        before=repo.get_business(self.b)['business_name']
        for filename,content in (('bad.svg',b'<svg/>'),('bad.png',b'\x89PNG\r\n\x1a\nbroken'),('bad.jpg',b'x'*(5*1024*1024+1))):
            self.client.post(self.url+'/identity',data=dict(branch_id=self.branch,name='Invalid change',photo=(io.BytesIO(content),filename)))
            self.assertEqual(repo.get_business(self.b)['business_name'],before)
        db.execute("UPDATE business_memberships SET role_in_business='STAFF' WHERE business_id=? AND user_id=?",(self.b,self.uid))
        self.assertEqual(self.client.post(self.url+'/identity',data=dict(branch_id=self.branch,name='Forbidden')).status_code,403)

    def test_http_transfer_requires_csrf_and_rejects_forged_accounts(self):
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        payload=dict(branch_id=self.branch,from_account_id=self.a,to_account_id=self.dest,amount='10',occurred_on='2026-09-10',idempotency_key='b'*32)
        self.assertEqual(self.client.post(self.url+'/internal-transfers',data=payload).status_code,400)
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=False
        payload['to_account_id']=self.pa
        self.client.post(self.url+'/internal-transfers',data=payload)
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM finance_internal_transfers')['n'],0)

    def test_schema_reapply_keeps_every_legacy_transaction_and_account(self):
        tx=f.create_transaction(self.b,'INCOME',321,self.a,self.cat,'2026-09-10',description='Legacy retained',actor_user_id=self.uid)
        self.transfer()
        before=(f.get_transaction(self.b,tx),self.balances())
        db.init_schema();db.init_schema()
        self.assertEqual(before,(f.get_transaction(self.b,tx),self.balances()))

    def test_existing_businesses_not_recreated_or_merged(self):
        count=db.query_one('SELECT COUNT(*) AS n FROM businesses')['n']
        self.client.post('/products/finance',data={'action':'create_trial','business_name':'Unwanted new business','setup_identity':'a'*32})
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM businesses')['n'],count)
        self.assertEqual(repo.get_business(self.other)['business_name'],'Other business')
