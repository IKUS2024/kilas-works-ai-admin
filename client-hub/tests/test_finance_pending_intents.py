"""Pending drafts can be interrupted without changing or confirming their values."""
import unittest
from unittest.mock import patch
import requests
import test_finance_semantic_agent as prior
import finance_assistant_flow as flow
import finance_ai_safety as safety
import finance_service as f
import finance_branches as branches

app=prior.app

class PendingIntentTests(unittest.TestCase):
    setUp=prior.SemanticAgentTests.setUp
    ask=prior.SemanticAgentTests.ask
    follow=prior.SemanticAgentTests.follow
    values=prior.SemanticAgentTests.values
    model=prior.SemanticAgentTests.model
    snapshot=prior.SemanticAgentTests.snapshot
    tx=prior.SemanticAgentTests.tx
    invoice=prior.SemanticAgentTests.invoice
    save=prior.SemanticAgentTests.save
    revise=prior.SemanticAgentTests.revise

    def interrupt(self,draft,text,query_context=None):
        payload=dict(text=text,context=draft['context'],confirmation=draft.get('token'))
        if query_context:payload['query_context']=query_context
        response=self.client.post(self.path+'/message',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json['kind'],'answer',response.json)
        self.assertTrue(response.json.get('keep_pending'),response.json)
        self.assertNotIn('token',response.json)
        self.assertNotIn('context',response.json)
        return response.json

    def test_expense_report_then_amount_updates_same_nonce(self):
        self.tx(90000,direction='EXPENSE')
        draft=self.ask('pengeluaran makan')
        self.assertEqual(draft['next_field'],'amount')
        before=self.snapshot()
        answer=self.interrupt(draft,'laporan pengeluaran')
        self.assertIn('90.000',str(answer['preview']))
        self.assertEqual(before,self.snapshot())
        response=self.client.post(self.path+'/message',json=dict(text='200 ribu',context=draft['context'],confirmation=None,query_context=answer['query_context']))
        self.assertEqual(self.values(response)['amount'],'200 ribu')
        with app.app_context():
            old=flow.unseal(self.b,self.uid,draft['context'],'review')
            new=flow.unseal(self.b,self.uid,response.json['context'],'review')
        self.assertEqual(old['nonce'],new['nonce'])
        self.assertEqual(old['action'],new['action'])
        self.assertEqual(before,self.snapshot())
        self.save(response.json)
        self.assertEqual(len(f.list_transactions(self.b)),2)
        self.http.assert_called()

    def test_recurring_date_can_be_interrupted_by_balance(self):
        draft=self.ask('tambah biaya rutin 2 juta untuk AI')
        draft=self.follow(draft,'bulanan').json
        self.assertEqual(draft['next_field'],'date')
        before=self.snapshot()
        answer=self.interrupt(draft,'saldo gw berapa?')
        self.assertEqual(answer['title'],'Saldo akun')
        continued=self.follow(draft,'tanggal 25')
        self.assertTrue(self.values(continued)['date'].endswith('-25'))
        self.assertEqual(before,self.snapshot())
        self.assertEqual(self.follow(continued.json,'batal').json['state'],'CANCELLED')
        self.assertEqual(f.list_recurring_expenses(self.b),[])

    def test_customer_phone_can_be_interrupted_by_receivables(self):
        invoice=self.invoice()
        draft=self.ask('tambah customer Putri')
        with app.app_context():
            context=flow.unseal(self.b,self.uid,draft['context'],'review')
            context['awaiting']='phone'
            draft['context']=flow.seal(self.b,self.uid,'review',context)
        before=self.snapshot()
        answer=self.interrupt(draft,'siapa yang belum bayar?')
        self.assertIn(invoice['invoice_number'],str(answer['preview']))
        continued=self.follow(draft,'nomornya 082213039137')
        self.assertEqual(self.values(continued)['phone'],'082213039137')
        self.assertEqual(self.values(continued)['name'],'Putri')
        self.assertEqual(before,self.snapshot())
        self.save(continued.json)
        self.assertEqual(next(c for c in f.list_customers(self.b) if c['name']=='Putri')['phone'],'082213039137')

    def test_invoice_income_query_then_original_due_date(self):
        f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        self.tx(600000)
        draft=self.ask('buat invoice Wilson jasa foto 2 juta')
        before=self.snapshot()
        answer=self.interrupt(draft,'cek pemasukan bulan ini')
        self.assertIn('600.000',str(answer['preview']))
        continued=self.follow(draft,'jatuh tempo 30 september')
        self.assertEqual(self.values(continued)['amount'],'2 juta')
        self.assertTrue(continued.json['ready'],continued.json)
        self.assertEqual(before,self.snapshot())
        self.save(continued.json)
        self.assertEqual(len(f.list_finance_invoices(self.b)),1)
        self.assertEqual(len(f.list_transactions(self.b)),1)

    def test_queries_interrupt_every_other_adapter_and_allow_cancel(self):
        invoice=self.invoice();transaction=self.tx(100000)
        usd=f.create_account(self.b,'BOFA',currency='USD',actor_user_id=self.uid)
        commands=['pemasukan','bayar invoice '+invoice['invoice_number'],
                  'tambah rekening BCA','tambah kategori Transport','buat cabang',
                  'catat FX','koreksi transaksi '+str(transaction),
                  'terbitkan '+self.invoice(issued=False)['invoice_number']]
        for command in commands:
            safety._RATE.clear()
            with self.subTest(command=command):
                draft=self.ask(command)
                self.assertEqual(draft['kind'],'review',draft)
                before=self.snapshot()
                answer=self.interrupt(draft,'laporan pengeluaran')
                self.assertIn('query_context',answer)
                self.assertEqual(self.follow(draft,'batal').json['state'],'CANCELLED')
                self.assertEqual(before,self.snapshot())

    def test_direct_draft_edits_still_work_without_provider(self):
        bca=f.create_account(self.b,'BCA',actor_user_id=self.uid)
        transport=next(c['id'] for c in f.list_categories(self.b,'EXPENSE') if c['name']=='Transport')
        draft=self.ask('pengeluaran makan')
        for text,key,value in [('200 ribu','amount','200 ribu'),('pakai BCA','account_id',str(bca)),
                               ('kategori transport','category_id',str(transport))]:
            response=self.follow(draft,text);self.assertEqual(self.values(response)[key],value);draft=response.json
        self.assertEqual(f.list_transactions(self.b),[])
        self.save(draft);self.http.assert_called()

    def test_semantic_read_without_report_keywords_is_not_a_slot(self):
        self.tx(123000)
        draft=self.ask('pengeluaran makan')
        before=self.snapshot()
        self.model({'intent':'balances','slots':{}})
        result=self.interrupt(draft,'duit kita masih nyisa segimana nih')
        self.assertEqual(result['title'],'Saldo akun')
        self.assertEqual(before,self.snapshot())
        self.assertEqual(self.http.call_count,2)
        self.assertEqual(self.values(self.follow(draft,'200 ribu'))['amount'],'200 ribu')

    def test_new_write_replaces_uncommitted_draft_without_cancel_gate(self):
        draft=self.ask('pengeluaran makan')
        before=self.snapshot()
        self.model({'intent':'create_income','slots':{'amount':'3 juta'}})
        response=self.client.post(self.path+'/message',json=dict(
            text='catat pemasukan 3 juta',context=draft['context'],confirmation=draft.get('token')))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json['kind'],'review',response.json)
        self.assertEqual(response.json['title'],'Pemasukan')
        self.assertIn('Draft sebelumnya tidak disimpan',response.json['message'])
        self.assertEqual(self.values(response)['amount'],'3 juta')
        self.assertEqual(before,self.snapshot())

    def test_semantic_continuation_can_fill_a_literal_free_text_slot(self):
        draft=self.ask('buat cabang')
        self.model({'intent':'continue_draft','slots':{'name':'BSD'}})
        result=self.follow(draft,'BSD')
        self.assertEqual(self.values(result)['name'],'BSD')
        self.assertEqual(self.http.call_count,2)
        self.assertFalse(any(r['name']=='BSD' for r in branches.list_branches(self.b,self.uid)))

    def test_query_followups_preserve_period_then_draft_can_resume(self):
        self.tx(210000,'2026-07-01',direction='EXPENSE')
        self.tx(320000,'2026-08-01',direction='EXPENSE')
        draft=self.ask('pengeluaran makan')
        july=self.interrupt(draft,'laporan pengeluaran juli 2026')
        august=self.interrupt(draft,'kalau agustus?',july['query_context'])
        self.assertIn('320.000',str(august['preview']))
        self.assertNotIn('210.000',str(august['preview']))
        self.assertEqual(self.values(self.follow(draft,'200 ribu'))['amount'],'200 ribu')

    def test_ready_draft_query_is_readonly_then_confirmation_is_idempotent(self):
        draft=self.ask('pengeluaran makan 200 ribu')
        before=self.snapshot()
        self.interrupt(draft,'saldo gw berapa?')
        self.assertEqual(before,self.snapshot())
        self.save(draft);self.save(draft)
        self.assertEqual(len(f.list_transactions(self.b)),1)

    def test_uncertain_or_unavailable_interpreter_preserves_free_text_slot(self):
        draft=self.ask('buat cabang')
        for output in ({'intent':'unknown','slots':{}},{'intent':'confirm','slots':{}},
                       {'intent':'continue_draft','slots':{'name':'invented'}},
                       {'intent':'continue_draft','slots':{'account_id':'123'}}):
            safety._RATE.clear();self.model(output)
            result=self.follow(draft,'tolong urus semuanya')
            self.assertTrue(result.json['keep_pending']);self.assertNotIn('context',result.json)
        safety._RATE.clear();self.http.side_effect=requests.Timeout('PRIVATE')
        result=self.follow(draft,'tolong urus semuanya')
        self.assertTrue(result.json['keep_pending']);self.assertNotIn('context',result.json)
        self.assertNotIn('PRIVATE',result.text)
        self.http.side_effect=None

    def test_query_does_not_bypass_scope_or_token_validation(self):
        draft=self.ask('pengeluaran makan')
        payload=dict(text='laporan pengeluaran',context=draft['context'],confirmation=None)
        foreign=self.client.post(f'/business/{self.other}/finance/assistant/message',json=payload)
        self.assertEqual(foreign.status_code,404)
        tampered=self.client.post(self.path+'/message',json=dict(payload,context=draft['context']+'x'))
        self.assertEqual(tampered.status_code,400)
        branch=branches.create_branch(self.b,'BSD',self.uid)
        wrong=self.client.post(self.path+'/message?branch_id='+str(branch),json=payload)
        self.assertEqual(wrong.status_code,400)
        bad_read=self.client.post(self.path+'/message',json=dict(payload,query_context='tampered'))
        self.assertEqual(bad_read.status_code,400)
        self.assertEqual(f.list_transactions(self.b),[])

    def test_customer_query_containing_name_label_does_not_rename_draft(self):
        f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        draft=self.ask('tambah customer Putri')
        result=self.interrupt(draft,'cek nama customer Wilson')
        self.assertIn('Wilson',str(result['preview']))
        self.save(draft)
        self.assertTrue(any(c['name']=='Putri' for c in f.list_customers(self.b)))

    def test_independent_direction_fragment_uses_semantics_before_amount(self):
        draft=self.ask('pengeluaran makan')
        self.model({'intent':'new_command','slots':{}})
        result=self.interrupt(draft,'pemasukan 2 juta')
        self.assertIn('batal',result['message'])
        self.assertEqual(self.http.call_count,2)
        self.assertEqual(self.values(self.follow(draft,'200 ribu'))['amount'],'200 ribu')

    def test_screenshot_balance_phrase_does_not_invent_an_account(self):
        self.tx(123000)
        self.model({'intent':'balances','slots':{}})
        result=self.ask('berapa saldo kita weh ?')
        self.assertEqual(result['title'],'Saldo akun')
        self.assertIn('123.000',str(result['preview']))
        with app.app_context(),branches.scope(self.b,self.branch,self.uid):
            plan=flow.unseal_query(self.b,self.uid,result['query_context'])['plan']
        self.assertNotIn('account',plan)
        self.assertEqual(self.http.call_count,1)

    def test_screenshot_balance_phrase_also_interrupts_pending_draft(self):
        draft=self.ask('pengeluaran makan')
        before=self.snapshot()
        self.model({'intent':'balances','slots':{}})
        result=self.interrupt(draft,'berapa saldo kita weh ?')
        self.assertEqual(result['title'],'Saldo akun')
        self.assertEqual(before,self.snapshot())
        self.assertEqual(self.values(self.follow(draft,'200 ribu'))['amount'],'200 ribu')

    def test_balance_semantics_can_extract_a_literal_account_name(self):
        self.model({'intent':'balances','slots':{'account':'BankTakAda'}})
        result=self.ask('berapa saldo punya kita di BankTakAda weh?')
        self.assertEqual(result['title'],'Rekening')
        with app.app_context(),branches.scope(self.b,self.branch,self.uid):
            plan=flow.unseal_query(self.b,self.uid,result['query_context'])['plan']
        self.assertEqual(plan['account'],'BankTakAda')
        self.assertEqual(plan['awaiting'],'account')

    def test_balance_semantic_failure_never_silently_broadens_scope(self):
        self.tx(987000)
        self.http.side_effect=requests.Timeout('PRIVATE')
        result=self.ask('berapa saldo BankTakAda weh?')
        self.assertEqual(result['kind'],'clarification')
        self.assertNotIn('987.000',str(result))
        self.assertNotIn('PRIVATE',str(result))
        self.http.side_effect=None

    def test_explicit_unknown_account_is_not_removed_by_semantics(self):
        self.model({'intent':'balances','slots':{'account':'BankTakAda'}})
        result=self.ask('saldo rekening BankTakAda berapa?')
        self.assertEqual(result['title'],'Rekening')
        self.http.assert_called()

    def test_known_balance_account_and_native_currency_are_preserved(self):
        usd=f.create_account(self.b,'BOFA',currency='USD',opening_balance_minor=10000,actor_user_id=self.uid)
        self.tx(987000)
        result=self.ask('berapa saldo BOFA kita weh?')
        self.assertIn('100.00',str(result['preview']))
        self.assertNotIn('987.000',str(result['preview']))
        self.http.assert_called()

    def test_unresolved_account_can_be_interrupted_by_a_new_complete_query(self):
        self.tx(421000)
        first=self.ask('saldo rekening BankTakAda berapa?')
        self.assertEqual(first['title'],'Rekening')
        second=self.ask('laporan pemasukan bulan ini',first)
        self.assertIn('421.000',str(second['preview']))
        with app.app_context(),branches.scope(self.b,self.branch,self.uid):
            plan=flow.unseal_query(self.b,self.uid,second['query_context'])['plan']
        self.assertNotIn('account',plan)
        self.assertNotIn('awaiting',plan)
        self.http.assert_called()

    def test_unresolved_account_still_accepts_a_genuine_entity_answer(self):
        self.tx(421000)
        account=f.get_account(self.b,self.a)['name']
        first=self.ask('saldo rekening BankTakAda berapa?')
        second=self.ask(account,first)
        self.assertEqual(second['title'],'Saldo akun')
        self.assertIn('421.000',str(second['preview']))
        self.http.assert_called()

    def test_assistant_html_uses_content_version_and_is_never_cached(self):
        import hashlib
        from pathlib import Path
        import routes_finance
        response=self.client.get(self.path)
        self.assertEqual(response.status_code,200)
        self.assertIn('no-store',response.headers['Cache-Control'])
        version=hashlib.sha256((Path(app.static_folder)/'finance_assistant.js').read_bytes()).hexdigest()[:16]
        self.assertIn('finance_assistant.js?v='+version,response.text)
        self.assertNotIn('semantic-finance-5',response.text)
        asset=self.client.get('/static/finance_assistant.js?v='+version)
        self.assertEqual(asset.status_code,200)
        self.assertIn(b'data.keep_pending',asset.data)
        self.assertIn('no-cache',asset.headers['Cache-Control'])
        with patch.object(routes_finance.Path,'read_bytes',return_value=b'changed-assistant-content'):
            updated=self.client.get(self.path)
        self.assertNotIn('finance_assistant.js?v='+version,updated.text)
        self.assertIn('finance_assistant.js?v='+hashlib.sha256(b'changed-assistant-content').hexdigest()[:16],updated.text)

    def test_query_does_not_refresh_an_expired_draft(self):
        draft=self.ask('pengeluaran makan')
        with app.app_context(),patch('itsdangerous.timed.TimestampSigner.get_timestamp',return_value=10**10):
            with self.assertRaisesRegex(ValueError,'invalid_draft'):
                flow.follow_up(self.b,self.uid,draft['context'],'laporan pengeluaran')

if __name__=='__main__':unittest.main()
