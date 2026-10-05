"""Owner-scoped clone association with a short private original-recording preview."""
import secrets
from datetime import timedelta
import db
from . import audio_store as store, audio_provider as provider, audio_media as media, usage


def get(user):
    row=db.query_one('SELECT voice_id FROM kilas_audio_personal_voices WHERE user_id=?',(user,))
    return row['voice_id'] if row else ''


def preview(user):
    row=db.query_one("SELECT preview_content FROM kilas_audio_personal_voices WHERE user_id=? AND voice_id<>''",(user,))
    return bytes(row['preview_content']) if row and row['preview_content'] else None


def has_preview(user):
    row=db.query_one("SELECT preview_content IS NOT NULL AS ready FROM kilas_audio_personal_voices WHERE user_id=? AND voice_id<>''",(user,))
    return bool(row and row['ready'])


def create(user,key,item,replace=False):
    token=secrets.token_hex(16);now=usage._now()
    with store.locked(user) as conn:
        usage._query(conn,'INSERT INTO kilas_audio_personal_voices(user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING',(user,))
        row=usage._query(conn,'SELECT voice_id,operation_key,claim_until FROM kilas_audio_personal_voices WHERE user_id=?',(user,),one=True)
        if row[0] and row[1]==key:return
        if row[2] and usage._as_utc(row[2])>now:raise store.AudioError('Suara sedang dibuat. Tunggu sampai selesai.','busy',409)
        if row[0] and not replace:raise store.AudioError('Konfirmasi penggantian Suara Saya terlebih dahulu.','replace_confirmation',409)
        active=usage._query(conn,"SELECT 1 FROM kilas_audio_jobs WHERE user_id=? AND status IN ('QUEUED','PROCESSING')",(user,),one=True)
        if active:raise store.AudioError('Tunggu voice over selesai sebelum mengganti suara.','busy',409)
        usage._query(conn,'UPDATE kilas_audio_personal_voices SET claim_token=?,claim_until=? WHERE user_id=?',(token,(now+timedelta(minutes=3)).isoformat(),user))
    new=''
    try:
        pcm=media.voice_sample(item)
        sample=media.personal_preview(pcm)
        new=provider.clone_voice(pcm)
        with store.locked(user) as conn:
            current=usage._query(conn,'SELECT claim_token FROM kilas_audio_personal_voices WHERE user_id=?',(user,),one=True)
            if not current or current[0]!=token:raise store.AudioError('Rekaman berubah. Coba kembali.','conflict',409)
            usage._query(conn,"UPDATE kilas_audio_personal_voices SET voice_id=?,preview_content=?,operation_key=?,consent_at=?,updated_at=?,claim_token='',claim_until='' WHERE user_id=?",(new,sample,key,now.isoformat(),usage._now().isoformat(),user))
    except Exception:
        if new:provider.delete_voice(new)
        with store.locked(user) as conn:
            usage._query(conn,"UPDATE kilas_audio_personal_voices SET claim_token='',claim_until='' WHERE user_id=? AND claim_token=?",(user,token))
        raise
    if row[0] and row[0]!=new:provider.delete_voice(row[0])
