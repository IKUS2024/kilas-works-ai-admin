"""Production journeys with real scoped services; only the language provider is mocked."""
import json
import unittest
from datetime import date
from unittest.mock import patch
import test_finance_semantic_brain as prior
import finance_assistant_flow as flow
import finance_service as f
import finance_branches as branches
import finance_ai_safety as safety
import db

app=prior.app

class LiveConversationTests(unittest.TestCase):
    setUp=prior.SemanticBrainTests.setUp
    ask=prior.SemanticBrainTests.ask
    follow=prior.SemanticBrainTests.follow
    model=prior.SemanticBrainTests.model
    save=prior.SemanticBrainTests.save
    propose=prior.SemanticBrainTests.propose
    edit=prior.SemanticBrainTests.edit
    snapshot=prior.SemanticBrainTests.snapshot
    race=prior.prior.SemanticAgentTests.race

    def fields(self,r):return {x['key']:x['value'] for x in r['fields']}
    def invoice(self,name='Wilson',amount=800000,status='ISSUED',customer=None):
        customer=customer or f.create_customer(self.b,name,notes='belum bayar 800 ribu',actor_user_id=self.uid)
        ident=f.create_finance_invoice(self.b,customer,date.today().isoformat(),date.today().isoformat(),
            [dict(description='Jasa desain',quantity=1,unit_price_minor=amount)],actor_user_id=self.uid)
        if status!='DRAFT':f.issue_finance_invoice(self.b,ident,self.uid)
        if status=='VOID':f.void_finance_invoice(self.b,ident,self.uid)
        return f.get_finance_invoice(self.b,ident,self.uid)

    def payment(self,text='atas nama Wilson lunas',slots=None,previous=None):
        return self.propose(text,'record_invoice_payment',slots or {'customer':'Wilson','settlement':'lunas'},previous)

    def complete_payment(self,draft):
        safety._RATE.clear()
        if not self.fields(draft)['date']:draft=self.edit(draft,'hari ini',{'date':'hari ini'})
        if not self.fields(draft)['category_id']:
            draft=self.edit(draft,'kategori '+f.list_categories(self.b,'INCOME')[0]['name'],{'category':f.list_categories(self.b,'INCOME')[0]['name']})
        return draft

    def test_customer_create_confirm_then_implicit_invoice_issue_and_combined_answer(self):
        draft=self.propose('buat customer Irvan','customer',{'name':'Irvan'})
        saved=self.save(draft)
        invoice=self.propose('nah buatkan invoice dan terbitkan','invoice',{'issue':'terbitkan'},saved)
        self.assertEqual(self.fields(invoice)['customer_id'],str(saved['record_id']))
        self.assertEqual(invoice['next_field'],'item_description')
        invoice=self.edit(invoice,'beli bensin 25 ribu',{'item_description':'beli bensin','amount':'25 ribu'})
        values=self.fields(invoice)
        self.assertEqual((values['item_description'],values['amount']),('beli bensin','25 ribu'))
        self.assertNotIn('item2_description',values)
        invoice=self.edit(invoice,'jatuh tempo 2 desember',{'due_date':'2 desember'})
        self.assertTrue(invoice['ready'],invoice)
        done=self.save(invoice);self.save(invoice)
        row=f.get_finance_invoice(self.b,done['record_id'])
        self.assertEqual(row['status'],'ISSUED')
        self.assertEqual(len(f.list_invoice_items(self.b,row['id'])),1)
        self.assertEqual(f.list_transactions(self.b),[])

    def test_existing_item_can_change_and_only_explicit_add_creates_second(self):
        self.invoice()
        draft=self.propose('buat invoice Wilson','invoice',{'customer':'Wilson'})
        draft=self.edit(draft,'untuk beli bensin',{'item_description':'beli bensin'})
        draft=self.edit(draft,'bensinnya 25 ribu',{'amount':'25 ribu'})
        self.assertNotIn('item2_description',self.fields(draft))
        draft=self.edit(draft,'tambah item oli 50 ribu',{'item_description':'oli','amount':'50 ribu'},'add_invoice_item')
        self.assertEqual(self.fields(draft)['item2_description'],'oli')
        draft=self.edit(draft,'terbitkan sekalian',{'issue':'terbitkan'})
        with app.app_context(),branches.scope(self.b,self.branch,self.uid):
            self.assertTrue(flow.unseal(self.b,self.uid,draft['context'],'review')['issue_after'])

    def test_read_entity_survives_pronoun_rename_void_and_stale_note(self):
        invoice=self.invoice('Putri')
        first=self.propose('utangnya Putri berapa','receivables',{'customer':'Putri'})
        self.assertIn('800.000',str(first['preview']))
        db.execute('UPDATE finance_customers SET name=? WHERE id=?',('Putri Baru',invoice['customer_id']))
        second=self.propose('sisanya berapa','continue_query',previous=first)
        self.assertIn('Putri Baru',str(second['preview']))
        f.void_finance_invoice(self.b,invoice['id'],self.uid)
        third=self.propose('utang dia berapa','receivables',{'customer_reference':'dia'},second)
        self.assertIn('tidak ada piutang aktif untuk Putri Baru',third['message'])
        self.assertIn('dibatalkan/direset',third['message'])
        self.assertNotIn('800.000',str(third));self.assertNotIn('800 ribu',str(third))
        fourth=self.propose('kalau yang belum lunas','continue_query',previous=third)
        self.assertIn('Putri Baru',fourth['message'])

    def test_removed_customer_reference_does_not_rebind_same_name(self):
        saved=self.save(self.propose('customer Irvan','customer',{'name':'Irvan'}))
        db.execute('DELETE FROM finance_customers WHERE id=?',(saved['record_id'],))
        f.create_customer(self.b,'Irvan',actor_user_id=self.uid)
        result=self.propose('buat invoice atas nama dia','invoice',{'customer_reference':'dia'},saved)
        self.assertEqual(result['kind'],'clarification')
        self.assertIn('tidak tersedia',result['message'])
        self.assertEqual(f.list_finance_invoices(self.b),[])

    def test_query_deactivated_customer_never_broadens_filter(self):
        putri=self.invoice('Putri');self.invoice('Wilson')
        answer=self.propose('utang Putri berapa','receivables',{'customer':'Putri'})
        db.execute('UPDATE finance_customers SET is_active=FALSE WHERE id=?',(putri['customer_id'],))
        answer=self.propose('sisanya berapa','continue_query',previous=answer)
        self.assertIn('tidak aktif',answer['message']);self.assertNotIn('Wilson',str(answer))

    def test_deleted_account_disappears_from_choices_and_signed_draft_refreshes(self):
        a=f.create_account(self.b,'BCA',actor_user_id=self.uid)
        draft=self.propose('pengeluaran 25 ribu pakai BCA','create_expense',{'amount':'25 ribu','account':'BCA'})
        db.execute('DELETE FROM finance_accounts WHERE id=?',(a,))
        refreshed=self.edit(draft,'kategori Bensin',{'category':'Bensin'})
        options=next(x['options'] for x in refreshed['fields'] if x['key']=='account_id')
        self.assertFalse(any(str(a)==x['value'] for x in options))
        self.assertEqual(self.fields(refreshed)['account_id'],'')
        self.assertEqual(f.list_transactions(self.b),[])

    def test_lunas_full_payment_review_oke_paid_and_single_ledger(self):
        invoice=self.invoice();before=self.snapshot()
        draft=self.payment()
        self.assertEqual(self.fields(draft)['invoice_id'],str(invoice['id']))
        self.assertEqual(self.fields(draft)['amount'],'800000')
        self.assertEqual(draft['next_field'],'date');self.assertEqual(before,self.snapshot())
        draft=self.complete_payment(draft)
        with patch.object(f,'record_invoice_payment',wraps=f.record_invoice_payment) as canonical:
            self.save(draft);self.save(draft)
            self.assertEqual(canonical.call_count,2)
        self.assertEqual(f.get_finance_invoice(self.b,invoice['id'])['status'],'PAID')
        self.assertEqual(f.get_invoice_totals(self.b,invoice['id'])['outstanding_minor'],0)
        self.assertEqual(len(f.list_invoice_payments(self.b,invoice['id'])),1)
        self.assertEqual(len(f.list_transactions(self.b)),1)
        self.assertEqual(f.list_transactions(self.b)[0]['amount_minor'],800000)

    def test_multiple_open_invoices_require_choice_and_do_not_select_other_customer(self):
        first=self.invoice();second=self.invoice(customer=first['customer_id'],amount=500000);other=self.invoice('Putri')
        draft=self.payment('Wilson lunas')
        self.assertEqual(draft['next_field'],'invoice_id')
        choices=next(x['options'] for x in draft['fields'] if x['key']=='invoice_id')
        self.assertEqual({x['value'] for x in choices},{str(first['id']),str(second['id'])})
        self.assertTrue(all('sisa Rp' in x['label'] for x in choices))
        selected=self.follow(draft,second['invoice_number']).json
        self.assertEqual(self.fields(selected)['amount'],'500000')
        self.assertEqual(f.list_transactions(self.b),[])

    def test_only_void_invoice_no_payment_no_revive(self):
        invoice=self.invoice(status='VOID');before=self.snapshot()
        result=self.payment('Wilson lunas')
        self.assertEqual(result['kind'],'answer');self.assertIn('tidak ada piutang aktif',result['message'])
        self.assertIn('dibatalkan/direset',result['message'])
        self.assertEqual(before,self.snapshot());self.assertEqual(f.get_finance_invoice(self.b,invoice['id'])['status'],'VOID')

    def test_partial_payment_uses_canonical_status_and_cash_once(self):
        invoice=self.invoice()
        draft=self.payment('Wilson bayar 300 ribu',{'customer':'Wilson','amount':'300 ribu'})
        draft=self.complete_payment(draft);self.save(draft);self.save(draft)
        self.assertEqual(f.get_finance_invoice(self.b,invoice['id'])['status'],'PARTIALLY_PAID')
        self.assertEqual(f.get_invoice_totals(self.b,invoice['id'])['outstanding_minor'],500000)
        self.assertEqual([t['amount_minor'] for t in f.list_transactions(self.b)],[300000])

    def test_void_between_payment_review_and_confirmation_no_write(self):
        invoice=self.invoice();draft=self.complete_payment(self.payment())
        f.void_finance_invoice(self.b,invoice['id'],self.uid)
        result=self.follow(draft,'oke')
        self.assertEqual(result.status_code,200,result.text)
        self.assertIn('tidak ada piutang aktif',result.json['message'])
        self.assertEqual(f.list_transactions(self.b),[])

    def test_changed_outstanding_requires_new_review_and_oke(self):
        invoice=self.invoice();draft=self.complete_payment(self.payment())
        f.record_invoice_payment(self.b,invoice['id'],300000,date.today().isoformat(),self.a,self.cat,actor_user_id=self.uid,idempotency_key='external_payment_12345')
        result=self.follow(draft,'oke').json
        self.assertEqual(result['kind'],'review');self.assertEqual(self.fields(result)['amount'],'500000')
        self.assertEqual(len(f.list_transactions(self.b)),1)
        self.save(result);self.save(result)
        self.assertEqual(f.get_finance_invoice(self.b,invoice['id'])['status'],'PAID')
        self.assertEqual(sum(t['amount_minor'] for t in f.list_transactions(self.b)),800000)

    def test_create_issue_paid_compound_order_replay_and_exact_cash(self):
        f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        draft=self.propose('buat invoice Wilson 800 ribu untuk jasa desain, dia sudah bayar','invoice',
            {'customer':'Wilson','amount':'800 ribu','item_description':'jasa desain','settlement':'sudah bayar'})
        draft=self.edit(draft,'jatuh tempo hari ini',{'due_date':'hari ini'})
        draft=self.edit(draft,'dibayar hari ini',{'date':'hari ini'})
        if not self.fields(draft)['category_id']:draft=self.edit(draft,'kategori '+f.list_categories(self.b,'INCOME')[0]['name'],{'category':f.list_categories(self.b,'INCOME')[0]['name']})
        self.assertTrue(draft['ready'],draft);self.assertEqual(f.list_finance_invoices(self.b),[])
        ordered=[]
        with patch.object(f,'create_finance_invoice',side_effect=lambda *a,**k:(ordered.append('create'),create(*a,**k))[1]) as c, \
             patch.object(f,'issue_finance_invoice',side_effect=lambda *a,**k:(ordered.append('issue'),issue(*a,**k))[1]), \
             patch.object(f,'record_invoice_payment',side_effect=lambda *a,**k:(ordered.append('payment'),pay(*a,**k))[1]):
            saved=self.save(draft)
        self.assertEqual(ordered,['create','issue','payment'])
        self.save(draft)
        row=f.get_finance_invoice(self.b,saved['record_id']);self.assertEqual(row['status'],'PAID')
        self.assertEqual(len(f.list_finance_invoices(self.b)),1);self.assertEqual(len(f.list_transactions(self.b)),1)
        self.assertEqual(f.get_invoice_totals(self.b,row['id'])['outstanding_minor'],0)

    def test_compound_rolls_back_all_operations_on_payment_failure(self):
        f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        draft=self.propose('invoice Wilson jasa desain 800 ribu sudah bayar hari ini','invoice',
            {'customer':'Wilson','amount':'800 ribu','item_description':'jasa desain','settlement':'sudah bayar','due_date':'hari ini','date':'hari ini'})
        if not self.fields(draft)['category_id']:draft=self.edit(draft,'kategori '+f.list_categories(self.b,'INCOME')[0]['name'],{'category':f.list_categories(self.b,'INCOME')[0]['name']})
        with patch.object(f,'record_invoice_payment',side_effect=ValueError('payment_failure')):
            self.assertEqual(self.follow(draft,'oke').status_code,400)
        self.assertEqual(f.list_finance_invoices(self.b),[]);self.assertEqual(f.list_transactions(self.b),[])

    def test_inactive_recurring_and_changed_balances_are_live(self):
        rule=f.create_recurring_expense(self.b,'Sewa',500000,self.a,self.meal,'MONTHLY',date.today().isoformat(),actor_user_id=self.uid)
        first=self.propose('biaya rutin aktif','recurring_list')
        self.assertIn('Sewa',str(first))
        db.execute('UPDATE finance_recurring_expenses SET is_active=FALSE WHERE id=?',(rule,))
        second=self.propose('yang aktif','continue_query',previous=first)
        self.assertNotIn('Sewa',str(second));self.assertIn('Belum ada biaya rutin aktif',second['message'])
        balance=self.propose('saldo berapa','balances')
        f.create_transaction(self.b,'INCOME',123000,self.a,self.cat,date.today().isoformat(),actor_user_id=self.uid)
        updated=self.propose('sekarang berapa','continue_query',previous=balance)
        self.assertNotEqual(balance['preview'],updated['preview'])

    def test_concurrent_partial_confirmation_posts_once(self):
        invoice=self.invoice()
        draft=self.complete_payment(self.payment('Wilson bayar 300 ribu',{'customer':'Wilson','amount':'300 ribu'}))
        def write():
            with app.app_context(),branches.scope(self.b,self.branch,self.uid):
                return flow.confirm(self.b,self.uid,draft['token'])['record_id']
        outcomes=self.race([write,write])
        self.assertEqual(outcomes[0],outcomes[1]);self.assertEqual(outcomes[0][0],'ok')
        self.assertEqual(len(f.list_transactions(self.b)),1)
        self.assertEqual(f.get_invoice_totals(self.b,invoice['id'])['outstanding_minor'],500000)

    def test_payment_review_tenant_branch_and_inactive_customer_boundaries(self):
        invoice=self.invoice();draft=self.complete_payment(self.payment())
        other=branches.create_branch(self.b,'BSD',self.uid)
        # Cross-branch signed context is rejected before any model or write.
        response=self.client.post(self.path+'/message?branch_id='+str(other),json=dict(text='oke',context=draft['context'],confirmation=draft['token']))
        self.assertEqual(response.status_code,400)
        response=self.client.post('/business/'+str(self.other)+'/finance/assistant/confirm',json={'token':draft['token'],'confirm':True})
        self.assertIn(response.status_code,(400,403,404))
        db.execute('UPDATE finance_customers SET is_active=FALSE WHERE id=?',(invoice['customer_id'],))
        self.assertEqual(self.follow(draft,'oke').status_code,400)
        self.assertEqual(f.list_transactions(self.b),[])

    def test_old_confirmation_cannot_authorize_added_issue_or_payment(self):
        f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        draft=self.propose('invoice Wilson jasa desain 800 ribu jatuh tempo hari ini','invoice',
            {'customer':'Wilson','amount':'800 ribu','item_description':'jasa desain','due_date':'hari ini'})
        updated=self.edit(draft,'terbitkan sekalian',{'issue':'terbitkan'})
        self.assertEqual(self.follow(updated,'oke',draft['token']).status_code,400)
        self.assertEqual(f.list_finance_invoices(self.b),[])

    def test_refreshed_same_partial_review_keeps_payment_idempotency_key(self):
        invoice=self.invoice()
        draft=self.complete_payment(self.payment('Wilson bayar 300 ribu',{'customer':'Wilson','amount':'300 ribu'}))
        with app.app_context(),branches.scope(self.b,self.branch,self.uid):
            refreshed=flow.review(self.b,self.uid,flow.unseal(self.b,self.uid,draft['context'],'review'))
        self.save(draft);self.save(refreshed)
        self.assertEqual(len(f.list_transactions(self.b)),1)
        self.assertEqual(f.get_invoice_totals(self.b,invoice['id'])['outstanding_minor'],500000)

    def test_lunas_can_be_corrected_to_partial_and_same_customer_read_after_payment(self):
        self.invoice();draft=self.complete_payment(self.payment())
        draft=self.edit(draft,'eh baru bayar 300 ribu',{'amount':'300 ribu'})
        self.assertEqual(self.fields(draft)['amount'],'300 ribu')
        saved=self.save(draft)
        answer=self.propose('utang dia berapa','receivables',{'customer_reference':'dia'},saved)
        self.assertIn('500.000',str(answer['preview']))

    def test_new_customer_query_switches_pronoun_and_unknown_does_not_reuse_old_person(self):
        self.invoice('Putri',100000);self.invoice('Wilson',800000)
        first=self.propose('utang Putri berapa','receivables',{'customer':'Putri'})
        second=self.propose('utang Wilson berapa','receivables',{'customer':'Wilson'},first)
        third=self.propose('utang dia berapa','receivables',{'customer_reference':'dia'},second)
        self.assertIn('800.000',str(third['preview']));self.assertNotIn('100.000',str(third['preview']))
        unknown=self.propose('utang Nobody berapa','receivables',{'customer':'Nobody'},third)
        result=self.propose('utang dia berapa','receivables',{'customer_reference':'dia'},unknown)
        self.assertEqual(result['kind'],'clarification');self.assertNotIn('800.000',str(result))

    def test_partial_over_current_outstanding_is_re_reviewed_without_adjusting_amount_silently(self):
        invoice=self.invoice()
        draft=self.complete_payment(self.payment('Wilson bayar 600 ribu',{'customer':'Wilson','amount':'600 ribu'}))
        f.record_invoice_payment(self.b,invoice['id'],300000,date.today().isoformat(),self.a,self.cat,
            actor_user_id=self.uid,idempotency_key='external_partial_1234')
        result=self.follow(draft,'oke').json
        self.assertEqual(result['kind'],'review');self.assertFalse(result['ready'])
        self.assertEqual(self.fields(result)['amount'],'')
        self.assertEqual(len(f.list_transactions(self.b)),1)


    def test_legacy_signed_payment_keeps_original_idempotency_protocol(self):
        import uuid
        invoice=self.invoice()
        with app.app_context(),branches.scope(self.b,self.branch,self.uid):
            prepared=flow.operator.prepare_fields(self.b,self.uid,'record_invoice_payment',dict(account_id=self.a,category_id=self.cat,
                date=date.today().isoformat(),invoice_id=invoice['id'],currency='IDR',amount_minor=300000,description=''))
            context=dict(action='record_invoice_payment',nonce=uuid.uuid4().hex,service_token=prepared['token'],values=dict(
                amount='300000',currency='IDR',date=date.today().isoformat(),account_id=str(self.a),category_id=str(self.cat),invoice_id=str(invoice['id']),description=''))
            token=flow.seal(self.b,self.uid,'confirm',context)
            first=flow.confirm(self.b,self.uid,token)
            self.assertEqual(first['record_id'],flow.confirm(self.b,self.uid,token)['record_id'])
            rereview=flow.review(self.b,self.uid,context)
            self.assertEqual(rereview['kind'],'answer');self.assertIn('sudah tercatat',rereview['message'])
        self.assertEqual(len(f.list_transactions(self.b)),1)


create=f.create_finance_invoice
issue=f.issue_finance_invoice
pay=f.record_invoice_payment
if __name__=='__main__':unittest.main()
