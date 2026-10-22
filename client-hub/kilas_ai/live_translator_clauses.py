"""Committed-clause output during input. RAM queue, durable per-clause admission.

No partial transcript is translated. Spoken clauses are immutable; later words
are translated with bounded prior context, never used to regenerate old audio.
"""
import hashlib
import re
from threading import Condition, Thread
from time import monotonic
import db
from . import audio_store, live_translator_store as sessions, live_translator_output as output

_items = {}
_lock = Condition()
MAX_PENDING = 2  # Backpressure, not a session/turn-count limit.


def failure(code='clause_backpressure'):
    return audio_store.AudioError('Input dan audio tertinggal. Sesi dijeda; ucapan tidak diulang otomatis.', code, 503)


class Stream:
    def __init__(self, owner, ident, key, info):
        self.owner, self.ident, self.key, self.info = owner, ident, key, info
        self.condition = Condition()
        self.pending = []
        self.entries = []
        self.next_index = 0
        self.acked = -1
        self.tail = ''
        self.previous = None
        self.final = False
        self.cancelled = False
        self.error = None
        self.done = False
        self.last_read = monotonic()
        from .live_translator_clause_audio import Audio
        self.audio=Audio(self)
        self.worker = Thread(target=self.run, name='kilas-committed-clauses', daemon=True)

    def check(self):
        if self.cancelled:raise failure('turn_cancelled')
        if self.error:raise self.error
        if monotonic()-self.last_read > 15:raise failure('clause_client_disconnected')
        sessions.check(self.owner, self.ident, self.key)

    def offer(self, text, final=False):
        # Only Relay.acknowledge supplies provider-committed text here.
        with self.condition:
            self.check()
            self.tail = ' '.join(p for p in (self.tail, text.strip()) if p)
            if len(self.tail)>1200:raise failure('clause_text_limit')
            # Keep an unfinished final sentence across provider segment commits.
            matches=[]
            for match in re.finditer(r'[.!?。！？؟।]+[\"\u201d\u2019)]*(?:\s+|$)', self.tail):
                word=re.search(r'([\w.]+)$',self.tail[:match.start()])
                if self.tail[match.start()]=='.' and word and (len(word[1])==1 or word[1].lower() in ('dr','mr','mrs','ms','prof','jr','sr','st','vs','etc','e.g','i.e')):continue
                matches.append(match)
            end=matches[-1].end() if matches else 0
            if final:end=len(self.tail)
            if end:
                if len(self.pending)+len(self.entries)>=MAX_PENDING:raise failure()
                self.pending.append(self.tail[:end].strip())
                self.tail=self.tail[end:].strip()
            if final:self.final=True
            self.condition.notify_all()

    def snapshot(self):
        with self.condition:
            self.last_read=monotonic()
            if self.error:raise self.error
            if self.cancelled:raise failure('turn_cancelled')
            return {'status':'COMPLETED' if self.done else 'PROCESSING',
                    'clauses':[dict(e) for e in self.entries], 'acked':self.acked}

    def ack(self, index):
        with self.condition:
            if index<=self.acked:return
            if not self.entries or self.entries[0]['index']!=index:raise failure('clause_sequence')
            entry=self.entries[0]
            if sessions.result(self.owner,self.ident,entry['key'])['status']!='COMPLETED':raise failure('clause_sequence')
            self.entries.pop(0);self.acked=index
            output.discard(self.owner,self.ident,entry['key'])
            self.condition.notify_all()

    def cancel(self):
        with self.condition:
            self.cancelled=True;self.pending.clear();self.tail=''
            entries=list(self.entries);self.condition.notify_all()
        with _lock:_items.pop((self.owner,self.ident,self.key),None)
        for entry in entries:
            output.discard(self.owner,self.ident,entry['key'])
            try:sessions.cancel_turn(self.owner,self.ident,entry['key'])
            except audio_store.AudioError as error:
                # End already atomically cancelled every child. It must still
                # close the input socket when clause cleanup runs afterwards.
                if error.code not in ('session_ended','session_unavailable'):raise

    def run(self):
        from . import live_translator as live
        try:
            while True:
                with self.condition:
                    self.check()
                    if not self.pending:
                        if self.final:
                            self.audio.finish()
                            sessions.finish(self.owner,self.ident,self.key,True,self.audio.job)
                            self.done=True;self.condition.notify_all();return
                        self.condition.wait(.1);continue
                    text=self.pending.pop(0);index=self.next_index;self.next_index+=1
                    key='live-'+hashlib.sha256((self.key+':'+str(index)).encode()).hexdigest()[:32]
                    sessions.claim_clause(self.owner,self.ident,self.key,key)
                    self.entries.append({'index':index,'key':key})
                self.check()
                result=self.audio.render(key,text,self.previous)
                self.previous={'source':text[-400:],'text':result['text'][-400:]}
        except Exception as error:
            self.error=error if isinstance(error,audio_store.AudioError) else failure('clause_failed')
            self.audio.fail(self.error.code)
            sessions.finish(self.owner,self.ident,self.key,False,code=self.error.code)
            self.cancel()
        finally:db._discard_cached_connection()


def create(owner,ident,key,info):
    stream=Stream(owner,ident,key,info)
    with _lock:
        for address,old in list(_items.items()):
            if old.done and monotonic()-old.last_read>600:del _items[address]
        if len(_items)>=4 and (owner,ident,key) not in _items:raise failure('service_busy')
        # A new input lease cannot silently discard an unplayed older lease.
        for address,old in list(_items.items()):
            if address[:2]==(owner,ident):
                if not old.done or old.entries:raise failure()
                del _items[address]
        _items[(owner,ident,key)]=stream
    output.discard(owner,ident,key)  # Parent has no audio; child jobs use the slots.
    stream.worker.start()
    return stream


def owned(owner,ident,key):
    state=sessions.result(owner,ident,key)
    if state['status'] not in ('PROCESSING','COMPLETED'):raise failure('turn_cancelled')
    with _lock:stream=_items.get((owner,ident,key))
    if not stream:raise failure('clause_worker_unavailable')
    return stream


def cancel(owner,ident,key=None):
    with _lock:items=[s for a,s in _items.items() if a[:2]==(owner,ident) and (key is None or a[2]==key)]
    for stream in items:stream.cancel()
