"""Real Gunicorn stdout visibility without root handlers; synthetic, no provider IO."""
import http.client
import io
import json
import os
from pathlib import Path
import queue
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest


# This temporary standalone WSGI fixture is never registered in the product app.
FIXTURE = r'''
import base64, io, json, logging
from types import SimpleNamespace
from flask import Flask
from PIL import Image
import requests
from kilas_ai import model_policy, vision_experiment as v

def forbidden(*args, **kwargs):
    raise AssertionError('Provider network forbidden in fixture')
requests.sessions.Session.request = forbidden
app = Flask('synthetic_fixture')
app.logger  # Flask installs its own handler, not an application root handler.

@app.get('/healthz')
def health():
    return 'ready'

@app.post('/probe')
def probe():
    output = io.BytesIO()
    Image.new('RGB', (900,1200), 'navy').save(output, 'PNG')
    block = {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode()}}
    context = model_policy.ChatContext([{'role':'user','content':[
        {'type':'text','text':'PRIVATE_PROMPT_MARKER synthetic.png https://private.invalid/source'},block]}])
    context._vision_experiment = v._Grant(v._ISSUER,id(context),'auto',1)
    payload = {'model':v.MODEL,'messages':[{'role':'system','content':'PRIVATE_SYSTEM_MARKER'}]+list(context),
        'reasoning_effort':'medium','max_completion_tokens':8192}
    _, diagnostic = v.begin(context,payload)
    if diagnostic:
        diagnostic.response(SimpleNamespace(status_code=200,headers={
            'x-request-id':'req_synthetic_sink','Authorization':'Bearer SYNTHETIC_KEY_DO_NOT_LOG'}))
        diagnostic.model(v.MODEL)
        diagnostic.tokens({'prompt_tokens':123,'completion_tokens':45,
            'prompt_tokens_details':{'cached_tokens':10,'cache_write_tokens':5},'private':'PRIVATE_USAGE_MARKER'})
        diagnostic.delta();diagnostic.finish('stop');diagnostic.end()
    return {'root_handlers':len(logging.getLogger().handlers),
        'module_handlers':len(v._log.handlers),'last_resort':logging.getLevelName(logging.lastResort.level),
        'begin_accepted':diagnostic is not None,'answer':'PRIVATE_ANSWER_MARKER','provider_calls':0}
'''


class GunicornSinkTests(unittest.TestCase):
    def test_request_and_response_are_visible_before_shutdown_without_root_handlers(self):
        with tempfile.TemporaryDirectory(prefix='vision-gunicorn-') as directory:
            path=Path(directory);(path/'fixture_app.py').write_text(FIXTURE)
            with socket.socket() as reserved:
                reserved.bind(('127.0.0.1',0));port=reserved.getsockname()[1]
            environment=dict(os.environ)
            environment.update(PYTHONPATH=str(Path(__file__).resolve().parents[1]),GUNICORN_CMD_ARGS='',
                DATABASE_URL='',CLIENT_HUB_DB_PATH=str(path/'unused.sqlite'),
                KILAS_AI_VISION_EVAL_BATCH='',OPENAI_API_KEY='synthetic-only')
            process=subprocess.Popen([sys.executable,'-m','gunicorn','fixture_app:app',
                '--bind',f'127.0.0.1:{port}','--workers','1','--threads','1',
                '--timeout','10','--graceful-timeout','2','--error-logfile','-'],
                cwd=directory,env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                text=True,bufsize=1,start_new_session=True)
            events=queue.Queue();captured={'stdout':[],'stderr':[]}
            def read(name,stream):
                for line in stream:captured[name].append(line);events.put((name,line))
            readers=[threading.Thread(target=read,args=(name,stream),daemon=True)
                for name,stream in (('stdout',process.stdout),('stderr',process.stderr))]
            for reader in readers:reader.start()
            def exchange(method,url):
                conn=http.client.HTTPConnection('127.0.0.1',port,timeout=.5)
                try:
                    conn.request(method,url);response=conn.getresponse()
                    return response.status,response.read()
                finally:conn.close()
            try:
                deadline=time.monotonic()+8
                while True:
                    try:
                        status,_=exchange('GET','/healthz')
                        if status==200:break
                    except (OSError,http.client.HTTPException):pass
                    if process.poll() is not None or time.monotonic()>=deadline:
                        self.fail('Synthetic Gunicorn did not start: '+''.join(captured['stderr']))
                    time.sleep(.05)
                status,body=exchange('POST','/probe')
                self.assertEqual(status,200)
                result=json.loads(body)
                self.assertEqual(result['root_handlers'],0)
                self.assertEqual(result['module_handlers'],0)
                self.assertEqual(result['last_resort'],'WARNING')
                self.assertTrue(result['begin_accepted']);self.assertEqual(result['provider_calls'],0)
                records=[];deadline=time.monotonic()+2
                while len(records)<2 and time.monotonic()<deadline:
                    try:name,line=events.get(timeout=.1)
                    except queue.Empty:continue
                    if name=='stdout' and line.startswith('kilas_vision_eval '):
                        records.append(json.loads(line.split(' ',1)[1]))
                self.assertIsNone(process.poll())  # Visibility cannot rely on exit flushing.
                self.assertEqual([record['event'] for record in records],['request','response'])
                self.assertEqual(records[0]['run'],records[1]['run'])
                self.assertEqual(records[0]['requested_model'],'gpt-6-luna')
                self.assertEqual(records[1]['returned_model'],'gpt-6-luna')
                self.assertEqual(records[1]['provider_request_id'],'req_synthetic_sink')
                self.assertEqual(records[1]['usage']['input_tokens'],123)
                self.assertEqual(records[1]['finish_reason'],'stop')
                self.assertEqual(records[0]['images'][0]['width'],900)
                self.assertEqual(records[0]['images'][0]['height'],1200)
                self.assertEqual(result['answer'],'PRIVATE_ANSWER_MARKER')
                combined=''.join(captured['stdout']+captured['stderr'])
                for forbidden in ('PRIVATE_PROMPT_MARKER','PRIVATE_SYSTEM_MARKER','PRIVATE_ANSWER_MARKER',
                        'PRIVATE_USAGE_MARKER','SYNTHETIC_KEY_DO_NOT_LOG','private.invalid','synthetic.png','data:image','base64'):
                    self.assertNotIn(forbidden,combined)
            finally:
                try:os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)
                for reader in readers:reader.join(timeout=1)
                process.stdout.close();process.stderr.close()


if __name__=='__main__':unittest.main()
