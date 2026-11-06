"""Product quota hooks only; never grants supplier access or changes funding caps."""
import hashlib
import io
import struct
import wave
import json
import os
import db
from . import usage,credit_policy as policy,credit_wallet as wallet


def settings():
    try:
        config=json.loads(os.environ.get('KILAS_CREDIT_TARIFFS_JSON','{}'))
        item=config['limits']['TRANSLATOR']
        ratio=wallet._amount(item['output_ratio_milli']);maximum=wallet._amount(item['source_ms'])
        if config['version']!='customer-credit-v1' or ratio>10000 or maximum>600000:raise ValueError()
        return ratio,maximum
    except (KeyError,TypeError,ValueError):raise wallet.WalletError('translator_bounds_unapproved') from None


def root_in(conn,user,key):
    if not policy.table_exists(conn,'kilas_credit_translation_links'):return None
    return usage._query(conn,'SELECT root_key,source_ms,output_ms,maximum_ms,output_ratio_milli,dispatched FROM kilas_credit_translation_links WHERE user_id=? AND operation_key=?',(user,key),one=True)


def claim_in(conn,user,session_id,key,info,maximum_ms,payload_digest=None):
    if not policy.enabled() or policy.owner(conn,user):return
    ratio,limit=settings()
    if maximum_ms>limit:raise wallet.WalletError('translator_request_outside_approved_bounds')
    if info['voice_alias'].startswith('gemini-live-'):
        from .live_gemini_budget import MODEL as model
    else:
        from .model_policy import luna_model
        model=luna_model()
    policy.validate_request(conn,user,'TRANSLATOR',{'model':model,'source_ms':maximum_ms})
    digest=policy.fingerprint({'source_sha256':payload_digest,'model':model,'session':session_id,'key':key,'languages':[info['language_a'],info['language_b']],'voice':info['voice_alias'],'maximum_source_ms':maximum_ms,'output_ratio_milli':ratio})
    admitted=policy.admit_in(conn,user,key,'TRANSLATOR',maximum_ms,digest)
    if not admitted['dispatch']:raise wallet.WalletError('operation_already_admitted')
    usage._query(conn,'INSERT INTO kilas_credit_translation_links(user_id,operation_key,root_key,maximum_ms,output_ratio_milli) VALUES (?,?,?,?,?)',(user,key,key,maximum_ms,ratio))


def child_in(conn,user,parent,key):
    row=root_in(conn,user,parent)
    if row:
        old=root_in(conn,user,key)
        if old:
            if old[0]!=row[0]:raise wallet.WalletError('translator_child_changed')
            return
        usage._query(conn,'INSERT INTO kilas_credit_translation_links(user_id,operation_key,root_key,maximum_ms,output_ratio_milli) VALUES (?,?,?,?,?)',(user,key,row[0],row[3],row[4]))


class SourceMeter:
    """Packet-invariant 20 ms digital-silence meter for PCM16 mono at 16 or 24 kHz.

    This is the existing STT silence floor, not linguistic voice activity
    detection. Hardware/background-noise calibration remains an activation gate.
    """
    def __init__(self,sample_rate=16000):
        if sample_rate not in (16000,24000):raise wallet.WalletError('invalid_pcm_meter')
        self.sample_rate=sample_rate;self.frame_bytes=sample_rate//50*2
        self.pending=b'';self.samples=0;self.digest=hashlib.sha256()

    def clone(self):
        other=SourceMeter(self.sample_rate);other.pending=self.pending;other.samples=self.samples;other.digest=self.digest.copy();return other

    @staticmethod
    def audible(part):return any(abs(n[0])>=32 for n in struct.iter_unpack('<h',part))

    def feed(self,raw):
        if not isinstance(raw,bytes) or len(raw)%2:raise wallet.WalletError('invalid_pcm_meter')
        self.digest.update(raw);self.pending+=raw
        while len(self.pending)>=self.frame_bytes:
            part,self.pending=self.pending[:self.frame_bytes],self.pending[self.frame_bytes:]
            if self.audible(part):self.samples+=self.frame_bytes//2
        return self.milliseconds

    @property
    def milliseconds(self):
        samples=self.samples+(len(self.pending)//2 if self.audible(self.pending) else 0)
        return (samples*1000+self.sample_rate-1)//self.sample_rate


def pcm_units(raw):
    return SourceMeter().feed(raw)


def wav_units(raw):
    with wave.open(io.BytesIO(raw)) as audio:
        if (audio.getnchannels(),audio.getsampwidth(),audio.getframerate())!=(1,2,16000):raise wallet.WalletError('invalid_pcm_meter')
        return pcm_units(audio.readframes(audio.getnframes()))


def source(user,key,raw,*,wav=False):
    if not has_links():return
    if wav:
        with wave.open(io.BytesIO(raw)) as audio:raw=audio.readframes(audio.getnframes())
    units=pcm_units(raw)
    with wallet._locked(user) as conn:
        row=root_in(conn,user,key)
        if not row:return
        if units>row[3]:raise wallet.WalletError('source_exceeds_reservation')
        usage._query(conn,'UPDATE kilas_credit_translation_links SET source_ms=?,source_digest=? WHERE user_id=? AND operation_key=?',(units,hashlib.sha256(raw).hexdigest(),user,row[0]))


def source_units(user,key,units,digest):
    if not has_links():return
    with wallet._locked(user) as conn:
        row=root_in(conn,user,key)
        if not row:return
        if units>row[3]:raise wallet.WalletError('source_exceeds_reservation')
        usage._query(conn,'UPDATE kilas_credit_translation_links SET source_ms=?,source_digest=? WHERE user_id=? AND operation_key=?',(units,digest,user,row[0]))


def dispatched(user,key):
    if not has_links():return
    with wallet._locked(user) as conn:
        row=root_in(conn,user,key)
        if row:usage._query(conn,'UPDATE kilas_credit_translation_links SET dispatched=1 WHERE user_id=? AND root_key=?',(user,row[0]))


def output_limit(user,key):
    if not policy.enabled():return None
    row=db.query_one('SELECT maximum_ms,output_ratio_milli FROM kilas_credit_translation_links WHERE user_id=? AND operation_key=?',(user,key))
    return (row['maximum_ms']*row['output_ratio_milli'])//1000 if row else None


def finish_turn_in(conn,user,key,success,code=None):
    row=root_in(conn,user,key)
    if not row or row[0]!=key:return
    if success and row[2]>(row[1]*row[4])//1000:
        # No truncation or automatic retries; requires explicit reconciliation.
        raise wallet.WalletError('translator_output_cap_exceeded')
    policy.finish_in(conn,user,key,row[1] if success else 0,success=success,definitive_failure=not row[5] or code in ('no_speech','provider_quota_exhausted'))


def admitted_audio(conn,user,key,mode,script,source_ms,reserve_ms,digest,live_session,credit_context,model):
    if not credit_context:return False
    if live_session:
        parent=root_in(conn,user,live_session[1])
        if parent:
            row=usage._query(conn,"SELECT status FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?",(user,parent[0]),one=True)
            if not row or row[0]!='RESERVED':raise wallet.WalletError('translator_parent_closed')
            return True
        if not parent:
            if not policy.enabled() or policy.owner(conn,user):return False
            raise wallet.WalletError('translator_parent_admission_missing')
        return True
    if not policy.enabled():return False
    feature='VOICE' if mode=='voiceover' else 'TRANSLATOR'
    policy.validate_request(conn,user,feature,{'model':model,'characters':len(script),'output_ms':reserve_ms,'source_ms':source_ms})
    admitted=policy.admit_in(conn,user,key,feature,reserve_ms if feature=='VOICE' else source_ms,digest,priced_units=len(script) if feature=='VOICE' else None)
    if not admitted['dispatch']:raise wallet.WalletError('operation_already_admitted')
    return True


def link_audio_in(conn,user,job,key,feature,source_ms,reserve_ms,live_session):
    parent=root_in(conn,user,live_session[1]) if live_session else None
    operation=parent[0] if parent else key
    limit=(parent[3]*parent[4])//1000 if parent else (source_ms*settings()[0])//1000 if feature=='TRANSLATOR' else reserve_ms
    usage._query(conn,'INSERT INTO kilas_credit_audio_links(user_id,job_id,operation_key,feature,source_ms,maximum_output_ms) VALUES (?,?,?,?,?,?)',(user,job,operation,feature,source_ms,limit))


def audio_link(conn,user,job):
    if not policy.table_exists(conn,'kilas_credit_audio_links'):return None
    return usage._query(conn,'SELECT operation_key,feature,source_ms,maximum_output_ms,dispatched FROM kilas_credit_audio_links WHERE user_id=? AND job_id=?',(user,job),one=True)


def mark_audio_dispatched(user,job):
    if not has_links():return
    with wallet._locked(user) as conn:
        row=audio_link(conn,user,job)
        if row:usage._query(conn,'UPDATE kilas_credit_audio_links SET dispatched=1 WHERE user_id=? AND job_id=?',(user,job))


def finish_audio_in(conn,user,job,actual_ms):
    row=audio_link(conn,user,job)
    if not row:return False
    if actual_ms>row[3]:raise wallet.WalletError('audio_output_cap_exceeded')
    parent=root_in(conn,user,row[0])
    if parent:
        if actual_ms>(parent[1]*parent[4])//1000:raise wallet.WalletError('translator_output_cap_exceeded')
        usage._query(conn,'UPDATE kilas_credit_translation_links SET output_ms=? WHERE user_id=? AND operation_key=?',(actual_ms,user,parent[0]))
    else:policy.finish_in(conn,user,row[0],actual_ms if row[1]=='VOICE' else row[2],success=True)
    return True


def fail_audio_in(conn,user,job,code):
    row=audio_link(conn,user,job)
    if not row:return
    if not root_in(conn,user,row[0]):policy.finish_in(conn,user,row[0],0,success=False,definitive_failure=not row[4] or code in ('provider_failed','provider_quota_exhausted','no_speech'))


def has_links():
    conn=usage._connect()
    try:return policy.table_exists(conn,'kilas_credit_translation_links')
    finally:conn.close()


def ratio(user,key):
    if not policy.enabled():return None
    row=db.query_one('SELECT output_ratio_milli FROM kilas_credit_translation_links WHERE user_id=? AND operation_key=?',(user,key))
    return row['output_ratio_milli'] if row else None
