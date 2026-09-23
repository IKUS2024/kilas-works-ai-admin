"""Current two-decimal ledger contracts and production assistant regressions."""
import unittest
from datetime import date
from unittest.mock import patch
import test_finance_semantic_brain as prior
import finance_service as f
import finance_branches as branches
import finance_assistant_flow as flow
import finance_conversation_brain as brain
import finance_semantics as semantics
import finance_ai_safety as safety

app=prior.app

class UpgradeTests(unittest.TestCase):
    setUp=prior.SemanticBrainTests.setUp
    ask=prior.SemanticBrainTests.ask
    follow=prior.SemanticBrainTests.follow
    model=prior.SemanticBrainTests.model
    save=prior.SemanticBrainTests.save
    propose=prior.SemanticBrainTests.propose
    edit=prior.SemanticBrainTests.edit

    def fields(self,d):return {x['key']:x['value'] for x in d['fields']}
    def invoice(self,name='Wilson'):
        customer=f.create_customer(self.b,name,actor_user_id=self.uid)
        ident=f.create_finance_invoice(self.b,customer,date.today().isoformat(),date.today().isoformat(),
            [dict(description='Jasa foto',quantity=1,unit_price_minor=200000000)],actor_user_id=self.uid)
        f.issue_finance_invoice(self.b,ident,self.uid)
        with app.app_context(),branches.scope(self.b,self.branch,self.uid):
            context=flow.seal_query(self.b,self.uid,{'last_record':{'kind':'invoice','id':ident}})
        return ident,dict(query_context=context)

    def test_partial_payment_after_invoice_never_becomes_full_settlement(self):
        ident,last=self.invoice()
        category=f.get_category(self.b,self.cat) if hasattr(f,'get_category') else next(c for c in f.list_categories(self.b,'INCOME') if c['id']==self.cat)
        text='bayar 1 juta hari ini kategori '+category['name']
        draft=self.propose(text,'record_invoice_payment',{'amount':'1 juta','date':'hari ini','category':category['name']},last)
        self.assertEqual(self.fields(draft)['amount'],'1 juta')
        self.save(draft);self.save(draft)
        self.assertEqual(f.get_invoice_totals(self.b,ident)['outstanding_minor'],100000000)
        self.assertEqual(len(f.list_invoice_payments(self.b,ident)),1)
        self.assertEqual(f.list_transactions(self.b)[0]['amount_minor'],100000000)

    def test_other_customer_payment_is_not_rebound_to_last_invoice(self):
        ident,last=self.invoice();other,_=self.invoice('Putri')
        draft=self.propose('Putri bayar 500 ribu','record_invoice_payment',{'customer':'Putri','amount':'500 ribu'},last)
        self.assertEqual(self.fields(draft)['invoice_id'],str(other))
        self.assertNotEqual(self.fields(draft)['invoice_id'],str(ident))

    def test_half_payment_uses_live_outstanding_and_review(self):
        ident,last=self.invoice()
        draft=self.propose('setengah dulu','record_invoice_payment',{'payment_fraction':'setengah dulu'},last)
        self.assertEqual(flow.minor(self.fields(draft)['amount'],'IDR'),100000000)
        self.assertEqual(f.list_invoice_payments(self.b,ident),[])
        draft=self.edit(draft,'lunas',{'settlement':'lunas'})
        self.assertEqual(flow.minor(self.fields(draft)['amount'],'IDR'),200000000)
        draft=self.edit(draft,'setengah dulu',{'payment_fraction':'setengah dulu'})
        self.assertEqual(flow.minor(self.fields(draft)['amount'],'IDR'),100000000)

    def test_name_and_compound_invoice_item_use_semantic_slots(self):
        draft=self.propose('buat customer baru','customer')
        draft=self.edit(draft,'nama customernya pacar putri',{'name':'pacar putri'})
        self.assertEqual(self.fields(draft)['name'],'pacar putri')
        saved=self.save(draft)
        invoice=self.propose('buat invoice untuk dia','invoice',{'customer_reference':'dia'},saved)
        invoice=self.edit(invoice,'beli bensin 25 ribu',{'item_description':'beli bensin','amount':'25 ribu'})
        self.assertEqual(self.fields(invoice)['item_description'],'beli bensin')
        self.assertEqual(self.fields(invoice)['amount'],'25 ribu')
        invoice=self.edit(invoice,'jatuh tempo hari ini',{'due_date':'hari ini'})
        saved=self.save(invoice)
        self.assertEqual(f.get_invoice_totals(self.b,saved['record_id'])['total_minor'],2500000)

    def test_interruption_resume_cancel_and_amount_units(self):
        draft=self.propose('catat pemgeluaran 300 ribu','create_expense',{'amount':'300 ribu'})
        self.model({'intent':'balances','slots':{}})
        answer=self.follow(draft,'saldo brp').json
        self.assertTrue(answer['keep_pending']);self.assertEqual(answer['title'],'Saldo akun')
        resumed=self.follow(draft,'yang tadi lanjut').json
        self.assertEqual(self.fields(resumed)['amount'],'300 ribu')
        question=self.edit(draft,'eh 250',{'amount':'250'})
        self.assertTrue(question['keep_pending']);self.assertIn('rupiah atau',question['message'])
        self.assertEqual(self.follow(draft,'batal').json['state'],'CANCELLED')
        self.assertEqual(f.list_transactions(self.b),[])

    def test_transaction_create_correction_and_void_use_live_ledger(self):
        category=next(c['name'] for c in f.list_categories(self.b,'EXPENSE') if c['id']==self.meal)
        draft=self.propose('catat beli susu 300 ribu dari Kas kategori '+category+' hari ini','create_expense',{'amount':'300 ribu','account':'Kas','category':category,'date':'hari ini','description':'beli susu'})
        saved=self.save(draft)
        self.assertEqual(f.list_transactions(self.b)[0]['amount_minor'],30000000)
        draft=self.propose('ubah yang tadi jadi 250 ribu','edit_transaction',{'target_reference':'yang tadi','amount':'250 ribu'},saved)
        self.save(draft)
        self.assertEqual(f.list_transactions(self.b)[0]['amount_minor'],25000000)
        draft=self.propose('hapus yang tadi','void_transaction',{'target_reference':'yang tadi'},saved)
        self.save(draft)
        self.assertEqual(sum(r['transaction_count'] for r in f.get_cash_totals(self.b,actor_user_id=self.uid)),0)

    def test_invalid_model_output_has_one_quota_limited_repair(self):
        with app.app_context(),branches.scope(self.b,self.branch,self.uid):
            valid={'intent':'recurring','slots':{'cadence':'tiap tanggal 10'}}
            with patch.object(semantics,'interpret',side_effect=[ValueError('invalid_result'),valid]) as model:
                self.assertEqual(brain.classify(self.b,self.uid,'tiap tanggal 10',{}),valid)
                self.assertEqual(model.call_count,2)
            with patch.object(semantics,'interpret',side_effect=ValueError('invalid_result')) as model:
                self.assertIsNone(brain.classify(self.b,self.uid,'tiap tanggal 10',{}))
                self.assertEqual(model.call_count,2)
            with patch.object(safety,'allow_attempt',side_effect=[True,False]),patch.object(semantics,'interpret',side_effect=ValueError('invalid_result')) as model:
                self.assertIsNone(brain.classify(self.b,self.uid,'tiap tanggal 10',{}))
                self.assertEqual(model.call_count,1)

    def test_comparison_keeps_both_relative_months(self):
        period=semantics.period_patch('bulan ini sama bulan lalu')
        self.assertEqual(len(period['ranges']),2)
        self.assertEqual(period['ranges'][0][0][:7],date.today().strftime('%Y-%m'))
        self.assertLess(period['ranges'][1][0],period['ranges'][0][0])

    def test_recurring_short_day_and_unclear_field_preserve_other_slots(self):
        category=next(c for c in f.list_categories(self.b,'EXPENSE') if c['name']=='Internet') if any(c['name']=='Internet' for c in f.list_categories(self.b,'EXPENSE')) else f.list_categories(self.b,'EXPENSE')[0]
        slots={'name':'internet','cadence':'tiap tanggal 10','date':'10','amount':'500 ribu','account':'Kas','category':category['name']}
        draft=self.propose('buat biaya internet tiap tanggal 10 sebesar 500 ribu dari Kas kategori '+category['name'],'recurring',slots)
        self.assertEqual(self.fields(draft)['cadence'],'MONTHLY')
        self.assertEqual(self.fields(draft)['date'][-2:],'10')
        self.assertEqual(self.fields(draft)['amount'],'500 ribu')
        self.save(draft)
        self.assertEqual(f.list_recurring_expenses(self.b)[0]['amount_minor'],50000000)
        self.assertEqual(f.list_transactions(self.b),[])
        slots['cadence']='tiap'
        draft=self.propose('buat biaya internet tiap tanggal 10 sebesar 500 ribu dari Kas kategori '+category['name'],'recurring',slots)
        self.assertFalse(draft['ready'])
        self.assertEqual(self.fields(draft)['amount'],'500 ribu')
        self.assertEqual(self.fields(draft)['date'][-2:],'10')
        self.assertEqual(draft['next_field'],'cadence')

    def test_recurring_edit_uses_existing_rule_without_posting(self):
        rid=f.create_recurring_expense(self.b,'Internet',50000000,self.a,self.meal,'MONTHLY',date.today().isoformat(),actor_user_id=self.uid)
        draft=self.propose('ubah biaya rutin Internet jadi 550 ribu','edit_recurring',{'target':'Internet','amount':'550 ribu'})
        self.assertTrue(draft['ready'],draft);self.save(draft);self.save(draft)
        self.assertEqual(f.get_recurring_expense(self.b,rid)['amount_minor'],55000000)
        self.assertEqual(len(f.list_recurring_expenses(self.b)),1)
        self.assertEqual(f.list_transactions(self.b),[])

    def test_invoice_edit_uses_revision_service_and_locks_paid_values(self):
        ident,last=self.invoice()
        draft=self.propose('ubah invoice yang tadi jadi 3 juta','edit_invoice',{'target_reference':'yang tadi','amount':'3 juta'},last)
        self.assertTrue(draft['ready'],draft);self.save(draft)
        self.assertEqual(f.get_invoice_totals(self.b,ident)['total_minor'],300000000)
        self.assertEqual(f.get_finance_invoice(self.b,ident)['revision'],1)
        f.record_invoice_payment(self.b,ident,100000000,date.today().isoformat(),self.a,self.cat,actor_user_id=self.uid,idempotency_key='upgrade_paid_invoice_test')
        self.model({'intent':'edit_invoice','slots':{'target_reference':'yang tadi','amount':'4 juta'}})
        response=self.client.post(self.path+'/message',json={'text':'ubah yang tadi jadi 4 juta','query_context':last['query_context']})
        self.assertEqual(response.status_code,400)
        self.assertEqual(f.get_invoice_totals(self.b,ident)['total_minor'],300000000)

    def test_budget_set_query_and_tenant_scope(self):
        category=next(c['name'] for c in f.list_categories(self.b,'EXPENSE') if c['id']==self.meal)
        draft=self.propose('anggaran '+category+' bulan ini 2 juta','set_budget',{'category':category,'month':'bulan ini','amount':'2 juta'})
        self.assertTrue(draft['ready'],draft);self.save(draft)
        answer=self.propose('lihat anggaran bulan ini','budgets',{'period':'bulan ini'})
        self.assertIn('2.000.000',str(answer['preview']))
        self.assertEqual(f.list_transactions(self.b),[])
        with app.app_context(),branches.scope(self.b,self.branch,self.uid):
            with self.assertRaises(ValueError):flow.unseal(self.b,self.uid+1000,draft['context'],'review')

    def test_named_delete_and_negative_payment_must_use_semantics(self):
        ident,last=self.invoice()
        with app.app_context(),branches.scope(self.b,self.branch,self.uid):
            previous=flow.unseal_query(self.b,self.uid,last['query_context'])
            for text in ('jangan hapus invoice','hapus invoice Wilson','belum bayar','Putri lunas','bayar 1 juta'):
                self.assertIsNone(brain.contextual_last_action(self.b,self.uid,text,previous),text)

    def test_document_account_question_can_be_interrupted_without_reupload(self):
        self.model({'intent':'balances','slots':{}})
        answer=self.client.post(self.path+'/message',json=dict(text='saldo brp',document_pending=True))
        self.assertEqual(answer.status_code,200);self.assertTrue(answer.json['keep_pending'])
        self.model({'intent':'select_document_account','slots':{'account':'Kas'}})
        choice=self.client.post(self.path+'/message',json=dict(text='pakai Kas',document_pending=True))
        self.assertEqual(choice.json,dict(kind='document_selection',account_id=str(self.a)))

    def test_new_actions_reject_aggregate_writes_and_cross_branch_tokens(self):
        draft=self.propose('buat customer Wilson','customer',{'name':'Wilson'})
        with app.app_context(),branches.scope(self.b,None,self.uid):
            choice=brain.start(self.b,self.uid,'set_budget',{}, {})
            self.assertEqual(choice['kind'],'branch_choice')
            with self.assertRaises(ValueError):flow.unseal(self.b,self.uid,draft['context'],'review')
        with branches.scope(self.b,self.branch,self.uid):
            other=branches.create_branch(self.b,'Other',self.uid)
        with app.app_context(),branches.scope(self.b,other,self.uid):
            with self.assertRaises(ValueError):flow.unseal(self.b,self.uid,draft['context'],'review')

    def test_multi_item_invoice_requires_item_selection(self):
        ident,last=self.invoice()
        import finance_invoice_editor as editor
        editor.edit(self.b,ident,dict(items=[dict(description='Foto',quantity=1,unit_price_minor=100000000),
            dict(description='Video',quantity=1,unit_price_minor=100000000)]),actor_user_id=self.uid)
        choice=self.propose('ubah yang tadi jadi 3 juta','edit_invoice',{'target_reference':'yang tadi','amount':'3 juta'},last)
        self.assertEqual(choice['kind'],'clarification')
        draft=self.propose('item 2','continue_command',{'item_number':'2'},choice)
        self.assertTrue(draft['ready'],draft);self.save(draft)
        self.assertEqual([i['unit_price_minor'] for i in f.list_invoice_items(self.b,ident)],[100000000,300000000])

    def test_budget_changed_after_preview_requires_new_review(self):
        category=next(c['name'] for c in f.list_categories(self.b,'EXPENSE') if c['id']==self.meal)
        draft=self.propose('anggaran '+category+' bulan ini 2 juta','set_budget',{'category':category,'month':'bulan ini','amount':'2 juta'})
        with branches.scope(self.b,self.branch,self.uid):
            f.set_monthly_budget(self.b,date.today().strftime('%Y-%m'),self.meal,300000000,actor_user_id=self.uid)
        self.assertEqual(self.follow(draft,'oke').status_code,400)
        self.assertEqual(f.list_monthly_budgets(self.b,date.today().strftime('%Y-%m'))[0]['amount_minor'],300000000)

if __name__=='__main__':unittest.main()
