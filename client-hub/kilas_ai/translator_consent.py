"""Explicit per-user, processing-scope/version consent. No audio or implied grants."""
import db
from . import usage, audio_store
from .autonomous_store import transaction

SCOPE='live-translator-elevenlabs-openai'
VERSION='2026-10-17-v1'
NOTICE='Saya memiliki izin dari pembicara dan mengizinkan ucapan dikirim ke ElevenLabs untuk transkripsi dan suara terjemahan, serta teks ke OpenAI untuk diterjemahkan. Audio dapat dikirim saat berbicara. Izin ini diingat untuk akun saya dan dapat dicabut melalui Izin pemrosesan ucapan.'
ERROR='Izin pemrosesan ucapan belum ada, berubah, atau telah dicabut. Tinjau penjelasan lalu pilih Izinkan dan mulai.'


def _granted(owner,conn=None):
    sql="SELECT 1 FROM kilas_translator_consents WHERE user_id=? AND scope=? AND version=? AND accepted_at<>'' AND revoked_at=''"
    params=(owner,SCOPE,VERSION)
    return bool(usage._query(conn,sql,params,one=True) if conn is not None else db.query_one(sql,params))


def state(owner):
    from ui_i18n import translate
    return {'scope':SCOPE,'version':VERSION,'granted':_granted(owner),'notice':translate(NOTICE)}


def require(owner):
    if not _granted(owner):raise audio_store.AudioError(ERROR,'processing_consent_required',409)


def validate(owner,fields,conn=None):
    accepted=fields.get('action')
    if fields.get('scope')!=SCOPE or fields.get('version')!=VERSION or accepted not in (None,'accept') or (accepted is None and not _granted(owner,conn)):
        raise audio_store.AudioError(ERROR,'processing_consent_required',409)


def admit(owner,fields,conn):
    """Called under the Start transaction's owner lock; failed Starts roll back."""
    validate(owner,fields,conn)
    if fields.get('action')=='accept':
        usage._query(conn,"INSERT INTO kilas_translator_consents(user_id,scope,version,accepted_at,revoked_at) VALUES (?,?,?,?,'') ON CONFLICT(user_id,scope,version) DO UPDATE SET accepted_at=excluded.accepted_at,revoked_at=''",
                     (owner,SCOPE,VERSION,usage._now().isoformat()))


def revoke(owner):
    """Revoke all versions of this scope and end only its owned classic sessions."""
    with transaction() as conn:
        suffix=' FOR UPDATE' if db.BACKEND=='postgres' else ''
        usage._query(conn,'SELECT id FROM users WHERE id=?'+suffix,(owner,),one=True)
        usage._query(conn,'UPDATE kilas_translator_consents SET revoked_at=? WHERE user_id=? AND scope=? AND revoked_at=?',
                     (usage._now().isoformat(),owner,SCOPE,''))
        rows=usage._rows(conn,"SELECT id FROM kilas_live_translator_sessions WHERE user_id=? AND status='ACTIVE' AND voice_alias IN (?,?)",(owner,'kilas-male','kilas-female'))
        usage._query(conn,"UPDATE kilas_live_translator_sessions SET status='ENDED' WHERE user_id=? AND status='ACTIVE' AND voice_alias IN (?,?)",(owner,'kilas-male','kilas-female'))
        usage._query(conn,"UPDATE kilas_live_translator_turns SET status='CANCELLED' WHERE status='PROCESSING' AND session_id IN (SELECT id FROM kilas_live_translator_sessions WHERE user_id=? AND voice_alias IN (?,?))",(owner,'kilas-male','kilas-female'))
    # Existing cross-worker End watchers remain authoritative. Clear local caches too.
    from . import live_translator_realtime,live_translator_output
    for row in rows:
        live_translator_realtime.cancel(owner,row[0])
        live_translator_output.discard(owner,row[0])
