"""Real conversations and accounting invariants, against the same manual services."""
import unittest
from datetime import date,timedelta
from unittest.mock import patch
import test_finance_conversation_agent as prior
import finance_assistant_flow as flow
import finance_service as f
import finance_branches as branches
import finance_semantics as semantics
import db
import repo

app=prior.app


class SemanticAgentTests(unittest.TestCase):
    setUp=prior.ConversationTests.setUp
    message=prior.ConversationTests.message
    follow=prior.ConversationTests.follow
    values=prior.ConversationTests.values
    revise=prior.ConversationTests.revise
    snapshot=prior.ConversationTests.snapshot
    model=prior.ConversationTests.model
    race=prior.ConversationTests.race

    def ask(self,text,previous=None):
        payload={'text':text}
        if previous and previous.get('query_context'):payload['query_context']=previous['query_context']
        r=self.client.post(self.path+'/message',json=payload)
        self.assertEqual(r.status_code,200,r.text)
        return r.json

    def save(self,draft):
        self.assertTrue(draft['ready'],draft)
        r=self.follow(draft,'oke');self.assertEqual(r.status_code,200,r.text)
        return r.json

    def tx(self,amount,when=None,direction='INCOME',account=None,currency='IDR',**extra):
        return f.create_transaction(self.b,direction,amount,account or self.a,self.cat if direction=='INCOME' else self.meal,
            when or date.today().isoformat(),currency=currency,actor_user_id=self.uid,**extra)

    def invoice(self,amount=2000000,issued=True,issue=None,due=None):
        customer=f.create_customer(self.b,'Wilson Wijaya',actor_user_id=self.uid)
        ident=f.create_finance_invoice(self.b,customer,issue or date.today().isoformat(),due or date.today().isoformat(),
            [dict(description='Jasa',quantity=1,unit_price_minor=amount)],actor_user_id=self.uid)
        if issued:f.issue_finance_invoice(self.b,ident,self.uid)
        return f.get_finance_invoice(self.b,ident,self.uid)

    def test_actual_all_time_spans_years_and_excludes_void(self):
        self.tx(350000,'2023-01-01');self.tx(250000)
        void=self.tx(9900000);f.void_transaction(self.b,void,self.uid)
        answer=self.ask('pendapatan keseluruhan dari awal?')
        self.assertIn('Rp600.000',str(answer['preview']));self.assertNotIn('9.900.000',str(answer))
        self.assertEqual(f.get_cash_totals(self.b,actor_user_id=self.uid)[0]['transaction_count'],2)

    def test_context_replaces_month_then_metric_then_alltime(self):
        self.tx(120000,'2026-07-02');self.tx(230000,'2026-08-02');self.tx(340000,'2026-08-03','EXPENSE')
        july=self.ask('pendapatan july?');self.assertIn('120.000',str(july))
        august=self.ask('kalau agustus?',july);self.assertIn('230.000',str(august['preview']));self.assertNotIn('120.000',str(august['preview']))
        expense=self.ask('kalau pengeluarannya?',august);self.assertIn('340.000',str(expense['preview']));self.assertNotIn('230.000',str(expense['preview']))
        alltime=self.ask('semuanya dari awal?',expense);self.assertIn('Semua waktu',str(alltime['preview']))
        julyagain=self.ask('bulan july aja',alltime);self.assertNotIn('340.000',str(julyagain['preview']))

    def test_currency_followup_replaces_old_currency(self):
        usd=f.create_account(self.b,'BOFA',currency='USD',actor_user_id=self.uid)
        self.tx(210000);self.tx(3456,account=usd,currency='USD')
        first=self.ask('pemasukan IDR bulan ini?')
        second=self.ask('yang USD?',first)
        self.assertIn('34.56',str(second['preview']));self.assertNotIn('210.000',str(second['preview']))
        third=self.ask('yang IDR?',second);self.assertIn('210.000',str(third['preview']));self.assertNotIn('34.56',str(third['preview']))

    def test_explicit_date_range_does_not_use_upload_or_creation_date(self):
        self.tx(510000,'2026-07-01');self.tx(710000,'2026-08-01')
        answer=self.ask('pemasukan 2026-07-01 sampai 2026-07-31 berapa?')
        self.assertIn('510.000',str(answer['preview']));self.assertNotIn('710.000',str(answer['preview']))

    def test_customers_typo_and_unknown_never_list_everyone(self):
        f.create_customer(self.b,'Wilson',phone='08112233',actor_user_id=self.uid)
        self.assertIn('08112233',str(self.ask('costumer Wilsom ada?')))
        unknown=self.ask('cari customer Nobody');self.assertNotIn('08112233',str(unknown));self.assertIn('belum',unknown['message'])
        self.assertIn('Wilson',str(self.ask('customer kita siapa aja?')))

    def test_ambiguous_customer_followup_choices_preserve_query(self):
        a=f.create_customer(self.b,'Wilson Wijaya',actor_user_id=self.uid)
        z=f.create_customer(self.b,'Wilson Kusuma',actor_user_id=self.uid)
        self.tx(100000,customer_id=a);self.tx(900000,customer_id=z)
        first=self.ask('pemasukan customer Wilson keseluruhan?')
        self.assertIn('Wilson Wijaya',first.get('choices',[]));self.assertNotIn('Rp1.000.000',str(first))
        second=self.ask('Wilson Wijaya',first);self.assertIn('100.000',str(second['preview']));self.assertNotIn('900.000',str(second['preview']))

    def test_context_never_answers_weather_as_finance(self):
        first=self.ask('saldo gw berapa?')
        self.assertIn('khusus',self.ask('cuaca gimana?',first)['message'])
        self.assertIn('khusus',self.ask('kalau cuaca gimana?',first)['message'])

    def test_aggregate_read_is_explicit_and_selected_branch_stays_isolated(self):
        self.tx(100000)
        other=branches.create_branch(self.b,'BSD',self.uid)
        with branches.scope(self.b,other,self.uid):
            account=f.list_accounts(self.b,actor_user_id=self.uid)[0]['id'];self.tx(900000,account=account)
        selected=self.ask('pemasukan keseluruhan?');self.assertNotIn('900.000',str(selected['preview']))
        aggregate=self.ask('pemasukan semua cabang keseluruhan?');self.assertIn('1.000.000',str(aggregate['preview']))
        isolated=self.ask('pemasukan cabang BSD keseluruhan?');self.assertIn('900.000',str(isolated['preview']));self.assertNotIn('1.000.000',str(isolated['preview']))

    def test_opening_fx_and_native_balances_are_not_cashflow(self):
        usd=f.create_account(self.b,'BOFA',currency='USD',opening_balance_minor=10000,actor_user_id=self.uid)
        f.record_currency_exchange(self.b,usd,self.a,5000,750000,date.today().isoformat(),actor_user_id=self.uid)
        self.assertEqual(f.get_cash_totals(self.b,actor_user_id=self.uid),[])
        balances=f.get_account_balance_report(self.b,date.today().isoformat(),self.uid)
        self.assertEqual(next(r for r in balances if r['id']==usd)['balance_minor'],5000)
        first=self.ask('saldo USD bulan lalu?');second=self.ask('saldo USD bulan ini?')
        self.assertEqual(first['preview'],second['preview'])

    def test_balance_totals_do_not_depend_on_export_row_cap(self):
        for _ in range(5):self.tx(100000)
        with patch.object(f,'MAX_REPORT_ROWS',3):
            totals=f.get_cash_totals(self.b,actor_user_id=self.uid)
            balances=f.get_account_balance_report(self.b,date.today().isoformat(),self.uid)
        self.assertEqual(totals[0]['total_income_minor'],500000)
        self.assertEqual(balances[0]['income_minor'],500000)

    def test_historical_receivable_survives_later_payment(self):
        row=self.invoice(issue='2026-07-01',due='2026-07-10')
        f.record_invoice_payment(self.b,row['id'],2000000,date.today().isoformat(),self.a,self.cat,actor_user_id=self.uid,idempotency_key='historical_payment_key')
        history=f.get_report_invoices(self.b,'2026-07-31',actor_user_id=self.uid,open_only=True)
        self.assertEqual(len(history),1);self.assertEqual(history[0]['outstanding_minor'],2000000);self.assertTrue(history[0]['overdue'])
        self.assertEqual(f.get_report_invoices(self.b,date.today().isoformat(),actor_user_id=self.uid,open_only=True),[])
        self.assertEqual(f.get_cash_totals(self.b,actor_user_id=self.uid)[0]['total_income_minor'],2000000)

    def test_draft_invoice_and_recurring_do_not_inflate_actuals(self):
        self.invoice(issued=False)
        f.create_recurring_expense(self.b,'AI',2000000,self.a,self.meal,'MONTHLY',date.today().isoformat(),actor_user_id=self.uid)
        self.assertEqual(f.get_cash_totals(self.b,actor_user_id=self.uid),[])
        self.assertEqual(f.get_receivables_summary(self.b,self.uid)['by_currency'][0]['outstanding_minor'] if f.get_receivables_summary(self.b,self.uid).get('by_currency') else 0,0)
        actual=self.ask('pengeluaran keseluruhan?');self.assertNotIn('2.000.000',str(actual['preview']))
        forecast=self.ask('bulan depan biaya rutin apa aja?');self.assertIn('2.000.000',str(forecast['preview']));self.assertIn('belum',forecast['message'])

    def test_recurring_slots_frequency_then_date_without_invention(self):
        f.create_account(self.b,'BCA',account_type='BANK',actor_user_id=self.uid)
        first=self.ask('tambah biaya rutin 2 juta untuk AI')
        self.assertEqual(first['next_field'],'cadence')
        second=self.follow(first,'bulanan');self.assertEqual(second.json['next_field'],'date')
        third=self.follow(second.json,'tanggal 25');self.assertEqual(third.json['next_field'],'account_id')
        fourth=self.follow(third.json,'BCA');self.assertTrue(fourth.json['ready'],fourth.json)
        self.save(fourth.json);self.assertEqual(len(f.list_recurring_expenses(self.b)),1);self.assertEqual(f.list_transactions(self.b),[])

    def test_recurring_unknown_cadence_is_not_silently_monthly(self):
        first=self.ask('tambah biaya rutin 2 juta untuk AI')
        second=self.follow(first,'tiap tahun')
        self.assertEqual(self.values(second)['cadence'],'');self.assertFalse(second.json['ready'])

    def test_recurring_post_one_reviewed_due_occurrence_once(self):
        f.create_recurring_expense(self.b,'AI',2000000,self.a,self.meal,'MONTHLY',date.today().isoformat(),actor_user_id=self.uid)
        draft=self.ask('bayar biaya rutin AI');self.assertTrue(draft['ready'],draft)
        self.assertEqual(f.list_transactions(self.b),[])
        for _ in range(2):self.save(draft)
        self.assertEqual(len(f.list_transactions(self.b)),1)
        self.assertEqual(f.get_cash_totals(self.b,actor_user_id=self.uid)[0]['total_expense_minor'],2000000)

    def test_new_account_review_fields_and_idempotency(self):
        draft=self.ask('tambah rekening BOFA USD')
        self.assertEqual(draft['next_field'],'account_type')
        draft=self.follow(draft,'bank').json
        before=len(f.list_accounts(self.b))
        for _ in range(2):self.save(draft)
        self.assertEqual(len(f.list_accounts(self.b)),before+1)
        row=next(r for r in f.list_accounts(self.b) if r['name']=='BOFA');self.assertEqual(row['currency'],'USD');self.assertEqual(row['opening_balance_minor'],0)

    def test_new_category_and_branch_use_manual_services(self):
        cat=self.ask('tambah kategori pengeluaran Perlengkapan');self.save(cat)
        self.assertTrue(any(r['name']=='Perlengkapan' and r['direction']=='EXPENSE' for r in f.list_categories(self.b)))
        branch=self.ask('buat cabang Serpong');self.save(branch)
        found=next(r for r in branches.list_branches(self.b,self.uid) if r['name']=='Serpong')
        with branches.scope(self.b,found['id'],self.uid):self.assertEqual(f.list_accounts(self.b)[0]['opening_balance_minor'],0)

    def test_command_atomic_retry_and_audit_failure_rollback(self):
        draft=self.ask('tambah kategori pengeluaran Storage')
        original=repo.write_audit
        def fail(actor,business,event,*args,**kwargs):
            if event=='FINANCE_ASSISTANT_COMMAND_CONFIRMED':raise RuntimeError('test rollback')
            return original(actor,business,event,*args,**kwargs)
        before=self.snapshot()
        with patch.object(repo,'write_audit',side_effect=fail):self.assertEqual(self.follow(draft,'oke').status_code,503)
        self.assertEqual(before,self.snapshot())
        self.save(draft)

    def test_competing_command_confirmations_make_one_record(self):
        draft=self.ask('tambah kategori pengeluaran Cloud')
        def write():
            with app.app_context():return flow.confirm(self.b,self.uid,draft['token'])
        answers=self.race([write,write]);self.assertEqual(answers[0][0],'ok',answers);self.assertEqual(answers[1][0],'ok',answers)
        self.assertEqual(answers[0][1]['record_id'],answers[1][1]['record_id'])
        self.assertEqual(len([r for r in f.list_categories(self.b) if r['name']=='Cloud']),1)

    def test_command_stale_snapshot_cannot_void_changed_transaction(self):
        ident=self.tx(100000)
        draft=self.ask('batalkan transaksi '+str(ident));self.assertTrue(draft['ready'])
        f.update_transaction(self.b,ident,amount_minor=200000,actor_user_id=self.uid)
        self.assertEqual(self.follow(draft,'oke').status_code,400)
        self.assertEqual(f.get_transaction(self.b,ident)['status'],'POSTED')

    def test_saved_transaction_reference_and_reviewed_correction(self):
        first=self.ask('pengeluaran makan 100 ribu');saved=self.save(first)
        draft=self.ask('ubah transaksi yang tadi',saved)
        revised=self.follow(draft,'ubah jadi 200 ribu');self.save(revised.json)
        rows=f.list_transactions(self.b);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['amount_minor'],200000)

    def test_saved_invoice_reference_issue_is_separate(self):
        f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        draft=self.ask('buat invoice Wilson jasa foto 2 juta jatuh tempo 30 september')
        saved=self.save(draft);row=f.get_finance_invoice(self.b,saved['record_id']);self.assertEqual(row['status'],'DRAFT')
        self.assertIn('Terbitkan yang tadi',saved.get('choices',[]))
        issue=self.ask('terbitkan yang tadi',saved);self.assertEqual(issue['title'],'Terbitkan invoice')
        issued=self.save(issue);self.assertEqual(f.get_finance_invoice(self.b,row['id'])['status'],'ISSUED')
        self.assertIn('masuk piutang',issued['message'])

    def test_multi_item_invoice_matches_manual_totals(self):
        f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        first=self.ask('buat invoice Wilson jasa foto 2 juta jatuh tempo 30 september')
        second=self.follow(first,'tambah item video 500 ribu qty 2')
        self.assertIn('3.000.000',str(second.json['preview']))
        saved=self.save(second.json)
        self.assertEqual(len(f.list_invoice_items(self.b,saved['record_id'])),2)
        self.assertEqual(f.get_invoice_totals(self.b,saved['record_id'])['total_minor'],3000000)

    def test_lunas_uses_exact_outstanding_and_one_payment(self):
        row=self.invoice()
        draft=self.ask('lunasi invoice '+row['invoice_number'])
        if not draft['ready']:draft=self.revise(draft,category_id=str(self.cat)).json
        self.save(draft);self.save(draft)
        self.assertEqual(len(f.list_invoice_payments(self.b,row['id'])),1)
        self.assertEqual(f.get_invoice_totals(self.b,row['id'])['outstanding_minor'],0)

    def test_reference_typos_resolve_server_side_with_review(self):
        account=f.create_account(self.b,'Mandiri',account_type='BANK',actor_user_id=self.uid)
        first=self.ask('pengeluaran makan 100 ribu')
        second=self.follow(first,'pakai Mandirii')
        self.assertEqual(self.values(second)['account_id'],str(account));self.assertEqual(f.list_transactions(self.b),[])

    def test_ambiguous_draft_account_cannot_confirm_old_account(self):
        for name in ('BCA Personal','BCA Bisnis'):f.create_account(self.b,name,actor_user_id=self.uid)
        first=self.ask('pengeluaran makan 100 ribu')
        second=self.follow(first,'pakai BCA')
        self.assertFalse(second.json['ready']);self.assertEqual(len(second.json['choices']),2)
        third=self.follow(second.json,'oke');self.assertNotEqual(third.json['kind'],'success');self.assertEqual(f.list_transactions(self.b),[])
        fourth=self.follow(second.json,'BCA Bisnis');self.assertTrue(fourth.json['ready']);self.save(fourth.json)

    def test_currency_symbol_and_english_calendar(self):
        usd=f.create_account(self.b,'BOFA',currency='USD',actor_user_id=self.uid)
        draft=self.ask('expense software US$25.50 hari ini')
        self.assertEqual(next(r['value'] for r in draft['fields'] if r['key']=='account_id'),str(usd))
        self.assertEqual(flow.proposed_date('30 september',True),flow.proposed_date('30 September',True))
        self.assertEqual(flow.proposed_date('1 july 2026',True),'2026-07-01')
        self.assertEqual(flow.proposed_date('bulan lalu'), '')
        self.assertEqual(flow.proposed_date('some vague date',default_today=False),'')

    def test_model_semantics_reject_ids_fabrication_and_arbitrary_intents(self):
        for output in ({'intent':'create_income','slots':{'account_id':'123'}},
                       {'intent':'delete_database','slots':{}},{'intent':'create_income','slots':{'amount':'9000000'}}):
            self.model(output)
            with self.assertRaises(ValueError):semantics.interpret('tolong urus pendapatan foto',('unknown','create_income'),('amount','account'))

    def test_semantic_fallback_creates_only_validated_review(self):
        self.model({'intent':'customer','slots':{'name':'Wilsen'}})
        answer=self.ask('customer baru kita namain Wilsen dong')
        self.assertEqual(answer['kind'],'review');self.assertIn('Wilsen',str(answer['preview']))
        self.assertFalse(any(r['name']=='Wilsen' for r in f.list_customers(self.b)))

    def test_missing_slot_context_supplied_to_model_without_ids(self):
        draft=self.ask('tambah customer Wilson')
        self.model({'updates':{'phone':'082213039137'}})
        second=self.follow(draft,'kontaknya tolong dibenerin 082213039137')
        self.assertEqual(self.values(second)['phone'],'082213039137')
        body=self.http.call_args.kwargs['json']['messages'][0]['content']
        self.assertIn('editable_fields',body);self.assertNotIn('account_id',body)

    def test_fx_review_once_and_void_restore_native_balances(self):
        usd=f.create_account(self.b,'BOFA',currency='USD',opening_balance_minor=20000,actor_user_id=self.uid)
        bca=f.create_account(self.b,'BCA',currency='IDR',actor_user_id=self.uid)
        draft=self.ask('catat penukaran 100 USD dari BOFA ke BCA jadi 1,5 juta')
        self.assertTrue(draft['ready'],draft);self.assertEqual(f.list_currency_exchanges(self.b),[])
        saved=self.save(draft);self.save(draft)
        self.assertEqual(len(f.list_currency_exchanges(self.b)),1);self.assertEqual(f.list_transactions(self.b),[])
        balances=f.get_account_balance_report(self.b,date.today().isoformat(),self.uid)
        self.assertEqual(next(r for r in balances if r['id']==usd)['balance_minor'],10000)
        self.assertEqual(next(r for r in balances if r['id']==bca)['balance_minor'],1500000)
        cancel=self.ask('batalkan fx '+str(saved['record_id']));self.save(cancel);self.save(cancel)
        balances=f.get_account_balance_report(self.b,date.today().isoformat(),self.uid)
        self.assertEqual(next(r for r in balances if r['id']==usd)['balance_minor'],20000)

    def test_new_commands_revalidate_currency_and_active_account(self):
        usd=f.create_account(self.b,'BOFA',currency='USD',actor_user_id=self.uid)
        draft=self.ask('catat penukaran 100 USD dari BOFA ke Kas jadi 1,5 juta')
        branches.update_record(self.b,'account',usd,deactivate=True,actor_user_id=self.uid)
        self.assertEqual(self.follow(draft,'oke').status_code,400)
        self.assertEqual(f.list_currency_exchanges(self.b),[])

    def test_old_confirm_cannot_save_changed_review_or_replay_new_values(self):
        first=self.ask('tambah kategori pengeluaran Storage')
        second=self.follow(first,'nama jadi Hosting').json
        self.assertEqual(self.follow(second,'oke',confirmation=first['token']).status_code,400)
        self.save(second)
        self.assertEqual(self.follow(first,'oke').status_code,400)

    def test_read_plan_token_tamper_and_branch_switch_fail_closed(self):
        first=self.ask('pemasukan keseluruhan?')
        bad=self.client.post(self.path+'/message',json={'text':'yang USD?','query_context':first['query_context']+'tamper'})
        self.assertEqual(bad.status_code,400)
        other=branches.create_branch(self.b,'Other',self.uid)
        bad=self.client.post(self.path+f'/message?branch_id={other}',json={'text':'yang USD?','query_context':first['query_context']})
        self.assertEqual(bad.status_code,400)

    def test_aggregate_write_asks_branch_for_settings_too(self):
        r=self.client.post(self.path+'/message?branch_id=all',json={'text':'tambah rekening BCA USD'})
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json['kind'],'branch_choice')
        self.assertFalse(any(r['name']=='BCA' for r in f.list_accounts(self.b)))

    def test_list_transactions_is_paginated_not_silently_truncated(self):
        for i in range(51):self.tx(100+i)
        first=self.ask('lihat transaksi keseluruhan');self.assertEqual(len(first['preview']),50);self.assertEqual(first['choices'],['Berikutnya'])
        second=self.ask('berikutnya',first);self.assertEqual(len(second['preview']),1);self.assertEqual(second['choices'],[])

    def test_native_category_rankings_do_not_add_income_to_expense(self):
        self.tx(700000,direction='EXPENSE');self.tx(9000000)
        read=self.ask('kategori pengeluaran terbesar keseluruhan?')
        self.assertIn('700.000',str(read['preview']));self.assertNotIn('9.000.000',str(read['preview']))

    def test_integer_aggregation_stays_exact_above_int64(self):
        self.tx(2**63-1);self.tx(2**63-1)
        self.assertEqual(f.get_cash_totals(self.b,actor_user_id=self.uid)[0]['total_income_minor'],2*(2**63-1))

    def test_scoped_project_filter_does_not_invent_project(self):
        r=self.ask('pengeluaran proyek TidakAda bulan ini berapa?')
        self.assertIn('belum jelas',r['message']);self.assertEqual(f.list_transactions(self.b),[])

    def test_recurring_initial_fragment_extracts_name_and_start(self):
        draft=self.ask('AI 2 juta tiap bulan mulai tanggal 25')
        self.assertEqual(next(r['value'] for r in draft['fields'] if r['key']=='name'),'AI')
        self.assertEqual(next(r['value'] for r in draft['fields'] if r['key']=='cadence'),'MONTHLY')
        self.assertTrue(next(r['value'] for r in draft['fields'] if r['key']=='date').endswith('-25'))

    def test_customer_name_is_literal_even_when_it_contains_finance_vocabulary(self):
        draft=self.ask('add customer Revenue Labs')
        self.assertEqual(next(r['value'] for r in draft['fields'] if r['key']=='name'),'Revenue Labs')
        self.save(draft);self.assertTrue(any(r['name']=='Revenue Labs' for r in f.list_customers(self.b)))

    def test_new_complete_question_does_not_inherit_previous_customer_filter(self):
        customer=f.create_customer(self.b,'Wilson',actor_user_id=self.uid)
        self.tx(100000,customer_id=customer);self.tx(900000)
        first=self.ask('pemasukan customer Wilson bulan ini?');self.assertIn('100.000',str(first['preview']))
        second=self.ask('pemasukan IDR bulan ini?',first);self.assertIn('1.000.000',str(second['preview']))

    def test_fx_confirmation_binds_the_reviewed_account_currencies(self):
        usd=f.create_account(self.b,'BOFA',currency='USD',actor_user_id=self.uid)
        first=self.ask('catat FX')
        draft=self.revise(first,from_account_id=str(usd),to_account_id=str(self.a),from_amount='100',to_amount='1500000').json
        self.assertTrue(draft['ready'],draft)
        db.execute('UPDATE finance_accounts SET currency=? WHERE id=?',('EUR',usd))
        self.assertEqual(self.follow(draft,'oke').status_code,400)
        self.assertEqual(f.list_currency_exchanges(self.b),[])


if __name__=='__main__':unittest.main()
