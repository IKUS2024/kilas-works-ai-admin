"""Locked prepaid-second accounting and owner-scoped durable audio jobs."""
import hashlib
import json
import logging
import math
from contextlib import contextmanager
from datetime import timedelta

import db
from . import usage, billing

PACKS = {'MINUTE': (60,19000), 'FIVE': (300,89000), 'TEN': (600,169000)}
log = logging.getLogger(__name__)


class AudioError(ValueError):
    def __init__(self, message, code='invalid', status=400):
        super().__init__(message)
        self.code, self.status = code, status


@contextmanager
def locked(user):
    conn = usage._connect()
    try:
        billing._lock_user(conn,user)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def _balance(conn,user):
    row = usage._query(conn,'SELECT seconds FROM kilas_audio_balances WHERE user_id=?',(user,),one=True)
    return int(row[0]) if row else 0


def _expire(conn,user):
    # Release stranded reservations on the next owner visit/action without a worker or retry.
    now=usage._now()
    usage._query(conn,"UPDATE kilas_audio_jobs SET status='FAILED',error_code='processing_timeout',reserved_seconds=0,source_content=NULL,script=NULL,updated_at=? WHERE user_id=? AND status IN ('QUEUED','PROCESSING') AND ((provider_id='' AND created_at<?) OR created_at<?)",
                 (now.isoformat(),user,(now-timedelta(minutes=3)).isoformat(),(now-timedelta(hours=2)).isoformat()))


def balance(user):
    with locked(user) as conn:
        _expire(conn,user)
        seconds = _balance(conn,user)
        reserved = usage._query(conn,"SELECT COALESCE(SUM(reserved_seconds),0) FROM kilas_audio_jobs WHERE user_id=? AND status IN ('QUEUED','PROCESSING')",(user,),one=True)[0]
        exempt = usage._qa_quota_exempt(conn,user,usage._now())
    return {'seconds':seconds,'available':max(0,seconds-int(reserved)), 'reserved':int(reserved), 'exempt':exempt}


def require_balance(user, required=1):
    state = balance(user)
    if not state['exempt'] and state['available'] < required:
        raise AudioError('Saldo Audio belum tersedia. Beli saldo untuk menggunakan Translate atau Voice Over.' if not state['available']
                         else f'Saldo tidak cukup. Dibutuhkan {required}s; saldo tersedia {state["available"]}s.',
                         'zero_balance' if not state['available'] else 'insufficient_balance',402)
    return state


def get(user,ident):
    return db.query_one("SELECT id,user_id,mode,title,source_language,target_language,voice_id,voice_name,estimated_seconds,source_ms,actual_ms,seconds_charged,status,provider_id,error_code,created_at,updated_at, CASE WHEN substr(result_content,5,4)=? THEN 1 ELSE 0 END AS result_is_video FROM kilas_audio_jobs WHERE id=? AND user_id=?",(b'ftyp',ident,user))


def history(user,page=1):
    return db.query_all('SELECT id,mode,title,source_language,target_language,voice_name,source_ms,actual_ms,status,created_at FROM kilas_audio_jobs WHERE user_id=? ORDER BY id DESC LIMIT 21 OFFSET ?',(user,(page-1)*20))


def create(user,key,mode,title,source,target,voice,voice_name,script,source_ms,pcm,estimated,reserve):
    fingerprint = hashlib.sha256(json.dumps([mode,title,source,target,voice,script,source_ms],ensure_ascii=False).encode()+(pcm or b'')).hexdigest()
    with locked(user) as conn:
        _expire(conn,user)
        if mode=='voiceover' and voice_name=='Suara Saya':
            personal=usage._query(conn,'SELECT voice_id,claim_until FROM kilas_audio_personal_voices WHERE user_id=?',(user,),one=True)
            if not personal or personal[0]!=voice or (personal[1] and usage._as_utc(personal[1])>usage._now()):
                raise AudioError('Suara Saya sedang diperbarui. Muat ulang lalu coba lagi.','voice_unavailable',409)
        existing = usage._query(conn,'SELECT id,fingerprint FROM kilas_audio_jobs WHERE user_id=? AND operation_key=?',(user,key),one=True)
        if existing:
            if existing[1]!=fingerprint:raise AudioError('Permintaan berubah. Mulai audio baru.','idempotency_conflict',409)
            return existing[0],False
        # One concurrent paid operation per account. Locks cover reservations across both modes.
        active = usage._query(conn,"SELECT 1 FROM kilas_audio_jobs WHERE user_id=? AND status IN ('QUEUED','PROCESSING')",(user,),one=True)
        if active:raise AudioError('Audio sebelumnya masih diproses. Buka hasilnya di riwayat.','busy',409)
        recent = usage._query(conn,'SELECT COUNT(*) FROM kilas_audio_jobs WHERE user_id=? AND created_at>?',(user,(usage._now()-timedelta(minutes=1)).isoformat()),one=True)[0]
        if recent>=5:raise AudioError('Tunggu sebentar sebelum membuat audio berikutnya.','rate_limit',429)
        exempt = usage._qa_quota_exempt(conn,user,usage._now())
        available = _balance(conn,user)
        if not exempt and available<reserve:
            raise AudioError(f'Saldo tidak cukup. Estimasi {estimated}s; perlu mencadangkan hingga {reserve}s. Saldo tersedia {available}s. Sisa reservasi dikembalikan setelah durasi aktual dihitung.','insufficient_balance',402)
        reserve = 0 if exempt else reserve
        now = usage._now().isoformat()
        sql = 'INSERT INTO kilas_audio_jobs(user_id,operation_key,fingerprint,mode,title,source_language,target_language,voice_id,voice_name,script,source_ms,source_content,estimated_seconds,reserved_seconds,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, ?,?)'
        params = (user,key,fingerprint,mode,title,source,target,voice,voice_name,script,source_ms,pcm,estimated,reserve,'QUEUED',now,now)
        if db.BACKEND=='postgres':ident=usage._query(conn,sql+' RETURNING id',params,one=True)[0]
        else:ident=conn.execute(sql,params).lastrowid
    log.info('KILAS_AUDIO job=%s user=%s mode=%s status=QUEUED reserved_seconds=%s',ident,user,mode,reserve)
    return ident,True


def start(user,ident):
    with locked(user) as conn:
        row=usage._query(conn,'SELECT status FROM kilas_audio_jobs WHERE id=? AND user_id=?',(ident,user),one=True)
        if not row or row[0]!='QUEUED':return False
        usage._query(conn,"UPDATE kilas_audio_jobs SET status='PROCESSING',updated_at=? WHERE id=? AND user_id=?",(usage._now().isoformat(),ident,user))
    return True


def payload(user,ident):
    return db.query_one('SELECT script,source_content FROM kilas_audio_jobs WHERE id=? AND user_id=?',(ident,user))


def submitted(user,ident,provider_id, *, retain_video=False):
    with locked(user) as conn:
        usage._query(conn,"UPDATE kilas_audio_jobs SET provider_id=?,source_content=CASE WHEN ? THEN source_content ELSE NULL END,script=NULL,updated_at=? WHERE id=? AND user_id=? AND status='PROCESSING'",(provider_id,retain_video,usage._now().isoformat(),ident,user))


def detected_source(user,ident,language):
    with locked(user) as conn:
        usage._query(conn,"UPDATE kilas_audio_jobs SET source_language=? WHERE id=? AND user_id=? AND source_language='auto' AND status='PROCESSING'",(language,ident,user))


def finish(user,ident,raw,actual_ms,provider_id=''):
    with locked(user) as conn:
        row=usage._query(conn,'SELECT mode,source_ms,reserved_seconds,status FROM kilas_audio_jobs WHERE id=? AND user_id=?',(ident,user),one=True)
        if not row or row[3]!='PROCESSING':return False
        exempt=usage._qa_quota_exempt(conn,user,usage._now())
        charge=0 if exempt else math.ceil((row[1] if row[0]=='translate' else actual_ms)/1000)
        if charge>row[2] or charge>_balance(conn,user):
            if not exempt:raise AudioError('Durasi hasil melebihi saldo yang dapat dicadangkan. Saldo tidak dipotong. Gunakan naskah lebih pendek.','output_exceeds_reservation',402)
        if charge:
            usage._query(conn,'UPDATE kilas_audio_balances SET seconds=seconds-? WHERE user_id=? AND seconds>=?',(charge,user,charge))
        # psycopg2 expands BYTEA parameters into SQL literals. Keep each statement
        # small on the production database; all chunks and settlement stay atomic.
        if db.BACKEND=='postgres' and len(raw)>512*1024:
            for offset in range(0,len(raw),512*1024):
                expression='?' if offset==0 else 'result_content || ?'
                usage._query(conn,'UPDATE kilas_audio_jobs SET result_content='+expression+' WHERE id=? AND user_id=? AND status=\'PROCESSING\'',
                             (raw[offset:offset+512*1024],ident,user))
            usage._query(conn,"UPDATE kilas_audio_jobs SET status='COMPLETED',actual_ms=?,seconds_charged=?,reserved_seconds=0,source_content=NULL,script=NULL,provider_id=CASE WHEN provider_id='' THEN ? ELSE provider_id END,updated_at=? WHERE id=? AND user_id=?",
                         (actual_ms,charge,provider_id,usage._now().isoformat(),ident,user))
        else:
            usage._query(conn,"UPDATE kilas_audio_jobs SET status='COMPLETED',actual_ms=?,seconds_charged=?,reserved_seconds=0,result_content=?,source_content=NULL,script=NULL,provider_id=CASE WHEN provider_id='' THEN ? ELSE provider_id END,updated_at=? WHERE id=? AND user_id=?",
                         (actual_ms,charge,raw,provider_id,usage._now().isoformat(),ident,user))
    log.info('KILAS_AUDIO job=%s user=%s status=COMPLETED duration_ms=%s seconds_charged=%s',ident,user,actual_ms,charge)
    return True


def fail(user,ident,code):
    with locked(user) as conn:
        usage._query(conn,"UPDATE kilas_audio_jobs SET status='FAILED',reserved_seconds=0,error_code=?,source_content=CASE WHEN mode='translate' AND substr(source_content,5,4)=? THEN source_content ELSE NULL END,script=NULL,updated_at=? WHERE id=? AND user_id=? AND status IN ('QUEUED','PROCESSING')",(code[:80],b'ftyp',usage._now().isoformat(),ident,user))
    log.warning('KILAS_AUDIO job=%s user=%s status=FAILED category=%s',ident,user,code[:80])


def poll_claim(user,ident):
    with locked(user) as conn:
        row=usage._query(conn,'SELECT status,poll_until FROM kilas_audio_jobs WHERE id=? AND user_id=?',(ident,user),one=True)
        if not row or row[0]!='PROCESSING' or (row[1] and usage._as_utc(row[1])>usage._now()):return False
        usage._query(conn,'UPDATE kilas_audio_jobs SET poll_until=? WHERE id=? AND user_id=?',((usage._now()+timedelta(seconds=60)).isoformat(),ident,user))
    return True


def poll_release(user,ident):
    with locked(user) as conn:
        usage._query(conn,'UPDATE kilas_audio_jobs SET poll_until=? WHERE id=? AND user_id=?',((usage._now()+timedelta(seconds=5)).isoformat(),ident,user))
