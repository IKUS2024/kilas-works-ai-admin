"""Actual shipped Gunicorn worker/config with a synthetic slow Chat provider."""
import json,os,socket,subprocess,sys,tempfile,threading,time
from pathlib import Path
import requests

def main():
    hub=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='chat-http-') as temp:
        out=Path(temp)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        origin=f'http://127.0.0.1:{port}';env={**os.environ,'PYTHONPATH':os.pathsep.join([str(hub),str(hub/'tests')]),'KILAS_CHAT_HTTP_FIXTURE':temp,'CLIENT_HUB_DB_PATH':str(out/'bootstrap.db'),'PYTHONDONTWRITEBYTECODE':'1'}
        with (out/'gunicorn.log').open('w') as log:
            proc=subprocess.Popen([sys.executable,'-m','gunicorn','-c',str(hub/'gunicorn.conf.py'),'--graceful-timeout','3','--bind',f'127.0.0.1:{port}','chat_hardening_wsgi:application'],cwd=hub,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+20
                while not (out/'ready.json').exists() and time.monotonic()<deadline:
                    assert proc.poll() is None,(out/'gunicorn.log').read_text();time.sleep(.03)
                info=json.loads((out/'ready.json').read_text());results=[]
                def send(owner):
                    prefix='' if owner==0 else 'other_'
                    result=requests.post(origin+f'/kilas-ai/threads/{info[prefix+"thread"]}/send',cookies={'session':info[prefix+'cookie']},data={'csrf_token':'work-csrf','content':'Explain API.','operation_key':'hardening_http_0000000'+str(owner),'selected_model':'gpt-6.1-sol'},timeout=10)
                    results.append((result.status_code,'event: done' in result.text))
                workers=[threading.Thread(target=send,args=(owner,)) for owner in range(2)]
                workers[0].start()
                while not (out/'entered').exists() and time.monotonic()<deadline:time.sleep(.01)
                assert (out/'entered').exists()
                workers[1].start()
                start=time.monotonic();health=requests.get(origin+'/healthz',timeout=3);elapsed=time.monotonic()-start
                for worker in workers:worker.join(10);assert not worker.is_alive()
                assert health.status_code==200 and elapsed<.6,(elapsed,health.status_code)
                assert results==[(200,True),(200,True)],results
                print(json.dumps({'workers':1,'worker_class':'gthread','threads':8,'simultaneous_owners':2,'synthetic_provider_delay_seconds':1.5,'health_wait_seconds':round(elapsed,3),'paid_calls':0}))
            finally:
                proc.terminate();proc.wait(timeout=10)
                # Report no fixture cookies or identifiers in public artifacts.
                print('worker_config_verified', 'Using worker: gthread' in (out/'gunicorn.log').read_text())

if __name__=='__main__':main()
