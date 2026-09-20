"""Production-shaped conversational journeys; disposable tenant and mocked provider."""
import base64
import io
import re
import unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch
import test_finance_assistant_inline as prior
import finance_assistant_flow as flow
import finance_draft_fields as contracts
import finance_service as f
import finance_branches as branches
import db
import finance_ai_safety as safety

app=prior.app

class ConversationTests(unittest.TestCase):
    setUp=prior.InlineTests.setUp
    message=prior.InlineTests.message
    confirm=prior.InlineTests.confirm
    revise=prior.InlineTests.revise
    snapshot=prior.InlineTests.snapshot
    model=prior.InlineTests.model
    race=prior.InlineTests.race
    document=prior.InlineTests.document
    receipt_model=prior.InlineTests.receipt_model
    def follow(self,draft,text,confirmation=None):
        return self.client.post(self.path+'/message',json=dict(text=text,context=draft['context'],confirmation=confirmation or draft.get('token')))
    def values(self,response):
        self.assertEqual(response.status_code,200,response.text)
        return {v['key']:v['value'] for v in response.json['fields']}
    def test_customer_real_three_turn_sequence_and_retry(self):
        before=len(f.list_customers(self.b))
        r=self.message('tambah customer wilson')
        r=self.follow(r.json,'nomor teleponya 082213039137')
        self.assertEqual(self.values(r)['phone'],'082213039137')
        r=self.follow(r.json,'emailnya wilson@gmail.com')
        self.assertEqual(self.values(r)['email'],'wilson@gmail.com')
        for _ in range(2):
            saved=self.follow(r.json,'oke');self.assertEqual(saved.status_code,200,saved.text)
        rows=[x for x in f.list_customers(self.b) if x['name']=='wilson']
        self.assertEqual(len(f.list_customers(self.b)),before+1)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['phone'],'082213039137')
        self.assertEqual(rows[0]['email'],'wilson@gmail.com');self.http.assert_not_called()
    def test_all_phone_variants_are_server_parsed(self):
        for label in ('nomor teleponya','nomor teleponnya','nomornya','no hp','nomor hpnya','hp nya','whatsappnya','whatsapnya','wa nya'):
            safety._RATE.clear()
            with self.subTest(label=label):
                r=self.follow(self.message('tambah customer Wilson').json,label+' 082213039137')
                self.assertEqual(self.values(r)['phone'],'082213039137')
        self.http.assert_not_called()
    def test_customer_name_notes_variants_optional_fields(self):
        for label in ('nama jadi','namanya','atas nama'):
            r=self.follow(self.message('tambah customer Wilson').json,label+' Wilson Wijaya')
            self.assertEqual(self.values(r)['name'],'Wilson Wijaya')
        r=self.follow(r.json,'catatannya customer lama')
        self.assertEqual(self.values(r)['notes'],'customer lama')
        self.assertTrue(self.message('tambah customer Nama Saja').json['ready'])
    def test_every_yes_word_confirms_only_reviewed_draft(self):
        for word in ('iya','ya','oke','ok','sip','benar','betul','lanjut','simpan','catat'):
            safety._RATE.clear()
            r=self.message('tambah customer Customer '+word)
            saved=self.follow(r.json,word)
            self.assertEqual(saved.status_code,200,saved.text);self.assertEqual(saved.json['state'],'CONFIRMED')
    def test_cancel_words_never_write(self):
        before=self.snapshot()
        for word in ('batal','ga jadi','jangan'):
            r=self.follow(self.message('tambah customer Wilson').json,word)
            self.assertEqual(r.json['state'],'CANCELLED')
        self.assertEqual(before,self.snapshot())
    def test_old_confirmation_not_valid_for_new_revision(self):
        first=self.message('tambah customer Wilson').json
        updated=self.follow(first,'nomornya 082213039137').json
        r=self.follow(updated,'oke',first['token'])
        self.assertEqual(r.status_code,400)
        self.assertFalse([c for c in f.list_customers(self.b) if c['name']=='Wilson'])
    def test_income_bca_confirm_replay_and_optional_fields_persist(self):
        bca=f.create_account(self.b,'BCA',actor_user_id=self.uid)
        r=self.message('tambahin pendapatan jasa foto 2200000 hari ini')
        r=self.follow(r.json,'pakai BCA');self.assertEqual(self.values(r)['account_id'],str(bca))
        r=self.follow(r.json,'pihak terkait Putri');self.assertEqual(self.values(r)['counterparty_name'],'Putri')
        r=self.follow(r.json,'catatannya shooting produk')
        for _ in range(2):self.assertEqual(self.follow(r.json,'oke').status_code,200)
        rows=f.list_transactions(self.b);self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['account_id'],rows[0]['amount_minor'],rows[0]['counterparty_name'],rows[0]['description']),
                         (bca,2200000,'Putri','shooting produk'))
    def test_followup_amount_date_category_combined_account(self):
        bca=f.create_account(self.b,'BCA',actor_user_id=self.uid)
        r=self.message('pengeluaran makan 200 ribu')
        r=self.follow(r.json,'pakai BCA kategori Bensin')
        self.assertEqual(self.values(r)['category_id'],str(self.gas))
        self.assertEqual(self.values(r)['account_id'],str(bca))
        for words,expected in [('ubah jadi 300 ribu','300 ribu'),('nominalnya 450 ribu','450 ribu')]:
            r=self.follow(r.json,words);self.assertEqual(self.values(r)['amount'],expected)
        r=self.follow(r.json,'tanggalnya kemarin')
        self.assertEqual(self.values(r)['date'],(date.today()-timedelta(days=1)).isoformat())
        self.assertEqual(self.values(r)['amount'],'450 ribu')
    def test_recurring_vendor_date_and_no_actual_expense(self):
        f.create_account(self.b,'BCA',actor_user_id=self.uid)
        cat=f.create_category(self.b,'EXPENSE','Internet',actor_user_id=self.uid)
        r=self.message('setiap bulan bayar internet 500 ribu ke Telkom tanggal 10')
        self.assertEqual(self.values(r)['counterparty_name'],'Telkom')
        self.assertEqual(self.values(r)['name'],'internet')
        r=self.follow(r.json,'pakai BCA kategori Internet')
        self.assertTrue(r.json['ready'],r.json)
        for _ in range(2):saved=self.follow(r.json,'oke');self.assertEqual(saved.status_code,200,saved.text)
        self.assertIn('Belum ada pengeluaran aktual',saved.json['message'])
        self.assertEqual(len(f.list_recurring_expenses(self.b)),1);self.assertEqual(f.list_transactions(self.b),[])
    def test_recurring_end_date_does_not_replace_first_due_or_amount(self):
        r=self.message('setiap bulan bayar makan 500 ribu tanggal 10')
        old=self.values(r).copy()
        r=self.follow(r.json,'sampai 2027-01-01')
        self.assertEqual(self.values(r)['date'],old['date']);self.assertEqual(self.values(r)['amount'],old['amount'])
        self.assertEqual(self.values(r)['end_on'],'2027-01-01')
    def test_invoice_create_review_exactly_once_no_issue_no_ledger(self):
        f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        r=self.message('buat invoice Wilson jasa foto 2 juta jatuh tempo 30 september')
        self.assertTrue(r.json['ready'],r.json)
        before=len(f.list_finance_invoices(self.b))
        for _ in range(2):
            saved=self.follow(r.json,'oke');self.assertEqual(saved.status_code,200,saved.text)
        rows=f.list_finance_invoices(self.b)
        self.assertEqual(len(rows),before+1);self.assertEqual(rows[0]['status'],'DRAFT')
        items=f.list_invoice_items(self.b,rows[0]['id'])
        self.assertEqual((items[0]['description'],items[0]['quantity'],items[0]['unit_price_minor']),('jasa foto',1,2000000))
        self.assertEqual(f.list_transactions(self.b),[])
    def test_invoice_concurrent_confirmation_and_conflict(self):
        f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        r=self.message('buat invoice Wilson jasa foto 2 juta jatuh tempo 30 september').json
        def write():
            with app.app_context():return flow.confirm(self.b,self.uid,r['token'])
        rows=self.race([write,write]);self.assertEqual(rows[0],rows[1])
        revised=self.follow(r,'ubah jadi 3 juta')
        self.assertEqual(self.follow(revised.json,'oke').status_code,400)
    def test_invoice_issue_separate_reviewed_confirmation(self):
        f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        r=self.message('buat invoice Wilson jasa foto 2 juta jatuh tempo 30 september')
        saved=self.follow(r.json,'oke').json
        row=f.get_finance_invoice(self.b,saved['record_id'])
        r=self.message('terbitkan '+row['invoice_number'])
        self.assertEqual(r.json['title'],'Terbitkan invoice')
        self.assertEqual(f.get_finance_invoice(self.b,row['id'])['status'],'DRAFT')
        self.assertEqual(self.follow(r.json,'oke').status_code,200)
        self.assertEqual(f.get_finance_invoice(self.b,row['id'])['status'],'ISSUED')
    def test_scoped_piutang_and_customer_search(self):
        customer=f.create_customer(self.b,'Wilson',phone='082213039137',actor_user_id=self.uid)
        other=f.create_customer(self.b,'Other Customer',actor_user_id=self.uid)
        for ident,amount in [(customer,2000000),(other,3000000)]:
            invoice=f.create_finance_invoice(self.b,ident,date.today().isoformat(),date.today().isoformat(),[dict(description='Jasa',quantity=1,unit_price_minor=amount)],actor_user_id=self.uid)
            f.issue_finance_invoice(self.b,invoice,self.uid)
        before=self.snapshot()
        r=self.message('piutang Wilson berapa?');self.assertEqual(r.json['kind'],'answer');self.assertIn('2.000.000',r.text);self.assertNotIn('3.000.000',r.text)
        self.assertEqual(self.message('siapa yang belum bayar?').json['kind'],'answer')
        self.assertIn('082213039137',self.message('nomor Wilson apa?').text)
        self.assertEqual(before,self.snapshot())
    def test_all_branches_reads_and_write_branch_choice(self):
        other=branches.create_branch(self.b,'BSD',self.uid)
        path=self.path+'?branch_id=all'
        self.assertEqual(self.client.get(path).status_code,200)
        read=self.client.post(self.path+'/message?branch_id=all',json={'text':'saldo berapa?'})
        self.assertEqual(read.status_code,200,read.text)
        r=self.client.post(self.path+'/message?branch_id=all',json={'text':'tambah pengeluaran 200 ribu'})
        self.assertEqual(r.json['kind'],'branch_choice');self.assertIn(other,[r['id'] for r in r.json['branches']])
        self.assertEqual(f.list_transactions(self.b),[])
    def test_all_branch_dashboard_offers_readonly_assistant(self):
        page=self.client.get(f'/business/{self.b}/finance?branch_id=all')
        self.assertEqual(page.status_code,200)
        self.assertIn(f'/business/{self.b}/finance/assistant?branch_id=all',page.text)
    def test_unknown_invoice_number_does_not_return_other_invoices(self):
        response=self.message('status invoice KFIN-2099-999999?')
        self.assertEqual(response.json['kind'],'answer')
        self.assertIn('belum dikenali',response.json['message'])
    def test_invoice_manual_field_contract(self):
        html=(Path(__file__).resolve().parents[1]/'templates/finance_invoice_form.html').read_text()
        for key in contracts.INVOICE:
            self.assertIn('name="'+key+'"',html) if key!='items' else self.assertIn('item_description',html)
        f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        draft=self.message('buat invoice Wilson jasa foto 2 juta jatuh tempo 30 september')
        data=__import__('finance_assistant_invoice').invoice_data(self.b,self.uid,self.values(draft))
        self.assertEqual(set(data),set(contracts.INVOICE))
    def test_currency_document_context_filters_bank_accounts(self):
        usd=f.create_account(self.b,'BOFA',currency='USD',actor_user_id=self.uid)
        self.model({'workflow':'BANK_STATEMENT','currency':'USD'})
        recognized=self.client.post(self.path+'/recognize',data={'sources':(io.BytesIO(self.raw),'a.png'),'text':''})
        token=recognized.json['document_context']
        self.model(self.result)
        r=self.document('BANK_STATEMENT',document_context=token)
        self.assertEqual(r.status_code,200,r.text);self.assertIn('BOFA',r.text)
        self.assertEqual(f.list_transactions(self.b),[])
        r=self.document('BANK_STATEMENT',document_context=token,account_id=str(self.a))
        self.assertEqual(r.status_code,400)
    def test_model_patch_accepts_raw_values_never_ids_or_action(self):
        draft=self.message('tambah customer Wilson').json
        for malicious in ({'updates':{'customer_id':'123'}},{'updates':{'action':'create_income'}},{'updates':{'phone':'999'}}):
            self.model(malicious);r=self.follow(draft,'tolong isi kontaknya dong 082213039137')
            self.assertEqual(self.values(r)['phone'],'')
        self.model({'updates':{'phone':'082213039137'}})
        r=self.follow(draft,'tolong isi kontaknya dong 082213039137')
        self.assertEqual(self.values(r)['phone'],'082213039137')
    def test_unknown_account_does_not_silently_replace(self):
        r=self.message('pengeluaran makan 200 ribu')
        old=self.values(r)['account_id']
        r=self.follow(r.json,'pakai rekening tidak dikenal')
        self.assertEqual(self.values(r)['account_id'],old);self.assertIn('belum jelas',r.json['message'])
    def test_payment_partial_then_full_retry_no_duplicates(self):
        customer=f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        ident=f.create_finance_invoice(self.b,customer,date.today().isoformat(),date.today().isoformat(),
                                      [dict(description='Jasa',quantity=1,unit_price_minor=2000000)],actor_user_id=self.uid)
        f.issue_finance_invoice(self.b,ident,self.uid)
        number=f.get_finance_invoice(self.b,ident)['invoice_number']
        for _ in range(2):
            draft=self.message('Wilson bayar invoice '+number+' 1 juta')
            if not draft.json['ready']:draft=self.revise(draft.json,category_id=str(self.cat))
            self.assertTrue(draft.json['ready'],draft.json)
            for retry in range(2):
                saved=self.follow(draft.json,'oke');self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(len(f.list_invoice_payments(self.b,ident)),2)
        self.assertEqual(f.get_invoice_totals(self.b,ident)['outstanding_minor'],0)
        self.assertIn('Sisa tagihan: Rp0',saved.json['message'])
    def test_invoice_issue_replay_and_changed_draft_rejected(self):
        f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        draft=self.message('buat invoice Wilson jasa foto 2 juta jatuh tempo 30 september')
        saved=self.follow(draft.json,'oke').json
        row=f.get_finance_invoice(self.b,saved['record_id'])
        issue=self.message('terbitkan '+row['invoice_number']).json
        db.execute('UPDATE finance_invoices SET notes=? WHERE id=?',('changed',row['id']))
        self.assertEqual(self.follow(issue,'oke').status_code,400)
        issue=self.message('terbitkan '+row['invoice_number']).json
        for _ in range(2):self.assertEqual(self.follow(issue,'oke').status_code,200)
    def test_reference_fields_cannot_cross_branch(self):
        draft=self.message('pengeluaran makan 200 ribu').json
        other=branches.create_branch(self.b,'BSD',self.uid)
        response=self.client.post(self.path+f'/message?branch_id={other}',json=dict(text='oke',context=draft['context'],confirmation=draft['token']))
        self.assertEqual(response.status_code,400)
        self.assertEqual(f.list_transactions(self.b),[])
    def test_finance_domain_refusal(self):
        r=self.message('cuaca hari ini bagaimana?');self.assertEqual(r.json['kind'],'answer');self.assertIn('khusus',r.text)
    def test_manual_contracts(self):
        root=Path(__file__).resolve().parents[1]/'templates'
        mappings=[('finance_receivables.html',contracts.CUSTOMER),('finance_dashboard.html',contracts.TRANSACTION),
                  ('finance_operations.html',contracts.RECURRING)]
        for filename,keys in mappings:
            html=(root/filename).read_text()
            for key in keys:self.assertIn('name="'+key+'"',html)
        for text,keys in [('tambah customer Wilson',contracts.CUSTOMER),('pengeluaran makan 200 ribu',contracts.TRANSACTION),('tiap bulan bayar makan 200 ribu tanggal 10',contracts.RECURRING)]:
            actual=set(self.values(self.message(text)))
            actual.add('direction');actual.update({'occurred_on','next_due_on'} if 'date' in actual else set())
            self.assertTrue(set(keys)<=actual)


    def test_colloquial_balance_and_customer_typo_queries(self):
        f.create_customer(self.b,'Wilson',phone='082200001111',actor_user_id=self.uid)
        balance=self.message('saldo gw berapa sekarang')
        self.assertEqual(balance.status_code,200,balance.text)
        self.assertEqual(balance.json['title'],'Saldo akun')
        self.assertNotIn('belum dikenali',balance.json['message'].lower())
        customer=self.message('cek nama costumer Wilsom')
        self.assertEqual(customer.status_code,200,customer.text)
        self.assertIn('Wilson',customer.text)
        self.assertIn('082200001111',customer.text)

    def test_all_time_report_and_readonly_followup_context(self):
        f.create_transaction(self.b,'INCOME',600000,self.a,self.cat,'2026-06-01',actor_user_id=self.uid)
        f.create_transaction(self.b,'INCOME',400000,self.a,self.cat,date.today().isoformat(),actor_user_id=self.uid)
        first=self.message('laproan pemasukan keseluruhan')
        self.assertEqual(first.status_code,200,first.text)
        self.assertIn('1.000.000',first.text)
        self.assertIn('Semua waktu',first.text)
        self.assertIn('query_context',first.json)
        follow=self.client.post(self.path+'/message',json={'text':'semuanya berapa dri bulan awal','query_context':first.json['query_context']})
        self.assertEqual(follow.status_code,200,follow.text)
        self.assertIn('1.000.000',follow.text)
        unrelated=self.client.post(self.path+'/message',json={'text':'cuaca gimana?','query_context':follow.json['query_context']})
        self.assertEqual(unrelated.status_code,200,unrelated.text)
        self.assertIn('khusus',unrelated.text)

    def test_readonly_followup_can_change_metric_without_losing_period(self):
        f.create_transaction(self.b,'INCOME',900000,self.a,self.cat,'2026-06-01',actor_user_id=self.uid)
        f.create_transaction(self.b,'EXPENSE',200000,self.a,self.meal,'2026-06-02',actor_user_id=self.uid)
        first=self.message('laporan pemasukan keseluruhan')
        follow=self.client.post(self.path+'/message',json={'text':'kalau pengeluarannya?','query_context':first.json['query_context']})
        self.assertEqual(follow.status_code,200,follow.text)
        self.assertIn('200.000',follow.text)
        self.assertNotIn('900.000',follow.text)

    def test_currency_names_are_understood_for_read_filters(self):
        self.assertEqual(flow.currency_hint('saldo dolar Singapura'),'SGD')
        self.assertEqual(flow.currency_hint('saldo 50 euro'),'EUR')
        self.assertEqual(flow.currency_hint('saldo 200 ringgit'),'MYR')
        self.assertEqual(flow.currency_hint('saldo 100 pound'),'GBP')
        self.assertEqual(flow.currency_hint('saldo 1000 yen'),'JPY')
        self.assertEqual(flow.currency_hint('saldo 500 yuan'),'CNY')
        self.assertEqual(flow.currency_hint('saldo 100 baht'),'THB')


    def test_english_july_and_month_aliases_are_understood(self):
        f.create_transaction(self.b,'INCOME',61108839,self.a,self.cat,'2026-07-31',actor_user_id=self.uid)
        for wording in ('pendapatan kita berapa bulan july','pemasukan bulan jul','laporan pendapatan Juli 2026'):
            response=self.message(wording)
            self.assertEqual(response.status_code,200,response.text)
            self.assertIn('61.108.839',response.text)
            self.assertIn('2026-07',response.text)

    def test_recurring_inventory_question_is_not_generic_empty_report(self):
        empty=self.message('biaya rutin kita ada?')
        self.assertEqual(empty.status_code,200,empty.text)
        self.assertEqual(empty.json['title'],'Biaya rutin')
        self.assertIn('Belum ada biaya rutin aktif',empty.json['message'])
        f.create_recurring_expense(self.b,'Internet',500000,self.a,self.meal,'MONTHLY',
                                   date.today().isoformat(),actor_user_id=self.uid)
        found=self.message('biaya rutin kita ada?')
        self.assertEqual(found.status_code,200,found.text)
        self.assertIn('Internet',found.text)
        self.assertIn('500.000',found.text)

if __name__=='__main__':unittest.main()
