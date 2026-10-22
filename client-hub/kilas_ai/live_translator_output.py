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


def begin(owner,ident,key,*,preserve=False):
    # Current service runs one Gunicorn worker/instance. A worker restart loses
    # temporary output and must fail closed, never trigger paid regeneration.
    if not single_worker():raise audio_store.AudioError('Penyimpanan sementara sesi belum tersedia.','session_storage_unavailable',503)
    global _sweeper_started
    with _lock:
        _expire()
        for old in list(_items):
            if not preserve and old[:2]==(owner,ident) and old[2]!=key:del _items[old]
        address=(owner,ident,key)
        if address in _items:raise audio_store.AudioError('Ucapan ini tidak diulang.','duplicate_turn',409)
        if len(_items)>=MAX_ENTRIES:raise audio_store.AudioError('Penyimpanan sementara sedang penuh.','session_storage_busy',503)
        _items[address]={'expires':monotonic()+TTL_SECONDS,'processing':False,'translation_ready':False,'job':None,'text':'','source_text':'','source_language':'','target_language':'','raw':None,'framed':None,'progress':None,'audio_sha256':None}
        if not _sweeper_started:
            threading.Thread(target=_sweep,name='kilas-live-output-expiry',daemon=True).start();_sweeper_started=True


def activate(owner,ident,key):
    if not single_worker():raise audio_store.AudioError('Penyimpanan sementara sesi belum tersedia.','session_storage_unavailable',503)
    with _lock:
        _expire();entry=_items.get((owner,ident,key))
        if not entry:raise audio_store.AudioError('Hasil sementara sesi tidak tersedia.','session_output_expired',409)
        if entry['processing']:raise audio_store.AudioError('Ucapan ini tidak diulang.','duplicate_turn',409)
        entry['processing']=True


def publish_translation(owner,ident,key,result):
    """One complete validated translation, not a partial transcript or audio result."""
    with _lock:
        _expire();entry=_items.get((owner,ident,key))
        if not entry or not entry['processing']:raise audio_store.AudioError('Hasil sementara sesi tidak tersedia.','session_output_expired',409)
        if entry['translation_ready'] and any(entry[name]!=result[field] for name,field in (('text','text'),('source_text','source_text'),('source_language','source_language'),('target_language','target_language'))):
            raise audio_store.AudioError('Terjemahan audio berubah.','translation_failed',409)
        entry.update(text=result['text'],source_text=result['source_text'],source_language=result['source_language'],target_language=result['target_language'],translation_ready=True)


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
        if values.get('raw') is not None:
            import hashlib
            values.update(progress=None,audio_sha256=hashlib.sha256(values['raw']).hexdigest())
        entry.update(values);entry['expires']=monotonic()+TTL_SECONDS
        return True


def discard(owner,ident,key=None):
    with _lock:
        for address in list(_items):
            if address[:2]==(owner,ident) and (key is None or address[2]==key):del _items[address]


def progress_begin(owner,job_id):
    with _lock:
        _expire();entry=next((v for a,v in _items.items() if a[0]==owner and v['job']==job_id),None)
        if not entry or entry['progress'] is not None:raise audio_store.AudioError('Audio tidak tersedia.','session_output_expired',409)
        entry['progress']=bytearray()


def progress_append(owner,job_id,part):
    with _lock:
        _expire();entry=next((v for a,v in _items.items() if a[0]==owner and v['job']==job_id),None)
        if not entry or entry['progress'] is None:raise audio_store.AudioError('Audio tidak tersedia.','session_output_expired',409)
        if len(entry['progress'])+len(part)>20*1024*1024:raise audio_store.AudioError('Audio melebihi batas.','stream_limit',413)
        entry['progress'].extend(part)


def progress_read(owner,ident,key,offset):
    # Immutable byte offsets: repeated GETs cannot create audio, advance a cursor,
    # or cross into another turn. One bounded copy; no waiting HTTP generator.
    with _lock:
        _expire();entry=_items.get((owner,ident,key))
        if not entry:return None
        raw=entry['raw'] if entry['raw'] is not None else entry['progress']
        if raw is None or type(offset) is not int or offset<0 or offset>len(raw):return None
        return bytes(raw[offset:offset+65536]),len(raw),entry['raw'] is not None,entry['audio_sha256']
