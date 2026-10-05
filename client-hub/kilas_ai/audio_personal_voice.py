"""Owner-scoped clone association with a short private original-recording preview."""
import secrets
from datetime import timedelta
import db
from . import audio_store as store, audio_provider as provider, audio_media as media, usage


def get(user):
    row=db.query_one('SELECT voice_id FROM kilas_audio_personal_voices WHERE user_id=?',(user,))
    if row and row['voice_id']:return row['voice_id']
    row=db.query_one('SELECT voice_id FROM kilas_audio_saved_voices WHERE user_id=? ORDER BY id LIMIT 1',(user,))
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
            if row[0]:usage._query(conn,'UPDATE kilas_audio_saved_voices SET voice_id=?,preview_content=?,operation_key=?,updated_at=? WHERE user_id=? AND voice_id=?',(new,sample,key,usage._now().isoformat(),user,row[0]))
    except Exception:
        if new:provider.delete_voice(new)
        with store.locked(user) as conn:
            usage._query(conn,"UPDATE kilas_audio_personal_voices SET claim_token='',claim_until='' WHERE user_id=? AND claim_token=?",(user,token))
        raise
    if row[0] and row[0]!=new:provider.delete_voice(row[0])


def saved_voices(user):
    # Import only this owner's existing clone, once, without another provider call.
    with store.locked(user) as conn:
        usage._query(conn,"INSERT INTO kilas_audio_saved_voices(user_id,name,voice_id,preview_content,operation_key,consent_at,updated_at) SELECT user_id,'Suara Saya',voice_id,preview_content,'legacy-' || user_id,consent_at,updated_at FROM kilas_audio_personal_voices WHERE user_id=? AND voice_id<>'' ON CONFLICT(user_id,voice_id) DO NOTHING",(user,))
    return db.query_all('SELECT id,name,preview_content IS NOT NULL AS has_preview FROM kilas_audio_saved_voices WHERE user_id=? ORDER BY id',(user,))


def saved(user,ident):
    return db.query_one('SELECT id,name,voice_id FROM kilas_audio_saved_voices WHERE user_id=? AND id=?',(user,ident))


def owns(user,voice):
    return bool(db.query_one('SELECT 1 FROM kilas_audio_saved_voices WHERE user_id=? AND voice_id=?',(user,voice))) or get(user)==voice


def saved_preview(user,ident):
    row=db.query_one('SELECT preview_content FROM kilas_audio_saved_voices WHERE user_id=? AND id=?',(user,ident))
    return bytes(row['preview_content']) if row and row['preview_content'] else None


def voice_name(value):
    name=' '.join(value.split())
    if not 1<=len(name)<=60 or any(ord(v)<32 for v in name):
        raise store.AudioError('Beri nama suara 1–60 karakter.','invalid_voice_name')
    return name


def _claim(user):
    token=secrets.token_hex(16);now=usage._now()
    with store.locked(user) as conn:
        usage._query(conn,'INSERT INTO kilas_audio_personal_voices(user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING',(user,))
        row=usage._query(conn,'SELECT claim_until FROM kilas_audio_personal_voices WHERE user_id=?',(user,),one=True)
        active=usage._query(conn,"SELECT 1 FROM kilas_audio_jobs WHERE user_id=? AND status IN ('QUEUED','PROCESSING')",(user,),one=True)
        if active or (row[0] and usage._as_utc(row[0])>now):
            raise store.AudioError('Tunggu proses suara selesai sebelum mengubah daftar suara.','busy',409)
        usage._query(conn,'UPDATE kilas_audio_personal_voices SET claim_token=?,claim_until=? WHERE user_id=?',(token,(now+timedelta(minutes=3)).isoformat(),user))
    return token


def _release(user,token):
    with store.locked(user) as conn:
        usage._query(conn,"UPDATE kilas_audio_personal_voices SET claim_token='',claim_until='' WHERE user_id=? AND claim_token=?",(user,token))


def save_named(user,key,item,name,ident=None):
    name=voice_name(name);saved_voices(user)
    prior=db.query_one('SELECT id,name FROM kilas_audio_saved_voices WHERE user_id=? AND operation_key=?',(user,key))
    if prior:return dict(prior)
    old=saved(user,ident) if ident else None
    if ident and not old:raise store.AudioError('Suara tidak ditemukan.','voice_not_found',404)
    token=_claim(user);new=''
    try:
        count=db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_saved_voices WHERE user_id=?',(user,))['n']
        if not ident and count>=10:raise store.AudioError('Maksimal 10 suara tersimpan. Hapus suara yang tidak digunakan.','voice_limit',409)
        pcm=media.voice_sample(item);sample=media.personal_preview(pcm);new=provider.clone_voice(pcm)
        with store.locked(user) as conn:
            current=usage._query(conn,'SELECT claim_token FROM kilas_audio_personal_voices WHERE user_id=?',(user,),one=True)
            if not current or current[0]!=token:raise store.AudioError('Proses suara berubah. Coba kembali.','conflict',409)
            now=usage._now().isoformat()
            if old:
                usage._query(conn,'UPDATE kilas_audio_saved_voices SET name=?,voice_id=?,preview_content=?,operation_key=?,consent_at=?,updated_at=? WHERE id=? AND user_id=?',(name,new,sample,key,now,now,ident,user))
                usage._query(conn,'UPDATE kilas_audio_personal_voices SET voice_id=?,preview_content=? WHERE user_id=? AND voice_id=?',(new,sample,user,old['voice_id']))
            else:
                sql='INSERT INTO kilas_audio_saved_voices(user_id,name,voice_id,preview_content,operation_key,consent_at,updated_at) VALUES (?,?,?,?,?,?,?)'
                params=(user,name,new,sample,key,now,now)
                ident=usage._query(conn,sql+' RETURNING id',params,one=True)[0] if db.BACKEND=='postgres' else conn.execute(sql,params).lastrowid
    except Exception:
        if new:provider.delete_voice(new)
        raise
    finally:_release(user,token)
    if old:provider.delete_voice(old['voice_id'])
    return {'id':ident,'name':name}


def rename_saved(user,ident,name):
    name=voice_name(name)
    with store.locked(user) as conn:
        row=usage._query(conn,'SELECT id FROM kilas_audio_saved_voices WHERE id=? AND user_id=?',(ident,user),one=True)
        if not row:raise store.AudioError('Suara tidak ditemukan.','voice_not_found',404)
        usage._query(conn,'UPDATE kilas_audio_saved_voices SET name=?,updated_at=? WHERE id=? AND user_id=?',(name,usage._now().isoformat(),ident,user))


def delete_saved(user,ident):
    row=saved(user,ident)
    if not row:raise store.AudioError('Suara tidak ditemukan.','voice_not_found',404)
    token=_claim(user)
    try:
        # A failed provider deletion keeps the saved voice and its preview intact.
        provider.request('DELETE','/voices/'+row['voice_id'],private=True)
        with store.locked(user) as conn:
            usage._query(conn,"UPDATE kilas_audio_personal_voices SET voice_id='',preview_content=NULL WHERE user_id=? AND voice_id=?",(user,row['voice_id']))
            usage._query(conn,'DELETE FROM kilas_audio_saved_voices WHERE id=? AND user_id=?',(ident,user))
    finally:_release(user,token)
