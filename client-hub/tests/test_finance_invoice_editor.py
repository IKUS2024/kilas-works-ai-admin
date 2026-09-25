"""Invoice-only correction, identity, ledger, UI and share regression tests."""
import copy
import json
import re
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from werkzeug.datastructures import MultiDict
import test_finance_phase2a as prior
import finance_invoice_editor as editor
import finance_invoice_view as view
import finance_invoice_pdf as pdf

f,db,repo,app=prior.f,prior.db,prior.repo,prior.app


class InvoiceEditorTests(unittest.TestCase):
    setUp=prior.ReceivablesTests.setUp
    draft=prior.ReceivablesTests.draft
    issued=prior.ReceivablesTests.issued
    pay=prior.ReceivablesTests.pay

    def data(self):
        return editor.clean_document(dict(sender=dict(name='Kilas Sender',address='Sender Road 10',phone='081111',email='sender@example.test',tax_id='NPWP-S',website='example.test'),
            recipient=dict(name='Wilson',pic='Putri',address='Recipient Road 20',phone='082222',email='wilson@example.test',tax_id='NPWP-R'),
            payment=dict(method='Transfer Bank',bank='BCA',account_number='123456789',account_holder='CV Kilas',instructions='Cantumkan nomor invoice'),reference='PO-123'))

    def edit(self,i,changes,**kwargs):
        return editor.edit(self.b,i,changes,actor_user_id=self.uid,**kwargs)

    def create(self,customer=None,key='a'*32,**kwargs):
        return editor.create(self.b,customer,self.data(),actor_user_id=self.uid,submission_key=key,
            issue_date='2026-09-01',due_date='2026-09-30',items=[dict(description='Service',quantity=1,unit_price_minor=100)],**kwargs)

    def test_existing_customer_and_inline_recipient_retries(self):
        i=self.create(self.c)
        self.assertEqual(f.get_finance_invoice(self.b,i)['customer_id'],self.c)
        self.assertEqual(len(f.list_customers(self.b)),1)
        n=self.create(key='b'*32)
        self.assertEqual(self.create(key='b'*32),n)
        self.assertEqual(len(f.list_customers(self.b)),2)
        self.assertEqual(view.document(self.b,n,self.uid)['customer']['name'],'Wilson')
        self.assertEqual(len(f.list_transactions(self.b)),0)

    def test_inline_reuses_exact_customer_and_rejects_ambiguous_identity(self):
        c=f.create_customer(self.b,'Wilson',phone='082222',email='wilson@example.test')
        i=self.create()
        self.assertEqual(f.get_finance_invoice(self.b,i)['customer_id'],c)
        f.create_customer(self.b,'Wilson')
        with self.assertRaisesRegex(f.FinanceError,'invoice_select_customer'):self.create(key='c'*32)

    def test_failed_inline_invoice_rolls_back_customer(self):
        before=len(f.list_customers(self.b))
        with patch.object(f,'create_finance_invoice',side_effect=f.FinanceError('test')):
            with self.assertRaises(f.FinanceError):self.create()
        self.assertEqual(len(f.list_customers(self.b)),before)

    def test_profile_defaults_and_branch_override_leave_profile_untouched(self):
        repo.upsert_business_profile(self.b,{'address':'Initial'})
        db.execute('UPDATE business_profiles SET address=?,business_phone=?,payment_bank_name=?,payment_account_number=?,payment_account_name=?,payment_instructions=? WHERE business_id=?',
                   ('Original address','08123','BCA','123','Owner','Transfer',self.b))
        d=editor.defaults(self.b,self.uid)
        self.assertEqual(d['sender']['name'],'Business');self.assertEqual(d['sender']['address'],'Original address')
        self.assertEqual(d['payment']['account_number'],'123')
        editor.save_defaults(self.b,{k:self.data()[k] for k in ('sender','payment')},self.uid)
        self.assertEqual(editor.defaults(self.b,self.uid)['sender']['name'],'Kilas Sender')
        self.assertEqual(db.query_one('SELECT address FROM business_profiles WHERE business_id=?',(self.b,))['address'],'Original address')
        i=self.draft();self.assertEqual(view.document(self.b,i,self.uid)['issuer'],'Kilas Sender')

    def test_snapshot_survives_profile_customer_and_settings_changes(self):
        i=self.create(self.c);before=view.document(self.b,i,self.uid)
        db.execute('UPDATE businesses SET business_name=? WHERE id=?',('Changed',self.b))
        f.update_customer(self.b,self.c,'Changed Customer',actor_user_id=self.uid)
        d=self.data();d['sender']['name']='Changed defaults';editor.save_defaults(self.b,{k:d[k] for k in ('sender','payment')},self.uid)
        self.assertEqual(view.document(self.b,i,self.uid),before)

    def test_draft_full_edit_number_and_no_income(self):
        i=self.draft();number=f.get_finance_invoice(self.b,i)['invoice_number']
        new=f.create_customer(self.b,'Replacement')
        self.edit(i,dict(customer_id=new,issue_date='2026-09-02',due_date='2026-10-01',currency='USD',notes='Revised',document_data=self.data(),
                         items=[dict(description='New',quantity=3,unit_price_minor=200)]))
        row=f.get_finance_invoice(self.b,i)
        self.assertEqual(row['invoice_number'],number);self.assertEqual(row['currency'],'USD')
        self.assertEqual(f.get_invoice_totals(self.b,i)['total_minor'],600)
        self.assertEqual(f.list_transactions(self.b),[])

    def test_issued_correction_receivable_and_audit(self):
        i=self.issued();self.edit(i,dict(items=[dict(description='Corrected',quantity=2,unit_price_minor=300)],due_date='2026-09-01',document_data=self.data()),expected_revision=0)
        self.assertEqual(f.get_receivables_summary(self.b)['total_outstanding_minor'],600)
        self.assertTrue(f.get_invoice_totals(self.b,i,today='2026-09-22')['overdue'])
        self.assertEqual(f.list_transactions(self.b),[])
        rev=db.query_one('SELECT * FROM finance_invoice_revisions WHERE invoice_id=?',(i,))
        self.assertEqual(rev['actor_user_id'],self.uid);self.assertTrue(rev['created_at'])
        self.assertIn('items',json.loads(rev['fields_changed']))
        self.assertEqual(json.loads(rev['before_json'])['items'][0]['unit_price_minor'],100)
        with self.assertRaisesRegex(f.FinanceError,'invoice_revision_conflict'):self.edit(i,dict(notes='Stale'),expected_revision=0)
        self.assertEqual(f.get_finance_invoice(self.b,i)['revision'],1)

    def test_partial_and_paid_financial_lock_and_text_edit(self):
        for amount in (100,250):
            i=self.issued();self.pay(i,amount,key=f'payment-lock-key-{amount}')
            before=f.list_invoice_payments(self.b,i);ledger=f.list_transactions(self.b);totals=f.get_invoice_totals(self.b,i)
            rows=[{k:r[k] for k in ('description','quantity','unit_price_minor')} for r in f.list_invoice_items(self.b,i)]
            for change in ({'currency':'USD'},{'due_date':'2026-10-01'},{'issue_date':'2026-09-02'},
                           {'customer_id':self.oc},{'items':[dict(description='Bad',quantity=1,unit_price_minor=250)]}):
                with self.subTest(amount=amount,change=change),self.assertRaises(f.FinanceError):self.edit(i,change)
            rows[0]['description']='Spelling corrected'
            self.edit(i,dict(document_data=self.data(),items=rows,notes='Thank you'))
            self.assertEqual(f.get_invoice_totals(self.b,i),totals)
            self.assertEqual(f.list_invoice_payments(self.b,i),before)
            self.assertEqual(f.list_transactions(self.b),ledger)
            self.assertEqual(view.document(self.b,i,self.uid)['customer']['name'],'Wilson')

    def test_payment_replay_after_edit_stays_once(self):
        i=self.issued();p=self.pay(i);self.edit(i,{'notes':'Corrected'})
        self.assertEqual(self.pay(i),p)
        self.assertEqual(len(f.list_invoice_payments(self.b,i)),1);self.assertEqual(len(f.list_transactions(self.b)),1)
        self.pay(i,150,key='another-payment-key-2');self.edit(i,{'notes':'Paid correction'})
        self.assertEqual(f.get_finance_invoice(self.b,i)['status'],'PAID')
        self.assertEqual(f.get_receivables_summary(self.b)['total_outstanding_minor'],0)

    def test_pdf_and_public_latest_projection_private_data_excluded(self):
        from pypdf import PdfReader
        i=self.create(self.c);f.issue_finance_invoice(self.b,i)
        with app.test_request_context():token=view.create_token(self.b,i,self.uid)
        d=self.data();d['recipient']['name']='Corrected Wilson';self.edit(i,{'document_data':d})
        doc=view.document(self.b,i,self.uid)
        self.assertEqual(doc,view.document(self.b,i,public=True))
        text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(pdf.build(doc))).pages)
        for value in ('Kilas Sender','Sender Road 10','Corrected Wilson','Recipient Road 20','123456789','CV Kilas','PO-123'):
            self.assertIn(value,text)
            for url in (self.url+f'/invoices/{i}','/finance/invoice-share/'+token):
                response=self.client.get(url);self.assertEqual(response.status_code,200);self.assertIn(value,response.get_data(as_text=True))
        public=self.client.get('/finance/invoice-share/'+token).get_data(as_text=True)
        for private in ('fields_changed','actor_user_id','ledger_transaction_id','before_json'):self.assertNotIn(private,public)

    def test_branch_tenant_isolation_and_all_read_only(self):
        i=self.draft();branch=f.branches.create_branch(self.b,'Second',actor_user_id=self.uid)
        with f.branches.scope(self.b,branch,self.uid):
            with self.assertRaises(f.FinanceError):self.edit(i,{'notes':'Wrong branch'})
            d=self.data();editor.save_defaults(self.b,{k:d[k] for k in ('sender','payment')},self.uid)
        self.assertEqual(editor.defaults(self.b,self.uid)['sender']['name'],'Business')
        with f.branches.scope(self.b,None,self.uid):
            with self.assertRaises(f.FinanceError):self.edit(i,{'notes':'All'})
        with self.assertRaises(f.FinanceError):editor.edit(self.other,i,{'notes':'Wrong tenant'},actor_user_id=self.other_uid)
        with self.assertRaises(f.FinanceError):editor.defaults(self.b,self.other_uid)

    def test_legacy_fallback_and_migration_backfill(self):
        i=self.draft();db.execute('UPDATE finance_invoices SET document_snapshot=NULL WHERE id=?',(i,))
        doc=view.document(self.b,i,self.uid);self.assertEqual(doc['customer']['name'],'Customer <test>')
        migration=(Path(__file__).parents[1]/'migrations/0047_finance_invoice_snapshots_sqlite.sql').read_text()
        backfill=migration[migration.index('UPDATE finance_invoices SET document_snapshot='):]
        db.execute(backfill)
        before=view.document(self.b,i,self.uid)
        f.update_customer(self.b,self.c,'Later change')
        self.assertEqual(view.document(self.b,i,self.uid),before)
        db.init_schema();self.assertEqual(view.document(self.b,i,self.uid),before)

    def test_list_compact_search_status_archive_pagination(self):
        for n in range(12):self.draft(notes=str(n))
        i=f.list_finance_invoices(self.b)[0]['id'];self.edit(i,{'document_data':self.data()})
        html=self.client.get(self.url+'/receivables?section=invoices').get_data(as_text=True)
        self.assertEqual(html.count('/invoices/new?branch_id='),1)
        self.assertNotIn('<div class="fin-tool-grid">',html)
        self.assertEqual(html.count('<article class="fin-entry fin-invoice-row">'),10)
        second=self.client.get(self.url+'/receivables?section=invoices&page=2').get_data(as_text=True)
        self.assertEqual(second.count('<article class="fin-entry fin-invoice-row">'),2)
        searched=self.client.get(self.url+'/receivables?section=invoices&q=Wilson').get_data(as_text=True)
        self.assertEqual(searched.count('<article class="fin-entry fin-invoice-row">'),1)
        f.issue_finance_invoice(self.b,i);self.pay(i,250);f.archive_finance_invoice(self.b,i)
        self.assertNotIn(f'KFIN-2026-{i:06d}',self.client.get(self.url+'/receivables?section=invoices').get_data(as_text=True))
        archived=self.client.get(self.url+'/receivables?section=invoices&archived=1&status=PAID').get_data(as_text=True)
        self.assertIn(f'KFIN-2026-{i:06d}',archived)
        self.assertNotIn(f'KFIN-2026-{i:06d}',self.client.get(self.url+'/receivables?section=invoices&archived=1&status=DRAFT').get_data(as_text=True))

    def form(self,i=None):
        d=self.data();form=MultiDict({f'{g}_{k}':v for g in editor.GROUPS for k,v in d[g].items()})
        form.update(dict(customer_id=str(self.c),issue_date='2026-09-01',due_date='2026-09-30',currency='IDR',reference='PO-123',notes='',revision='0',submission_key='d'*32))
        form.add('item_description','Service');form.add('quantity','1');form.add('unit_price','1.00')
        return form

    def test_http_create_inline_edit_and_error_preserves_input(self):
        form=self.form();form['customer_id']=''
        response=self.client.post(self.url+'/invoices/new',data=form);self.assertEqual(response.status_code,303)
        i=f.list_finance_invoices(self.b)[0]['id']
        get=self.client.get(self.url+f'/invoices/{i}/edit');self.assertEqual(get.status_code,200)
        form['customer_id']=str(f.get_finance_invoice(self.b,i)['customer_id']);form['recipient_name']='Wilson Corrected'
        response=self.client.post(self.url+f'/invoices/{i}/edit',data=form);self.assertEqual(response.status_code,303)
        self.assertEqual(view.document(self.b,i)['customer']['name'],'Wilson Corrected')
        form['unit_price']='bad';response=self.client.post(self.url+f'/invoices/{i}/edit',data=form)
        self.assertEqual(response.status_code,400);self.assertIn('Wilson Corrected',response.get_data(as_text=True))

    def test_http_paid_tampering_csrf_and_other_tenant(self):
        i=self.issued();self.pay(i)
        form=self.form();response=self.client.post(self.url+f'/invoices/{i}/edit',data=form)
        self.assertEqual(response.status_code,400);self.assertIn('dikunci',response.get_data(as_text=True))
        self.assertEqual(self.client.get(f'/business/{self.other}/finance/invoices/{i}/edit').status_code,404)
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        self.assertEqual(self.client.post(self.url+f'/invoices/{i}/edit',data=form).status_code,400)
        self.assertEqual(self.client.post(self.url+'/invoices/settings',data=form).status_code,400)

    def test_revision_failure_rolls_back_every_edit(self):
        i=self.issued();before=view.document(self.b,i)
        original=db.execute
        def fail(sql,*args,**kwargs):
            if 'INSERT INTO finance_invoice_revisions' in sql:raise RuntimeError('audit unavailable')
            return original(sql,*args,**kwargs)
        with patch.object(db,'execute',side_effect=fail):
            with self.assertRaises(RuntimeError):self.edit(i,{'notes':'Should roll back'})
        self.assertEqual(view.document(self.b,i),before)

    def test_document_retries_when_revision_changes_during_read(self):
        i=self.issued();original=f.get_invoice_totals;changed=False
        def concurrent_edit(*args,**kwargs):
            nonlocal changed
            if not changed:
                changed=True
                self.edit(i,dict(document_data=self.data(),items=[dict(description='New revision',quantity=1,unit_price_minor=999)]))
            return original(*args,**kwargs)
        with patch.object(f,'get_invoice_totals',side_effect=concurrent_edit):doc=view.document(self.b,i,self.uid)
        self.assertEqual(doc['customer']['name'],'Wilson')
        self.assertEqual(doc['items'][0]['description'],'New revision')
        self.assertEqual(doc['totals']['total_minor'],999)

    def test_void_and_zero_issued_total_rejected(self):
        i=self.issued()
        with self.assertRaises(f.FinanceError):self.edit(i,{'items':[dict(description='Zero',quantity=1,unit_price_minor=0)]})
        f.void_finance_invoice(self.b,i)
        with self.assertRaises(f.FinanceError):self.edit(i,{'notes':'Void correction'})

if __name__=='__main__':unittest.main()
