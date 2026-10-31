"""Bounded per-worker Copilot jobs. HTTP polls never wait for provider IO.

No raw audio in the registry, no credentials, no background retries. Durable
operation/primary rows recover final results after process restart. The existing
single-worker deployment is retained; this is not a cross-worker queue.
"""
from copy import deepcopy
from threading import Event, Lock, Thread
from time import monotonic
from . import copilot

_lock = Lock()
_jobs = {}
MAX_JOBS = 32
RESULT_TTL = 300


def _prune():
    for address, job in list(_jobs.items()):
        if job['finished'] and monotonic()-job['finished'] > RESULT_TTL:
            del _jobs[address]


def start(app, owner, ident, operation_key, factory, release):
    address=(owner,ident,operation_key)
    with _lock:
        _prune()
        if len(_jobs)>=MAX_JOBS:
            finished=sorted(((k,v) for k,v in _jobs.items() if v['finished']),key=lambda pair:pair[1]['finished'])
            for key,_ in finished[:max(0,len(_jobs)-MAX_JOBS+1)]:del _jobs[key]
        if len(_jobs)>=MAX_JOBS:
            raise copilot.CopilotError('server_busy',503)
        stopped=Event()
        job={'stop':stopped,'finished':None,'snapshot':{'state':'processing','text':'','stage':'transcription','version':0,'statuses':[]}}
        _jobs[address]=job
    def run():
        iterator=None;terminal={'state':'failed','code':'incomplete_stream'}
        with app.app_context():
            try:
                iterator=factory(stopped.is_set)
                for event in iterator:
                    with _lock:
                        view=job['snapshot'];view['version']+=1
                        if event['type']=='status':
                            view['status_text']=event['text']
                            if event['text'] not in view['statuses']:view['statuses'].append(event['text'])
                            view['stage']='translation' if event['text']=='Menerjemahkan…' else 'reply' if event['text']=='Menyiapkan saran jawaban…' else 'transcription'
                        elif event['type']=='delta':view['text']=(view['text']+event['text'])[:4000]
                        elif event['type']=='primary_complete':view['primary']=event['turn']
                        elif event['type']=='complete':terminal={'state':'complete','result':event}
                        elif event['type']=='error':terminal={'state':'failed','code':event['code']}
            except Exception:
                terminal={'state':'failed','code':'provider_failed'}
            finally:
                try:
                    if iterator is not None:iterator.close()
                finally:
                    release()
                    with _lock:
                        job['snapshot'].update(terminal);job['snapshot']['version']+=1
                        job['finished']=monotonic()
    try:Thread(target=run,name='copilot-background',daemon=True).start()
    except Exception:
        with _lock:_jobs.pop(address,None)
        raise


def cancel(owner, ident, operation_key):
    with _lock:
        if job:=_jobs.get((owner,ident,operation_key)):job['stop'].set()


def snapshot(owner, ident, operation_key):
    # The route validates ownership before consulting this process-local cache.
    with _lock:
        _prune()
        job=_jobs.get((owner,ident,operation_key))
        return deepcopy(job['snapshot']) if job else None
