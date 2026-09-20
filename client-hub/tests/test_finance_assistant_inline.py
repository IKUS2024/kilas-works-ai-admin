"""Authenticated production-shaped Assistant requests; no network or customer data."""
import io
import json
import time
import unittest
from datetime import date,timedelta
from unittest.mock import patch
from PIL import Image
import test_finance_unified_assistant as prior
from test_finance_phase6a import pdf_bytes
import finance_assistant_flow as flow
import finance_service as f
import finance_bank_service as bank
import finance_branches as branches
import finance_ai_safety as safety
import file_utils
import db
import repo

app=prior.app

class InlineTests(unittest.TestCase):
    def setUp(self):
        prior.UnifiedTests.setUp(self)
        self.meal=f.create_category(self.b,'EXPENSE','Makan',actor_user_id=self.uid)
        self.gas=f.create_category(self.b,'EXPENSE','Bensin',actor_user_id=self.uid)
        self.branch=branches.list_branches(self.b,self.uid)[0]['id']
        self.path=self.assistant
        from finance_semantic_fixtures import install
        install(self)
    snapshot=prior.UnifiedTests.snapshot
    race=prior.UnifiedTests.race
    model=prior.UnifiedTests.model
    def message(self,text):return self.client.post(self.path+'/message',json={'text':text})
    def confirm(self,token,**extra):return self.client.post(self.path+'/confirm',json=dict({'token':token,'confirm':True},**extra))
    def revise(self,data,**changes):
        values={v['key']:v['value'] for v in data['fields']};values.update(changes)
        return self.client.post(self.path+'/review',json=dict(context=data['context'],values=values))
    def document(self,workflow='RECEIPT',raw=None,name='photo.png',**fields):
        data=dict(sources=(io.BytesIO(self.raw if raw is None else raw),name),workflow=workflow,text='');data.update(fields)
        return self.client.post(self.path+'/document',data=data)
    def receipt_model(self):
        self.model(dict(merchant_name='Warung',transaction_date=date.today().isoformat(),total_minor=120000,currency='IDR',receipt_number=None,description='Makan',suggested_category_name='Makan',readable=True))
    def test_expense_fills_draft_no_write_and_confirm_once(self):
        before=self.snapshot();r=self.message('pengeluaran makan 120 ribu hari ini')
        self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json['ready'],r.json)
        self.assertEqual(before,self.snapshot());self.http.assert_called()
        fields={v['key']:v['value'] for v in r.json['fields']}
        self.assertEqual(fields['account_id'],str(self.a));self.assertEqual(fields['category_id'],str(self.meal));self.assertEqual(fields['date'],date.today().isoformat())
        for _ in range(2):self.assertEqual(self.confirm(r.json['token']).status_code,200)
        rows=f.list_transactions(self.b);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['amount_minor'],120000)
    def test_income_default_today_and_review(self):
        r=self.message('pemasukan 2 juta dari Andi');self.assertEqual(r.status_code,200,r.text)
        if not r.json['ready']:r=self.revise(r.json,category_id=str(self.cat))
        self.assertTrue(r.json['ready'],r.json);self.assertEqual(self.confirm(r.json['token']).status_code,200)
        self.assertEqual(f.list_transactions(self.b)[0]['direction'],'INCOME')
    def test_yesterday_and_unsupported_date(self):
        r=self.message('tadi beli bensin 300rb kemarin');self.assertTrue(r.json['ready'])
        fields={x['key']:x['value'] for x in r.json['fields']};self.assertEqual(fields['date'],(date.today()-timedelta(days=1)).isoformat())
        r=self.message('pengeluaran makan 100rb besok');self.assertFalse(r.json['ready'])
    def test_one_account_selected_multiple_accounts_ask(self):
        f.create_account(self.b,'Kas lain',actor_user_id=self.uid)
        r=self.message('pengeluaran makan 120 ribu');self.assertFalse(r.json['ready']);self.assertIn('rekening mana',r.json['message'])
        self.assertEqual(f.list_transactions(self.b),[])
        self.assertTrue(self.revise(r.json,account_id=str(self.a)).json['ready'])
    def test_explicit_add_income_is_write_not_report_question(self):
        r=self.message('tambahin pendapatan jasa foto 2200000 hari ini')
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json['kind'],'review')
        self.assertEqual(r.json['title'],'Pemasukan')
        self.assertNotEqual(r.json.get('kind'),'answer')
        values={v['key']:v['value'] for v in r.json['fields']}
        self.assertEqual(values['amount'],'2200000')
        self.assertEqual(f.list_transactions(self.b),[])

    def test_plain_integer_amount_is_preserved_while_account_is_missing(self):
        f.create_account(self.b,'Kas lain',actor_user_id=self.uid)
        r=self.message('tambahin pendapatan dari jasa foto 2200000')
        self.assertEqual(r.status_code,200,r.text);self.assertFalse(r.json['ready'])
        values={v['key']:v['value'] for v in r.json['fields']}
        self.assertEqual(values['amount'],'2200000')
        self.assertIn('Nominal sudah terbaca',r.json['message'])
        self.assertEqual(f.list_transactions(self.b),[])

    def test_exact_account_currency_and_foreign_amount(self):
        usd=f.create_account(self.b,'BOFA',currency='USD',actor_user_id=self.uid)
        r=self.message('pengeluaran software 25.50 USD hari ini');self.assertEqual(r.status_code,200,r.text)
        values={v['key']:v['value'] for v in r.json['fields']};self.assertEqual(values['account_id'],str(usd));self.assertEqual(values['currency'],'USD')
        r=self.revise(r.json,category_id=str(self.expense['id']));self.assertTrue(r.json['ready'],r.json)
        self.assertEqual(self.confirm(r.json['token']).status_code,200)
        row=f.list_transactions(self.b)[0];self.assertEqual((row['amount_minor'],row['currency']),(2550,'USD'))
    def test_ambiguous_category_not_invented(self):
        before=len(f.list_categories(self.b))
        r=self.message('catat peralatan 100rb');self.assertFalse(r.json['ready']);self.assertIn('Kategori',r.json['message'])
        self.assertEqual(len(f.list_categories(self.b)),before)
    def test_chat_is_finance_only_and_monthly_language_becomes_recurring(self):
        outside=self.message('siapa presiden sekarang?')
        self.assertEqual(outside.status_code,200);self.assertEqual(outside.json['kind'],'clarification')
        self.assertIn('khusus',outside.json['message'].lower())
        recurring=self.message('setiap bulan bayar internet 500 ribu')
        self.assertEqual(recurring.status_code,200,recurring.text)
        self.assertEqual(recurring.json['title'],'Biaya rutin')

    def test_read_only_questions_immediate(self):
        before=self.snapshot()
        for question in ('bulan ini pengeluaran saya berapa?','pengeluaran terbesar apa?','saldo BOFA berapa?','customer yang belum bayar siapa?'):
            r=self.message(question);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json['kind'],'answer');self.assertNotIn('token',r.json)
        self.assertEqual(before,self.snapshot());self.http.assert_called()
    def test_customer_conversational_name_cleanup_and_manual_field_contract(self):
        r=self.message('tambah customer atas nama irvan ya')
        self.assertEqual(r.status_code,200,r.text)
        values={x['key']:x['value'] for x in r.json['fields']}
        self.assertEqual(values['name'],'irvan')
        self.assertEqual(set(values),{'name','phone','email','notes'})

    def test_transaction_and_recurring_drafts_expose_manual_optional_fields(self):
        tx=self.message('pengeluaran makan 120 ribu hari ini')
        tx_keys={x['key'] for x in tx.json['fields']}
        for key in ('project_id','customer_id','counterparty_name','description','account_id','category_id','amount','date'):
            self.assertIn(key,tx_keys)
        recurring=self.message('setiap bulan bayar internet 500 ribu hari ini')
        recurring_keys={x['key'] for x in recurring.json['fields']}
        for key in ('name','project_id','counterparty_name','description','account_id','category_id','amount','cadence','date','end_on'):
            self.assertIn(key,recurring_keys)

    def test_transaction_optional_manual_fields_persist_through_assistant(self):
        r=self.message('pengeluaran makan 120 ribu hari ini')
        r=self.revise(r.json,counterparty_name='Warung Test')
        self.assertTrue(r.json['ready'],r.json)
        self.assertEqual(self.confirm(r.json['token']).status_code,200)
        row=f.list_transactions(self.b)[0]
        self.assertEqual(row['counterparty_name'],'Warung Test')

    def test_recurring_manual_optional_fields_persist_through_assistant(self):
        r=self.message('setiap bulan bayar internet 500 ribu hari ini')
        r=self.revise(r.json,category_id=str(self.expense['id']),counterparty_name='Telkom',description='Internet kantor')
        self.assertTrue(r.json['ready'],r.json)
        self.assertEqual(self.confirm(r.json['token']).status_code,200)
        rule=f.list_recurring_expenses(self.b)[0]
        self.assertEqual(rule['counterparty_name'],'Telkom')
        self.assertEqual(rule['description'],'Internet kantor')

    def test_customer_exact_fields_and_idempotency(self):
        before=len(f.list_customers(self.b))
        r=self.message('tambah customer PT ABC, nomor 08123456789');self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json['ready'])
        self.assertEqual(len(f.list_customers(self.b)),before)
        for _ in range(2):self.assertEqual(self.confirm(r.json['token']).status_code,200)
        rows=[c for c in f.list_customers(self.b) if c['name']=='PT ABC'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['phone'],'08123456789');self.assertIsNone(rows[0]['email'])
    def test_customer_name_only_and_email(self):
        for text,name,email in [('tambah customer Budi','Budi',''),('masukin customer Santi email santi@example.com','Santi','santi@example.com')]:
            r=self.message(text);self.assertTrue(r.json['ready']);values={x['key']:x['value'] for x in r.json['fields']}
            self.assertEqual(values['name'],name);self.assertEqual(values['email'],email);self.assertEqual(values['phone'],'')
    def test_customer_concurrent_confirm_and_audit_rollback(self):
        r=self.message('tambah customer Budi');token=r.json['token']
        def write():
            with app.app_context():return flow.confirm(self.b,self.uid,token)
        out=self.race([write,write]);self.assertEqual(out[0],out[1]);self.assertEqual(len([c for c in f.list_customers(self.b) if c['name']=='Budi']),1)
    def test_recurring_date_ten_schedule_only(self):
        r=self.message('internet 500 ribu tiap tanggal 10');self.assertEqual(r.status_code,200,r.text)
        r=self.revise(r.json,category_id=str(self.expense['id']));self.assertTrue(r.json['ready'],r.json)
        for _ in range(2):self.assertEqual(self.confirm(r.json['token']).status_code,200)
        rows=f.list_recurring_expenses(self.b);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['next_due_on'][-2:],'10');self.assertEqual(f.list_transactions(self.b),[])
    def test_recurring_incomplete_month_requires_date(self):
        f.create_account(self.b,'BOFA',currency='USD',actor_user_id=self.uid)
        r=self.message('software 25 USD tiap bulan mulai Oktober');self.assertFalse(r.json['ready'])
        self.assertEqual(next(v['value'] for v in r.json['fields'] if v['key']=='date'),'')
    def test_invoice_payment_does_not_guess(self):
        r=self.message('Budi bayar invoice INV-001 sebesar 1 juta');self.assertEqual(r.status_code,200,r.text);self.assertFalse(r.json['ready'])
        self.assertEqual(next(v['value'] for v in r.json['fields'] if v['key']=='invoice_id'),'')
    def test_multiple_amounts_clarification_no_writes(self):
        r=self.message('makan 100rb dan bensin 200rb hari ini');self.assertEqual(r.json['kind'],'clarification');self.assertEqual(f.list_transactions(self.b),[])
    def test_tamper_expiry_explicit_confirm(self):
        token=self.message('pengeluaran makan 120 ribu').json['token']
        self.assertEqual(self.confirm(token+'x').status_code,400)
        self.assertEqual(self.confirm(token,confirm=False).status_code,400)
        with patch('itsdangerous.timed.time.time',return_value=time.time()+flow.TTL+30):self.assertEqual(self.confirm(token).status_code,400)
        self.assertEqual(f.list_transactions(self.b),[])
    def test_tenant_branch_and_reference_revalidation(self):
        token=self.message('pengeluaran makan 120 ribu').json['token']
        self.assertEqual(self.client.post(f'/business/{self.other}/finance/assistant/confirm',json=dict(token=token,confirm=True)).status_code,404)
        other=branches.create_branch(self.b,'Other',self.uid)
        self.assertEqual(self.client.post(self.path+f'/confirm?branch_id={other}',json=dict(token=token,confirm=True)).status_code,400)
        db.execute('UPDATE finance_accounts SET is_active=FALSE WHERE id=?',(self.a,))
        self.assertEqual(self.client.post(self.path+f'/confirm?branch_id={self.branch}',json=dict(token=token,confirm=True)).status_code,400)
    def test_csrf_multipart_branch_and_inline_errors(self):
        self.receipt_model()
        with patch.dict(app.config,CLIENT_HUB_FORCE_CSRF_IN_TESTS=True):
            r=self.document();self.assertEqual(r.status_code,400);self.assertTrue(r.is_json)
            self.client.get(self.path+f'?branch_id={self.branch}')
            with self.client.session_transaction() as session:csrf=session['_csrf_token']
            r=self.client.post(self.path+f'/document?branch_id={self.branch}',data=dict(csrf_token=csrf,branch_id=str(self.branch),workflow='RECEIPT',sources=(io.BytesIO(self.raw),'a.png')))
            self.assertEqual(r.status_code,200,r.text)
    def test_entitlement_expired_inline(self):
        self.time.return_value+=timedelta(days=8)
        for r in (self.message('catat makan 100rb'),self.document()):
            self.assertTrue(r.is_json);self.assertIn(r.status_code,(401,403));self.assertNotIn('<html',r.text)
    def test_receipt_review_then_confirm_duplicate(self):
        self.receipt_model();r=self.document();self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json['ready'],r.json)
        self.assertEqual(f.list_transactions(self.b),[])
        for _ in range(2):self.assertEqual(self.confirm(r.json['token']).status_code,200)
        self.assertEqual(len(f.list_transactions(self.b)),1);self.assertIn('sudah tercatat',self.document().json['title'])
    def test_receipt_pdf(self):
        self.receipt_model();r=self.document(raw=pdf_bytes(text=True),name='a.pdf');self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json['ready'])
    def test_large_real_phone_photo_normalized_original_identity(self):
        raw=io.BytesIO();Image.effect_noise((3000,3000),100).convert('RGB').save(raw,'JPEG',quality=100)
        raw=raw.getvalue();self.assertGreater(len(raw),5*1024*1024);self.assertLess(len(raw),20*1024*1024)
        with self.assertRaises(file_utils.UploadRejected):file_utils.validate_receipt_upload('phone.jpg',raw)
        self.receipt_model();r=self.document(raw=raw,name='phone.jpg');self.assertEqual(r.status_code,200,r.text)
        import base64,hashlib
        provider=base64.b64decode(self.http.call_args.kwargs['json']['messages'][0]['content'][0]['source']['data'])
        self.assertLessEqual(len(provider),4*1024*1024)
        with app.app_context():
            outer=flow.unseal(self.b,self.uid,r.json['context'],'review')
            import finance_receipts
            self.assertEqual(finance_receipts.resolve_token(outer['receipt_token'],self.b,self.uid)['receipt_hash'],hashlib.sha256(raw).hexdigest())
    def test_high_megapixel_phone_image_and_exif(self):
        out=io.BytesIO();image=Image.new('RGB',(6000,4000),'white');exif=Image.Exif();exif[274]=6;image.save(out,'JPEG',exif=exif)
        name,mime,text,raw=file_utils.prepare_finance_document('phone.jpg',out.getvalue())
        with Image.open(io.BytesIO(raw)) as normalized:self.assertLessEqual(max(normalized.size),3200);self.assertGreater(normalized.height,normalized.width)
    def test_corrupt_unsupported_and_oversized_inline(self):
        for raw,name in [(b'corrupt','a.jpg'),(b'executable','a.exe'),(b'%PDF broken','a.pdf')]:
            r=self.document(raw=raw,name=name);self.assertEqual(r.status_code,400);self.assertTrue(r.is_json);self.assertNotIn('Traceback',r.text);self.assertNotIn('<html',r.text)
        self.http.assert_not_called()
        r=self.client.post(self.path+'/document',data=b'x'*(27*1024*1024),content_type='multipart/form-data');self.assertEqual(r.status_code,413);self.assertTrue(r.is_json)
    def test_csv_known_unknown_and_malformed(self):
        r=self.document('BANK_STATEMENT',self.csv,'bank.csv');self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json['count'],1);self.http.assert_not_called();self.assertEqual(f.list_transactions(self.b),[])
        self.model(self.result)
        r=self.document('BANK_STATEMENT',b'Booking date,Details,Debit amount,Credit amount\n2026-09-17,Lunch,100000,0','unknown.csv')
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json['count'],1)
        r=self.document('BANK_STATEMENT',b'date,description,debit,credit\n2026-09-17,"bad,1,0','bad.csv');self.assertEqual(r.status_code,400);self.assertTrue(r.is_json)
    def test_bank_pdf_image_and_scanned_fallback(self):
        self.model(self.result)
        for name,raw in [('a.pdf',pdf_bytes(text=True)),('scan.pdf',pdf_bytes()),('a.png',self.raw)]:
            r=self.document('BANK_STATEMENT',raw,name);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json['kind'],'bank_review');self.assertTrue(r.json['ready']);self.assertIn('token',r.json);self.assertNotIn('review_url',r.json)
        self.assertEqual(f.list_transactions(self.b),[])
    def test_notes_and_uncertain_notes_never_post(self):
        self.model(self.result);r=self.document('HANDWRITTEN_NOTE');self.assertEqual(r.status_code,200);self.assertEqual(r.json['count'],1);self.assertIn('FINANCIAL NOTE',self.http.call_args.kwargs['json']['system'])
        self.model(dict(rows=[],readable=False));r=self.document('HANDWRITTEN_NOTE',pdf_bytes(),'scan.pdf');self.assertEqual(r.status_code,200);self.assertEqual(r.json['count'],0);self.assertTrue(r.json['fallback']);self.assertEqual(f.list_transactions(self.b),[])
    def test_bank_account_ambiguity_then_only_account(self):
        f.create_account(self.b,'Other',actor_user_id=self.uid)
        r=self.document('BANK_STATEMENT',self.csv,'bank.csv');self.assertEqual(r.json['kind'],'document_account');self.assertEqual([f['key'] for f in r.json['fields']],['account_id']);self.http.assert_not_called()
        r=self.document('BANK_STATEMENT',self.csv,'bank.csv',account_id=str(self.a));self.assertEqual(r.json['count'],1)
    def test_bank_duplicate_file_preserves_import(self):
        first=self.document('BANK_STATEMENT',self.csv,'bank.csv').json
        second=self.document('BANK_STATEMENT',self.csv,'bank.csv').json
        self.assertEqual(first['count'],second['count']);self.assertIn('token',first);self.assertIn('token',second);self.assertEqual(len(bank.list_imports(self.b,self.uid)),1)
    def test_bank_chat_confirmation_posts_safe_rows_without_redirect(self):
        r=self.document('BANK_STATEMENT',self.csv,'bank.csv')
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json['kind'],'bank_review')
        self.assertEqual(f.list_transactions(self.b),[])
        done=self.confirm(r.json['token'])
        self.assertEqual(done.status_code,200,done.text)
        self.assertIn('Kilas Finance',done.json['message'])
        self.assertEqual(len(f.list_transactions(self.b)),1)
        again=self.confirm(r.json['token'])
        self.assertEqual(again.status_code,200,again.text)
        self.assertEqual(len(f.list_transactions(self.b)),1)

    def test_upload_recognition_image_pdf_and_csv(self):
        for workflow,raw,name in [('RECEIPT',self.raw,'a.png'),('BANK_STATEMENT',pdf_bytes(),'bank.pdf'),('HANDWRITTEN_NOTE',self.raw,'a.png')]:
            self.model({'workflow':workflow});r=self.client.post(self.path+'/recognize',data={'sources':(io.BytesIO(raw),name),'text':''});self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json['workflow'],workflow)
        self.http.reset_mock();r=self.client.post(self.path+'/recognize',data={'sources':(io.BytesIO(self.csv),'bank.csv')});self.assertEqual(r.json['workflow'],'BANK_STATEMENT');self.http.assert_not_called()
    def test_exact_invoice_payment_reuses_service_once(self):
        customer=f.create_customer(self.b,'Budi',actor_user_id=self.uid)
        ident=f.create_finance_invoice(self.b,customer,date.today().isoformat(),date.today().isoformat(),[dict(description='Desain',quantity=1,unit_price_minor=2000000)],actor_user_id=self.uid)
        f.issue_finance_invoice(self.b,ident,self.uid)
        number=f.get_finance_invoice(self.b,ident,self.uid)['invoice_number']
        r=self.message('Budi bayar invoice '+number+' sebesar 1 juta')
        self.assertEqual(r.status_code,200,r.text)
        if not r.json['ready']:r=self.revise(r.json,category_id=str(self.cat),date=date.today().isoformat())
        self.assertTrue(r.json['ready'],r.json)
        for _ in range(2):self.assertEqual(self.confirm(r.json['token']).status_code,200)
        self.assertEqual(len(f.list_invoice_payments(self.b,ident)),1)
        self.assertEqual(f.get_invoice_totals(self.b,ident)['outstanding_minor'],1000000)
    def test_customer_audit_failure_rolls_back_then_retries(self):
        token=self.message('tambah customer Rollback').json['token']
        original=repo.write_audit
        def fail(*args,**kw):
            if args[2]=='FINANCE_ASSISTANT_CUSTOMER_CONFIRMED':raise RuntimeError('synthetic')
            return original(*args,**kw)
        with patch.object(repo,'write_audit',side_effect=fail):self.assertEqual(self.confirm(token).status_code,503)
        self.assertFalse([c for c in f.list_customers(self.b) if c['name']=='Rollback'])
        self.assertEqual(self.confirm(token).status_code,200)
    def test_pdf_text_timeout_only_falls_back_after_structure_validation(self):
        import subprocess
        run=subprocess.run
        def fail_text(args,**kw):
            if '--validate-only' not in args:raise subprocess.TimeoutExpired(args,8)
            return run(args,**kw)
        with patch.object(subprocess,'run',side_effect=fail_text):
            for validator in (file_utils.validate_bank_pdf,file_utils.validate_receipt_upload):
                with self.assertRaises(file_utils.UploadRejected) as error:validator('bank.pdf',pdf_bytes(text=True))
                self.assertEqual(error.exception.code,'parser_timeout')
    def test_encrypted_pdf_rejected_before_provider(self):
        from pypdf import PdfWriter
        writer=PdfWriter();writer.add_blank_page(100,100);writer.encrypt('password');out=io.BytesIO();writer.write(out)
        r=self.document('BANK_STATEMENT',out.getvalue(),'encrypted.pdf')
        self.assertEqual(r.status_code,400);self.assertTrue(r.is_json);self.assertIn('terenkripsi',r.json['error']);self.http.assert_not_called()
    def test_high_resolution_shared_receipt_recognition_bank_paths(self):
        out=io.BytesIO();Image.new('RGB',(6000,4000),'white').save(out,'JPEG');raw=out.getvalue()
        self.receipt_model()
        r=self.client.post(self.url+'/receipts/analyze',data={'receipt':(io.BytesIO(raw),'phone.jpg')});self.assertEqual(r.status_code,200,r.text)
        self.model({'workflow':'BANK_STATEMENT'})
        r=self.client.post(self.path+'/recognize',data={'sources':(io.BytesIO(raw),'phone.jpg')});self.assertEqual(r.status_code,200,r.text)
        self.model(self.result)
        r=self.client.post(self.url+'/bank-imports/analyze',data={'account_id':str(self.a),'sources':(io.BytesIO(raw),'phone.jpg')});self.assertEqual(r.status_code,302,r.text)
        self.assertEqual(f.list_transactions(self.b),[])
    def test_other_branch_account_not_auto_selected(self):
        other=branches.create_branch(self.b,'Other',self.uid)
        with branches.scope(self.b,other,self.uid):
            f.create_account(self.b,'Other account',actor_user_id=self.uid)
        r=self.client.post(self.path+f'/message?branch_id={self.branch}',json={'text':'catat makan 120rb'})
        self.assertTrue(r.json['ready']);self.assertEqual(next(v['value'] for v in r.json['fields'] if v['key']=='account_id'),str(self.a))
    def test_incomplete_invoice_creation_does_not_invent(self):
        r=self.message('buat invoice Budi jasa desain 2 juta jatuh tempo tanggal 30')
        self.assertEqual(r.status_code,200);self.assertEqual(r.json['kind'],'review');self.assertFalse(r.json['ready']);self.assertNotIn('token',r.json)

    def test_template_and_no_native_handoff(self):
        html=self.client.get(self.path).text
        self.assertEqual(html.count('<textarea'),1);self.assertIn('assistant/message',html);self.assertIn('assistant/document',html)
        self.assertNotIn('id="operator-fields"',html)
        for name in ('finance_assistant.html','finance_receipt.html','finance_bank_detail.html'):app.jinja_env.get_template(name)

if __name__=='__main__':unittest.main()
