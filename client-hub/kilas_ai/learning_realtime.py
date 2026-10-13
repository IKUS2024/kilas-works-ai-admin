"""Server-owned Scribe realtime stream; bounded PCM chunks, no client provider key.

HTTP chunks bridge the existing WSGI service to a private outbound WebSocket.
Only stable committed provider text reaches the tutor. No batch STT fallback.
"""
import hashlib
import json
import os
from datetime import timedelta
from time import monotonic, sleep
import websocket
import db
from . import learning, learning_store as store, usage, audio_store
from . import audio_transcription_budget as budget, audio_transcription_provider as stt

MODEL='scribe_v2_realtime'
PRICE_VERSION='elevenlabs-scribe-realtime-039usd-hour-20261013'
MAX_AUDIO_BYTES=25*16000*2
MAX_CONNECTION_SECONDS=45
# Reserve the full bounded connection time, including possible silence, even
# though public API pricing meters audio minutes. Never claim this is an invoice.
RESERVE_MICRO=(MAX_CONNECTION_SECONDS*390000+3599)//3600


def _owned(conn,owner,ident,turn):
    store._session(conn,owner,ident)
    row=usage._query(conn,'SELECT i.status,i.next_chunk,i.sent_chunk,i.audio_bytes,i.dispatched,i.created_at,t.status FROM kilas_learning_inputs i JOIN kilas_learning_turns t ON t.id=i.turn_id WHERE i.turn_id=? AND t.session_id=?',(turn,ident),one=True)
    if not row:
        raise store.Error('Stream tidak ditemukan.', 'not_found',404)
    if row[0] not in ('WAITING','STREAMING','COMMITTING') or row[6]!='PROCESSING':
        raise store.Error('Stream sudah dihentikan.', 'cancelled',409)
    if usage._now()-usage._as_utc(row[5])>timedelta(seconds=MAX_CONNECTION_SECONDS):
        raise store.Error('Batas waktu stream tercapai.', 'stt_timeout',503)
    return row


def begin(owner,ident,turn):
    learning.require_ready(owner)
    store.key(turn);store.session(owner,ident)
    if not learning._slots.acquire(blocking=False):
        raise store.Error('Tutor sedang sibuk. Coba lagi nanti.', 'capacity',503)
    try:
        if not store.claim(owner,ident,turn,'realtime'):
            learning._slots.release()
            return False
        config=budget.policy()
        with audio_store.locked(owner) as conn:
            store._session(conn,owner,ident)
            current=usage._query(conn,'SELECT status FROM kilas_learning_turns WHERE id=? AND session_id=?',(turn,ident),one=True)
            if not current or current[0]!='PROCESSING':
                raise store.Error('Stream sudah dibatalkan.', 'cancelled',409)
            if db.BACKEND=='postgres':
                usage._query(conn,'SELECT pg_advisory_xact_lock(74109302)')
            month=usage._now().replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat()
            own=usage._query(conn,'SELECT COALESCE(SUM(i.charge_micro),0) FROM kilas_learning_inputs i JOIN kilas_learning_turns t ON t.id=i.turn_id JOIN kilas_learning_sessions s ON s.id=t.session_id WHERE s.user_id=? AND i.created_at>=?',(owner,month),one=True)[0]
            total=usage._query(conn,'SELECT COALESCE(SUM(charge_micro),0) FROM kilas_learning_inputs WHERE created_at>=?',(month,),one=True)[0]
            cap=int(os.environ.get('KILAS_LEARNING_REALTIME_BUDGET_MICRO_USD','0'))
            if not config or not 1<=cap<=config['account_micro'] or int(own)+RESERVE_MICRO>cap or int(total)+RESERVE_MICRO>config['global_micro']:
                raise store.Error('Batas transkripsi Learning tercapai. Tidak ada pembelian otomatis.', 'learning_stt_limit',429)
            count=usage._query(conn,'SELECT COUNT(*) FROM kilas_learning_inputs i JOIN kilas_learning_turns t ON t.id=i.turn_id JOIN kilas_learning_sessions s ON s.id=t.session_id WHERE s.user_id=? AND i.created_at>?',(owner,(usage._now()-timedelta(hours=1)).isoformat()),one=True)[0]
            if count>=20:
                raise store.Error('Terlalu banyak percobaan. Coba lagi nanti.', 'rate_limit',429)
            usage._query(conn,"INSERT INTO kilas_learning_inputs(turn_id,status,charge_micro,created_at) VALUES (?,'WAITING',?,?)",(turn,RESERVE_MICRO,usage._now().isoformat()))
        learning._executor.submit(_work,owner,ident,turn)
        return True
    except Exception:
        learning._slots.release()
        store.finish(owner,ident,turn,None,'',{},'stt_admission_failed')
        raise


def append(owner,ident,turn,index,pcm):
    learning.require_ready(owner)
    if not pcm or len(pcm)>8192 or len(pcm)%2 or not 0<=index<200:
        raise store.Error('Potongan PCM tidak valid.', 'invalid_audio')
    digest=hashlib.sha256(pcm).hexdigest()
    with audio_store.locked(owner) as conn:
        row=_owned(conn,owner,ident,turn)
        old=usage._query(conn,'SELECT fingerprint FROM kilas_learning_input_chunks WHERE turn_id=? AND sequence=?',(turn,index),one=True)
        if old:
            if old[0]!=digest:raise store.Error('Potongan audio berubah.', 'idempotency_conflict',409)
            return
        if row[0]=='COMMITTING' or index!=row[1] or row[1]-row[2]>=12 or row[3]+len(pcm)>MAX_AUDIO_BYTES:
            raise store.Error('Urutan atau batas stream tidak valid. Tidak ada audio yang dikirim ulang.', 'stream_limit',409)
        usage._query(conn,'INSERT INTO kilas_learning_input_chunks VALUES (?,?,?,?)',(turn,index,digest,pcm))
        usage._query(conn,'UPDATE kilas_learning_inputs SET next_chunk=next_chunk+1,audio_bytes=audio_bytes+? WHERE turn_id=?',(len(pcm),turn))


def commit(owner,ident,turn):
    with audio_store.locked(owner) as conn:
        _owned(conn,owner,ident,turn)
        usage._query(conn,"UPDATE kilas_learning_inputs SET status='COMMITTING' WHERE turn_id=?",(turn,))


def cancel(owner,ident,turn):
    store.key(turn)
    with audio_store.locked(owner) as conn:
        store._session(conn,owner,ident,False)
        row=usage._query(conn,'SELECT 1 FROM kilas_learning_turns WHERE id=? AND session_id=?',(turn,ident),one=True)
        if not row:
            # Fence a cancellation that arrives before its delayed admission.
            usage._query(conn,"INSERT INTO kilas_learning_turns(id,session_id,fingerprint,status,created_at) VALUES (?,?,'realtime','CANCELLED',?) ON CONFLICT(id) DO NOTHING",(turn,ident,usage._now().isoformat()))
            return
        usage._query(conn,"UPDATE kilas_learning_inputs SET status='CANCELLED' WHERE turn_id=? AND status IN ('WAITING','STREAMING','COMMITTING')",(turn,))
        usage._query(conn,"UPDATE kilas_learning_turns SET status='CANCELLED' WHERE id=? AND status='PROCESSING'",(turn,))
        usage._query(conn,'UPDATE kilas_learning_input_chunks SET pcm=NULL WHERE turn_id=?',(turn,))


def take(owner,ident,turn):
    learning.require_ready(owner)
    with audio_store.locked(owner) as conn:
        row=_owned(conn,owner,ident,turn)
        chunk=usage._query(conn,'SELECT pcm FROM kilas_learning_input_chunks WHERE turn_id=? AND sequence=?',(turn,row[2]),one=True)
        if not chunk:
            return None,row[0]=='COMMITTING'
        # At-most-once: mark consumed BEFORE send. An uncertain send aborts the
        # utterance instead of replaying potentially billed/recognized audio.
        usage._query(conn,'UPDATE kilas_learning_inputs SET sent_chunk=sent_chunk+1 WHERE turn_id=?',(turn,))
        usage._query(conn,'UPDATE kilas_learning_input_chunks SET pcm=NULL WHERE turn_id=? AND sequence=?',(turn,row[2]))
        return bytes(chunk[0]),False


def transcribe(owner,ident,turn,connect=websocket.create_connection,now=monotonic,wait=sleep):
    import base64
    started=now();sock=None;last_audio=started;committed=False;finals=[];timings={}
    try:
        # Do not open a paid connection until actual microphone PCM is present.
        first=None
        while first is None:
            first,done=take(owner,ident,turn)
            if done or now()-started>8:
                raise store.Error('Belum terdengar ucapan. Stream tidak dibuka.', 'empty_speech',422)
            if first is None:wait(.08)
        stt.require_subscription_credit()
        with audio_store.locked(owner) as conn:
            _owned(conn,owner,ident,turn)
            usage._query(conn,"UPDATE kilas_learning_inputs SET dispatched=1,status=CASE WHEN status='COMMITTING' THEN status ELSE 'STREAMING' END WHERE turn_id=?",(turn,))
        sock=connect('wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id='+MODEL+'&audio_format=pcm_16000&commit_strategy=manual',
                     header=['xi-api-key: '+os.environ['ELEVENLABS_API_KEY'].strip()],timeout=5,redirect_limit=0)
        sock.settimeout(.1)
        def send(pcm,final=False):
            learning.require_ready(owner);store.check(owner,ident,turn)
            sock.send(json.dumps({'message_type':'input_audio_chunk','audio_base_64':base64.b64encode(pcm).decode(),'sample_rate':16000,**({'commit':True} if final else {})}))
        send(first)
        while now()-started<MAX_CONNECTION_SECONDS:
            store.check(owner,ident,turn)
            if not committed:
                chunk,done=take(owner,ident,turn)
                if chunk:
                    send(chunk);last_audio=now()
                elif done:
                    send(b'',True);committed=True;timings['utterance_end_ms']=round((now()-started)*1000,1)
                elif now()-last_audio>8:
                    raise store.Error('Audio terputus. Stream dihentikan tanpa retry.', 'stt_idle_timeout',503)
            try:
                message=sock.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if not message:raise store.Error('Stream terputus.', 'stt_transport',503)
            if len(message)>65536:raise store.Error('Hasil stream terlalu besar.', 'stt_invalid',503)
            event=json.loads(message)
            kind=event.get('message_type')
            if kind=='committed_transcript':
                text=event.get('text')
                if not isinstance(text,str):raise store.Error('Hasil transkripsi tidak valid.', 'stt_invalid',503)
                if text.strip():finals.append(text.strip())
                if sum(map(len,finals))>4000:raise store.Error('Ucapan terlalu panjang.', 'stt_limit',413)
                if committed:
                    if not finals:raise store.Error('Ucapan belum terbaca.', 'empty_speech',422)
                    timings['stt_result_ms']=round((now()-started)*1000,1)
                    return ' '.join(finals),timings
            elif kind not in ('session_started','partial_transcript','committed_transcript_with_timestamps','warning'):
                # Do not expose raw provider errors, URLs, transcripts or credentials.
                raise store.Error('Transkripsi realtime belum berhasil. Tidak ada retry otomatis.', 'stt_provider_error',503)
        raise store.Error('Stream melewati batas waktu.', 'stt_timeout',503)
    except (store.Error,budget.BudgetError):
        raise
    except (websocket.WebSocketException,OSError,ValueError,TypeError):
        raise store.Error('Koneksi transkripsi realtime terputus. Tidak diulang otomatis.', 'stt_transport',503) from None
    finally:
        if sock is not None:sock.close()


def _work(owner,ident,turn):
    success=False;error='stt_failed'
    try:
        text,timings=transcribe(owner,ident,turn)
        with audio_store.locked(owner) as conn:
            _owned(conn,owner,ident,turn)
            usage._query(conn,"UPDATE kilas_learning_inputs SET status='DONE',first_final_ms=? WHERE turn_id=?",(round(timings['stt_result_ms']),turn))
        learning.run(owner,ident,turn,transcript=text,input_timings=timings)
        success=True
    except Exception as exc:
        error=getattr(exc,'code','stt_failed')
        store.finish(owner,ident,turn,None,'',{},error)
    finally:
        with audio_store.locked(owner) as conn:
            # Unknown dispatched cost remains reserved conservatively; never refund
            # an ambiguous provider connection. Never change Voice Over's ledger.
            usage._query(conn,"UPDATE kilas_learning_inputs SET status=CASE WHEN status='CANCELLED' THEN status ELSE ? END,charge_micro=CASE WHEN dispatched=0 THEN 0 ELSE charge_micro END WHERE turn_id=?",('DONE' if success else 'FAILED',turn))
            usage._query(conn,'UPDATE kilas_learning_input_chunks SET pcm=NULL WHERE turn_id=?',(turn,))
        learning._slots.release();db._discard_cached_connection()
