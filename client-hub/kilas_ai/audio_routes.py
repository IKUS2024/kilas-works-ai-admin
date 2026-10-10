"""Authenticated Translator utility, private media and existing admin review."""
import io
import math
import re
import secrets
from flask import Blueprint, abort, redirect, render_template, request, send_file, session, url_for
import db
import security
import payment_service
from .routes import enabled
from .billing_routes import admin_bp
from . import audio_store as store, audio_provider as provider, audio_service as service, audio_media as media, audio_billing as billing
from . import audio_personal_voice as personal
from . import audio_voice_script as voice_script

audio_bp=Blueprint('kilas_audio',__name__,url_prefix='/kilas-translator')


@audio_bp.before_request
def access():
    if not enabled():abort(404)
    if not session.get('user_id'):return redirect(url_for('auth.login_page'))
    user=security.current_user()
    if not user or user['role']!='CLIENT_OWNER':abort(404)


@audio_bp.errorhandler(store.AudioError)
@audio_bp.errorhandler(media.MediaError)
def invalid(error):
    return {'error':str(error),'code':getattr(error,'code','invalid'),'purchase_url':url_for('kilas_audio.home')+'#audio-packs'},getattr(error,'status',400)


def owned(ident):
    job=store.get(session['user_id'],ident)
    if not job:abort(404)
    return job


def seconds(value):
    value=int(value)
    return f'{value//60}m {value%60:02d}s' if value>=60 else f'{value}s'


@audio_bp.get('')
@audio_bp.get('/jobs/<int:ident>')
def home(ident=None,initial_brief=None,home_task=None):
    from .content_projects import draft
    content_draft = draft(session['user_id'])
    user=session['user_id'];job=owned(ident) if ident else None
    state=store.balance(user)
    try:page=max(1,min(10000,int(request.args.get('page',1))))
    except ValueError:abort(400)
    rows=store.history(user,page)
    saved_voices=personal.saved_voices(user)
    return render_template('kilas_translator/home.html',content_draft=content_draft,initial_brief=initial_brief,home_task=home_task,balance=state,job=job,history=rows[:20],more=len(rows)>20,page=page,
                           voices=provider.voices() if state['exempt'] or state['available'] else [],
                           personal_voice=bool(personal.get(user)),personal_preview=personal.has_preview(user),voice_operation_key=secrets.token_hex(16),
                           saved_voices=saved_voices,
                           provider_ready=provider.configured(),languages=provider.LANGUAGES,packs=store.PACKS,
                           seconds=seconds,operation_key=secrets.token_hex(16),max_mb=media.file_limit()//1024//1024,audio_max_mb=media.file_limit('wav')//1024//1024,max_seconds=media.duration_limit())


@audio_bp.post('/inspect')
def inspect():
    store.require_balance(session['user_id'])  # Zero balance never even decodes/uploads to provider.
    name,ms,_=media.upload(request.files.get('file'))
    return {'filename':name,'duration_ms':ms,'required_seconds':math.ceil(ms/1000),'duration_label':seconds(math.ceil(ms/1000))}


@audio_bp.post('/jobs')
def create():
    user=session['user_id'];key=request.form.get('operation_key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',key):abort(400)
    existing=db.query_one('SELECT id FROM kilas_audio_jobs WHERE user_id=? AND operation_key=?',(user,key))
    if existing:return {'url':url_for('kilas_audio.home',ident=existing['id']),'id':existing['id']},200
    store.require_balance(user)
    if not provider.configured():raise store.AudioError('Audio sedang belum tersedia. Saldo kamu tetap aman.','not_configured',503)
    mode=request.form.get('mode');source=request.form.get('source_language','auto');target=request.form.get('language','en')
    if (target not in provider.LANGUAGES and not (mode=='voiceover' and target=='auto')) or (source!='auto' and source not in provider.LANGUAGES):abort(400)
    voice=voice_name=script='';ms=0;pcm=None
    if mode=='translate':
        title,ms,pcm=media.upload(request.files.get('file'),preserve_video=True)
        estimated=reserve=math.ceil(ms/1000)
    elif mode=='voiceover':
        translated=request.form.get('translate_script')=='yes'
        script=request.form.get('translated_script' if translated else 'script','').strip()
        if not 1<=len(script)<=4000 or not re.search(r'\w',script):raise store.AudioError('Tulis naskah 1–4.000 karakter dalam bahasa yang dipilih.')
        voice=request.form.get('voice','')
        if voice.startswith('personal:'):
            try:choice=personal.saved(user,int(voice.split(':',1)[1]))
            except ValueError:abort(400)
            if choice:choice={'id':choice['voice_id'],'name':choice['name']}
        elif voice=='personal':
            saved=personal.get(user)
            choice={'id':saved,'name':'Suara Saya'} if saved else None
        else:
            choices=provider.voices()
            choice=next((v for i,v in enumerate(choices) if voice in (v['id'],'kilas-'+str(i))),None)
        if not choice:raise store.AudioError('Suara belum tersedia. Pilih kembali atau coba lagi nanti.','voice_unavailable',503)
        voice=choice['id'];voice_name=choice['name'];title=' '.join(script.split())[:100];source=target
        if translated:
            if target not in provider.LANGUAGES:abort(400)
            source=request.form.get('translation_source','auto')
            if source!='auto' and source not in provider.LANGUAGES:abort(400)
        estimated,reserve=service.estimate(script)
        if estimated>media.duration_limit():raise store.AudioError('Naskah terlalu panjang. Pendekkan naskah sebelum membuat audio.')
    else:abort(400)
    ident,new=store.create(user,key,mode,title,source,target,voice,voice_name,script,ms,pcm,estimated,reserve,personal_required=mode=='voiceover' and request.form.get('voice','').startswith('personal:'))
    if new:service.submit(user,ident)
    return {'url':url_for('kilas_audio.home',ident=ident),'id':ident},201 if new else 200


@audio_bp.post('/personal-voice')
def create_personal_voice():
    if request.form.get('consent')!='yes':raise store.AudioError('Setujui izin penggunaan suara sebelum melanjutkan.','consent_required')
    key=request.form.get('operation_key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',key):abort(400)
    store.require_balance(session['user_id'])
    try:
        if 'name' in request.form:
            ident=request.form.get('saved_voice_id','')
            if ident and not ident.isdigit():abort(400)
            result=personal.save_named(session['user_id'],key,request.files.get('recording'),request.form['name'],int(ident) if ident else None)
            return {'ready':True,**result},200,{'Cache-Control':'private, no-store'}
        personal.create(session['user_id'],key,request.files.get('recording'),request.form.get('replace')=='yes')
    except provider.ProviderError:
        return {'error':'Suara belum berhasil dibuat. Rekamanmu tetap aman untuk dicoba kembali.'},503
    return {'ready':True},200,{'Cache-Control':'private, no-store'}


@audio_bp.get('/personal-voice/preview')
def personal_voice_preview():
    raw=personal.preview(session['user_id'])
    if not raw:abort(404)
    response=send_file(io.BytesIO(raw),mimetype='audio/mpeg')
    response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
    return response


@audio_bp.get('/personal-voices/<int:ident>/preview')
def saved_voice_preview(ident):
    raw=personal.saved_preview(session['user_id'],ident)
    if not raw:abort(404)
    response=send_file(io.BytesIO(raw),mimetype='audio/mpeg')
    response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
    return response


@audio_bp.post('/personal-voices/<int:ident>/rename')
def rename_saved_voice(ident):
    personal.rename_saved(session['user_id'],ident,request.form.get('name',''))
    return {'ready':True},200,{'Cache-Control':'private, no-store'}


@audio_bp.post('/personal-voices/<int:ident>/delete')
def delete_saved_voice(ident):
    try:personal.delete_saved(session['user_id'],ident)
    except provider.ProviderError:
        return {'error':'Suara belum berhasil dihapus. Suara tersimpan tetap tersedia. Coba lagi nanti.'},503
    return {'ready':True},200,{'Cache-Control':'private, no-store'}


@audio_bp.post('/voice-script/translate')
def translate_voice_script():
    import time
    store.require_balance(session['user_id'])
    text=request.form.get('script','').strip();target=request.form.get('language','')
    if not 1<=len(text)<=4000 or target not in provider.LANGUAGES:abort(400)
    now=time.time();recent=[v for v in session.get('voice_translation_times',[]) if now-v<60]
    if len(recent)>=6:raise store.AudioError('Terlalu banyak terjemahan. Coba lagi sebentar.','translation_rate_limit',429)
    session['voice_translation_times']=recent+[now]
    return voice_script.translate(text,target),200,{'Cache-Control':'private, no-store'}


@audio_bp.get('/jobs/<int:ident>/status')
def status(ident):
    owned(ident);job=service.refresh(session['user_id'],ident)
    return {'status':job['status'],'id':ident,'status_label':{'QUEUED':'Menunggu','PROCESSING':'Diproses','COMPLETED':'Selesai','FAILED':'Belum berhasil'}[job['status']],
            'duration_label':seconds(((job['source_ms'] if job['mode']=='translate' else job['actual_ms'])+999)//1000),
            'balance_html':render_template('kilas_translator/_balance.html',balance=store.balance(session['user_id']),seconds=seconds),
            'html':render_template('kilas_translator/_result.html',job=job,languages=provider.LANGUAGES,seconds=seconds)},200,{'Cache-Control':'no-store'}


@audio_bp.get('/jobs/<int:ident>/result')
def result(ident):
    job=owned(ident)
    if job['status']!='COMPLETED':abort(404)
    item=db.query_one("SELECT result_content FROM kilas_audio_jobs WHERE id=? AND user_id=? AND status='COMPLETED'",(ident,session['user_id']))
    raw=bytes(item['result_content'])
    # Ignore user paths; only the sanitized display stem and fixed provider language name.
    from werkzeug.utils import secure_filename
    video=raw[4:8]==b'ftyp'
    name=(secure_filename(job['title']).rsplit('.',1)[0][:80] or 'audio')+'-'+provider.LANGUAGES.get(job['target_language'],'Voice Over').split(' / ')[0]+('.mp4' if video else '.mp3')
    response=send_file(io.BytesIO(raw),mimetype='video/mp4' if video else 'audio/mpeg',download_name=name,as_attachment=request.args.get('download')=='1')
    response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
    return response


@audio_bp.post('/checkout')
def checkout():
    ident=billing.create(session['user_id'],request.form.get('pack'))
    return redirect(url_for('kilas_audio.invoice',ident=ident),code=303)


@audio_bp.get('/orders/<int:ident>')
def invoice(ident):
    item=billing.order(session['user_id'],ident)
    if not item:abort(404)
    return render_template('kilas_translator/invoice.html',invoice=item,bank=payment_service.BANK_DETAILS,seconds=seconds)


@audio_bp.post('/orders/<int:ident>/proof')
def proof(ident):
    if not billing.order(session['user_id'],ident):abort(404)
    billing.proof(session['user_id'],ident,request.files.get('proof'))
    return redirect(url_for('kilas_audio.invoice',ident=ident),code=303)


@admin_bp.get('/audio/<int:ident>/proof')
def audio_proof(ident):
    row=db.query_one("SELECT proof_content,proof_filename,proof_mime_type FROM kilas_audio_orders WHERE id=? AND status='UNDER_REVIEW'",(ident,))
    if not row:abort(404)
    response=send_file(io.BytesIO(bytes(row['proof_content'])),mimetype=row['proof_mime_type'],download_name=row['proof_filename'])
    response.headers['Cache-Control']='private, no-store';response.headers['Content-Security-Policy']="default-src 'none'; sandbox"
    response.headers['X-Content-Type-Options']='nosniff';return response


@admin_bp.post('/audio/<int:ident>/review')
def audio_review(ident):
    try:billing.review(ident,session['user_id'],request.form.get('decision'),request.form.get('note'))
    except store.AudioError as error:return {'error':str(error)},error.status
    return redirect(url_for('kilas_ai_admin.payments'),code=303)
