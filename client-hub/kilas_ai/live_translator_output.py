"""Bounded RAM-only Live output, scoped to owner/session/turn. Never a file store."""
import os
import shlex
import threading
from time import monotonic
from . import audio_store

TTL_SECONDS=600
MAX_ENTRIES=4
MAX_ENTRY_BYTES=40*1024*1024
ORIGIN='live_session'
_lock=threading.RLock()
_items={}
_sweeper_started=False


def _expire():
    now=monotonic()
    for key in list(_items):
        if _items[key]['expires']<=now:del _items[key]


def _sweep():
    while True:
        threading.Event().wait(30)
        with _lock:_expire()


def single_worker():
    try:
        counts=[int(os.environ.get('WEB_CONCURRENCY','1'))]
        args=iter(shlex.split(os.environ.get('GUNICORN_CMD_ARGS','')))
        for arg in args:
            if arg in ('--workers','-w'):counts.append(int(next(args)))
            elif arg.startswith('--workers='):counts.append(int(arg.split('=',1)[1]))
            elif arg.startswith('-w') and len(arg)>2:counts.append(int(arg[2:].lstrip('=')))
        return all(count==1 for count in counts)
    except (ValueError,StopIteration):return False


def begin(owner,ident,key):
    # Current service runs one Gunicorn worker/instance. A worker restart loses
    # temporary output and must fail closed, never trigger paid regeneration.
    if not single_worker():raise audio_store.AudioError('Penyimpanan sementara sesi belum tersedia.','session_storage_unavailable',503)
    global _sweeper_started
    with _lock:
        _expire()
        for old in list(_items):
            if old[:2]==(owner,ident) and old[2]!=key:del _items[old]
        address=(owner,ident,key)
        if address in _items:raise audio_store.AudioError('Ucapan ini tidak diulang.','duplicate_turn',409)
        if len(_items)>=MAX_ENTRIES:raise audio_store.AudioError('Penyimpanan sementara sedang penuh.','session_storage_busy',503)
        _items[address]={'expires':monotonic()+TTL_SECONDS,'processing':False,'job':None,'text':'','source_text':'','source_language':'','target_language':'','raw':None,'framed':None}
        if not _sweeper_started:
            threading.Thread(target=_sweep,name='kilas-live-output-expiry',daemon=True).start();_sweeper_started=True


def activate(owner,ident,key):
    if not single_worker():raise audio_store.AudioError('Penyimpanan sementara sesi belum tersedia.','session_storage_unavailable',503)
    with _lock:
        _expire();entry=_items.get((owner,ident,key))
        if not entry:raise audio_store.AudioError('Hasil sementara sesi tidak tersedia.','session_output_expired',409)
        if entry['processing']:raise audio_store.AudioError('Ucapan ini tidak diulang.','duplicate_turn',409)
        entry['processing']=True


def bind(owner,ident,key,job,result):
    with _lock:
        _expire();entry=_items.get((owner,ident,key))
        if not entry:raise audio_store.AudioError('Hasil sementara sesi tidak tersedia.','session_output_expired',409)
        entry.update(job=job,text=result['text'],source_text=result.get('source_text',''),source_language=result['source_language'],target_language=result['target_language'])


def get(owner,ident,key):
    with _lock:
        _expire();entry=_items.get((owner,ident,key))
        return dict(entry) if entry else None


def job(owner,job_id):
    with _lock:
        _expire()
        return next((dict(entry) for address,entry in _items.items() if address[0]==owner and entry['job']==job_id),None)


def update(owner,job_id,**values):
    with _lock:
        _expire()
        entry=next((entry for address,entry in _items.items() if address[0]==owner and entry['job']==job_id),None)
        if not entry:return False  # End/expiry must never recreate a deleted entry.
        size=sum(len(values.get(name,entry[name]) or b'') for name in ('raw','framed'))
        if size>MAX_ENTRY_BYTES:raise audio_store.AudioError('Audio sementara melebihi batas.','stream_limit',413)
        entry.update(values);entry['expires']=monotonic()+TTL_SECONDS
        return True


def discard(owner,ident,key=None):
    with _lock:
        for address in list(_items):
            if address[:2]==(owner,ident) and (key is None or address[2]==key):del _items[address]
