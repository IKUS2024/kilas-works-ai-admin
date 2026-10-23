"""One metered audio job per input lease, with incremental clause reservations.

The existing five-job/minute admission and one active audio job/account remain
unchanged. Each clause reserves before dispatch and settles cumulative seconds.
"""
import hashlib
import math
from time import monotonic
from . import audio_store as store, audio_service, audio_media, usage, free_test
from . import live_translator as live, live_translator_store as sessions
from . import live_translator_output as output, live_translator_segments as segments


class Audio:
    def __init__(self,stream):self.stream=stream;self.job=None

    def publish(self,key,**values):
        s=self.stream
        with output._lock:
            output._expire();entry=output._items.get((s.owner,s.ident,key))
            if not entry:raise store.AudioError('Hasil sesi dibatalkan.','session_output_expired',409)
            entry.update(values)

    def append(self,key,part):
        s=self.stream
        with output._lock:
            entry=output._items.get((s.owner,s.ident,key))
            if not entry or entry['progress'] is None:raise store.AudioError('Hasil sesi dibatalkan.','session_output_expired',409)
            if len(entry['progress'])+len(part)>20*1024*1024:raise store.AudioError('Audio melebihi batas.','stream_limit',413)
            entry['progress'].extend(part)

    def reserve(self,key,result,voice):
        s=self.stream;expected,reserve=audio_service.estimate(result['text'])
        live.require_audio_allowance(s.owner,reserve)
        if self.job is None:
            self.job,new=store.create(s.owner,s.key+'-audio','voiceover','Live Translator',
                result['source_language'],result['target_language'],voice['id'],voice['name'],
                result['text'],0,None,expected,reserve,live_session=(s.ident,s.key))
            if not new or not store.start(s.owner,self.job):raise store.AudioError('Audio tidak diulang.','duplicate_turn',409)
        with store.locked(s.owner) as conn:
            sessions.locked(s.owner,s.ident,conn)
            parent=usage._query(conn,'SELECT status FROM kilas_live_translator_turns WHERE session_id=? AND operation_key=?',(s.ident,s.key),one=True)
            child=usage._query(conn,'SELECT status FROM kilas_live_translator_turns WHERE session_id=? AND operation_key=?',(s.ident,key),one=True)
            row=usage._query(conn,'SELECT status,actual_ms,reserved_seconds FROM kilas_audio_jobs WHERE id=? AND user_id=?',(self.job,s.owner),one=True)
            if not parent or parent[0]!='PROCESSING' or not child or child[0]!='PROCESSING' or not row or row[0]!='PROCESSING':raise store.AudioError('Ucapan dibatalkan.','turn_cancelled',409)
            exempt=free_test.sponsored_audio(conn,s.owner,self.job) or usage._qa_quota_exempt(conn,s.owner,usage._now())
            if not exempt and store._balance(conn,s.owner)<reserve:raise store.AudioError('Saldo audio tidak cukup.','insufficient_balance',402)
            # The previous clause has settled. Retain known incurred duration
            # plus this possible dispatch in the durable safety allowance.
            usage._query(conn,"UPDATE kilas_audio_jobs SET reserved_seconds=?,initial_reserved_seconds=?,provider_id=?,updated_at=? WHERE id=? AND user_id=?",(0 if exempt else reserve,math.ceil(row[1]/1000)+reserve,'clauses-v1:reserved:'+key,usage._now().isoformat(),self.job,s.owner))
            usage._query(conn,'UPDATE kilas_live_translator_turns SET audio_job_id=? WHERE session_id=? AND operation_key=?',(self.job,s.ident,key))

    def settle(self,key,duration):
        s=self.stream
        with store.locked(s.owner) as conn:
            row=usage._query(conn,'SELECT status,actual_ms,seconds_charged,reserved_seconds,initial_reserved_seconds,provider_id FROM kilas_audio_jobs WHERE id=? AND user_id=?',(self.job,s.owner),one=True)
            if row and row[5]=='clauses-v1:settled:'+key:return False
            if not row or row[0]!='PROCESSING' or row[5]!='clauses-v1:reserved:'+key:raise store.AudioError('Audio dibatalkan.','turn_cancelled',409)
            total=row[1]+duration;exempt=free_test.sponsored_audio(conn,s.owner,self.job) or usage._qa_quota_exempt(conn,s.owner,usage._now())
            charge=0 if exempt else math.ceil(total/1000);delta=charge-row[2]
            if math.ceil(total/1000)>row[4] or delta<0 or (not exempt and (delta>row[3] or delta>store._balance(conn,s.owner))):raise store.AudioError('Durasi melebihi cadangan audio.','output_exceeds_reservation',402)
            if delta:usage._query(conn,'UPDATE kilas_audio_balances SET seconds=seconds-? WHERE user_id=?',(delta,s.owner))
            usage._query(conn,'UPDATE kilas_audio_jobs SET actual_ms=?,seconds_charged=?,reserved_seconds=0,initial_reserved_seconds=?,provider_id=?,updated_at=? WHERE id=? AND user_id=?',(total,charge,math.ceil(total/1000),'clauses-v1:settled:'+key,usage._now().isoformat(),self.job,s.owner))

    def render(self,key,text,previous):
        s=self.stream;began=monotonic();timings={}
        def check():
            s.check();live.check_session(s.owner,s.ident,key)
            if monotonic()-began>180:raise store.AudioError('Audio melewati batas waktu.','turn_timeout',503)
        check();store.require_balance(s.owner);live.require_audio_allowance(s.owner)
        output.activate(s.owner,s.ident,key)
        result=live.translation(s.owner,key,text,s.info['language_a'],s.info['language_b'],check,clause_context=previous or {'source':'','text':''})
        timings['translation_ms']=(monotonic()-began)*1000
        check();voice=live.voices.resolve(s.info['voice_alias'])
        if not voice:raise store.AudioError('Suara tidak tersedia.','voice_unavailable',409)
        live.stt.require_subscription_credit();check();self.reserve(key,result,voice);check()
        output.publish_translation(s.owner,s.ident,key,{**result,'source_text':text})
        output.bind(s.owner,s.ident,key,self.job,{**result,'source_text':text})
        self.publish(key,progress=bytearray(),clause=True)
        def first_byte():timings.setdefault('first_audio_ms',(monotonic()-began)*1000)
        raw=segments.speech(result['text'],voice['id'],check,first_byte,language=result['target_language'],on_chunk=lambda part:self.append(key,part))
        # A fully received response is settled even when End races publication.
        self.settle(key,audio_media.mp3_duration(raw));check()
        self.publish(key,raw=raw,progress=None,audio_sha256=hashlib.sha256(raw).hexdigest())
        sessions.finish(s.owner,s.ident,key,True,self.job)
        # Numeric evidence only. This measures server work, not audible latency
        # on a device; it contains no transcript, account, voice ID or credential.
        timings['complete_ms']=(monotonic()-began)*1000
        try:print('KILAS_LIVE_CLAUSE '+ ' '.join(f'{name}={value:.1f}' for name,value in timings.items()),flush=True)
        except OSError:pass
        return result

    def finish(self):
        if self.job is None:return
        s=self.stream
        with store.locked(s.owner) as conn:
            sessions.locked(s.owner,s.ident,conn)
            usage._query(conn,"UPDATE kilas_audio_jobs SET status='COMPLETED',reserved_seconds=0,updated_at=? WHERE id=? AND user_id=? AND status='PROCESSING'",(usage._now().isoformat(),self.job,s.owner))

    def fail(self,code):
        if self.job is not None:store.fail(self.stream.owner,self.job,code)
