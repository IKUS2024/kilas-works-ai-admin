"""Offline Unified Assistant handoff contracts and final Finance safety regressions.

Assistant routing sends metadata only. Browser handoffs use the original endpoints;
these integration tests exercise the same route-then-downstream sequence.
"""
import io
import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import test_finance_phase6b as prior
import finance_assistant as assistant
import finance_analyst as analyst
import finance_operator as operator
import finance_receipts as receipts
import finance_bank_extract as extract
import finance_bank_service as bank
import finance_service as finance
import finance_ai_safety as safety
import file_utils
import db

app = prior.app
ROOT = Path(__file__).resolve().parents[1]


class AssistantTests(unittest.TestCase):
    def setUp(self):
        prior.BankTests.setUp(self)
        env = patch.dict(os.environ, KILAS_FINANCE_ANALYST_BUSINESS_IDS=str(self.b),
                         KILAS_FINANCE_OPERATOR_BUSINESS_IDS=str(self.b))
        env.start(); self.addCleanup(env.stop)
        self.assistant_url = self.url + '/assistant'
        self.op_url = self.url + '/operator'
        self.analysis_url = self.url + '/analyst'

    snapshot = prior.BankTests.snapshot
    ledger = prior.BankTests.ledger
    create = prior.BankTests.create
    rows = prior.BankTests.rows
    imp = prior.BankTests.imp
    tx = prior.BankTests.tx
    fields = prior.BankTests.fields
    post = prior.BankTests.post
    race = prior.BankTests.race
    upload = prior.BankTests.upload
    import_id = prior.BankTests.import_id

    def route(self, text='', mode='auto', files=(), **kwargs):
        return self.client.post(self.assistant_url+'/route',
            json=dict(text=text,mode=mode,files=[{'name':name} for name in files]), **kwargs)

    def analysis(self):
        self.set_model({'observations':[{'text':'Periksa kategori pengeluaran.','refs':['f1']}], 'suggestions':[]})
        return self.client.post(self.analysis_url,json=dict(question='Apa pengeluaran terbesar?',scope='categories',month='2026-09'))

    def set_model(self, result):
        self.response.status_code = 200
        self.response.json.return_value = {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(result)}]}

    def op_payload(self, action='create_expense', **changes):
        payload=dict(action=action,request='catat bensin 300 ribu hari ini',date='2026-09-17',
                     account_id=self.a,category_id=self.expense['id'] if action=='create_expense' else self.cat,invoice_id=None)
        payload.update(changes)
        return payload

    def draft(self, action='create_expense', **changes):
        self.set_model(dict(action=action,amount_text='300 ribu',description='bensin'))
        return self.client.post(self.op_url+'/draft',json=self.op_payload(action,**changes))

    def confirm(self, token, **changes):
        payload=dict(token=token,confirm=True);payload.update(changes)
        return self.client.post(self.op_url+'/confirm',json=payload)

    def receipt(self, filename='receipt.png', raw=None):
        self.set_model(dict(merchant_name='Shop',transaction_date='2026-09-17',total_minor=300000,
            currency='IDR',receipt_number='R-1',description='bensin',suggested_category_name=None,readable=True))
        return self.client.post(self.url+'/receipts/analyze',data={'receipt':(io.BytesIO(self.raw if raw is None else raw),filename)},content_type='multipart/form-data')

    def receipt_token(self, response):
        self.assertEqual(response.status_code,200)
        match=re.search(rb'name="analysis_token" value="([^"]+)"',response.data)
        self.assertIsNotNone(match)
        return match[1].decode()

    def receipt_confirm(self, token, **changes):
        fields=dict(analysis_token=token,confirmed='yes',currency='IDR',amount='300000',occurred_on='2026-09-17',
                    account_id=str(self.a),category_id=str(self.expense['id']),merchant_name='Shop',description='bensin')
        fields.update(changes)
        return self.client.post(self.url+'/receipts/confirm',data=fields)

    def totals(self):
        return finance.get_cashflow_report(self.b,'2026-09-01','2026-09-30',actor_user_id=self.uid)

    def test_authenticated_page_and_primary_dashboard_link(self):
        before=self.snapshot()
        response=self.client.get(self.assistant_url)
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Kilas Finance AI',response.data)
        self.assertIn(self.assistant_url.encode(),self.client.get(self.url).data)
        self.assertEqual(before,self.snapshot());self.http.assert_not_called()

    def test_unauthenticated_access(self):
        client=app.test_client()
        self.assertIn(client.get(self.assistant_url).status_code,(302,401))
        self.assertIn(client.post(self.assistant_url+'/route',json={}).status_code,(302,401))

    def test_beta_gate(self):
        with patch.dict(os.environ,KILAS_FINANCE_BETA='off'):
            self.assertEqual(self.client.get(self.assistant_url).status_code,404)
            self.assertEqual(self.route('apa kabar?').status_code,404)

    def test_membership_access(self):
        with self.client.session_transaction() as session:session['user_id']=self.other_uid
        self.assertIn(self.client.get(self.assistant_url).status_code,(403,404))
        self.assertIn(self.route('apa saldo?').status_code,(403,404))

    def test_assistant_privacy_headers(self):
        for response in (self.client.get(self.assistant_url),self.route('apa saldo?')):
            self.assertEqual(response.headers['Cache-Control'],'private, no-store')
            self.assertEqual(response.headers['Referrer-Policy'],'no-referrer')
            self.assertIn('noindex',response.headers['X-Robots-Tag'])

    def test_no_query_string_workflow(self):
        response=self.client.get(self.assistant_url+'?text=PRIVATE&mode=bank')
        self.assertEqual(response.status_code,302);self.assertNotIn('text=',response.location);self.assertNotIn('mode=',response.location);self.assertIn('branch_id=',response.location)
        self.assertNotIn(b'PRIVATE',response.data)
        self.assertEqual(self.client.post(self.assistant_url+'/route?text=PRIVATE',json={}).status_code,400)

    def test_router_strict_schema_and_enum(self):
        payload={'text':'apa saldo?','mode':'auto','files':[]}
        for update in ({'account_id':self.a},{'mode':'post'},{'files':[{'name':'x.pdf','raw':'PRIVATE'}]}, {'text':None}):
            with self.assertRaises(ValueError):assistant.propose(dict(payload,**update))
        with patch.object(assistant,'classify',return_value='POST_NOW'):
            self.assertEqual(assistant.propose(payload),{'workflow':'NEEDS_CLARIFICATION'})

    def test_router_failure_clarifies(self):
        with patch.object(assistant,'classify',side_effect=RuntimeError('PRIVATE')):
            response=self.route('tolong cek ini',files=['a.pdf'])
        self.assertEqual(response.json['workflow'],'NEEDS_CLARIFICATION')
        self.assertNotIn(b'PRIVATE',response.data);self.http.assert_not_called()

    def test_route_boundary_unexpected_failure_safe(self):
        with patch.object(assistant,'propose',side_effect=RuntimeError('PRIVATE')):
            response=self.route('apa saldo?')
        self.assertEqual(response.json['workflow'],'NEEDS_CLARIFICATION')
        self.assertNotIn(b'PRIVATE',response.data)

    def test_routing_zero_db_or_quota_effect(self):
        before=self.snapshot();quota=dict(safety._RATE)
        for mode in ('auto','ask','record','receipt','bank'):
            self.assertEqual(self.route('tolong cek ini',mode,files=['a.pdf']).status_code,200)
        self.assertEqual(before,self.snapshot());self.assertEqual(quota,safety._RATE);self.http.assert_not_called()

    def test_router_module_has_no_financial_capability(self):
        source=(ROOT/'finance_assistant.py').read_text()
        for token in ('import db','import finance_service','import requests','create_transaction','bank.analyze','receipts.analyze'):
            self.assertNotIn(token,source)

    def test_router_result_only_allowlisted_proposals(self):
        result=self.route('catat bensin 300 ribu').json
        self.assertEqual(set(result),{'workflow','suggested_action'})
        self.assertEqual(result['suggested_action'],'create_expense')
        for field in ('account_id','category_id','invoice_id','amount_minor','token'):self.assertNotIn(field,result)

    def test_analysis_handoff_reuses_original_endpoint(self):
        page=self.client.get(self.assistant_url).data
        self.assertIn(('data-message="'+self.assistant_url+'/message?branch_id=').encode(),page)
        before=self.snapshot()
        self.assertEqual(self.route('pengeluaran terbesar apa?').json['workflow'],'READ_ONLY_ANALYSIS')
        response=self.analysis();self.assertEqual(response.status_code,200)
        self.assertEqual(before,self.snapshot())

    def test_analyst_allowlist_page_and_endpoint(self):
        with patch.dict(os.environ,KILAS_FINANCE_ANALYST_BUSINESS_IDS=''):
            page=self.client.get(self.assistant_url)
            self.assertNotIn(b'id="analyst-form"',page.data)
            self.assertTrue(page.status_code==200)
            self.assertEqual(self.analysis().status_code,404)
        self.http.assert_not_called()

    def test_analyst_no_write_functions(self):
        with patch.object(finance,'_write',side_effect=AssertionError('no write')):
            self.assertEqual(self.route('apa laporan?').json['workflow'],'READ_ONLY_ANALYSIS')
            self.assertEqual(self.analysis().status_code,200)

    def test_analyst_facts_authoritative(self):
        self.tx(amount_minor=42)
        response=self.analysis()
        self.assertEqual(response.status_code,200)
        facts={fact['label']:fact['value'] for fact in response.json['context']['facts']}
        self.assertEqual(facts['Pengeluaran IDR'],42)
        self.assertEqual(facts['Transaksi IDR'],1)

    def test_analyst_invalid_model_numbers_safe(self):
        self.set_model(dict(observations=[{'text':'Sudah dibayar 999','refs':[]}],suggestions=[]))
        response=self.client.post(self.analysis_url,json=dict(question='apa laporan?',month='2026-09',scope='summary'))
        self.assertEqual(response.status_code,503);self.assertEqual(self.ledger(),[])

    def test_expense_proposal_stops_before_draft(self):
        before=self.snapshot();result=self.route('catat bensin 300 ribu').json
        self.assertEqual(result['suggested_action'],'create_expense')
        self.http.assert_not_called();self.assertEqual(before,self.snapshot())

    def test_income_proposal_stops_before_draft(self):
        result=self.route('catat pemasukan 300 ribu').json
        self.assertEqual(result['suggested_action'],'create_income');self.http.assert_not_called()

    def test_invoice_proposal_requires_invoice_selection(self):
        self.assertEqual(self.route('catat pembayaran invoice 300 ribu').json['suggested_action'],'record_invoice_payment')
        response=self.draft('record_invoice_payment')
        self.assertEqual(response.status_code,400);self.http.assert_not_called()

    def test_operator_embedded_controls_blank_references(self):
        page=self.client.get(self.assistant_url).data
        self.assertIn(b'id="assistant-result"',page)
        self.assertNotIn(b'id="op-action"',page)
        self.assertIn((self.assistant_url+'/review').encode(),page)
        self.assertIn((self.assistant_url+'/confirm').encode(),page)

    def test_operator_draft_no_ledger_before_confirm(self):
        before=self.snapshot();self.route('catat bensin 300 ribu')
        response=self.draft();self.assertEqual(response.status_code,200)
        self.assertEqual(before,self.snapshot());self.assertIn('token',response.json)

    def test_operator_confirmation_no_ai_and_idempotent(self):
        token=self.draft().json['token'];self.http.reset_mock()
        first=self.confirm(token);second=self.confirm(token)
        self.assertEqual(first.status_code,200);self.assertEqual(first.json,second.json)
        self.assertEqual(len(self.ledger()),1);self.http.assert_not_called()

    def test_operator_allowlist_preserved(self):
        with patch.dict(os.environ,KILAS_FINANCE_OPERATOR_BUSINESS_IDS=''):
            self.assertNotIn(b'id="operator-form"',self.client.get(self.assistant_url).data)
            self.assertEqual(self.draft().status_code,404)
        self.http.assert_not_called()

    def test_operator_foreign_references_rejected(self):
        foreign_account=finance.list_accounts(self.other)[0]['id']
        foreign_category=finance.list_categories(self.other,'EXPENSE')[0]['id']
        for fields in ({'account_id':foreign_account},{'category_id':foreign_category}):
            self.assertEqual(self.draft(**fields).status_code,400)
        self.http.assert_not_called();self.assertEqual(self.ledger(),[])

    def test_receipt_reuses_validator_and_review(self):
        before=self.snapshot();self.route('ini pengeluaran',files=['receipt.png'])
        with patch.object(file_utils,'validate_receipt_upload',wraps=file_utils.validate_receipt_upload) as validate:
            response=self.receipt()
        validate.assert_called_once();self.assertEqual(before,self.snapshot())
        self.assertIn(b'Nilai akhir yang akan dicatat',response.data);self.assertIn(b'Catat Pengeluaran',response.data)

    def test_receipt_explicit_confirmation_required(self):
        token=self.receipt_token(self.receipt())
        self.assertEqual(self.receipt_confirm(token,confirmed='').status_code,400)
        self.assertEqual(self.ledger(),[])

    def test_receipt_origin_and_duplicate(self):
        token=self.receipt_token(self.receipt())
        self.assertEqual(self.receipt_confirm(token).status_code,302)
        self.assertEqual(self.receipt_confirm(token).status_code,302)
        self.assertEqual(len(self.ledger()),1);self.assertEqual(self.ledger()[0]['source_type'],'FINANCE_RECEIPT')
        self.http.reset_mock();self.receipt();self.http.assert_not_called()

    def test_receipt_token_user_binding(self):
        token=self.receipt_token(self.receipt())
        db.execute('INSERT INTO business_memberships (business_id,user_id,role_in_business) VALUES (?,?,?)',(self.b,self.other_uid,'OWNER'))
        with self.client.session_transaction() as session:session['user_id']=self.other_uid
        self.assertEqual(self.receipt_confirm(token).status_code,400);self.assertEqual(self.ledger(),[])

    def test_receipt_token_business_binding(self):
        token=self.receipt_token(self.receipt())
        with app.test_request_context(),self.assertRaises(ValueError):receipts.resolve_token(token,self.other,self.uid)

    def test_receipt_cannot_skip_analysis(self):
        self.assertEqual(self.receipt_confirm('not-signed').status_code,400)
        self.assertEqual(self.ledger(),[])

    def test_csv_handoff_uses_deterministic_parser(self):
        self.route(files=['bank.csv'])
        with patch.object(extract,'parse_csv',wraps=extract.parse_csv) as parse:
            i=self.import_id(self.upload())
        parse.assert_called_once();self.http.assert_not_called()
        self.assertEqual(self.imp(i)['status'],'REVIEW')

    def test_bank_pdf_handoff_reuses_extraction(self):
        self.route('cocokin mutasi ini',files=['bank.pdf'])
        with patch.object(extract,'extract',wraps=extract.extract) as call:
            i=self.import_id(self.upload([('bank.pdf',prior.pdf_bytes(text=True))]))
        call.assert_called_once();self.assertEqual(self.imp(i)['status'],'REVIEW')

    def test_bank_screenshot_handoff_reuses_extraction(self):
        self.route('mutasi bank',files=['bank.png'])
        with patch.object(extract,'extract',wraps=extract.extract) as call:
            self.import_id(self.upload([('bank.png',self.raw)]))
        call.assert_called_once()

    def test_multi_screenshot_handoff_one_request(self):
        self.route('mutasi bank',files=['a.png','b.jpg'])
        self.import_id(self.upload([('a.png',self.raw),('b.jpg',prior.image_bytes('JPEG'))]))
        self.assertEqual(self.http.call_count,1)

    def test_bank_staging_no_automatic_decisions(self):
        before=self.ledger();self.route(files=['bank.csv'])
        i=self.import_id(self.upload())
        self.assertEqual(self.imp(i)['status'],'REVIEW')
        self.assertEqual(before,self.ledger())
        for row in self.rows(i):
            self.assertEqual(row['reconciliation_status'],'UNMATCHED')
            self.assertIsNone(row['matched_transaction_id']);self.assertIsNone(row['created_transaction_id'])

    def test_bank_explicit_open_still_required(self):
        i=self.import_id(self.upload());rid=self.rows(i)[0]['id']
        with self.assertRaises(ValueError):bank.decide(self.b,i,rid,'ignore',self.uid)
        self.assertEqual(self.client.post(self.base+f'/{i}/open',data={'revision':0}).status_code,400)

    def test_bank_origin_and_exactly_once_totals(self):
        i=self.create();before=self.totals()['total_expense_minor'];first=self.post(i);self.post(i)
        self.assertEqual(self.totals()['total_expense_minor'],before+100000)
        self.assertEqual(finance.get_transaction(self.b,first)['source_type'],'FINANCE_BANK_IMPORT')

    def test_bank_duplicate_source_reuse(self):
        self.route(files=['bank.csv'])
        first=self.import_id(self.upload());second=self.import_id(self.upload())
        self.assertEqual(first,second);self.assertEqual(self.ledger(),[])

    def test_bank_candidates_bounded_and_unchanged(self):
        i=self.create()
        for _ in range(12):self.tx()
        with patch.object(db,'query_all',wraps=db.query_all) as calls:
            result=bank.candidates(self.b,i,self.uid)
        self.assertEqual(len(result[self.rows(i)[0]['id']]),10)
        self.assertEqual(sum('SELECT t.* FROM finance_transactions' in call.args[0] for call in calls.call_args_list),1)

    def test_bank_foreign_import_rejected(self):
        i=self.create()
        with self.client.session_transaction() as session:session['user_id']=self.other_uid
        self.assertEqual(self.client.get(f'/business/{self.other}/finance/bank-imports/{i}').status_code,404)

    def test_ambiguity_no_paid_extraction_or_staging(self):
        before=self.snapshot()
        for filename in ('a.pdf','a.png'):
            result=self.route('tolong cek ini',files=[filename])
            self.assertEqual(result.json['workflow'],'NEEDS_CLARIFICATION')
        self.assertEqual(before,self.snapshot());self.http.assert_not_called()

    def test_clarification_receipt_choice_then_existing_path(self):
        self.route('tolong cek ini',files=['a.png'])
        self.assertEqual(self.route('tolong cek ini','receipt',['a.png']).json['workflow'],'RECEIPT')
        self.http.assert_not_called();self.receipt_token(self.receipt());self.assertEqual(self.ledger(),[])

    def test_clarification_bank_choice_then_existing_path(self):
        self.route('tolong cek ini',files=['a.pdf'])
        self.assertEqual(self.route('tolong cek ini','bank',['a.pdf']).json['workflow'],'BANK_STATEMENT')
        self.http.assert_not_called();i=self.import_id(self.upload([('a.pdf',prior.pdf_bytes())]))
        self.assertEqual(self.imp(i)['status'],'REVIEW');self.assertEqual(self.ledger(),[])

    def test_csrf_required_assistant_and_downstream(self):
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        self.assertEqual(self.route('apa laporan?').status_code,400)
        for suffix in ('/operator/draft','/operator/confirm','/receipts/analyze','/receipts/confirm','/bank-imports/analyze'):
            self.assertEqual(self.client.post(self.url+suffix,json={}).status_code,400)

    def test_valid_assistant_csrf(self):
        app.config['CLIENT_HUB_FORCE_CSRF_IN_TESTS']=True
        self.client.get(self.assistant_url)
        with self.client.session_transaction() as session:token=session['_csrf_token']
        self.assertEqual(self.route('apa laporan?',headers={'X-CSRF-Token':token}).status_code,200)

    def test_xss_user_and_filename_not_reflected_in_router(self):
        response=self.route('<script>alert(1)</script>','receipt',['<img onerror=evil>.png'])
        self.assertEqual(response.status_code,200)
        self.assertNotIn(b'<script',response.data);self.assertNotIn(b'<img',response.data)

    def test_xss_account_name_autoescaped(self):
        finance.create_account(self.b,'<script>evil</script>')
        response=self.client.get(self.assistant_url)
        self.assertEqual(response.status_code,200)  # Choices now arrive as JSON and use textContent (UI test).
        self.assertNotIn(b'<script>evil',response.data)

    def test_safe_router_logs_no_prompt_filename(self):
        with self.assertLogs('kilas.finance_ai',level='INFO') as logs:
            with patch.object(assistant,'propose',side_effect=RuntimeError('PRIVATE ERROR')):
                response=self.route('PRIVATE PROMPT',files=['PRIVATE FILE.pdf'])
        for value in ('PRIVATE ERROR','PRIVATE PROMPT','PRIVATE FILE'):
            self.assertNotIn(value,str(logs.output));self.assertNotIn(value,response.get_data(as_text=True))

    def test_no_raw_attachment_accepted_by_router(self):
        before=self.snapshot()
        response=self.client.post(self.assistant_url+'/route',data={'file':(io.BytesIO(self.raw),'private.png')},content_type='multipart/form-data')
        self.assertEqual(response.status_code,415);self.assertEqual(before,self.snapshot());self.http.assert_not_called()

    def test_provider_error_safe_downstream(self):
        self.http.side_effect=extract.requests.Timeout('PRIVATE PROVIDER KEY')
        response=self.analysis();self.assertEqual(response.status_code,503)
        self.assertNotIn(b'PRIVATE PROVIDER',response.data)
        receipt=self.receipt();self.assertEqual(receipt.status_code,200)
        self.assertNotIn(b'PRIVATE PROVIDER',receipt.data);self.assertEqual(self.ledger(),[])

    def test_text_length_boundaries(self):
        self.assertEqual(self.route('x'*2000,'ask').status_code,200)
        self.assertEqual(self.route('x'*2001,'ask').status_code,400)
        self.assertEqual(self.route('\x00','ask').status_code,400)

    def test_small_request_envelope(self):
        response=self.client.post(self.assistant_url+'/route',data='x'*(16*1024+1),content_type='application/json')
        self.assertEqual(response.status_code,413)

    def test_metadata_bounds(self):
        self.assertEqual(self.route(files=['x.png']*10).status_code,200)
        self.assertEqual(self.route(files=['x.png']*11).status_code,400)
        self.assertEqual(self.route(files=['x'*256]).status_code,400)

    def test_existing_upload_request_limits_preserved(self):
        from flask import request
        for path,limit in ((self.assistant_url+'/route',16*1024),(self.base+'/analyze',26*1024*1024),(self.url+'/receipts/analyze',26*1024*1024)):
            with app.test_request_context(path,method='POST'):
                app.preprocess_request();self.assertEqual(request.max_content_length,limit)

    def test_receipt_byte_limit_not_weakened(self):
        response=self.receipt(raw=b'x'*(5*1024*1024+1))
        self.assertEqual(response.status_code,400);self.http.assert_not_called()

    def test_receipt_pdf_limit_not_weakened(self):
        response=self.receipt('a.pdf',prior.pdf_bytes(11))
        self.assertEqual(response.status_code,400);self.http.assert_not_called()

    def test_bank_pdf_limit_not_weakened(self):
        self.assertEqual(self.upload([('a.pdf',prior.pdf_bytes(21))]).status_code,400)
        self.http.assert_not_called()

    def test_receipt_memory_only_upload(self):
        from flask import request
        with app.test_request_context(self.url+'/receipts/analyze',method='POST',data={'receipt':(io.BytesIO(self.raw+b' '*(600*1024)),'a.png')}):
            self.assertIsInstance(request.files['receipt'].stream,io.BytesIO)

    def test_no_chat_tables_or_migration(self):
        tables={r['name'] for r in db.query_all("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse({'assistant_chat','finance_messages','finance_chat_messages'} & tables)
        # Final product flow explicitly adds independent billing, never Assistant/chat storage.
        for migration in (ROOT/'migrations').glob('0032*'):
            self.assertNotIn('assistant_chat',migration.read_text())
            self.assertIn('finance_entitlements',migration.read_text())

    def test_no_sensitive_session_persistence(self):
        self.route('PRIVATE PROMPT','receipt',['PRIVATE FILE.png'])
        with self.client.session_transaction() as session:
            self.assertNotIn('PRIVATE',str(dict(session)))

    def test_analyst_shared_quota(self):
        for _ in range(6):safety.allow_attempt(self.uid,self.b,'ai')
        self.route('apa laporan?')
        self.assertEqual(self.analysis().status_code,429);self.http.assert_not_called()

    def test_operator_shared_quota(self):
        for _ in range(6):safety.allow_attempt(self.uid,self.b,'ai')
        self.route('catat bensin 300 ribu')
        self.assertEqual(self.draft().status_code,429);self.http.assert_not_called()

    def test_receipt_shared_quota_fallback(self):
        for _ in range(6):safety.allow_attempt(self.uid,self.b,'ai')
        response=self.receipt();self.receipt_token(response)
        self.assertIn(b'Isi semua nilai akhir secara manual',response.data);self.http.assert_not_called()

    def test_bank_shared_quota_fallback(self):
        for _ in range(6):safety.allow_attempt(self.uid,self.b,'ai')
        i=self.import_id(self.upload([('a.png',self.raw)]))
        self.assertEqual(self.rows(i),[]);self.assertEqual(self.imp(i)['status'],'REVIEW');self.http.assert_not_called()

    def test_confirmation_spends_no_ai_quota(self):
        token=self.draft().json['token'];before={k:list(v) for k,v in safety._RATE.items() if k[0]=='ai'}
        self.confirm(token)
        self.assertEqual(before,{k:list(v) for k,v in safety._RATE.items() if k[0]=='ai'})

    def test_quota_cross_workflow_no_endpoint_hopping(self):
        for _ in range(5):safety.allow_attempt(self.uid,self.b,'ai')
        self.assertEqual(self.analysis().status_code,200)
        self.assertEqual(self.draft().status_code,429)
        self.http.reset_mock();self.receipt();self.http.assert_not_called()

    def test_manual_transaction_unchanged(self):
        tx=self.tx(amount_minor=123)
        self.assertEqual(finance.get_transaction(self.b,tx)['amount_minor'],123)
        self.assertEqual(self.totals()['total_expense_minor'],123)

    def test_all_managed_origins_reject_padded_conversion(self):
        tx=self.tx();before=self.snapshot()
        for origin in ('FINANCE_OPERATOR','FINANCE_INVOICE_PAYMENT','FINANCE_RECURRING_EXPENSE','FINANCE_RECEIPT','FINANCE_BANK_IMPORT'):
            with self.subTest(origin=origin),self.assertRaises(ValueError):
                finance.update_transaction(self.b,tx,source_type=' '+origin+' ',source_ref='a'*64)
        self.assertEqual(before,self.snapshot())

    def test_operator_origin_immutable(self):
        tx=self.confirm(self.draft().json['token']).json['record_id']
        for change in ({'source_ref':'b'*32},{'source_type':None}):
            with self.assertRaises(ValueError):finance.update_transaction(self.b,tx,**change)

    def test_receipt_origin_immutable(self):
        self.receipt_confirm(self.receipt_token(self.receipt()));tx=self.ledger()[0]['id']
        with self.assertRaises(ValueError):finance.update_transaction(self.b,tx,source_type=None)

    def test_bank_origin_immutable(self):
        tx=self.post(self.create())
        with self.assertRaises(ValueError):finance.update_transaction(self.b,tx,source_ref='b'*64)

    def test_receipt_analysis_totals_unchanged(self):
        self.tx();before=self.totals();self.receipt();self.assertEqual(before,self.totals())

    def test_bank_staging_totals_unchanged(self):
        self.tx();before=self.totals();self.upload();self.assertEqual(before,self.totals())

    def test_bank_match_totals_unchanged(self):
        tx=self.tx();i=self.create();before=self.totals()
        bank.decide(self.b,i,self.rows(i)[0]['id'],'match',self.uid,transaction_id=tx)
        self.assertEqual(before,self.totals())

    def test_operator_void_replay_no_recreation(self):
        token=self.draft().json['token'];tx=self.confirm(token).json['record_id'];finance.void_transaction(self.b,tx)
        self.confirm(token);self.assertEqual(len(self.ledger()),1)
        self.assertEqual(self.totals()['total_expense_minor'],0)

    def test_receipt_void_no_recreation(self):
        token=self.receipt_token(self.receipt());self.receipt_confirm(token);finance.void_transaction(self.b,self.ledger()[0]['id'])
        self.receipt_confirm(token);self.assertEqual(len(self.ledger()),1);self.assertEqual(self.totals()['total_expense_minor'],0)

    def test_bank_void_no_recreation(self):
        i=self.create();tx=self.post(i);finance.void_transaction(self.b,tx)
        with self.assertRaises(ValueError):self.post(i)
        self.assertEqual(len(self.ledger()),1);self.assertEqual(self.totals()['total_expense_minor'],0)

    def test_all_finance_workspaces_no_store(self):
        for suffix in ('','/assistant','/analyst','/operator','/receipts/new','/bank-imports','/reports','/receivables','/operations'):
            response=self.client.get(self.url+suffix)
            self.assertEqual(response.status_code,200,suffix)
            self.assertEqual(response.headers['Cache-Control'],'private, no-store',suffix)

    def test_concurrent_operator_confirmation(self):
        token=self.draft().json['token']
        def confirm():
            with app.test_request_context():return operator.confirm(self.b,self.uid,token)['record_id']
        results=self.race([confirm,confirm])
        self.assertEqual(results[0],results[1]);self.assertEqual(len(self.ledger()),1)

    def test_mobile_accessible_composer(self):
        page=self.client.get(self.assistant_url).data
        for value in ('id="assistant-composer"','maxlength="2000"','for="assistant-files"','for="assistant-mode"',
                      'role="status"','aria-live="polite"','type="button"','multiple','id="assistant-file-list"'):
            self.assertIn(value.encode(),page)
        css=(ROOT/'static/finance_assistant.css').read_text()
        for value in ('min-height:44px','flex-wrap:wrap','overflow-wrap:anywhere','@media'):self.assertIn(value,css)

    def test_loading_and_double_submit_guard(self):
        js=(ROOT/'static/finance_assistant.js').read_text()
        for value in ('if(busy)','aria-busy',"pending?.context",'if(!pending?.token)', 'setBusy(true)','setBusy(false)'):
            self.assertIn(value,js)

    def test_no_unsafe_dom_or_sensitive_storage(self):
        for filename in ('finance_assistant.js','finance_analyst.js','finance_operator.js'):
            js=(ROOT/'static'/filename).read_text()
            for forbidden in ('innerHTML','localStorage','sessionStorage','console.log','document.write'):
                self.assertNotIn(forbidden,js)
            self.assertIn('textContent',js)

    def test_browser_handoffs_only_existing_engines(self):
        page=self.client.get(self.assistant_url).data
        self.assertIn(('data-recognize="'+self.assistant_url+'/recognize?branch_id=').encode(),page)
        self.assertIn(('data-document="'+self.assistant_url+'/document?branch_id=').encode(),page)
        js=(ROOT/'static/finance_assistant.js').read_text()
        self.assertNotIn('HTMLFormElement.prototype.submit.call(composer)',js)
        self.assertIn('composer.dataset.document',js)
        self.assertNotIn('readAsDataURL',js)
        self.assertNotIn('/confirm',js)

    def test_downstream_strong_signing_configuration(self):
        for key in ('short','dev-only-insecure-secret-key-do-not-use-in-production'):
            with app.test_request_context(),patch.dict(app.config,SECRET_KEY=key,TESTING=False):
                with self.assertRaises(ValueError):operator.prepare(self.b,self.uid,self.op_payload())
                with self.assertRaises(ValueError):receipts.analyze(self.b,self.uid,'a.png',self.raw)
        self.http.assert_not_called()


ROUTING_CASES = {
    'explicit_ask': ('catat pengeluaran','ask',[], 'READ_ONLY_ANALYSIS'),
    'explicit_record': ('apa laporan?','record',[], 'TEXT_OPERATOR'),
    'explicit_receipt': ('mutasi bank','receipt',['a.pdf'], 'RECEIPT'),
    'explicit_bank': ('ini struk','bank',['a.png'], 'BANK_STATEMENT'),
    'csv_auto': ('','auto',['a.csv'], 'BANK_STATEMENT'),
    'receipt_auto': ('ini pengeluaran','auto',['a.png'], 'RECEIPT'),
    'bank_pdf_auto': ('cocokin mutasi ini','auto',['a.pdf'], 'BANK_STATEMENT'),
    'bank_multi_auto': ('mutasi bank','auto',['a.png','b.png'], 'BANK_STATEMENT'),
    'ambiguous_pdf': ('tolong cek ini','auto',['a.pdf'], 'NEEDS_CLARIFICATION'),
    'ambiguous_image': ('tolong cek ini','auto',['a.png'], 'NEEDS_CLARIFICATION'),
    'ambiguous_text': ('tolong','auto',[], 'NEEDS_CLARIFICATION'),
    'conflicting_file_intent': ('struk atau mutasi bank','auto',['a.pdf'], 'NEEDS_CLARIFICATION'),
    'unsupported_archive': ('mutasi','auto',['a.zip'], 'UNSUPPORTED'),
    'unsupported_svg': ('struk','receipt',['a.svg'], 'UNSUPPORTED'),
    'analysis_auto': ('bulan ini pengeluaran terbesar apa?','auto',[], 'READ_ONLY_ANALYSIS'),
    'operator_auto': ('catat bensin 300 ribu hari ini','auto',[], 'TEXT_OPERATOR'),
    'transfer_unsupported': ('transfer uang ke bank','auto',[], 'UNSUPPORTED'),
    'question_about_recording': ('bagaimana catat bensin?','auto',[], 'NEEDS_CLARIFICATION'),
}


def routing_case(text, mode, files, expected):
    def test(self):
        response=self.route(text,mode,files)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['workflow'],expected)
        self.http.assert_not_called();self.assertEqual(self.ledger(),[])
    return test


for name, values in ROUTING_CASES.items():
    setattr(AssistantTests,'test_routing_'+name,routing_case(*values))


if __name__ == '__main__':
    unittest.main()
