"""Unified input, visual routing, recurring confirmation and bank reliability, offline."""
import io
import json
import os
import re
import time
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import test_final_product_flow as fixture
import finance_service as f
import finance_bank_service as bank
import finance_bank_extract as extraction
import finance_assistant as router
import finance_assistant_recurring as recurring
import finance_branches as branches
import finance_ai_safety as safety
import db
import repo

app=fixture.app


class UnifiedTests(unittest.TestCase):
    def setUp(self):
        fixture.FinalFlowTests.setUp(self)
        fixture.FinalFlowTests.trial(self)
        self.assistant=self.url+'/assistant'
    snapshot=fixture.FinalFlowTests.snapshot
    race=fixture.FinalFlowTests.race

    def model(self,result,stop='end_turn'):
        self.response.json.return_value={'stop_reason':stop,'content':[{'type':'text','text':json.dumps(result)}]}
    def recognize(self,raw=None,filename='photo.png',url=None):
        return self.client.post((url or self.assistant)+'/recognize',data={'sources':(io.BytesIO(self.raw if raw is None else raw),filename),'text':''})
    def payload(self,**changes):
        values=dict(name='Sewa kantor',amount_text='2 juta',cadence='MONTHLY',
            next_due_on=(date.today()+timedelta(days=20)).isoformat(),end_on=None,
            account_id=self.a,category_id=self.expense['id'])
        values.update(changes);return values
    def draft(self,**changes):
        return self.client.post(self.assistant+'/recurring/draft',json=self.payload(**changes))
    def confirm(self,token,**changes):
        values=dict(token=token,confirm=True);values.update(changes)
        return self.client.post(self.assistant+'/recurring/confirm',json=values)

    def test_text_routes_analysis_transactions_recurring_and_notes(self):
        for text,workflow in [('beli bensin 50rb','TEXT_OPERATOR'),('terima penjualan 2 juta','TEXT_OPERATOR'),
             ('berapa pengeluaran bulan ini?','READ_ONLY_ANALYSIS'),('sewa 2 juta tiap bulan','RECURRING_DRAFT'),
             ('berapa biaya rutin?','READ_ONLY_ANALYSIS'),('hapus semua transaksi','UNSUPPORTED')]:
            with self.subTest(text=text):
                self.assertEqual(router.propose(dict(text=text,mode='auto',files=[]))['workflow'],workflow)
        self.assertEqual(router.propose(dict(text='catatan tulisan tangan',mode='auto',files=[{'name':'a.jpg'}]))['workflow'],'HANDWRITTEN_NOTE')
    def test_recurring_suggestions_never_guess_date_or_ids(self):
        self.assertEqual(recurring.suggest('sewa 2 juta tiap bulan')['amount_text'],'2 juta')
        result=recurring.suggest('sewa 2 juta dan listrik 300 ribu tiap bulan')
        self.assertEqual(result['amount_text'],'')
        self.assertNotIn('next_due_on',result);self.assertNotIn('account_id',result)
    def test_one_visible_text_input_and_all_workflows(self):
        html=self.client.get(self.assistant).text
        self.assertEqual(len(re.findall(r'<textarea\b',html)),1)
        for value in ('assistant/recognize','assistant/message','value="notes"','value="recurring"'):
            self.assertIn(value,html)
        self.assertIn('id="assistant-result"',html)
        self.assertNotIn('id="operator-fields"',html)
    def test_visual_routing_returns_only_kind_and_no_writes(self):
        before=self.snapshot()
        for workflow in ('RECEIPT','BANK_STATEMENT','HANDWRITTEN_NOTE','NEEDS_CLARIFICATION'):
            self.model({'workflow':workflow});response=self.recognize()
            self.assertEqual(response.status_code,200);self.assertEqual(response.json,{'workflow':workflow})
            self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertEqual(before,self.snapshot())
    def test_visual_invalid_or_truncated_output_never_authorizes_action(self):
        for result,stop in [({'workflow':'POST_NOW'},'end_turn'),({'workflow':'RECEIPT','amount':50},'end_turn'),({'workflow':'RECEIPT'},'max_tokens')]:
            self.model(result,stop)
            self.assertEqual(self.recognize().json['workflow'],'NEEDS_CLARIFICATION')
        self.assertEqual(f.list_transactions(self.b),[])
    def test_visual_invalid_bytes_no_provider(self):
        self.assertEqual(self.recognize(b'NOT_IMAGE').status_code,400);self.http.assert_not_called()
    def test_csv_recognition_no_model(self):
        self.assertEqual(self.recognize(self.csv,'bank.csv').json['workflow'],'BANK_STATEMENT')
        self.http.assert_not_called()
    def test_visual_timeout_safe_and_retry_manual(self):
        import requests
        self.http.side_effect=requests.Timeout('PRIVATE')
        response=self.recognize();self.assertEqual(response.json['workflow'],'NEEDS_CLARIFICATION')
        self.assertNotIn('PRIVATE',response.text)
    def test_visual_tenant_access_and_expiry(self):
        self.assertEqual(self.recognize(url=f'/business/{self.other}/finance/assistant').status_code,404)
        self.time.return_value+=timedelta(days=7)
        self.assertIn(self.recognize().status_code,(302,303,401,403));self.http.assert_not_called()
    def test_new_endpoints_require_csrf(self):
        with patch.dict(app.config,CLIENT_HUB_FORCE_CSRF_IN_TESTS=True):
            self.assertEqual(self.recognize().status_code,400)
            self.assertEqual(self.draft().status_code,400)
            self.assertEqual(self.confirm('x').status_code,400)
        self.http.assert_not_called()
    def test_new_endpoints_accept_valid_csrf(self):
        with patch.dict(app.config,CLIENT_HUB_FORCE_CSRF_IN_TESTS=True):
            self.client.get(self.assistant)
            with self.client.session_transaction() as session:token=session['_csrf_token']
            response=self.client.post(self.assistant+'/recurring/draft',json=self.payload(),headers={'X-CSRF-Token':token})
            self.assertEqual(response.status_code,200)
            self.model({'workflow':'RECEIPT'})
            response=self.client.post(self.assistant+'/recognize',data={'sources':(io.BytesIO(self.raw),'photo.png'),'csrf_token':token,'text':''})
            self.assertEqual(response.status_code,200);self.assertEqual(response.json['workflow'],'RECEIPT')
    def test_recurring_preview_is_read_only_future_schedule_allowed(self):
        before=self.snapshot();response=self.draft()
        self.assertEqual(response.status_code,200);self.assertIn('token',response.json)
        self.assertEqual(before,self.snapshot());self.http.assert_not_called()
    def test_recurring_confirm_once_no_ledger(self):
        token=self.draft().json['token']
        first=self.confirm(token);second=self.confirm(token)
        self.assertEqual(first.status_code,200);self.assertEqual(first.json,second.json)
        self.assertEqual(len(f.list_recurring_expenses(self.b)),1);self.assertEqual(f.list_transactions(self.b),[])
        self.assertFalse(f.recurring_needs_attention(self.b,first.json['record_id']))
    def test_recurring_concurrent_confirmation_is_idempotent(self):
        token=self.draft().json['token']
        def execute():
            with app.app_context():return recurring.confirm(self.b,self.uid,token)
        results=self.race([execute,execute])
        self.assertEqual(results[0],results[1]);self.assertEqual(len(f.list_recurring_expenses(self.b)),1)
    def test_recurring_tamper_expiry_and_explicit_confirmation(self):
        token=self.draft().json['token']
        self.assertEqual(self.confirm(token,confirm=False).status_code,400)
        self.assertEqual(self.confirm(token+'changed').status_code,400)
        with app.app_context():
            data=recurring.signer().loads(token)
            with patch('itsdangerous.timed.time.time',return_value=time.time()-recurring.TTL-10):old=recurring.signer().dumps(data)
        self.assertEqual(self.confirm(old).status_code,400)
        self.assertEqual(f.list_recurring_expenses(self.b),[])
    def test_recurring_revalidates_account_on_confirmation(self):
        token=self.draft().json['token']
        db.execute('UPDATE finance_accounts SET is_active=FALSE WHERE id=?',(self.a,))
        self.assertEqual(self.confirm(token).status_code,400);self.assertEqual(f.list_recurring_expenses(self.b),[])
    def test_recurring_cross_branch_and_tenant_token_rejected(self):
        token=self.draft().json['token'];other_branch=branches.create_branch(self.b,'Other',self.uid)
        response=self.client.post(self.assistant+f'/recurring/confirm?branch_id={other_branch}',json={'token':token,'confirm':True})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.client.post(f'/business/{self.other}/finance/assistant/recurring/confirm',json={'token':token,'confirm':True}).status_code,404)
        self.assertEqual(f.list_recurring_expenses(self.b),[])
    def test_recurring_rollback_includes_audit_marker(self):
        token=self.draft().json['token'];original=repo.write_audit
        def audit(*args,**kw):
            if args[2]==recurring.EVENT:raise RuntimeError('synthetic')
            return original(*args,**kw)
        with patch.object(repo,'write_audit',side_effect=audit):
            self.assertEqual(self.confirm(token).status_code,503)
        self.assertEqual(f.list_recurring_expenses(self.b),[])
        self.assertEqual(self.confirm(token).status_code,200)
    def test_recurring_invalid_fields_cannot_create(self):
        for values in ({'amount_text':'-1'},{'cadence':'DAILY'},{'next_due_on':'nonsense'},
                       {'end_on':'2020-01-01'},{'account_id':True},{'category_id':self.cat}):
            with self.subTest(values=values):self.assertEqual(self.draft(**values).status_code,400)
        self.assertEqual(f.list_recurring_expenses(self.b),[])
    def test_recurring_capability_disabled(self):
        with patch.dict(os.environ,KILAS_FINANCE_OPERATOR_ENABLED='off'):
            self.assertEqual(self.draft().status_code,404)
    def test_future_actual_transactions_still_rejected(self):
        with self.assertRaises(f.FinanceError):
            f.create_transaction(self.b,'EXPENSE',1,self.a,self.expense['id'],(date.today()+timedelta(days=1)).isoformat(),actor_user_id=self.uid)
    def test_notes_use_explicit_note_prompt_and_staging_only(self):
        self.model(self.result)
        response=self.client.post(self.url+'/bank-imports/analyze',data={'account_id':str(self.a),'document_kind':'notes','sources':(io.BytesIO(self.raw),'note.png')})
        self.assertEqual(response.status_code,302)
        self.assertIn('FINANCIAL NOTE',self.http.call_args.kwargs['json']['system'])
        self.assertEqual(f.list_transactions(self.b),[])
        row=db.query_one('SELECT * FROM finance_bank_imports WHERE business_id=?',(self.b,))
        self.assertEqual(row['status'],'REVIEW');self.assertIn('Catatan',row['display_label'])
    def test_bank_empty_failure_can_retry_same_file(self):
        self.model({'readable':False,'rows':[]})
        ident,fallback=bank.analyze(self.b,self.a,[('a.png',self.raw)],self.uid)
        self.assertTrue(fallback);self.assertEqual(bank.get_rows(self.b,ident,self.uid),[])
        self.model(self.result)
        second,fallback=bank.analyze(self.b,self.a,[('a.png',self.raw)],self.uid)
        self.assertEqual(second,ident);self.assertFalse(fallback)
        self.assertEqual(len(bank.get_rows(self.b,ident,self.uid)),1);self.assertEqual(f.list_transactions(self.b),[])
    def test_bank_retry_never_overwrites_manual_rows(self):
        self.model({'readable':False,'rows':[]})
        ident,_=bank.analyze(self.b,self.a,[('a.png',self.raw)],self.uid)
        bank.edit_row(self.b,ident,None,0,self.row,self.uid)
        before=self.snapshot();self.http.reset_mock()
        self.assertEqual(bank.analyze(self.b,self.a,[('a.png',self.raw)],self.uid),(ident,False))
        self.assertEqual(before,self.snapshot());self.http.assert_not_called()
    def test_bank_truncated_response_no_partial_rows(self):
        self.model(self.result,'max_tokens')
        ident,fallback=bank.analyze(self.b,self.a,[('a.png',self.raw)],self.uid)
        self.assertTrue(fallback);self.assertEqual(bank.get_rows(self.b,ident,self.uid),[])
    def test_semicolon_tab_csv_and_ambiguous_direction(self):
        for sep in (';','\t'):
            raw=sep.join(['tanggal','keterangan','jumlah','jenis'])+'\n'+sep.join(['17/09/2026','bensin','100.000,00','KELUAR'])
            self.assertEqual(extraction.parse_csv(raw.encode())[0]['amount_minor'],100000)
        with self.assertRaises(ValueError):extraction.parse_csv(b'date;description;debit;credit\n2026-09-17;x;1;1')
    def test_recognize_multipart_stays_memory_bounded(self):
        with app.test_request_context(self.assistant+'/recognize'):
            from flask import request
            request.url_rule=app.url_map.bind('').match(self.assistant+'/recognize',method='POST',return_rule=True)[0]
            self.assertIsInstance(request._get_file_stream(1000000,'image/png','a.png'),io.BytesIO)
        response=self.client.post(self.assistant+'/recognize',data=b'x'*(26*1024*1024+1),content_type='multipart/form-data')
        self.assertEqual(response.status_code,413)


    def test_makan_text_routes_and_confirms_exactly_once(self):
        text='catat makan 120 ribu'
        response=self.client.post(self.assistant+'/route',json=dict(text=text,mode='auto',files=[]))
        self.assertEqual(response.json['suggested_action'],'create_expense')
        self.model(dict(action='create_expense',amount_text='120 ribu',description='makan'))
        result=self.client.post(self.url+'/operator/draft',json=dict(action='create_expense',request=text,
            date='2026-09-17',account_id=self.a,category_id=self.expense['id'],invoice_id=None))
        self.assertEqual(result.status_code,200);self.assertEqual(f.list_transactions(self.b),[])
        for _ in range(2):
            self.assertEqual(self.client.post(self.url+'/operator/confirm',json={'token':result.json['token'],'confirm':True}).status_code,200)
        rows=f.list_transactions(self.b);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['amount_minor'],120000)
    def test_bank_text_pdf_failed_structure_retries_original_as_vision(self):
        from test_finance_phase6a import pdf_bytes
        source=extraction.validate_sources([('bank.pdf',pdf_bytes(text=True))])
        empty={'stop_reason':'end_turn','content':[{'type':'text','text':'{"rows":[],"readable":false}'}]}
        good={'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(self.result)}]}
        self.response.json.side_effect=[empty,good]
        rows,fallback=extraction.extract(source,self.uid,self.b)
        self.assertFalse(fallback);self.assertEqual(rows,[self.row]);self.assertEqual(self.http.call_count,2)
        contents=[call.kwargs['json']['messages'][0]['content'][0] for call in self.http.call_args_list]
        self.assertEqual([c['type'] for c in contents],['text','document'])
        self.assertEqual(f.list_transactions(self.b),[])
    def test_bank_scanned_pdf_direct_vision_and_jpeg_path(self):
        from test_finance_phase6a import pdf_bytes,image_bytes
        self.model(self.result)
        for name,raw,kind in [('scan.pdf',pdf_bytes(),'document'),('photo.jpg',image_bytes('JPEG'),'image')]:
            self.http.reset_mock();source=extraction.validate_sources([(name,raw)])
            rows,fallback=extraction.extract(source,self.uid,self.b)
            self.assertFalse(fallback);self.assertEqual(self.http.call_count,1)
            self.assertEqual(self.http.call_args.kwargs['json']['messages'][0]['content'][0]['type'],kind)
    def test_csv_unknown_layout_safe_text_fallback_and_no_writes(self):
        raw=b'Booking date,Details,Debit amount,Credit amount\n2026-09-17,Lunch,100000,0'
        self.model(self.result)
        rows,fallback=extraction.extract(extraction.validate_sources([('bank.csv',raw)]),self.uid,self.b)
        self.assertFalse(fallback);self.assertEqual(rows,[self.row]);self.assertEqual(self.http.call_count,1)
        self.assertEqual(self.http.call_args.kwargs['json']['messages'][0]['content'][0]['type'],'text')
        self.assertEqual(f.list_transactions(self.b),[])
    def test_csv_malformed_unknown_layout_never_sent_to_ai(self):
        for raw in (b'Booking date,Details,Debit amount,Credit amount\n2026-09-17,"unterminated,100000,0',
                    b'Booking date,Details,Debit amount,Credit amount\n2026-09-17,bad"quotes,100000,0'):
            with self.assertRaises(ValueError):
                extraction.extract(extraction.validate_sources([('bank.csv',raw)]),self.uid,self.b)
        self.http.assert_not_called()
    def test_currency_preserved_in_bank_and_recurring(self):
        account=f.create_account(self.b,'USD',currency='USD',actor_user_id=self.uid)
        raw=b'date,description,amount,direction\n2026-09-17,Software,25.50,EXPENSE'
        ident,_=bank.analyze(self.b,account,[('usd.csv',raw)],self.uid)
        row=bank.get_rows(self.b,ident,self.uid)[0];self.assertEqual(row['amount_minor'],2550)
        bank.open_import(self.b,ident,0,self.uid)
        record=bank.decide(self.b,ident,row['id'],'post',self.uid,fields=dict(category_id=self.expense['id'],occurred_on=row['occurred_on'],description='Software',counterparty_name=None))
        self.assertEqual(f.get_transaction(self.b,record)['currency'],'USD')
        draft=self.draft(account_id=account,amount_text='25.50 USD')
        self.assertEqual(draft.status_code,200);self.assertIn('25.50',str(draft.json['preview']))
        confirmed=self.confirm(draft.json['token']);self.assertEqual(confirmed.status_code,200)
        rule=f.get_recurring_expense(self.b,confirmed.json['record_id']);self.assertEqual((rule['currency'],rule['amount_minor']),('USD',2550))
    def test_receipt_text_pdf_falls_back_to_original_pdf(self):
        from test_finance_phase6a import pdf_bytes
        import finance_receipts
        good=dict(merchant_name='Toko',transaction_date='2026-09-17',total_minor=120000,
            currency='IDR',receipt_number=None,description='makan',suggested_category_name=None,readable=True)
        def body(result):return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(result)}]}
        self.response.json.side_effect=[body(finance_receipts.empty_result()),body(good)]
        response=self.client.post(self.url+'/receipts/analyze',data={'receipt':(io.BytesIO(pdf_bytes(text=True)),'receipt.pdf')})
        self.assertEqual(response.status_code,200);self.assertIn('value="120000"',response.text)
        self.assertEqual(self.http.call_count,2);self.assertEqual(f.list_transactions(self.b),[])
        self.assertEqual(self.http.call_args.kwargs['json']['messages'][0]['content'][0]['type'],'document')
    def test_pdf_worker_text_exception_preserves_visual_fallback(self):
        from test_finance_phase6a import pdf_bytes
        import finance_receipt_pdf as worker
        import pypdf, resource
        class Input:
            buffer=io.BytesIO(pdf_bytes(text=True))
        output=io.StringIO()
        with patch.object(worker.sys,'stdin',Input()),patch.object(worker.sys,'stdout',output),patch.object(worker.sys,'argv',['worker','--bank-statement']),patch.object(resource,'setrlimit'),patch.object(worker.logging,'disable'),patch.object(pypdf._page.PageObject,'extract_text',side_effect=ValueError('broken font')):
            worker.main()
        self.assertEqual(json.loads(output.getvalue()),{'text':''})

    def test_changed_templates_compile_and_pdf_worker_budget(self):
        from pathlib import Path
        import runpy
        for name in ('finance_assistant.html','_finance_analyst_workspace.html','_finance_operator_workspace.html',
                     '_finance_recurring_workspace.html','finance_bank_new.html'):
            app.jinja_env.get_template(name)
        config=runpy.run_path(str(Path(__file__).resolve().parents[1]/'gunicorn.conf.py'))
        self.assertGreater(config['timeout'],2*(5+45)+8)


if __name__=='__main__':unittest.main()
