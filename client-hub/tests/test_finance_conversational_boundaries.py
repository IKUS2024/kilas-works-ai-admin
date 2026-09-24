"""Production typo/slang requests must retain intent, scope and reviewed writes."""
import unittest
from datetime import date
import requests
import test_finance_semantic_agent as prior
import finance_assistant_flow as flow
import finance_ai_safety as safety
import finance_service as f
import finance_branches as branches
import finance_semantics as semantics

app=prior.app


class ConversationalBoundaryTests(unittest.TestCase):
    setUp=prior.SemanticAgentTests.setUp
    ask=prior.SemanticAgentTests.ask
    follow=prior.SemanticAgentTests.follow
    values=prior.SemanticAgentTests.values
    model=prior.SemanticAgentTests.model
    snapshot=prior.SemanticAgentTests.snapshot
    save=prior.SemanticAgentTests.save
    invoice=prior.SemanticAgentTests.invoice
    tx=prior.SemanticAgentTests.tx
    revise=prior.SemanticAgentTests.revise

    def test_screenshot_customer_list_uses_semantic_scope(self):
        f.create_customer(self.b,'Daniel',actor_user_id=self.uid)
        f.create_customer(self.b,'Putri',actor_user_id=self.uid)
        import finance_entitlements
        finance_entitlements.start_trial(self.other,self.other_uid)
        f.create_customer(self.other,'Hidden',actor_user_id=self.other_uid)
        before=self.snapshot()
        self.model({'intent':'customers','slots':{}})
        answer=self.ask('jita punya customer namanya siapa aja')
        self.assertEqual(answer['title'],'Data pelanggan')
        self.assertIn('Daniel',str(answer['preview']))
        self.assertIn('Putri',str(answer['preview']))
        self.assertNotIn('Hidden',str(answer['preview']))
        self.assertEqual(self.http.call_count,1)
        self.assertEqual(before,self.snapshot())

    def test_existing_list_phrases_and_english_plurals(self):
        f.create_customer(self.b,'Daniel',actor_user_id=self.uid)
        for text in ('customer kita siapa aja','pelanggan siapa aja','customers kita siapa aja'):
            with self.subTest(text=text):
                answer=self.ask(text)
                self.assertEqual(answer['title'],'Data pelanggan')
                self.assertIn('Daniel',str(answer['preview']))
        self.http.assert_called()

    def test_semantic_list_scope_applies_across_entity_types(self):
        for noun,title in (('customer','Data pelanggan'),('proyek','Proyek'),('rekening','Rekening'),
                           ('kategori','Kategori'),('cabang','Cabang')):
            with self.subTest(noun=noun):
                safety._RATE.clear()
                self.model({'intent':{'rekening':'accounts','customer':'customers','proyek':'projects','kategori':'categories','cabang':'branches'}[noun],'slots':{}})
                answer=self.ask(noun+' namanya apa aja yang tersedia?')
                self.assertEqual(answer['title'],title,answer)
                self.assertNotIn('belum jelas',answer['message'])

    def test_named_multiword_customer_is_not_broadened(self):
        f.create_customer(self.b,'Daniel',actor_user_id=self.uid)
        self.model({'intent':'customers','slots':{'customer':'Nobody Here'}})
        answer=self.ask('customer Nobody Here ada?')
        self.assertIn('belum jelas',answer['message'])
        self.assertNotIn('Daniel',str(answer['preview']))

    def test_uncertain_or_unavailable_scope_keeps_safe_clarification(self):
        f.create_customer(self.b,'Daniel',actor_user_id=self.uid)
        for failure in ('unknown','unavailable','fabricated'):
            with self.subTest(failure=failure):
                safety._RATE.clear()
                self.http.side_effect=None
                self.model({'intent':'unknown','slots':{}} if failure!='fabricated' else
                           {'intent':'customers','slots':{'customer':'Daniel'}})
                if failure=='unavailable':self.http.side_effect=requests.Timeout()
                answer=self.ask('customer Nobody Here ada?')
                self.assertEqual(answer['kind'],'clarification')
                self.assertNotIn('Daniel',str(answer))

    def test_screenshot_write_variants_start_amount_first_today(self):
        f.create_account(self.b,'BOFA',currency='USD',actor_user_id=self.uid)
        before=self.snapshot()
        for text in ('buatkan pemgeluaran untuk hari ini','bikinin pengeluaran hari ini',
                     'tambahkan pengeluaran','tolong buatin expense hari ini',
                     'masukin pengeluran hari ini','tambahin pemasukkan hari ini'):
            with self.subTest(text=text):
                safety._RATE.clear()
                draft=self.ask(text)
                self.assertEqual(draft['kind'],'review',draft)
                self.assertEqual(draft['next_field'],'amount')
                self.assertEqual(draft['message'],'Nominalnya berapa?')
                self.assertEqual(next(x['value'] for x in draft['fields'] if x['key']=='date'),date.today().isoformat())
                self.assertFalse(draft['ready'])
                self.assertNotIn('token',draft)
                self.assertEqual(self.follow(draft,'batal').json['state'],'CANCELLED')
        self.assertEqual(before,self.snapshot())
        self.http.assert_called()

    def test_amount_account_category_then_confirm_once(self):
        f.create_account(self.b,'BCA',actor_user_id=self.uid)
        before=self.snapshot()
        draft=self.ask('buatkan pemgeluaran untuk hari ini')
        # Exercise all missing fields, including an explicitly cleared suggestion.
        draft=self.revise(draft,category_id='').json
        unchanged=self.follow(draft,'oke').json
        self.assertEqual(unchanged['next_field'],'amount')
        draft=self.follow(draft,'200 ribu').json
        self.assertEqual(draft.get('next_field'),'account_id',draft)
        account=next(a for a in f.list_accounts(self.b) if a['id']==self.a)
        draft=self.follow(draft,'pakai '+account['name']).json
        self.assertEqual(draft['next_field'],'category_id')
        draft=self.follow(draft,'kategori Makan').json
        self.assertTrue(draft['ready'],draft)
        self.assertEqual(before,self.snapshot())
        self.save(draft);self.save(draft)
        rows=f.list_transactions(self.b)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['amount_minor'],20000000)
        self.assertEqual(rows[0]['account_id'],self.a)
        self.assertEqual(rows[0]['occurred_on'],date.today().isoformat())

    def test_typo_write_draft_remains_resumable_after_report(self):
        draft=self.ask('buatkan pemgeluaran untuk hari ini')
        before=self.snapshot()
        answer=self.follow(draft,'laporan pengeluaran').json
        self.assertTrue(answer['keep_pending'])
        self.assertEqual(answer['kind'],'answer')
        draft=self.follow(draft,'200 ribu').json
        self.assertEqual(next(x['value'] for x in draft['fields'] if x['key']=='amount'),'200 ribu')
        self.assertEqual(self.follow(draft,'batal').json['state'],'CANCELLED')
        self.assertEqual(before,self.snapshot())

    def test_productive_verb_forms_route_all_creation_adapters(self):
        cases=(('bikinin pemasukan','create_income',None),('buatin pengeluaran','create_expense',None),
               ('masukin customer Revenue Labs','customer',None),('tambahin invoice','invoice',None),
               ('buatkan biaya rutin','recurring',None),('masukkan rekening BCA','command','create_account'),
               ('bikinkan kategori Transport','command','create_category'),('tambahin cabang BSD','command','create_branch'),
               ('buatkan FX','command','exchange'),('add invoices','invoice',None))
        before=self.snapshot()
        for text,action,operation in cases:
            with self.subTest(text=text):
                safety._RATE.clear()
                draft=self.ask(text)
                self.assertEqual(draft['kind'],'review',draft)
                with app.app_context(),branches.scope(self.b,self.branch,self.uid):
                    context=flow.unseal(self.b,self.uid,draft['context'],'review')
                self.assertEqual(context['action'],action)
                self.assertEqual(context.get('operation'),operation)
                self.assertEqual(self.follow(draft,'batal').json['state'],'CANCELLED')
        self.assertEqual(before,self.snapshot())
        self.http.assert_called()

    def test_normalization_preserves_literal_customer_name(self):
        for verb in ('buatkan','bikinin','tambahin','masukin','create'):
            with self.subTest(verb=verb):
                self.assertTrue(semantics.normalize(verb+' customer Revenue Expense Buatkan').endswith('Revenue Expense Buatkan'))

    def test_payment_issue_correction_and_void_keep_review_boundary(self):
        invoice=self.invoice();draft_invoice=self.invoice(issued=False)
        transaction=self.tx(5000000)
        before=self.snapshot()
        for text,title in (('tambahkan payment invoice '+invoice['invoice_number'],'Pembayaran invoice'),
                           ('issue invoice '+draft_invoice['invoice_number'],'Terbitkan invoice'),
                           ('koreksi transaksi '+str(transaction),'Koreksi transaksi'),
                           ('void transaksi '+str(transaction),'Batalkan transaksi')):
            with self.subTest(text=text):
                safety._RATE.clear()
                draft=self.ask(text)
                self.assertEqual(draft['kind'],'review',draft)
                self.assertEqual(draft['title'],title)
                self.assertEqual(self.follow(draft,'batal').json['state'],'CANCELLED')
        self.assertEqual(before,self.snapshot())

    def test_unfamiliar_write_verb_with_date_uses_semantics(self):
        self.model({'intent':'create_expense','slots':{'date':'hari ini'}})
        before=self.snapshot()
        draft=self.ask('buattkn pemgeluaran hari ini')
        self.assertEqual(draft['kind'],'review')
        self.assertEqual(draft['title'],'Pengeluaran')
        self.assertEqual(draft['next_field'],'amount')
        self.assertEqual(before,self.snapshot())
        self.assertEqual(self.http.call_count,1)

    def test_unknown_temporal_intent_does_not_default_to_report(self):
        self.http.side_effect=requests.Timeout()
        before=self.snapshot()
        answer=self.ask('buattkn pemgeluaran hari ini')
        self.assertEqual(answer['kind'],'clarification')
        self.assertEqual(before,self.snapshot())

    def test_unfamiliar_noun_uses_semantics_after_strong_write(self):
        self.model({'intent':'create_income','slots':{}})
        draft=self.ask('bikinin uang masuk dong')
        self.assertEqual(draft['title'],'Pemasukan')
        self.assertEqual(draft['kind'],'review')
        self.assertEqual(f.list_transactions(self.b),[])

    def test_new_write_escapes_previous_entity_question(self):
        previous=self.ask('cari customer Nobody')
        answer=self.ask('buatkan pemgeluaran hari ini',previous)
        self.assertEqual(answer['kind'],'review')
        self.assertEqual(answer['title'],'Pengeluaran')

    def test_capabilities_are_current_and_do_not_claim_money_transfers(self):
        before=self.snapshot()
        answer=self.ask('kamu bisa apa aja')
        self.assertEqual(answer['kind'],'answer')
        for capability in ('pemasukan','pengeluaran','pelanggan','rekening','kategori','cabang','tagihan',
                           'invoice','pembayaran','piutang','laporan','proyek','penukaran mata uang',
                           'struk','mutasi bank','ringkasan','sebelum konfirmasi'):
            self.assertIn(capability,answer['message'])
        self.assertNotIn('transfer uang',answer['message'])
        self.assertEqual(before,self.snapshot())


if __name__=='__main__':unittest.main()
