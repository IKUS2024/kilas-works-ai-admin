"""Owner-scoped session/turn fences across workers. No recorded audio or transcript here."""
import secrets
from datetime import timedelta
import db
from . import usage, audio_store
from .autonomous_store import transaction


def locked(owner, ident, conn):
    suffix=' FOR UPDATE' if db.BACKEND=='postgres' else ''
    row=usage._query(conn,'SELECT status,expires_at,language_a,language_b,voice_alias FROM kilas_live_translator_sessions WHERE id=? AND user_id=?'+suffix,(ident,owner),one=True)
    if not row:raise audio_store.AudioError('Sesi tidak tersedia.','session_unavailable',404)
    if row[0]!='ACTIVE' or usage._as_utc(row[1])<=usage._now():raise audio_store.AudioError('Sesi berakhir. Mulai kembali bila ingin melanjutkan.','session_ended',409)
    return {'language_a':row[2],'language_b':row[3],'voice_alias':row[4]}


def create(owner,a,b,voice):
    now=usage._now();ident=secrets.token_hex(24)
    with transaction() as conn:
        # One session per owner, including double Start from separate tabs.
        suffix=' FOR UPDATE' if db.BACKEND=='postgres' else ''
        usage._query(conn,'SELECT id FROM users WHERE id=?'+suffix,(owner,),one=True)
        active=usage._query(conn,"SELECT 1 FROM kilas_live_translator_sessions WHERE user_id=? AND status='ACTIVE' AND expires_at>?",(owner,now.isoformat()),one=True)
        if active:raise audio_store.AudioError('Sesi lain masih aktif. Akhiri sesi itu terlebih dahulu.','session_busy',409)
        usage._query(conn,"INSERT INTO kilas_live_translator_sessions VALUES (?,?,?,?,?,'ACTIVE',?,?)",(ident,owner,a,b,voice,now.isoformat(),(now+timedelta(minutes=30)).isoformat()))
    return ident


def claim(owner,ident,key):
    with transaction() as conn:
        info=locked(owner,ident,conn)
        old=usage._query(conn,'SELECT status FROM kilas_live_translator_turns WHERE operation_key=?',(key,),one=True)
        if old:raise audio_store.AudioError('Ucapan ini sudah diproses. Tidak diulang otomatis.','duplicate_turn',409)
        busy=usage._query(conn,"SELECT 1 FROM kilas_live_translator_turns WHERE session_id=? AND status='PROCESSING'",(ident,),one=True)
        if busy:raise audio_store.AudioError('Ucapan sebelumnya masih diproses.','turn_busy',409)
        usage._query(conn,"INSERT INTO kilas_live_translator_turns(operation_key,session_id,status,created_at) VALUES (?,?,'PROCESSING',?)",(key,ident,usage._now().isoformat()))
        return info


def check(owner,ident,key):
    with transaction() as conn:
        info=locked(owner,ident,conn)
        row=usage._query(conn,'SELECT status FROM kilas_live_translator_turns WHERE session_id=? AND operation_key=?',(ident,key),one=True)
        if not row or row[0]!='PROCESSING':raise audio_store.AudioError('Ucapan dibatalkan.','turn_cancelled',409)
        return info


def finish(owner,ident,key,success,job=None,code=None):
    with transaction() as conn:
        if success:locked(owner,ident,conn)
        usage._query(conn,"UPDATE kilas_live_translator_turns SET status=?,audio_job_id=?,error_code=? WHERE operation_key=? AND session_id=? AND status='PROCESSING' AND EXISTS(SELECT 1 FROM kilas_live_translator_sessions WHERE id=? AND user_id=?)",('COMPLETED' if success else 'FAILED',job,code,key,ident,ident,owner))


def end(owner,ident):
    with transaction() as conn:
        suffix=' FOR UPDATE' if db.BACKEND=='postgres' else ''
        row=usage._query(conn,'SELECT id FROM kilas_live_translator_sessions WHERE id=? AND user_id=?'+suffix,(ident,owner),one=True)
        if not row:raise audio_store.AudioError('Sesi tidak tersedia.','session_unavailable',404)
        usage._query(conn,"UPDATE kilas_live_translator_sessions SET status='ENDED' WHERE id=?",(ident,))
        usage._query(conn,"UPDATE kilas_live_translator_turns SET status='CANCELLED' WHERE session_id=? AND status='PROCESSING'",(ident,))


def result(owner,ident,key):
    row=db.query_one('SELECT t.status,t.audio_job_id,t.error_code,s.status AS session_status,s.expires_at FROM kilas_live_translator_turns t JOIN kilas_live_translator_sessions s ON s.id=t.session_id WHERE s.user_id=? AND s.id=? AND t.operation_key=?',(owner,ident,key))
    if not row:raise audio_store.AudioError('Ucapan tidak tersedia.','turn_unavailable',404)
    if row['session_status']!='ACTIVE' or usage._as_utc(row['expires_at'])<=usage._now():return {'status':'CANCELLED'}
    if row['status']=='PROCESSING' and usage._as_utc(db.query_one('SELECT created_at FROM kilas_live_translator_turns WHERE operation_key=?',(key,))['created_at'])<usage._now()-timedelta(minutes=4):return {'status':'FAILED','error_code':'processing_interrupted'}
    return {'status':row['status'],'audio_job_id':row['audio_job_id'],'error_code':row['error_code']}
