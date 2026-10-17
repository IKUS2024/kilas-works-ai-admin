"""Code-first workspace contracts. Synthetic inputs, forbidden external transport."""
import base64
import io
import json
import os
import stat
import threading
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from werkzeug.datastructures import FileStorage
import test_kilas_chat_models as fixture
from kilas_ai import workspace_files as files,workspace_projects as projects,workspace_model_tools as native
from kilas_ai import work_office,work_artifacts,work_attachments,selected_image,image_models,workspace_streams,workspace_execution
from kilas_ai import autonomous_store as jobs,autonomous_runner as runner,autonomous_planner as planner,agent_store
import db
import app as application


class WorkspaceTests(unittest.TestCase):
    setUp=fixture.RouteTests.setUp
    client=fixture.RouteTests.client
    submit=fixture.RouteTests.submit

    def test_real_zip_roundtrip_paths_and_no_source_execution(self):
        source={'README.md':'# Example\nRun tests locally.','src/main.py':'raise RuntimeError("must never execute")\n','package.json':'{"scripts":{"test":"node test.js"}}'}
        raw=files.package(source);self.assertEqual(files.read_archive(raw),source)
        self.assertIn('not executed',files.describe(source))
        self.assertFalse(workspace_execution.capability()['available'])
        for name in ('../oops.py','/etc/passwd','.env','a/../../x.js','a\\x.py','node_modules/a.js','a/.git/x.py'):
            with self.subTest(name=name),self.assertRaises(ValueError):files.package({name:'x'})
        with self.assertRaises(SyntaxError):files.package({'broken.py':'def broken('})

    def test_malicious_archives_rejected_before_provider(self):
        for kind in ('traversal','symlink','duplicate','bomb'):
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
                if kind=='traversal':archive.writestr('../oops.py','x')
                elif kind=='symlink':
                    info=zipfile.ZipInfo('link.py');info.external_attr=(stat.S_IFLNK|0o777)<<16;archive.writestr(info,'/etc/passwd')
                elif kind=='duplicate':archive.writestr('A.py','x');archive.writestr('a.py','y')
                else:archive.writestr('large.txt','x'*300000)
            with self.subTest(kind=kind),self.assertRaises(ValueError):files.read_archive(out.getvalue())
        with self.assertRaises(Exception):work_attachments.prepare_many([FileStorage(io.BytesIO(b'not zip'),filename='bad.zip',content_type='application/zip')],'PRO')

    def test_upload_source_and_zip_coverage_and_removal_contract(self):
        raw=files.package({'README.md':'# Project\nSynthetic input','src/main.ts':'export const ready = true;\n'})
        items=work_attachments.prepare_many([FileStorage(io.BytesIO(raw),filename='project.zip',content_type='application/zip'),FileStorage(io.BytesIO(b'print("source only")'),filename='main.py',content_type='text/x-python')],'PRO')
        self.assertEqual(len(items),2);self.assertEqual(items[0]['content'],raw)
        self.assertIn('src/main.ts',items[0]['extracted_text']);self.assertIn('not executed',items[0]['extracted_text'])
        page=self.client().get('/kilas-ai/agent').text
        self.assertIn('.zip,.md,.json,.html,.css,.js',page);self.assertIn('maxlength="24000"',page)

    def test_xlsx_real_formulas_and_charts_without_external_formula_execution(self):
        from openpyxl import load_workbook
        source=json.dumps({'sheets':[{'name':'Budget','rows':[['Item','Amount'],['One',12],['Two',30],['Total','=SUM(B2:B3)']],
                                      'charts':[{'type':'bar','data_column':2,'label_column':1,'title':'Budget'}]}]})
        artifact=work_office.render(source,'xlsx');work_artifacts.validate(artifact)
        book=load_workbook(io.BytesIO(artifact['content']),data_only=False)
        self.assertEqual(book['Budget']['B4'].value,'=SUM(B2:B3)');self.assertEqual(len(book['Budget']._charts),1)
        self.assertTrue(book.calculation.fullCalcOnLoad)
        for formula in ('=HYPERLINK("https://bad","x")','=WEBSERVICE("https://bad")',"=cmd|' /C calc'!A0",'=[other.xlsx]Sheet1!A1','=INDIRECT(A1)','=SUM(AA1:AA2)'):
            with self.subTest(formula=formula),self.assertRaises(ValueError):work_office.checked_formula(formula)
        with self.assertRaises(ValueError):work_office.render('Name,Value\nx,=SUM(B2:B3)','xlsx')

    def test_native_provider_tool_payload_and_exact_model_response(self):
        for model in ('gpt-6.1-sol','claude-sonnet-5-5','gemini-4-argon'):
            provider=fixture.models.spec(model)['provider'];history=native.initial(provider,'Build a synthetic source project')
            data=({'model':model,'status':'completed','output':[{'type':'function_call','call_id':'call1','name':'list_files','arguments':'{}'}],'usage':{'input_tokens':10,'output_tokens':20}} if provider=='openai' else
                  {'model':model,'stop_reason':'tool_use','content':[{'type':'tool_use','id':'call1','name':'list_files','input':{}}],'usage':{'input_tokens':10,'output_tokens':20}} if provider=='anthropic' else
                  {'modelVersion':model,'candidates':[{'finishReason':'STOP','content':{'role':'model','parts':[{'functionCall':{'name':'list_files','args':{}}}]}}],'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':20}})
            with self.subTest(model=model),patch.dict(os.environ,{key:'synthetic' for key in fixture.models.KEYS.values()}),patch.object(native.requests,'post',return_value=SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)) as post:
                result=native.turn(model,history,'Use only registered tools')
            self.assertEqual(result['calls'][0]['name'],'list_files');self.assertEqual(result['model_provenance']['requested_model'],model)
            self.assertEqual(post.call_count,1)
            if provider=='openai':self.assertTrue(post.call_args.args[0].endswith('/responses'));self.assertEqual(post.call_args.kwargs['json']['model'],model)
            native.tool_results(provider,history,[(result['calls'][0],{'files':[]})]);self.assertGreater(len(history),2)

    def test_project_real_tools_publish_once_persist_zip_and_preview_auth(self):
        request='Create a website project ZIP with a useful README and self-contained HTML'
        self.assertEqual(self.submit('gpt-6.1-sol',request).status_code,303)
        job=jobs.list_jobs(self.owner)[0];claimed=jobs.claim_due(1);runner.execute(*claimed[0])
        self.assertEqual(jobs.steps(job['id'])[-1]['worker'],'PROJECT')
        calls=[{'calls':[{'id':'a','name':'list_files','arguments':{}}],'usage':{'input_tokens':100,'output_tokens':50},'model_provenance':{'requested_model':'gpt-6.1-sol','returned_model':'gpt-6.1-sol','provider':'openai'}},
               {'calls':[{'id':'b','name':'publish_project','arguments':{'files':[{'name':'README.md','content':'# Example\nUse a browser to open index.html. Tests not run.'},{'name':'index.html','content':'<!doctype html><html><title>Example</title><body><h1>Example</h1><script>document.body.dataset.ready="true"</script></body></html>'}]}}], 'usage':{'input_tokens':100,'output_tokens':100},'model_provenance':{'requested_model':'gpt-6.1-sol','returned_model':'gpt-6.1-sol','provider':'openai'}}]
        with patch.object(native,'turn',side_effect=calls) as dispatch:
            runner.execute(*jobs.claim_due(1)[0])
            self.assertEqual(dispatch.call_count,2)
        self.assertEqual(jobs.get(self.owner,job['id'])['status'],'COMPLETED')
        artifacts=work_artifacts.listing(self.owner,job_id=job['id']);self.assertEqual(len(artifacts),2)
        zip_artifact=next(a for a in artifacts if a['media_type']=='application/zip');html=next(a for a in artifacts if a['media_type']=='text/html')
        client=self.client();download=client.get(f'/kilas-ai/agent/jobs/{job["id"]}/artifacts/{zip_artifact["id"]}?download=1')
        self.assertIn('index.html',files.read_archive(download.data));self.assertIn('execution',work_artifacts.source(self.owner,zip_artifact['id'],self.conversation))
        url=f'/kilas-ai/agent/jobs/{job["id"]}/artifacts/{html["id"]}/preview';preview=client.get(url)
        self.assertEqual(preview.status_code,200);self.assertIn("connect-src 'none'",preview.headers['Content-Security-Policy']);self.assertNotIn('allow-same-origin',preview.headers['Content-Security-Policy'])
        self.assertEqual(self.client(self.other).get(url).status_code,404)
        page=client.get('/kilas-ai/agent').text;self.assertIn('sandbox="allow-scripts"',page)

    def test_generation_failure_is_terminal_not_automatically_retried(self):
        self.submit('gpt-6.1-sol','Create a website project ZIP with README')
        job=jobs.list_jobs(self.owner)[0];runner.execute(*jobs.claim_due(1)[0])
        with patch.object(native,'turn',side_effect=fixture.providers.ProviderError('timeout')) as dispatch:
            runner.execute(*jobs.claim_due(1)[0]);self.assertEqual(dispatch.call_count,1)
        self.assertEqual(jobs.get(self.owner,job['id'])['status'],'FAILED');self.assertEqual(jobs.claim_due(1),[])

    def test_image_edit_passes_two_original_inputs_without_fallback(self):
        source=io.BytesIO();Image.new('RGB',(20,12),'blue').save(source,'PNG');raw=source.getvalue()
        output=io.BytesIO();Image.new('RGB',(1024,1024),'green').save(output,'PNG')
        sources=[{'filename':'first.png','mime_type':'image/png','content':raw},{'filename':'second.png','mime_type':'image/png','content':raw+b''}]
        for model in ('gpt-image-2','gemini-3-pro-image'):
            data=({'model':model,'data':[{'b64_json':base64.b64encode(output.getvalue()).decode()}]} if model.startswith('gpt') else {'modelVersion':model,'candidates':[{'finishReason':'STOP','content':{'parts':[{'inlineData':{'mimeType':'image/png','data':base64.b64encode(output.getvalue()).decode()}}]}}]})
            with patch.object(image_models,'check',return_value={'available':True}),patch.dict(os.environ,{'OPENAI_API_KEY':'synthetic','GEMINI_API_KEY':'synthetic'}),patch.object(selected_image.requests,'post',return_value=SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)) as post:
                result=selected_image.generate(model,'Change the backgrounds using both references',sources)
            self.assertEqual(post.call_count,1);self.assertEqual(result['image_options']['reference_count'],2)
            if model.startswith('gpt'):self.assertEqual([part[1][1] for part in post.call_args.kwargs['files']],[raw,raw])
            else:self.assertEqual([base64.b64decode(p['inlineData']['data']) for p in post.call_args.kwargs['json']['contents'][0]['parts'][1:]],[raw,raw])

    def test_durable_stream_replay_is_owned_and_cancellation_not_regeneration(self):
        client=self.client();calls=[]
        def output():
            calls.append('one');yield {'type':'delta','text':'Synthetic streamed answer'};yield {'type':'done'}
        class InlineThread:
            def __init__(self,target,args,**kwargs):self.target=target;self.args=args
            def start(self):self.target(*self.args)
        from auth_test_helpers import authenticate
        with application.app.test_request_context('/kilas-ai/work/streams'):
            from flask import session
            session['user_id']=self.owner
            with patch.object(workspace_streams.threading,'Thread',InlineThread):response=workspace_streams.start(self.owner,self.conversation,'synthetic-stream-123456',output())
            ident=int(response.headers['X-Workspace-Stream'])
            response.close()
        replay=client.get('/kilas-ai/work/streams/'+str(ident));self.assertIn('Synthetic streamed answer',replay.text);self.assertEqual(calls,['one'])
        self.assertEqual(self.client(self.other).get('/kilas-ai/work/streams/'+str(ident)).status_code,404)
        self.assertNotEqual(client.post('/kilas-ai/work/streams/'+str(ident)+'/cancel').status_code,200)
        with application.app.test_request_context('/kilas-ai/work/streams'):
            from flask import session
            session['user_id']=self.owner
            replay_response=workspace_streams.start(self.owner,self.conversation,'synthetic-stream-123456',output())
            self.assertEqual(replay_response.headers['X-Workspace-Stream'],str(ident));replay_response.close()
        self.assertEqual(calls,['one'])

    def test_cancel_fences_stream_and_cannot_repeat_provider(self):
        ident=db.query_one('INSERT INTO kilas_workspace_streams(user_id,conversation_id,operation_key,created_at,updated_at) VALUES (?,?,?,?,?) RETURNING id',(self.owner,self.conversation,'cancel-1234567890',jobs.stamp(),jobs.stamp()))['id']
        calls=[]
        def output():
            calls.append(1);yield {'type':'delta','text':'First partial.'}
            db.execute('UPDATE kilas_workspace_streams SET cancel_requested=1 WHERE id=?',(ident,))
            yield {'type':'delta','text':'This must not be streamed.'}
        workspace_streams._slots.acquire()
        workspace_streams._run(application.app,ident,output())
        self.assertEqual(db.query_one('SELECT state FROM kilas_workspace_streams WHERE id=?',(ident,))['state'],'CANCELLED')
        replay=self.client().get('/kilas-ai/work/streams/'+str(ident)).text
        self.assertNotIn('This must not be streamed',replay);self.assertIn('CANCELLED',replay);self.assertEqual(calls,[1])


if __name__=='__main__':unittest.main()
