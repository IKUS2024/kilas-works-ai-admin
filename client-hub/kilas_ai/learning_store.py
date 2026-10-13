"""Owner-fenced Learning sessions, idempotent turns and private audio segments."""
import json
import math
import re
import uuid
from datetime import timedelta
import db
from . import audio_store, audio_service, audio_media, usage

TARGETS = {'en': 'Inggris', 'zh': 'Mandarin', 'es': 'Spanyol'}
NATIVES = {'id': 'Indonesia', 'en': 'English', 'zh': 'Mandarin', 'es': 'Español'}
LEVELS = {'beginner': 'Pemula', 'intermediate': 'Menengah', 'advanced': 'Lanjutan'}
Error = audio_store.AudioError


def key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,70}', value):
        raise Error('Permintaan tidak valid.', 'invalid_key')
    return value


def _session(conn, owner, ident, active=True):
    row = usage._query(conn, 'SELECT id,target,native,level,voice,status,expires_at FROM kilas_learning_sessions WHERE id=? AND user_id=?', (ident, owner), one=True)
    if not row:
        raise Error('Sesi tidak ditemukan.', 'not_found', 404)
    if active and (row[5] != 'ACTIVE' or usage._as_utc(row[6]) <= usage._now()):
        raise Error('Sesi sudah berakhir. Mulai sesi baru.', 'session_ended', 409)
    return dict(zip(('id','target','native','level','voice','status','expires_at'), row))


def session(owner, ident, active=True):
    with audio_store.locked(owner) as conn:
        return _session(conn, owner, ident, active)


def create(owner, start_key, target, native, level, voice):
    key(start_key)
    if target not in TARGETS or native not in NATIVES or level not in LEVELS or voice not in ('kilas-male','kilas-female'):
        raise Error('Pilihan belajar tidak valid.')
    with audio_store.locked(owner) as conn:
        if usage._query(conn,'SELECT 1 FROM kilas_learning_cancelled_starts WHERE user_id=? AND start_key=?',(owner,start_key),one=True):
            raise Error('Sesi sudah dibatalkan.', 'cancelled',409)
        old = usage._query(conn, 'SELECT id,target,native,level,voice FROM kilas_learning_sessions WHERE user_id=? AND start_key=?', (owner,start_key), one=True)
        if old:
            if old[1:] != (target,native,level,voice):
                raise Error('Pilihan sesi berubah. Mulai sesi baru.', 'idempotency_conflict', 409)
            return old[0], False
        now = usage._now()
        usage._query(conn, "UPDATE kilas_learning_sessions SET status='ENDED' WHERE user_id=? AND expires_at<=?", (owner,now.isoformat()))
        if usage._query(conn, "SELECT 1 FROM kilas_learning_sessions WHERE user_id=? AND status='ACTIVE'", (owner,), one=True):
            raise Error('Sesi Learning masih aktif. Lanjutkan atau akhiri dahulu.', 'active_session', 409)
        ident = uuid.uuid4().hex
        usage._query(conn, "INSERT INTO kilas_learning_sessions VALUES (?,?,?,?,?,?,?,'ACTIVE',?,?)", (ident,owner,start_key,target,native,level,voice,now.isoformat(),(now+timedelta(minutes=30)).isoformat()))
        return ident, True


def current(owner):
    row = db.query_one("SELECT id FROM kilas_learning_sessions WHERE user_id=? AND status='ACTIVE' AND expires_at>? ORDER BY created_at DESC LIMIT 1", (owner,usage._now().isoformat()))
    return row['id'] if row else None


def claim(owner, ident, turn, fingerprint):
    key(turn)
    with audio_store.locked(owner) as conn:
        _session(conn,owner,ident)
        old = usage._query(conn, 'SELECT session_id,fingerprint FROM kilas_learning_turns WHERE id=?', (turn,), one=True)
        if old:
            if old != (ident,fingerprint):
                raise Error('Permintaan berubah.', 'idempotency_conflict', 409)
            return False
        if usage._query(conn, "SELECT 1 FROM kilas_learning_turns WHERE session_id=? AND status='PROCESSING'", (ident,), one=True):
            raise Error('Tutor masih menyiapkan jawaban.', 'busy', 409)
        count = usage._query(conn, 'SELECT COUNT(*) FROM kilas_learning_turns WHERE session_id=?', (ident,), one=True)[0]
        if count >= 40:
            raise Error('Batas sesi tercapai. Akhiri lalu mulai sesi baru.', 'session_limit', 429)
        usage._query(conn, "INSERT INTO kilas_learning_turns(id,session_id,fingerprint,status,created_at) VALUES (?,?,?,'PROCESSING',?)", (turn,ident,fingerprint,usage._now().isoformat()))
        return True


def check(owner, ident, turn):
    session(owner,ident)
    row = db.query_one('SELECT status,created_at FROM kilas_learning_turns WHERE id=? AND session_id=?', (turn,ident))
    if not row or row['status'] != 'PROCESSING':
        raise Error('Ucapan dibatalkan.', 'cancelled', 409)
    if usage._now()-usage._as_utc(row['created_at']) > timedelta(minutes=3):
        raise Error('Proses terlalu lama. Permintaan tidak diulang otomatis.', 'processing_timeout', 503)


def context(owner, ident):
    session(owner,ident)
    rows = db.query_all("SELECT input_text,output_text FROM kilas_learning_turns WHERE session_id=? AND status='COMPLETED' ORDER BY created_at DESC LIMIT 8", (ident,))
    messages = []
    for row in reversed(rows):
        if row['input_text']:
            messages.append({'role':'user','content':row['input_text']})
        messages.append({'role':'assistant','content':row['output_text']})
    return messages


def finish(owner, ident, turn, text, output, timings, error=None):
    with audio_store.locked(owner) as conn:
        s = _session(conn,owner,ident,False)
        # End never resurrects a turn or stores late transcripts.
        if s['status'] != 'ACTIVE' or usage._as_utc(s['expires_at']) <= usage._now():
            error = 'cancelled'
        usage._query(conn, "UPDATE kilas_learning_turns SET status=?,input_text=?,output_text=?,error_code=?,timings=? WHERE id=? AND session_id=? AND status='PROCESSING'", ('FAILED' if error else 'COMPLETED',None if error else text,None if error else output,error,json.dumps(timings),turn,ident))


def end(owner, ident):
    with audio_store.locked(owner) as conn:
        _session(conn,owner,ident,False)
        usage._query(conn, "UPDATE kilas_learning_sessions SET status='ENDED' WHERE id=? AND user_id=?", (ident,owner))
        usage._query(conn, "UPDATE kilas_learning_turns SET status=CASE WHEN status='PROCESSING' THEN 'CANCELLED' ELSE status END,input_text=NULL,output_text=NULL WHERE session_id=?", (ident,))
        usage._query(conn, 'UPDATE kilas_learning_clips SET audio=NULL WHERE turn_id IN (SELECT id FROM kilas_learning_turns WHERE session_id=?)', (ident,))
        _clear_inputs(conn,ident)


def cancel_start(owner, start_key, ident=None):
    # A tombstone fences End racing a delayed Start before its session exists.
    if start_key:
        key(start_key)
    with audio_store.locked(owner) as conn:
        if start_key:
            usage._query(conn,'INSERT INTO kilas_learning_cancelled_starts VALUES (?,?,?) ON CONFLICT(user_id,start_key) DO NOTHING',(owner,start_key,usage._now().isoformat()))
        row=usage._query(conn,'SELECT id FROM kilas_learning_sessions WHERE user_id=? AND start_key=?',(owner,start_key),one=True) if start_key else None
        if ident:
            _session(conn,owner,ident,False)
        chosen=ident or (row[0] if row else None)
        if chosen:
            usage._query(conn,"UPDATE kilas_learning_sessions SET status='ENDED' WHERE id=? AND user_id=?",(chosen,owner))
            usage._query(conn,"UPDATE kilas_learning_turns SET status=CASE WHEN status='PROCESSING' THEN 'CANCELLED' ELSE status END,input_text=NULL,output_text=NULL WHERE session_id=?",(chosen,))
            usage._query(conn,'UPDATE kilas_learning_clips SET audio=NULL WHERE turn_id IN (SELECT id FROM kilas_learning_turns WHERE session_id=?)',(chosen,))
            _clear_inputs(conn,chosen)


def _clear_inputs(conn,ident):
    usage._query(conn,"UPDATE kilas_learning_inputs SET status='CANCELLED' WHERE turn_id IN (SELECT id FROM kilas_learning_turns WHERE session_id=?) AND status IN ('WAITING','STREAMING','COMMITTING')",(ident,))
    usage._query(conn,'UPDATE kilas_learning_input_chunks SET pcm=NULL WHERE turn_id IN (SELECT id FROM kilas_learning_turns WHERE session_id=?)',(ident,))


def state(owner, ident, turn=None):
    s = session(owner,ident,False)
    if not turn:
        row = db.query_one('SELECT id FROM kilas_learning_turns WHERE session_id=? ORDER BY created_at DESC LIMIT 1', (ident,))
        turn = row['id'] if row else None
    row = db.query_one('SELECT id,status,error_code,created_at,timings FROM kilas_learning_turns WHERE id=? AND session_id=?', (turn,ident)) if turn else None
    if turn and not row:
        raise Error('Ucapan tidak ditemukan.', 'not_found', 404)
    ended = s['status'] != 'ACTIVE' or usage._as_utc(s['expires_at']) <= usage._now()
    status = row['status'] if row else None
    if status == 'PROCESSING' and usage._now()-usage._as_utc(row['created_at']) > timedelta(minutes=3):
        status = 'FAILED'  # Read-only recovery; never enqueue a paid retry.
    clips = [] if ended or not row else db.query_all('SELECT sequence,duration_ms FROM kilas_learning_clips WHERE turn_id=? AND audio IS NOT NULL ORDER BY sequence', (turn,))
    return {'session_id':ident,'ended':ended,'target':s['target'],'native':s['native'],'level':s['level'],'voice':s['voice'],
            'turn':turn,'status':status,'error_code':row['error_code'] if row else None,
            'clips':[{'index':c['sequence'],'duration_ms':c['duration_ms']} for c in clips],
            'timings':json.loads(row['timings']) if row else {}}


def clip(owner, ident, turn, index):
    session(owner,ident)
    row = db.query_one('SELECT c.audio FROM kilas_learning_clips c JOIN kilas_learning_turns t ON t.id=c.turn_id WHERE t.session_id=? AND c.turn_id=? AND c.sequence=?', (ident,turn,index))
    if not row or not row['audio']:
        raise Error('Audio tidak tersedia.', 'not_found', 404)
    session(owner,ident)
    return bytes(row['audio'])


def dispatch_clip(owner, ident, turn, index, phrase, job):
    """Persist possible-paid marker and reserve bounded audio BEFORE one TTS call."""
    _, reserve = audio_service.estimate(phrase)
    with audio_store.locked(owner) as conn:
        _session(conn,owner,ident)
        row = usage._query(conn, "SELECT status FROM kilas_learning_turns WHERE id=? AND session_id=?", (turn,ident), one=True)
        if not row or row[0] != 'PROCESSING':
            raise Error('Ucapan dibatalkan.', 'cancelled', 409)
        count = usage._query(conn,'SELECT COUNT(*) FROM kilas_learning_clips WHERE turn_id=?',(turn,),one=True)[0]
        if index != count or index >= 16:
            raise Error('Urutan audio tidak valid.', 'segment_limit', 409)
        # Finite additional provider-cost guard also applies to internal QA owners.
        used = usage._query(conn, 'SELECT COALESCE(SUM(c.chars),0) FROM kilas_learning_clips c JOIN kilas_learning_turns t ON t.id=c.turn_id JOIN kilas_learning_sessions s ON s.id=t.session_id WHERE s.user_id=? AND c.dispatched_at>=?', (owner,(usage._now()-timedelta(days=1)).isoformat()),one=True)[0]
        if int(used)+len(phrase)>6000:
            raise Error('Batas suara Learning harian tercapai. Coba lagi besok.', 'learning_audio_limit',429)
        ledger = usage._query(conn,'SELECT status FROM kilas_audio_jobs WHERE id=? AND user_id=?',(job,owner),one=True)
        if not ledger or ledger[0]!='PROCESSING':
            raise Error('Audio tidak tersedia.', 'audio_unavailable',409)
        exempt = usage._qa_quota_exempt(conn,owner,usage._now())
        if not exempt:
            pending = usage._query(conn,"SELECT COALESCE(SUM(reserved_seconds),0) FROM kilas_audio_jobs WHERE user_id=? AND status IN ('QUEUED','PROCESSING')",(owner,),one=True)[0]
            if audio_store._balance(conn,owner)-int(pending)<reserve:
                raise Error('Saldo Audio tidak cukup untuk jawaban berikutnya.', 'insufficient_balance',402)
            usage._query(conn,'UPDATE kilas_audio_jobs SET reserved_seconds=reserved_seconds+? WHERE id=? AND user_id=?',(reserve,job,owner))
        usage._query(conn,'INSERT INTO kilas_learning_clips(turn_id,sequence,chars,dispatched_at) VALUES (?,?,?,?)',(turn,index,len(phrase),usage._now().isoformat()))


def commit_clip(owner, ident, turn, index, job, raw, ms):
    # Charge validated output even if End raced the provider response. End prevents
    # publication and further dispatch, not supplier costs already incurred.
    with audio_store.locked(owner) as conn:
        row=usage._query(conn,'SELECT actual_ms,seconds_charged,reserved_seconds,status FROM kilas_audio_jobs WHERE id=? AND user_id=?',(job,owner),one=True)
        if not row or row[3]!='PROCESSING':
            raise Error('Audio tidak tersedia.', 'audio_unavailable',409)
        cliprow=usage._query(conn,'SELECT duration_ms FROM kilas_learning_clips WHERE turn_id=? AND sequence=?',(turn,index),one=True)
        if not cliprow or cliprow[0]:
            raise Error('Audio sudah dicatat.', 'duplicate_clip',409)
        total=int(row[0])+ms
        exempt=usage._qa_quota_exempt(conn,owner,usage._now())
        charge=0 if exempt else math.ceil(total/1000)
        delta=charge-int(row[1])
        if delta<0 or (not exempt and (delta>int(row[2]) or delta>audio_store._balance(conn,owner))):
            raise Error('Durasi melebihi cadangan Audio.', 'output_exceeds_reservation',402)
        if delta:
            usage._query(conn,'UPDATE kilas_audio_balances SET seconds=seconds-? WHERE user_id=? AND seconds>=?',(delta,owner,delta))
        usage._query(conn,'UPDATE kilas_audio_jobs SET actual_ms=?,seconds_charged=?,reserved_seconds=reserved_seconds-?,updated_at=? WHERE id=? AND user_id=?',(total,charge,delta,usage._now().isoformat(),job,owner))
        s=_session(conn,owner,ident,False)
        active=s['status']=='ACTIVE' and usage._as_utc(s['expires_at'])>usage._now()
        usage._query(conn,'UPDATE kilas_learning_clips SET duration_ms=?,audio=? WHERE turn_id=? AND sequence=?',(ms,raw if active else None,turn,index))


def close_audio(owner, job, success):
    raw=None
    if success:
        rows=db.query_all('SELECT c.audio FROM kilas_learning_clips c JOIN kilas_learning_turns t ON t.id=c.turn_id JOIN kilas_learning_sessions s ON s.id=t.session_id WHERE t.audio_job_id=? AND s.user_id=? ORDER BY c.sequence',(job,owner))
        combined=b''.join(bytes(row['audio']) for row in rows if row['audio'])
        # Validate the complete existing Audio-history download; call playback
        # still consumes each independently decoded clip in sequence.
        if combined:
            raw,_=audio_media.ensure_mp3(combined)
        else:
            success=False
    with audio_store.locked(owner) as conn:
        # All seconds were already settled once per clip. Never debit them again.
        usage._query(conn,"UPDATE kilas_audio_jobs SET status=?,error_code=?,reserved_seconds=0,result_content=?,script=NULL,source_content=NULL,updated_at=? WHERE id=? AND user_id=? AND status='PROCESSING'",('COMPLETED' if success else 'FAILED','' if success else 'learning_call_interrupted',raw,usage._now().isoformat(),job,owner))
