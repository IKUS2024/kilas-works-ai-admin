"""Actual thread composer/worker/download contracts; provider and E2B mocked."""
import base64,io,json,os,unittest,zipfile
from types import SimpleNamespace
from unittest.mock import patch
import test_kilas_chat_models as fixture
import test_kilas_workspace_execution as remote
import db
from test_kilas_sandbox_binary_artifacts import frames
from kilas_ai import thread_projects as bridge,workspace_execution as execution,workspace_model_tools as native
from kilas_ai import autonomous_store as jobs,store,providers,usage

PROMPT='Buat laporan penjualan: Kopi 10 unit harga 20000 biaya 12000; Teh 8 unit harga 15000 biaya 7000; Roti 5 unit harga 18000 biaya 10000. Jalankan Python di sandbox tanpa internet, hitung revenue/cost/profit. Buat HTML dan CSV serta ZIP untuk diunduh.'
HTML=b'<!doctype html><html><head><title>Sales</title></head><body><h1>Sales</h1><p>Revenue 410000 Cost 226000 Profit 184000</p></body></html>'
CSV=b'item,revenue,cost,profit\nTotal,410000,226000,184000\n'
SOURCE={'README.md':'# Sales\nRun main.py. Synthetic data only.','main.py':'from pathlib import Path\nPath("output").mkdir(exist_ok=True)\nPath("output/report.html").write_text("Sales 410000 226000 184000")\n'}


class ThreadProjects(unittest.TestCase):
    setUp=remote.ExecutionTests.setUp
    client=fixture.RouteTests.client
    submit=fixture.RouteTests.submit
    sandbox=remote.ExecutionTests.sandbox
    enabled=remote.ExecutionTests.enabled

    def post(self,prompt=PROMPT,key='thread_project_once_00000001',client=None):
        return (client or self.client()).post(f'/kilas-ai/threads/{self.thread}/send',data={'content':prompt,'operation_key':key,'selected_model':'gpt-6-luna','csrf_token':'work-csrf'})

    def provider(self):
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'model':'gpt-6-luna','status':'completed','output':[{'type':'function_call','call_id':'publish','name':'publish_project','arguments':json.dumps({'files':[{'name':n,'content':v} for n,v in SOURCE.items()]})}],'usage':{'input_tokens':100,'output_tokens':200}})

    def test_actual_thread_post_native_tool_vm_artifacts_download_reload_idempotent(self):
        outputs=frames({'report.html':HTML,'sales.csv':CSV})
        report={'exit_code':0,'stdout':'410000 226000 184000\n','stderr':'','timed_out':False,'outputs':{n:base64.b64encode(v.encode()).decode() for n,v in outputs.items()}}
        sandbox=self.sandbox(report);create=self.enabled(sandbox)
        with patch.object(native.requests,'post',return_value=self.provider()) as model,patch.object(providers,'stream',side_effect=AssertionError('ordinary Chat must not run')):
            response=self.post();self.assertEqual(response.status_code,200);self.assertIn('event: job',response.text)
            job=jobs.list_jobs(self.owner)[0];checkpoint=json.loads(job['checkpoint_json'])
            self.assertEqual(checkpoint['origin_thread_id'],self.thread);self.assertEqual(checkpoint['author_model'],'gpt-6-luna')
            self.assertIsNone(job['origin_conversation_id']);self.assertEqual(model.call_count,0)
            result=self.client().post(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}/start',data={'csrf_token':'work-csrf'})
            self.assertEqual(result.status_code,200);self.assertTrue(result.json['started'])
            self.assertEqual(model.call_count,1);self.assertEqual(create.call_count,1)
            self.assertEqual(model.call_args.args[0],'https://api.openai.com/v1/responses')
            self.assertEqual(model.call_args.kwargs['json']['model'],'gpt-6-luna');self.assertIn('tools',model.call_args.kwargs['json'])
            self.assertIn('output/report.html',str(sandbox.files.write.call_args_list))
            self.assertEqual(jobs.get(self.owner,job['id'])['status'],'COMPLETED')
            status=self.client().get(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}').json
            self.assertIn('report.html',[f['filename'] for f in status['files']]);self.assertIn('execution-output.zip',[f['filename'] for f in status['files']])
            for item in status['files']:
                data=self.client().get(item['url']);self.assertEqual(data.status_code,200);self.assertIn('attachment;',data.headers['Content-Disposition'])
                self.assertEqual(self.client(self.other).get(item['url']).status_code,404)
                if item['filename']=='report.html':self.assertEqual(data.data,HTML);self.assertIn("default-src 'none'",data.headers['Content-Security-Policy'])
                if item['filename']=='execution-output.zip':
                    with zipfile.ZipFile(io.BytesIO(data.data)) as archive:self.assertEqual(archive.read('sales.csv'),CSV)
            self.assertIn('data-workspace-job=',self.client().get(f'/kilas-ai/threads/{self.thread}').text)
            self.assertIn('event: job',self.post().text)
            self.client().post(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}/start',data={'csrf_token':'work-csrf'})
            self.assertEqual(model.call_count,1);self.assertEqual(create.call_count,1);sandbox.kill.assert_called_once()
            self.assertEqual(len(db.query_all("SELECT * FROM kilas_ai_usage WHERE user_id=? AND operation_type='CHAT'",(self.owner,))),1)
            self.assertEqual(len(jobs.list_jobs(self.owner)),1)

    def test_plain_outcome_intent_and_discussion_negation(self):
        for text in ('Buat laporan penjualan dan jadikan ZIP','Create a sales report and provide CSV and ZIP','Crea un informe de ventas y genera ZIP','生成销售报告并制作ZIP','Buat website lalu berikan ZIP',PROMPT):
            self.assertTrue(bridge.requested(text),text)
        for text in ('Apa itu Python dan ZIP?','Jelaskan cara membuat ZIP dengan Python','Jangan buat file baru. Jelaskan laporan ini.',"Don't create a ZIP; explain it.",'Can you create a ZIP?'):
            self.assertFalse(bridge.requested(text),text)

    def test_foreign_thread_disabled_quota_and_provider_failure_never_create_vm(self):
        sandbox=self.sandbox();create=self.enabled(sandbox)
        self.assertEqual(self.post(client=self.client(self.other)).status_code,404)
        with patch.object(execution,'capability',return_value={'available':False}),patch.object(native.requests,'post') as model:
            self.assertEqual(self.post().status_code,429);model.assert_not_called()
        response=self.post();self.assertEqual(response.status_code,200);job=jobs.list_jobs(self.owner)[0]
        with patch.object(usage,'reserve',side_effect=usage.UsageLimit('Kapasitas Premium belum cukup.')),patch.object(native.requests,'post') as model:
            self.client().post(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}/start',data={'csrf_token':'work-csrf'});model.assert_not_called()
        self.assertEqual(jobs.get(self.owner,job['id'])['status'],'FAILED');create.assert_not_called()
        self.assertEqual(self.client(self.other).get(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}').status_code,404)

    def test_model_without_tool_result_is_honest_terminal_failure_and_cancel_is_not_retry(self):
        create=self.enabled(self.sandbox());self.post();job=jobs.list_jobs(self.owner)[0]
        response=SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'model':'gpt-6-luna','status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'I cannot run code'}]}],'usage':{'input_tokens':10,'output_tokens':10}})
        with patch.object(native.requests,'post',return_value=response) as model:
            self.client().post(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}/start',data={'csrf_token':'work-csrf'})
            self.assertEqual(model.call_count,1)
        self.assertEqual(jobs.get(self.owner,job['id'])['status'],'FAILED');create.assert_not_called()
        self.assertFalse(self.client().get(f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}').json['files'])
        self.post(key='thread_project_cancel_00000002');second=jobs.list_jobs(self.owner)[0]
        self.client().post(f'/kilas-ai/threads/{self.thread}/jobs/{second["id"]}/stop',data={'csrf_token':'work-csrf'})
        result=self.client().post(f'/kilas-ai/threads/{self.thread}/jobs/{second["id"]}/start',data={'csrf_token':'work-csrf'})
        self.assertFalse(result.json['started']);create.assert_not_called()

    def test_context_upload_scope_normal_chat_and_json_csrf(self):
        self.enabled(self.sandbox())
        store.append_user_once(self.owner,self.thread,'Earlier fact: sales use rupiah.','FAST','earlier_thread_fact_000001')
        client=self.client()
        response=client.post(f'/kilas-ai/threads/{self.thread}/send',data={'content':'Buat laporan penjualan dan jadikan ZIP','operation_key':'thread_upload_context_000001','selected_model':'gpt-6-luna','csrf_token':'work-csrf','attachments':(io.BytesIO(b'Units: 10. Price: 20000.'),'sales.txt')})
        self.assertEqual(response.status_code,200)
        job=jobs.list_jobs(self.owner)[0];checkpoint=json.loads(job['checkpoint_json'])
        from kilas_ai import workspace_projects
        self.assertIn('sales use rupiah',checkpoint['thread_context'])
        self.assertIn('Units: 10',workspace_projects.sources(job,checkpoint)['sales.txt'])
        other_thread=store.create_thread(self.owner)
        self.assertEqual(client.get(f'/kilas-ai/threads/{other_thread}/jobs/{job["id"]}').status_code,404)
        path=f'/kilas-ai/threads/{self.thread}/jobs/{job["id"]}/start'
        self.assertEqual(client.post(path).status_code,400)
        # The real browser uses JSON+CSRF, not a form-only test substitute.
        with patch.object(native.requests,'post',side_effect=native.requests.ConnectionError()):
            self.assertTrue(client.post(path,json={},headers={'X-CSRF-Token':'work-csrf'}).json['started'])
        before=len(jobs.list_jobs(self.owner))
        with patch.object(providers,'stream',side_effect=fixture.answer) as answer:
            result=self.submit('gpt-6-luna','Jelaskan cara membuat ZIP dengan Python.',agent=False)
        self.assertEqual(result.status_code,200);self.assertEqual(answer.call_count,1)
        self.assertEqual(len(jobs.list_jobs(self.owner)),before)
