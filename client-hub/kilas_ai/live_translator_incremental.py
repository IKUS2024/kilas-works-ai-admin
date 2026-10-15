"""Owned, RAM-only clause work during speech; no draft audio or paid retries."""
import os
from threading import Event,Lock,Thread
from time import monotonic
import db
from . import audio_store

MAX_CLAUSES=2
MAX_CLAUSE_CHARS=1200
FINAL_WAIT_SECONDS=12


def enabled():
    return os.environ.get('KILAS_LIVE_INCREMENTAL_ENABLED','true').lower() in ('1','true','on')


def startup_report():
    try:print(f'KILAS_LIVE_INCREMENTAL configured={str(enabled()).lower()} max_clauses={MAX_CLAUSES} endpoint_ms=2000 paid_qa=false',flush=True)
    except OSError:pass


def validate_drafts(source,drafts,a,b):
    if not isinstance(source,str) or not 1<=len(source)<=4000 or not 1<=len(drafts)<=MAX_CLAUSES:raise ValueError('invalid drafts')
    pieces=[]
    for item in drafts:
        if not isinstance(item,dict):raise ValueError('invalid draft')
        text,original=item.get('text'),item.get('source')
        if (not isinstance(text,str) or not 1<=len(text)<=4000 or not isinstance(original,str)
                or not 1<=len(original)<=MAX_CLAUSE_CHARS
                or {item.get('source_language'),item.get('target_language')}!={a,b}
                or item.get('source_language')==item.get('target_language')):raise ValueError('invalid draft')
        pieces.append(original)
    prefix=' '.join(pieces)
    if source!=prefix and not source.startswith(prefix+' '):raise ValueError('source changed')


def reconcile(source,drafts,value,a,b):
    validate_drafts(source,drafts,a,b)
    keep=value.get('keep_clauses');replacement=value.get('replacement_text')
    if type(keep) is not int or not 0<=keep<=len(drafts) or not isinstance(replacement,str):raise ValueError('invalid final patch')
    # Validate EXACT selected directions before retaining any previously spoken
    # wording; canonical regional aliases remain handled by the ordinary path.
    direction=(value.get('source_language'),value.get('target_language'))
    if not all(isinstance(v,str) for v in direction) or set(direction)!={a,b}:raise ValueError('invalid final language')
    kept=drafts[:keep]
    if any((d['source_language'],d['target_language'])!=direction for d in kept):raise ValueError('changed direction')
    if not replacement.strip() and ' '.join(d['source'] for d in kept)!=source:raise ValueError('missing final tail')
    text=' '.join([d['text'] for d in kept]+([replacement.strip()] if replacement.strip() else []))
    if not 1<=len(text)<=4000:raise ValueError('invalid final text')
    return {'text':text,'source_language':direction[0],'target_language':direction[1]}


class Clauses:
    def __init__(self,owner,ident,key,info):
        self.owner,self.ident,self.key,self.info=owner,ident,key,dict(info)
        self.lock=Lock();self.cancelled=Event();self.done=Event();self.done.set()
        self.pending=[];self.results={};self.claimed=set();self.worker=None
        self.error=None;self.frozen=False;self.elapsed_ms=0;self.started_count=0

    def check(self):
        from . import live_translator as live
        if self.cancelled.is_set():raise audio_store.AudioError('Ucapan dibatalkan.','turn_cancelled',409)
        live.check_session(self.owner,self.ident,self.key)
        if self.cancelled.is_set():raise audio_store.AudioError('Ucapan dibatalkan.','turn_cancelled',409)

    def raise_error(self):
        with self.lock:error=self.error
        if error is not None:raise error

    def offer(self,index,text,previous_source=''):
        # Only a matching provider commit ACK calls this, never interim tokens.
        if (not isinstance(text,str) or not 1<=len(text)<=MAX_CLAUSE_CHARS
                or not text.endswith(('.', '!', '?', '。', '！', '？'))):return False
        with self.lock:
            if self.frozen or self.cancelled.is_set() or index!=len(self.claimed) or len(self.claimed)>=MAX_CLAUSES:return False
            self.claimed.add(index);self.pending.append((index,text,previous_source[-400:]));self.done.clear()
            if self.worker is None:
                self.worker=Thread(target=self.run,name='kilas-live-clause',daemon=True)
                self.worker.start()
        return True

    def run(self):
        from . import live_translator as live
        try:
            while True:
                with self.lock:
                    if self.cancelled.is_set() or not self.pending:
                        self.worker=None;self.done.set();return
                    index,text,previous_source=self.pending.pop(0)
                    previous=self.results.get(index-1,{})
                    self.started_count+=1
                began=monotonic()
                def check():
                    self.check()
                    if monotonic()-began>30:raise audio_store.AudioError('Terjemahan melewati batas waktu.','turn_timeout',503)
                result=live.translation(self.owner,self.key+'-clause-'+str(index),text,
                    self.info['language_a'],self.info['language_b'],check,
                    clause_context={'source':previous_source,'text':previous.get('text','')})
                check()
                with self.lock:
                    if not self.cancelled.is_set():self.results[index]={'source':text,**result}
                    self.elapsed_ms+=(monotonic()-began)*1000
        except Exception as error:
            with self.lock:
                self.error=error;self.pending.clear();self.worker=None;self.done.set()
        finally:db._discard_cached_connection()

    def freeze(self):
        # Once speech ends, do not dispatch a queued optional clause. Its source
        # is already part of the authoritative final transcript, not discarded.
        with self.lock:self.frozen=True;self.pending.clear()

    def finish(self,source,check,timings):
        from . import live_translator as live
        self.freeze()
        began=monotonic()
        while not self.done.wait(.1):
            check();self.raise_error()
            if monotonic()-began>=FINAL_WAIT_SECONDS:
                self.cancel()
                raise audio_store.AudioError('Terjemahan belum selesai. Ucapan tidak diulang otomatis.','turn_timeout',503)
        check();self.raise_error()
        with self.lock:
            drafts=[]
            # Only a contiguous source prefix can be retained by the final patch.
            for index in range(MAX_CLAUSES):
                if index not in self.results:break
                drafts.append(dict(self.results[index]))
            timings['incremental_clauses']=self.started_count
            timings['incremental_provider_ms']=self.elapsed_ms
            timings['incremental_wait_ms']=(monotonic()-began)*1000
        if drafts:
            try:validate_drafts(source,drafts,self.info['language_a'],self.info['language_b'])
            except (ValueError,TypeError):drafts=[]
        # Exactly one translated segment that IS the complete final source has
        # no unseen tail/context. Reuse it without a second paid text request.
        if len(drafts)==1 and drafts[0]['source']==source:
            timings['incremental_reused']=1
            return {k:drafts[0][k] for k in ('text','source_language','target_language')}
        return live.translation(self.owner,self.key,source,self.info['language_a'],self.info['language_b'],check,
                                timings=timings,**({'drafts':drafts} if drafts else {}))

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            self.pending.clear();self.results.clear()
