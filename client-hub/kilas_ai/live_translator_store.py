"""Owner-scoped session/turn fences across workers. No recorded audio or transcript here."""
import secrets
from datetime import timedelta
import db
from . import usage, audio_store
from .autonomous_store import transaction

# Empty expiry marks an explicit-End session, without changing the deployed schema.
# Older expired rows remain historical; do not revive an abandoned tab on a read.
def alive(status,expiry):
    return status=='ACTIVE' and (not expiry or usage._as_utc(expiry)>usage._now())


def require_pair(a,b):
    from .audio_provider import LANGUAGES
    if not isinstance(a,str) or not isinstance(b,str) or a not in LANGUAGES or b not in LANGUAGES or a==b:
        raise audio_store.AudioError('Pilih dua bahasa yang berbeda sebelum memulai sesi.','invalid_language_pair',400)


def active(owner):
    # Read only: an idle row is not proof that another tab has stopped listening.
    row=db.query_one("SELECT s.id,s.expires_at,EXISTS(SELECT 1 FROM kilas_live_translator_turns t WHERE t.session_id=s.id AND t.status='PROCESSING') AS processing FROM kilas_live_translator_sessions s WHERE s.user_id=? AND s.status='ACTIVE' AND (s.expires_at='' OR s.expires_at>?) ORDER BY s.created_at DESC LIMIT 1",(owner,usage._now().isoformat()))
    return {'session_id':row['id'],'expires_at':row['expires_at'] or None,'expires_in_seconds':max(0,int((usage._as_utc(row['expires_at'])-usage._now()).total_seconds())+1) if row['expires_at'] else None,'processing':bool(row['processing'])} if row else None


def locked(owner, ident, conn):
    suffix=' FOR UPDATE' if db.BACKEND=='postgres' else ''
    row=usage._query(conn,'SELECT status,expires_at,language_a,language_b,voice_alias FROM kilas_live_translator_sessions WHERE id=? AND user_id=?'+suffix,(ident,owner),one=True)
    if not row:raise audio_store.AudioError('Sesi tidak tersedia.','session_unavailable',404)
    if not alive(row[0],row[1]):raise audio_store.AudioError('Sesi berakhir. Mulai kembali bila ingin melanjutkan.','session_ended',409)
    require_pair(row[2],row[3])
    return {'language_a':row[2],'language_b':row[3],'voice_alias':row[4]}


def create(owner,a,b,voice,*,processing_consent=None):
    require_pair(a,b)
    now=usage._now();ident=secrets.token_hex(24)
    with transaction() as conn:
        # One session per owner, including double Start from separate tabs.
        suffix=' FOR UPDATE' if db.BACKEND=='postgres' else ''
        usage._query(conn,'SELECT id FROM users WHERE id=?'+suffix,(owner,),one=True)
        if processing_consent is not None:
            from . import translator_consent
            translator_consent.admit(owner,processing_consent,conn)
        active=usage._query(conn,"SELECT 1 FROM kilas_live_translator_sessions WHERE user_id=? AND status='ACTIVE' AND (expires_at='' OR expires_at>?)",(owner,now.isoformat()),one=True)
        if active:raise audio_store.AudioError('Sesi lain masih aktif. Akhiri sesi itu terlebih dahulu.','session_busy',409)
        usage._query(conn,"INSERT INTO kilas_live_translator_sessions VALUES (?,?,?,?,?,'ACTIVE',?,?)",(ident,owner,a,b,voice,now.isoformat(),''))
    return ident


def claim(owner,ident,key):
    with transaction() as conn:
        info=locked(owner,ident,conn)
        old=usage._query(conn,'SELECT status FROM kilas_live_translator_turns WHERE operation_key=?',(key,),one=True)
        if old:raise audio_store.AudioError('Ucapan ini sudah diproses. Tidak diulang otomatis.','duplicate_turn',409)
        busy=usage._query(conn,"SELECT 1 FROM kilas_live_translator_turns WHERE session_id=? AND status='PROCESSING'",(ident,),one=True)
        if busy:raise audio_store.AudioError('Ucapan sebelumnya masih diproses.','turn_busy',409)
        usage._query(conn,"INSERT INTO kilas_live_translator_turns(operation_key,session_id,status,created_at) VALUES (?,?,'PROCESSING',?)",(key,ident,usage._now().isoformat()))
        from . import live_translator_output
        live_translator_output.begin(owner,ident,key)  # Reserve before even realtime STT can dispatch.
        return info


def check(owner,ident,key):
    # This is a read fence, not a mutation. The former transaction opened a fresh
    # connection and locked the session for EVERY streamed translation event, then
    # released that lock before returning. One joined snapshot keeps the same
    # per-event End/expiry/owner checks using the existing thread-local connection.
    # Admission, completion and End still use their original write transactions.
    row=db.query_one('SELECT s.status AS session_status,s.expires_at,s.language_a,s.language_b,s.voice_alias,t.status AS turn_status FROM kilas_live_translator_sessions s LEFT JOIN kilas_live_translator_turns t ON t.session_id=s.id AND t.operation_key=? WHERE s.id=? AND s.user_id=?',(key,ident,owner))
    if not row:raise audio_store.AudioError('Sesi tidak tersedia.','session_unavailable',404)
    if not alive(row['session_status'],row['expires_at']):raise audio_store.AudioError('Sesi berakhir. Mulai kembali bila ingin melanjutkan.','session_ended',409)
    if row['turn_status']!='PROCESSING':raise audio_store.AudioError('Ucapan dibatalkan.','turn_cancelled',409)
    require_pair(row['language_a'],row['language_b'])
    return {name:row[name] for name in ('language_a','language_b','voice_alias')}


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
    from . import live_translator_output
    live_translator_output.discard(owner,ident)


def cancel_turn(owner,ident,key):
    """Cancel this turn only, including a POST whose admission arrives late."""
    with transaction() as conn:
        locked(owner,ident,conn)
        row=usage._query(conn,'SELECT session_id,status FROM kilas_live_translator_turns WHERE operation_key=?',(key,),one=True)
        if row and row[0]!=ident:raise audio_store.AudioError('Ucapan tidak tersedia.','turn_unavailable',404)
        if not row:
            # Tombstone blocks a late original POST before any paid work is admitted.
            usage._query(conn,"INSERT INTO kilas_live_translator_turns(operation_key,session_id,status,created_at,error_code) VALUES (?,?,'CANCELLED',?,'turn_cancelled')",(key,ident,usage._now().isoformat()))
            return 'CANCELLED'
        if row[1]=='PROCESSING':
            usage._query(conn,"UPDATE kilas_live_translator_turns SET status='CANCELLED',error_code='turn_cancelled' WHERE operation_key=? AND session_id=? AND status='PROCESSING'",(key,ident))
            from . import live_translator_output
            live_translator_output.discard(owner,ident,key)
            return 'CANCELLED'
        return row[1]


def status(owner,ident):
    row=db.query_one("SELECT s.status,s.expires_at,EXISTS(SELECT 1 FROM kilas_live_translator_turns t WHERE t.session_id=s.id AND t.status='PROCESSING') AS processing FROM kilas_live_translator_sessions s WHERE s.id=? AND s.user_id=?",(ident,owner))
    if not row:raise audio_store.AudioError('Sesi tidak tersedia.','session_unavailable',404)
    return {'status':'ACTIVE' if alive(row['status'],row['expires_at']) else 'ENDED','processing':bool(row['processing'])}


def result(owner,ident,key):
    row=db.query_one('SELECT t.status,t.audio_job_id,t.error_code,t.created_at,s.status AS session_status,s.expires_at,s.language_a,s.language_b FROM kilas_live_translator_turns t JOIN kilas_live_translator_sessions s ON s.id=t.session_id WHERE s.user_id=? AND s.id=? AND t.operation_key=?',(owner,ident,key))
    if not row:raise audio_store.AudioError('Ucapan tidak tersedia.','turn_unavailable',404)
    if not alive(row['session_status'],row['expires_at']):return {'status':'CANCELLED'}
    require_pair(row['language_a'],row['language_b'])
    if row['status']=='PROCESSING' and usage._as_utc(row['created_at'])<usage._now()-timedelta(minutes=4):return {'status':'FAILED','error_code':'processing_interrupted'}
    return {'status':row['status'],'audio_job_id':row['audio_job_id'],'error_code':row['error_code']}
