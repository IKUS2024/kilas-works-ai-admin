"""Authenticated Translator utility, private media and existing admin review."""
import io
import hashlib
import math
import os
import re
import secrets
from flask import Response, Blueprint, abort, redirect, render_template, request, send_file, session, url_for
import db
import security
from . import free_test
import payment_service
from .routes import enabled
from .billing_routes import admin_bp
from . import audio_store as store, audio_provider as provider, audio_service as service, audio_media as media, audio_billing as billing, usage
from . import audio_personal_voice as personal
from . import audio_branded_voices as branded
from . import translator_languages as translator
from . import audio_voice_script as voice_script
from . import audio_transcription_budget as video_budget, audio_transcription_provider as video_stt

audio_bp=Blueprint('kilas_audio',__name__,url_prefix='/kilas-translator')


@audio_bp.record_once
def warm_translator_catalog(state):
    if not state.app.testing:translator.warmup()  # Read-only model metadata; no audio.


def _shared_native_user(user):
    from . import live_gemini_budget as budget
    config=budget.policy()
    return bool(config and config['mode']=='owner_lifetime'
                and config.get('audience')=='authenticated' and budget.allowed(user,config))


def _native_default_ready(user):
    from . import live_gemini as native, live_gemini_pair as pair
    # Native remains an explicit opt-in; ordinary Translator uses Kilas voices.
    if os.environ.get('KILAS_TRANSLATOR_PROVIDER','elevenlabs')!='gemini':return False
    if request.args.get('classic')=='1':return False
    row=db.query_one("SELECT voice_alias FROM kilas_live_translator_sessions WHERE user_id=? AND status='ACTIVE' AND (expires_at='' OR expires_at>?) ORDER BY created_at DESC LIMIT 1",(user,usage._now().isoformat()))
    # An old session stays on its original page until its user explicitly ends
    # it. A GET cannot migrate it or imply that its old pipeline uses Gemini.
    # Funding/busy state disables native Start; it must not switch providers.
    return row['voice_alias'] in (native.VOICE,*pair.VOICES) if row else native.ready(user)


def _active_native_session(user):
    from . import live_gemini as native, live_gemini_pair as pair
    return bool(db.query_one("SELECT 1 FROM kilas_live_translator_sessions WHERE user_id=? AND voice_alias IN (?,?,?) AND status='ACTIVE' AND (expires_at='' OR expires_at>?)",(user,native.VOICE,*pair.VOICES,usage._now().isoformat())))


def _native_route_access(user):
    """An explicit native exception; legacy audio keeps its existing role gate."""
    from . import live_gemini as native, live_gemini_pair as pair
    endpoint=request.endpoint
    shared=_shared_native_user(user)
    if endpoint=='kilas_audio.live_gemini_home':
        return shared or _active_native_session(user)
    if endpoint in {
        'kilas_audio.live_gemini_session',
        'kilas_audio.live_gemini_turn','kilas_audio.live_gemini_chunk',
        'kilas_audio.live_gemini_finish',
    }:
        return shared
    if (endpoint=='kilas_audio.live_translator_home'
            or (endpoint=='kilas_audio.home' and request.view_args.get('ident') is None
                and request.args.get('mode')=='live')):
        return (shared or _active_native_session(user)) and _native_default_ready(user)
    if endpoint=='kilas_audio.live_translator_active':
        # The browser discovers only its own session. An existing native user
        # can still recover after rollout is disabled; never expose legacy
        # sessions through the native-only exception.
        row=db.query_one("SELECT voice_alias FROM kilas_live_translator_sessions WHERE user_id=? AND status='ACTIVE' AND (expires_at='' OR expires_at>?) ORDER BY created_at DESC LIMIT 1",(user,usage._now().isoformat()))
        if row:return row['voice_alias'] in (native.VOICE,*pair.VOICES)
        # After a successful explicit End the recovery UI checks once more.
        # Native participation grants this empty discovery response even OFF.
        return shared or bool(db.query_one('SELECT 1 FROM kilas_live_translator_sessions WHERE user_id=? AND voice_alias IN (?,?,?) LIMIT 1',(user,native.VOICE,*pair.VOICES)))
    if endpoint in {'kilas_audio.live_translator_session_status',
                    'kilas_audio.live_translator_end','kilas_audio.live_translator_cancel_turn'}:
        row=db.query_one('SELECT voice_alias FROM kilas_live_translator_sessions WHERE user_id=? AND id=?',
                         (user,request.view_args['ident']))
        return bool(row and row['voice_alias'] in (native.VOICE,*pair.VOICES))
    return False


@audio_bp.before_request
def access():
    if not enabled():abort(404)
    if not session.get('user_id'):return redirect(url_for('auth.login_page'))
    if type(session['user_id']) is not int or not 0<session['user_id']<=10**9:abort(404)
    user=security.current_user()
    if not user or user['id']!=session['user_id'] or session.get('role')!=user['role']:abort(404)
    # The app's customer_auth middleware has already checked the revocable
    # login, disabled state and fresh DB role. A signed cookie alone cannot
    # establish access. This exception grants no legacy product entitlement.
    if user['role']!='CLIENT_OWNER' and not free_test.eligible(session['user_id']) and not _native_route_access(session['user_id']):abort(404)


@audio_bp.errorhandler(store.AudioError)
@audio_bp.errorhandler(media.MediaError)
def invalid(error):
    result = {'error':str(error),'code':getattr(error,'code','invalid')}
    if getattr(error,'purchase_applicable',True):
        result['purchase_url'] = url_for('kilas_ai.usage_page')+'#audio-settings-title'
    return result,getattr(error,'status',400)


def owned(ident):
    job=store.get(session['user_id'],ident)
    if not job or store.is_live_output(session['user_id'],ident) or store.is_learning_output(session['user_id'],ident):abort(404)
    return job


def seconds(value):
    value=int(value)
    return f'{value//60}m {value%60:02d}s' if value>=60 else f'{value}s'


def _history_args():
    try:
        page=int(request.args.get('page',1))
        through=int(request.args['through']) if 'through' in request.args else None
        selected=int(request.args['selected']) if request.args.get('selected') else None
    except ValueError:abort(400)
    if any(value is not None and not 0<=value<=2**63-1 for value in (through,selected)):abort(400)
    return page,through,selected


@audio_bp.get('/history')
def history_fragment():
    page,through,selected=_history_args()
    kind=request.args.get('kind','voiceover')
    if kind not in ('voiceover','translate'):abort(400)
    data=store.history_page(session['user_id'],page,through=through,kind=kind)
    html=render_template('kilas_translator/_history.html',**data,selected_job_id=selected,
                         video_script_ready=video_budget.ready(session['user_id']),
                         languages=provider.LANGUAGES,translation_labels=translator.localized_names(),seconds=seconds)
    return {'html':html,'page':data['history_page'],'pages':data['history_page_count'],
            'total':data['history_total']},200,{'Cache-Control':'private, no-store'}


@audio_bp.get('')
@audio_bp.get('/jobs/<int:ident>')
def home(ident=None,initial_brief=None,home_task=None):
    if ident is None and request.args.get('mode')=='live':
        return live_translator_home()
    from .content_projects import draft
    content_draft = draft(session['user_id'])
    user=session['user_id'];job=owned(ident) if ident else None
    mode_hint=request.args.get('mode')
    active_mode=mode_hint if mode_hint in ('translate','voiceover') else home_task if home_task in ('translate','voiceover') else job['mode'] if job else content_draft['mode'] if content_draft and content_draft['mode'] in ('translate','voiceover') else 'translate'
    from .audio_presentation import upload_translation_visible
    if not upload_translation_visible():active_mode='voiceover'
    return_to=request.form.get('return_to','') if request.method=='POST' else ''
    if not re.fullmatch(r'/products/start|/kilas-ai/threads/[0-9]+|/kilas-ai/agent(?:\?conversation=[0-9]+)?',return_to):return_to=''
    state=store.balance(user)
    page,through,_=_history_args()
    recent=store.history_page(user,page,through=through,kind=active_mode)
    saved_voices=personal.saved_voices(user)
    return render_template('kilas_translator/home.html',**recent,selected_job_id=job['id'] if job else None,active_mode=active_mode,video_script_ready=video_budget.ready(user),content_draft=content_draft,initial_brief=initial_brief,home_task=home_task,balance=state,job=job,return_to=return_to,
                           voices=branded.public_choices(),voice_sample_aliases=branded.sample_aliases(),
                           personal_voice=bool(personal.get(user)),personal_preview=personal.has_preview(user),voice_operation_key=secrets.token_hex(16),
                           saved_voices=saved_voices,
                           provider_ready=provider.configured(),languages=provider.LANGUAGES,translation_labels=translator.localized_names(),
                           translator_language_names=translator.localized_names(),dubbing_languages=translator.names(translator.DUBBING),dubbing_sources=translator.names(translator.STT&translator.DUBBING),packs=store.PACKS,
                           seconds=seconds,operation_key=secrets.token_hex(16),max_mb=media.file_limit()//1024//1024,audio_max_mb=media.file_limit('wav')//1024//1024,max_seconds=media.duration_limit())


@audio_bp.post('')
def home_handoff():
    if request.form.get('task') not in ('translate','voiceover'):abort(400)
    from .home_tasks import open_task
    return open_task()


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
    targets=translator.DUBBING if mode=='translate' else provider.LANGUAGES
    sources=translator.STT&translator.DUBBING if mode=='translate' else provider.LANGUAGES
    if (target not in targets and not (mode=='voiceover' and target=='auto')) or (source!='auto' and source not in sources):abort(400)
    voice=voice_name=script='';original_script=None;ms=0;pcm=None
    if mode=='translate':
        title,ms,pcm=media.upload(request.files.get('file'),preserve_video=True)
        estimated=reserve=math.ceil(ms/1000)
    elif mode=='voiceover':
        original_script=request.form.get('script')
        if original_script is not None and len(original_script)>4000:raise store.AudioError('Naskah asli maksimal 4.000 karakter; teks tidak dipotong.')
        if not original_script or not re.search(r'\w',original_script):original_script=None
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
        elif voice in ('kilas-male','kilas-female'):
            choice=branded.resolve(voice)
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
    ident,new=store.create(user,key,mode,title,source,target,voice,voice_name,script,ms,pcm,estimated,reserve,personal_required=mode=='voiceover' and request.form.get('voice','').startswith('personal:'),original_script=original_script)
    if new:service.submit(user,ident)
    return {'url':url_for('kilas_audio.home',ident=ident),'id':ident},201 if new else 200


@audio_bp.post('/jobs/<int:ident>/alternate')
def alternate(ident):
    user=session['user_id'];job=owned(ident)
    key=request.form.get('operation_key','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',key):abort(400)
    if job['mode']!='voiceover' or job['status']!='COMPLETED' or not job['has_spoken_script']:abort(409)
    existing=db.query_one('SELECT id,alternate_of FROM kilas_audio_jobs WHERE user_id=? AND operation_key=?',(user,key))
    if existing:
        if existing['alternate_of']!=ident:abort(409)
        return {'url':url_for('kilas_audio.home',ident=existing['id']),'id':existing['id']},200
    store.require_balance(user)
    if not provider.configured():raise store.AudioError('Audio sedang belum tersedia. Saldo kamu tetap aman.','not_configured',503)
    if job['voice_is_personal'] and not personal.owns(user,job['voice_id']):
        raise store.AudioError('Suara tidak lagi tersedia. Pilih kembali.','voice_unavailable',409)
    source=db.query_one('SELECT spoken_script,original_script FROM kilas_audio_jobs WHERE id=? AND user_id=?',(ident,user))
    estimate,reserve=service.estimate(source['spoken_script'])
    new_id,new=store.create(user,key,'voiceover',job['title'],job['source_language'],job['target_language'],job['voice_id'],job['voice_name'],source['spoken_script'],0,None,estimate,reserve,
                           original_script=source['original_script'],alternate_of=ident,delivery_stability=0.65 if job['delivery_stability']==0.35 else 0.35)
    if new:service.submit(user,new_id)
    return {'url':url_for('kilas_audio.home',ident=new_id),'id':new_id},201 if new else 200


@audio_bp.post('/personal-voice/inspect')
def inspect_personal_voice():
    # Local decoder only: no clone, provider request, voice mutation or balance deduction.
    store.require_balance(session['user_id'])
    ms,_=media.voice_sample(request.files.get('recording'),with_duration=True)
    return {'duration_ms':ms},200,{'Cache-Control':'private, no-store'}


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


@audio_bp.get('/voices/<alias>/sample')
def branded_voice_sample(alias):
    raw=branded.sample(alias)
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


@audio_bp.route('/voice-script/video',methods=['POST','GET'])
def video_script():
    owner=session['user_id'];key=request.args.get('operation_key') if request.method=='GET' else request.form.get('operation_key')
    headers={'Cache-Control':'private, no-store'}
    try:
        video_budget.key_valid(key)
        if request.method=='GET':
            row=video_budget.owned(owner,key)
            if not row:abort(404)
            return row,200,headers
        if request.form.get('action')=='cancel':return video_budget.cancel(owner,key),200,headers
        if request.form.get('consent')!='yes':raise video_budget.BudgetError('consent_required',400)
        if not video_budget.ready(owner):raise video_budget.BudgetError('budget_unavailable')
        item=request.files.get('video')
        if not item or not item.filename or item.filename.rsplit('.',1)[-1].lower()!='mp4':raise video_budget.BudgetError('invalid_video',400)
        _,_,pcm=media.upload(item)
        pcm,ms=video_stt.normalize(pcm)
        row,capability=video_budget.claim(owner,key,hashlib.sha256(pcm).hexdigest(),ms)
        if capability:
            text=video_stt.transcribe(pcm,capability)
            row=video_budget.owned(owner,key)
            if text is not None and row['status']=='COMPLETED':row['text']=text
        return row,200,headers
    except video_budget.BudgetError as error:
        messages={'budget_unavailable':'Unggah video ke naskah belum tersedia. Batas biaya transkripsi belum diaktifkan; kamu tetap bisa mengetik atau memakai Bantu AI.',
                  'budget_limit':'Batas transkripsi tercapai. Naskah kamu tetap aman.',
                  'consent_required':'Setujui pemrosesan ucapan dari video terlebih dahulu.',
                  'script_too_long':'Hasil lebih dari 4.000 karakter. Video tidak dipotong; naskah semula tetap aman. Pilih video lebih pendek.',
                  'invalid_video':'Pilih file MP4 yang valid.',
                  'attempt_limit':'Batas percobaan hari ini tercapai. Naskah kamu tetap aman.'}
        return {'error':messages.get(error.code,'Video belum dapat dijadikan naskah. Naskah semula tetap aman; tidak ada pengulangan otomatis.'),'code':error.code},error.status,headers


@audio_bp.post('/voice-script/dictate')
def dictate():
    owner=session['user_id'];key=request.form.get('operation_key')
    headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}
    try:
        video_budget.key_valid(key)
        if not key.startswith('dictate-'):raise video_budget.BudgetError('invalid_operation',400)
        if request.form.get('action')=='cancel':return video_budget.cancel(owner,key),200,headers
        if request.form.get('consent')!='yes':raise video_budget.BudgetError('consent_required',400)
        # Owner usage renews its finite monthly allowance; QA remains fixed/expiring.
        if not video_budget.ready(owner):raise video_budget.BudgetError('budget_unavailable')
        pcm=media.voice_sample(request.files.get('recording'),sample_rate=16000)
        pcm,ms=video_stt.normalize(pcm)
        if (video_budget.policy() or {}).get('mode')=='owner':video_stt.require_subscription_credit()
        row,capability=video_budget.claim(owner,key,hashlib.sha256(pcm).hexdigest(),ms)
        if capability:
            text=video_stt.transcribe(pcm,capability)
            row=video_budget.owned(owner,key)
            if text is not None and row['status']=='COMPLETED':row['text']=text
        return row,200,headers
    except video_budget.BudgetError as error:
        message={'budget_unavailable':'Dikte belum aktif. Batas biaya transkripsi belum terverifikasi; naskah tetap aman.',
                 'consent_required':'Setujui pemrosesan rekaman sebelum mulai.',
                 'attempt_limit':'Batas percobaan transkripsi hari ini tercapai. Naskah tetap aman.',
                 'rate_limit':'Terlalu banyak dikte dalam satu jam. Coba lagi nanti; naskah tetap aman.',
                 'provider_credit_exhausted':'Kapasitas layanan suara tidak cukup. Dikte dihentikan tanpa pembelian tambahan; naskah tetap aman.',
                 'provider_billing_unverified':'Status layanan suara belum terverifikasi. Dikte dihentikan; naskah tetap aman.',
                 'provider_credit_check_failed':'Kapasitas layanan suara belum dapat diperiksa. Coba lagi nanti; naskah tetap aman.',
                 'script_too_long':'Hasil melebihi 4.000 karakter. Rekam ucapan yang lebih pendek.',
                 'budget_limit':'Batas transkripsi tercapai. Naskah tetap aman.'}.get(error.code,
                 'Dikte belum berhasil. Naskah tetap aman. Tidak ada pengulangan otomatis; kamu dapat merekam kembali.')
        return {'error':message,'code':error.code},error.status,headers


@audio_bp.route('/jobs/<int:ident>/reconstruct-script',methods=['POST','GET'])
def reconstruct_script(ident):
    # Never fetch an arbitrary URL or overwrite an archived original.
    owner=session['user_id'];job=owned(ident)
    headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}
    if job['mode']!='voiceover' or job['status']!='COMPLETED':abort(404)
    key=request.args.get('operation_key') if request.method=='GET' else request.form.get('operation_key')
    try:
        video_budget.key_valid(key)
        if not key.startswith('legacy-'+str(ident)+'-'):raise video_budget.BudgetError('invalid_operation',400)
        if request.method=='GET':
            row=video_budget.owned(owner,key)
            if not row:abort(404)
        elif request.form.get('action')=='cancel':row=video_budget.cancel(owner,key)
        else:
            original=store.edit_script(owner,ident)
            if original is not None:
                return {'status':'COMPLETED','text':original,'source_kind':'original_script','job_id':ident},200,headers
            if request.form.get('consent')!='yes':raise video_budget.BudgetError('consent_required',400)
            if not video_budget.ready(owner):raise video_budget.BudgetError('budget_unavailable')
            size=db.query_one("SELECT length(result_content) AS size FROM kilas_audio_jobs WHERE id=? AND user_id=? AND mode='voiceover' AND status='COMPLETED' AND original_script IS NULL",(ident,owner))
            if not size or not size['size'] or size['size']>20*1024*1024:raise video_budget.BudgetError('invalid_audio',400)
            item=db.query_one("SELECT result_content FROM kilas_audio_jobs WHERE id=? AND user_id=? AND mode='voiceover' AND status='COMPLETED' AND original_script IS NULL",(ident,owner))
            if not item or not item['result_content']:raise video_budget.BudgetError('invalid_audio',400)
            raw=bytes(item['result_content'])
            if not (raw[:3]==b'ID3' or (len(raw)>1 and raw[0]==255 and raw[1]&224==224)):raise video_budget.BudgetError('invalid_audio',400)
            _,pcm=media.decode(raw,'mp3');pcm,ms=video_stt.normalize(pcm)
            row,capability=video_budget.claim(owner,key,hashlib.sha256(pcm).hexdigest(),ms)
            if capability:
                text=video_stt.transcribe(pcm,capability);row=video_budget.owned(owner,key)
                if text is not None and row['status']=='COMPLETED':row['text']=text
        return {**row,'source_kind':'audio_reconstruction','job_id':ident},200,headers
    except (video_budget.BudgetError,media.MediaError) as error:
        code=getattr(error,'code','invalid_audio')
        message='Transkripsi audio lama belum diaktifkan. Kamu tetap bisa memakai naskah asli tersimpan atau mengetik; draf dan audio tetap aman.' if code=='budget_unavailable' else 'Audio lama belum dapat ditranskripsikan. Naskah asli tidak direka; draf dan hasil audio tetap aman. Tidak ada pengulangan otomatis.'
        return {'error':message,'code':code},getattr(error,'status',400),headers


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
            'edit_script_url':url_for('kilas_audio.script_for_edit',ident=ident) if job['has_edit_script'] else None,
            'html':render_template('kilas_translator/_result.html',job=job,languages=provider.LANGUAGES,translation_labels=translator.localized_names(),seconds=seconds,video_script_ready=video_budget.ready(session['user_id']))},200,{'Cache-Control':'no-store'}


@audio_bp.get('/jobs/<int:ident>/script')
def script_for_edit(ident):
    owned(ident)
    user=session['user_id'];snapshot=store.spoken_edit_script(user,ident)
    headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}
    if snapshot is None:
        return {'error':'Naskah yang diucapkan tidak tersimpan untuk hasil lama ini. Hasil audio tetap tersimpan.','code':'script_unavailable'},409,headers
    # Return a selector understood by the existing form, never another voice
    # with a similar name. Missing/deleted voices require an explicit choice.
    voice=None
    saved=db.query_one('SELECT id FROM kilas_audio_saved_voices WHERE user_id=? AND voice_id=? ORDER BY id LIMIT 1',(user,snapshot['voice_id']))
    if saved:voice='personal:'+str(saved['id'])
    if not voice and not snapshot['voice_is_personal']:
        voice=next((row['alias'] for row in branded.choices() if row['id']==snapshot['voice_id']),None)
    return {'script':snapshot['spoken_script'],'source_kind':'spoken_script',
            'language':snapshot['target_language'],'voice':voice},200,headers


@audio_bp.get('/jobs/<int:ident>/result')
def result(ident):
    job=owned(ident)
    if job['status']!='COMPLETED':abort(404)
    item=db.query_one("SELECT result_content FROM kilas_audio_jobs WHERE id=? AND user_id=? AND status='COMPLETED'",(ident,session['user_id']))
    raw=bytes(item['result_content'])
    # Ignore user paths; only the sanitized display stem and fixed provider language name.
    from werkzeug.utils import secure_filename
    video=raw[4:8]==b'ftyp'
    wav = request.args.get('format') == 'wav'
    if wav:
        if job['mode'] != 'voiceover' or video:abort(400)
        raw = media.download_wav(raw)
    name=(secure_filename(job['title']).rsplit('.',1)[0][:80] or 'audio')+'-'+(translator.NAMES if job['mode']=='translate' else provider.LANGUAGES).get(job['target_language'],'Voice Over').split(' / ')[0]+('.wav' if wav else '.mp4' if video else '.mp3')
    response=send_file(io.BytesIO(raw),mimetype='audio/wav' if wav else 'video/mp4' if video else 'audio/mpeg',download_name=name,as_attachment=request.args.get('download')=='1')
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


@audio_bp.get('/live')
def live_translator_home():
    from . import live_translator as live
    if _native_default_ready(session['user_id']):
        # Navigation never ends or replaces an active session. Native Start
        # retains the existing session_busy fence and explicit recovery UI.
        return redirect(url_for('kilas_audio.live_gemini_home')),302,{'Cache-Control':'private, no-store'}
    languages=translator.classic_names()
    return render_template('kilas_translator/live.html',live_ready=live.ready(session['user_id']) and len(languages)>1,voices=branded.public_choices(),languages=languages,translator_language_names=translator.localized_names()),200,{'Cache-Control':'private, no-store'}


@audio_bp.post('/live/sessions')
def live_translator_start():
    from . import live_translator as live, live_translator_store as sessions
    live.require_ready(session['user_id'])
    if request.form.get('consent')!='yes':raise store.AudioError('Setujui pemrosesan ucapan sebelum mulai.','consent_required',400)
    a,b=request.form.get('language_a'),request.form.get('language_b');voice=request.form.get('voice')
    sessions.require_explicit_pair(a,b,voice=voice)
    translator.require_classic(a,b)
    if not branded.resolve(voice):raise store.AudioError('Suara yang dipilih tidak tersedia.','voice_unavailable',409)
    store.require_balance(session['user_id'])
    capture=request.form.get('capture_transport')
    if capture not in (None,'batch','realtime-v1'):raise store.AudioError('Input browser tidak valid.','input_mode_changed',400)
    from . import live_translator_realtime as realtime
    mode='realtime-v1' if capture!='batch' and realtime.ready(session['user_id']) else 'batch'
    ident=sessions.create(session['user_id'],a,b,voice)
    return {'session_id':ident,'input_mode':mode},201,{'Cache-Control':'private, no-store'}


@audio_bp.post('/live/sessions/<ident>/renew')
def live_translator_renew(ident):
    from . import live_translator as live, live_translator_store as sessions, live_translator_realtime as realtime
    live.require_ready(session['user_id'])
    if request.form.get('consent')!='yes':raise store.AudioError('Setujui pemrosesan ucapan sebelum mulai.','consent_required',400)
    a,b,voice=(request.form.get(name) for name in ('language_a','language_b','voice'))
    sessions.require_explicit_pair(a,b,voice=voice);translator.require_classic(a,b)
    if not branded.resolve(voice):raise store.AudioError('Suara yang dipilih tidak tersedia.','voice_unavailable',409)
    capture=request.form.get('capture_transport')
    if capture not in (None,'batch','realtime-v1'):raise store.AudioError('Input browser tidak valid.','input_mode_changed',400)
    requested=request.form.get('input_mode')
    mode='realtime-v1' if capture!='batch' and realtime.ready(session['user_id']) else 'batch'
    if requested!=mode:raise store.AudioError('Input sesi berubah. Akhiri sesi lalu mulai kembali.','input_mode_changed',409)
    store.require_balance(session['user_id']);live.require_audio_allowance(session['user_id'])
    new=sessions.renew(session['user_id'],ident,a,b,voice)
    realtime.cancel(session['user_id'],ident)
    return {'session_id':new,'input_mode':mode},201,{'Cache-Control':'private, no-store'}


@audio_bp.post('/live/sessions/<ident>/end')
def live_translator_end(ident):
    # End remains allowed when a rollout flag/campaign expires or is switched off.
    from . import live_translator_store as sessions
    sessions.end(session['user_id'],ident)
    from . import live_translator_realtime
    live_translator_realtime.cancel(session['user_id'],ident)
    from . import live_gemini
    live_gemini.cancel(session['user_id'],ident)
    return {'status':'ENDED'},200,{'Cache-Control':'private, no-store'}


@audio_bp.get('/live/sessions/active')
def live_translator_active():
    # Like End, owner recovery remains available when rollout readiness is off.
    from . import live_translator_store as sessions
    return {'session':sessions.active(session['user_id'])},200,{'Cache-Control':'private, no-store'}


@audio_bp.get('/live/sessions/<ident>')
def live_translator_session_status(ident):
    from . import live_translator_store as sessions
    return sessions.status(session['user_id'],ident),200,{'Cache-Control':'private, no-store'}


@audio_bp.post('/live/sessions/<ident>/turns/<key>/cancel')
def live_translator_cancel_turn(ident,key):
    from . import live_translator_store as sessions
    if not re.fullmatch(r'live-[a-f0-9]{32}',key):abort(400)
    status=sessions.cancel_turn(session['user_id'],ident,key)
    from . import live_translator_realtime
    live_translator_realtime.cancel(session['user_id'],ident,key)
    from . import live_gemini
    live_gemini.cancel(session['user_id'],ident,key)
    return {'status':status,**({} if live_translator_realtime.settled(session['user_id'],key) else {'input_settled':False})},200,{'Cache-Control':'private, no-store'}


@audio_bp.get('/live/gemini')
def live_gemini_home():
    from . import live_gemini as native, live_gemini_pair as pair
    active=db.query_one("SELECT voice_alias,language_a,language_b FROM kilas_live_translator_sessions WHERE user_id=? AND status='ACTIVE' AND (expires_at='' OR expires_at>?) ORDER BY created_at DESC LIMIT 1",(session['user_id'],usage._now().isoformat()))
    # Existing one-way sessions retain their original protocol and consent.
    # The server-owned marker, never a request flag, selects their backend.
    two_way = not active or active['voice_alias']!=native.VOICE
    backend = pair if two_way else native
    info=active if active and active['voice_alias'] in (native.VOICE,*pair.VOICES) else {
        'voice_alias':pair.VOICE,'language_a':'id','language_b':'en'}
    enabled = backend.ready(session['user_id'])
    recovery_only = not enabled and _active_native_session(session['user_id'])
    if not enabled and not recovery_only and not native.ready(session['user_id']) and not native.preview_owner(session['user_id']):
        raise native.failure('gemini_unavailable',404)
    return render_template('kilas_translator/gemini.html', languages=translator.native_names(),translator_language_names=translator.localized_names(native=True), gemini_ready=enabled,
                           gemini_recovery_only=recovery_only,gemini_two_way=two_way,
                           gemini_protocol=_native_protocol(backend,info)),200,{'Cache-Control':'private, no-store'}


@audio_bp.get('/live/gemini/fixtures')
def live_gemini_fixtures():
    from . import live_gemini_capture as capture
    capture.require_owner(session['user_id'])
    return {'fixtures':capture.list_for_owner(session['user_id'])}, 200, {
        'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff'}


@audio_bp.get('/live/gemini/fixtures/<opaque>/<kind>')
def live_gemini_fixture_export(opaque, kind):
    from . import live_gemini_capture as capture
    capture.require_owner(session['user_id'])
    artifact = capture.export(session['user_id'], opaque, kind)
    response = send_file(io.BytesIO(artifact['data']), mimetype=artifact['mimetype'],
                         as_attachment=True, download_name=artifact['filename'],
                         conditional=False, etag=False, max_age=0)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@audio_bp.post('/live/gemini/sessions')
def live_gemini_session():
    from . import live_gemini as native, live_gemini_pair as pair, live_translator_store as sessions
    mode=request.form.get('translation_mode')
    if mode=='two_way':
        backend=pair;consent=request.form.get('consent');order=request.form.get('output_order')
        if consent==pair.INPUT_MODE and order==pair.OUTPUT_ORDER:
            voice=pair.VOICE
        elif consent==pair.LEGACY_INPUT_MODE and order in (None,pair.LEGACY_OUTPUT_ORDER):
            # Cached v1 forms retain their original full-turn playback contract.
            voice=pair.LEGACY_VOICE
        elif consent not in (pair.INPUT_MODE,pair.LEGACY_INPUT_MODE):
            raise store.AudioError('Setujui pemrosesan ucapan sebelum mulai.', 'consent_required',400)
        else:
            raise store.AudioError('Muat ulang halaman sebelum memulai mode audio ini.','invalid_output_order',400)
    elif mode in (None,'one_way'):
        # A cached one-way page can only request its original single stream.
        backend=native;consent='gemini-live-v1';voice=native.VOICE
    else:
        raise store.AudioError('Pilih mode terjemahan yang tersedia.','invalid_translation_mode',400)
    if not backend.ready(session['user_id']):raise native.failure('gemini_unavailable',404)
    if request.form.get('consent') != consent:
        raise store.AudioError('Setujui pemrosesan ucapan sebelum mulai.', 'consent_required', 400)
    a, b = request.form.get('language_a'), request.form.get('language_b')
    sessions.require_pair(a, b,voice=voice)
    store.require_balance(session['user_id'])
    ident = sessions.create(session['user_id'], a, b, voice)
    info={'voice_alias':voice,'language_a':a,'language_b':b}
    return {'session_id':ident, **_native_protocol(backend,info),
            'max_input_ms':60000, 'max_output_ms':90000}, 201, {'Cache-Control':'private, no-store'}


def _native_protocol(backend,info):
    from . import live_gemini_pair as pair
    if backend is pair:
        return pair.protocol(info)
    return {'input_mode':'gemini-live-v1','translation_mode':'one_way','target_language':info['language_b']}


def _owned_native_backend(ident):
    from . import live_gemini as native, live_gemini_pair as pair
    row=db.query_one('SELECT voice_alias,language_a,language_b FROM kilas_live_translator_sessions WHERE id=? AND user_id=?',
                     (ident,session['user_id']))
    if not row or row['voice_alias'] not in (native.VOICE,*pair.VOICES):
        raise store.AudioError('Sesi tidak tersedia.','session_unavailable',404)
    return (pair if row['voice_alias'] in pair.VOICES else native),row


@audio_bp.route('/live/gemini/sessions/<ident>/turns/<key>', methods=['GET','POST'])
def live_gemini_turn(ident, key):
    if not re.fullmatch(r'live-[a-f0-9]{32}', key):
        abort(400)
    backend,info=_owned_native_backend(ident)
    if request.method == 'POST':
        backend.start(session['user_id'], ident, key)
        return {'status':'LISTENING', **_native_protocol(backend,info)}, 202, {'Cache-Control':'private, no-store'}
    try:
        after = int(request.args.get('after','0'))
    except ValueError:
        abort(400)
    result = backend.owned(session['user_id'], ident, key).snapshot(after)
    return result, 200, {'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff'}


@audio_bp.post('/live/gemini/sessions/<ident>/turns/<key>/chunks/<int:index>')
def live_gemini_chunk(ident, key, index):
    from . import live_gemini as native
    backend,_=_owned_native_backend(ident)
    relay = backend.owned(session['user_id'], ident, key)
    try:
        sample = request.files.get('pcm')
        if not sample or sample.mimetype != 'application/octet-stream':
            raise native.failure('gemini_input_invalid',400)
        relay.accept(index, sample.stream.read(16001))
    except Exception as error:
        relay.stop(error)
        raise
    return {'accepted_index':index}, 202, {'Cache-Control':'private, no-store'}


@audio_bp.post('/live/gemini/sessions/<ident>/turns/<key>/finish')
def live_gemini_finish(ident, key):
    from . import live_gemini as native
    backend,_=_owned_native_backend(ident)
    relay = backend.owned(session['user_id'], ident, key)
    try:
        value = request.form.get('count','')
        if not re.fullmatch(r'[0-9]{1,4}',value):
            raise native.failure('gemini_input_invalid',400)
        relay.finish_input(int(value))
    except Exception as error:
        relay.stop(error)
        raise
    return {'status':'DRAINING'}, 202, {'Cache-Control':'private, no-store'}


@audio_bp.post('/live/sessions/<ident>/turns/<key>/input/start')
def live_realtime_start(ident,key):
    from . import live_translator_realtime as realtime
    if not re.fullmatch(r'live-[a-f0-9]{32}',key):abort(400)
    capture_mode=request.form.get('capture_mode')
    if capture_mode not in (None,'hold-v1','clauses-v1'):raise realtime.failure('realtime_chunk_invalid')
    chunk_transport=request.form.get('chunk_transport')
    if chunk_transport not in (None,'pcm-coalesce-v1'):raise realtime.failure('realtime_chunk_invalid')
    relay=realtime.start(session['user_id'],ident,key,hold_to_talk=capture_mode=='hold-v1',coalesced=chunk_transport=='pcm-coalesce-v1',clauses=capture_mode=='clauses-v1')
    return {'status':'LISTENING','input_mode':'realtime-v1','max_chunk_bytes':relay.max_chunk_bytes},202,{'Cache-Control':'private, no-store'}


@audio_bp.route('/live/sessions/<ident>/turns/<key>/clauses',methods=['GET','POST'])
def live_clauses(ident,key):
    from . import live_translator_clauses as clauses
    if not re.fullmatch(r'live-[a-f0-9]{32}',key):abort(400)
    stream=clauses.owned(session['user_id'],ident,key)
    if request.method=='POST':
        index=request.form.get('index','')
        if not re.fullmatch(r'0|[1-9][0-9]{0,6}',index):abort(400)
        stream.ack(int(index))
    return stream.snapshot(),200,{'Cache-Control':'private, no-store'}


@audio_bp.post('/live/sessions/<ident>/turns/<key>/input/chunks/<int:index>')
def live_realtime_chunk(ident,key,index):
    from . import live_translator_realtime as realtime
    if not re.fullmatch(r'live-[a-f0-9]{32}',key):abort(400)
    relay=realtime.owned(session['user_id'],ident,key)
    try:
        sample=request.files.get('pcm')
        if not sample or sample.mimetype!='application/octet-stream':raise realtime.failure('realtime_chunk_invalid')
        relay.accept(index,sample.stream.read(relay.max_chunk_bytes+1))
    except Exception as error:
        relay.close(error);raise
    return {'accepted_index':index},202,{'Cache-Control':'private, no-store'}


@audio_bp.post('/live/sessions/<ident>/turns/<key>/input/commit')
def live_realtime_commit(ident,key):
    from . import live_translator_realtime as realtime
    if not re.fullmatch(r'live-[a-f0-9]{32}',key):abort(400)
    relay=realtime.owned(session['user_id'],ident,key)
    try:
        value=request.form.get('count','')
        if not re.fullmatch(r'[0-9]{1,4}',value):raise realtime.failure('realtime_chunk_invalid')
        relay.commit(int(value))
    except Exception as error:
        relay.close(error);raise
    return {'status':'PROCESSING'},202,{'Cache-Control':'private, no-store'}


@audio_bp.route('/live/sessions/<ident>/turns/<key>',methods=['GET','POST'])
def live_translator_turn(ident,key):
    from . import live_translator as live, live_translator_store as sessions
    video_budget.key_valid(key)
    if not re.fullmatch(r'live-[a-f0-9]{32}',key):abort(400)
    if request.method=='POST':
        # Cached clients may still request sentence prefixes. Every new utterance
        # now produces one complete output; existing segment GETs remain readable.
        live.enqueue(session['user_id'],ident,key,request.files.get('recording'),whole_output=True)
        return {'status':'PROCESSING'},202,{'Cache-Control':'private, no-store'}
    state=sessions.result(session['user_id'],ident,key)
    from . import live_translator_segments as segments
    progress=segments.progress(session['user_id'],ident,key,state)
    if progress:
        for part in progress['segments']:
            part['audio_url']=url_for('kilas_audio.live_translator_segment',ident=ident,key=key,index=part['index'])
        if state['status']=='COMPLETED':progress['audio_url']=url_for('kilas_audio.live_translator_result',ident=ident,key=key)
        return {'status':state['status'],'stream_output':'sentences-v1',**progress},200,{'Cache-Control':'private, no-store'}
    if state['status']=='COMPLETED':
        from . import live_translator_output as temporary
        owned_job=db.query_one("SELECT id FROM kilas_audio_jobs WHERE id=? AND user_id=? AND (status='COMPLETED' OR (status='PROCESSING' AND substr(provider_id,1,11)='clauses-v1:')) AND content_origin='live_session'",(state['audio_job_id'],session['user_id']))
        if not owned_job:abort(404)
        job=temporary.get(session['user_id'],ident,key)
        if not job or job['job']!=owned_job['id'] or not job['raw']:
            return {'status':'FAILED','code':'session_output_expired','recoverable':True,'error':'Hasil sementara sesi sudah tidak tersedia. Ucapan ini tidak dibuat ulang otomatis.'},200,{'Cache-Control':'private, no-store'}
        state={'status':'COMPLETED','translation_key':key,'audio_url':url_for('kilas_audio.live_translator_result',ident=ident,key=key),
               'translated_text':job['text'],'source_text':job.get('source_text',''),
               'source_language':job['source_language'],'target_language':job['target_language'],'audio_sha256':job.get('audio_sha256')}
    elif state['status']=='PROCESSING':
        from . import live_translator_output as temporary
        job=temporary.get(session['user_id'],ident,key)
        if job and job.get('translation_ready'):
            state={**state,'translation_ready':True,'translation_key':key,
                   'translated_text':job['text'],'source_text':job['source_text'],
                   'source_language':job['source_language'],'target_language':job['target_language'],'audio_sha256':job.get('audio_sha256')}
            if job.get('progress'):
                state['audio_progress_url']=url_for('kilas_audio.live_translator_progress',ident=ident,key=key)
    elif state['status']=='FAILED':
        code=state.get('error_code')
        messages={'detection_unavailable':'Data deteksi bahasa belum tersedia dari layanan suara. Pilih bahasa sumber lalu bicara kembali.',
                  'detection_uncertain':'Bahasa ucapan belum terdeteksi dengan yakin. Pilih bahasa sumber lalu bicara kembali.',
                  'detected_language_unsupported':'Bahasa yang terdeteksi belum didukung oleh suara Translator. Pilih bahasa sumber yang didukung.',
                  'detected_language_is_target':'Bahasa ucapan sama dengan bahasa tujuan. Pilih bahasa tujuan lain.',
                  'translation_ambiguous':'Makna atau arah ucapan belum jelas dalam pasangan bahasa ini. Ucapkan kembali dengan lebih lengkap.',
                  'no_speech':'Ucapan belum terbaca dalam pasangan bahasa ini. Bicara kembali.',
                  'translation_language_mismatch':'Bahasa hasil terjemahan belum sesuai dengan pasangan yang dipilih. Ucapan ini tidak diulang otomatis.',
                  'provider_credit_exhausted':'Kapasitas layanan suara tidak cukup. Sesi dijeda tanpa pembelian tambahan.',
                  'provider_credit_check_failed':'Kapasitas layanan suara belum dapat diperiksa. Sesi dijeda sebelum permintaan berikutnya.',
                  'provider_billing_unverified':'Status layanan suara belum terverifikasi. Sesi dijeda.',
                  'budget_limit':'Batas biaya input suara periode ini tercapai. Lanjutkan tidak menambah kapasitas.',
                  'rate_limit':'Batas percobaan input suara per jam tercapai. Coba lagi setelah batas pulih.',
                  'attempt_limit':'Batas percobaan input suara hari ini tercapai. Coba lagi besok.',
                  'already_processing':'Ucapan sebelumnya masih diproses. Tunggu sebelum melanjutkan.',
                  'service_busy':'Layanan input suara sedang sibuk. Coba lagi sebentar.',
                  'live_audio_limit':'Batas audio Live Translator tercapai. Sesi dijeda tanpa pembelian tambahan.',
                  'zero_balance':'Kuota audio Live Translator belum tersedia untuk akun ini.',
                  'insufficient_balance':'Kuota audio tidak cukup untuk ucapan berikutnya.',
                  'stream_unavailable':'Audio belum tersedia. Sesi dijeda; ucapan ini tidak diulang otomatis.'}
        if code in ('realtime_transport','realtime_input_idle','realtime_commit_timeout','realtime_worker_unavailable','realtime_queue_full'):messages[code]='Input suara terputus. Silakan bicara kembali.'
        state={'status':'FAILED','code':code,'recoverable':code in ('detection_unavailable','detection_uncertain','detected_language_unsupported','detected_language_is_target','translation_ambiguous','no_speech','realtime_transport','realtime_input_idle','realtime_commit_timeout','realtime_worker_unavailable','realtime_queue_full','translation_failed','translation_language_mismatch','transcription_failed','speech_failed','processing_failed','processing_interrupted'),
               'error':messages.get(code,'Ucapan belum berhasil diproses. Ucapan ini tidak diulang otomatis.')}
    else:state={'status':state['status']}
    if state['status'] in ('FAILED','CANCELLED'):
        from . import live_translator_realtime
        if not live_translator_realtime.settled(session['user_id'],key):state['input_settled']=False
    return state,200,{'Cache-Control':'private, no-store'}


@audio_bp.get('/live/sessions/<ident>/turns/<key>/audio/segments/<int:index>')
def live_translator_segment(ident,key,index):
    if not re.fullmatch(r'live-[a-f0-9]{32}',key) or not 0<=index<8:abort(404)
    from . import live_translator_segments as segments
    raw=segments.clip(session['user_id'],ident,key,index)
    return raw,200,{'Content-Type':'audio/mpeg','Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}


@audio_bp.get('/live/sessions/<ident>/turns/<key>/audio')
def live_translator_result(ident,key):
    from . import live_translator_store as sessions
    from . import live_translator_output as temporary
    row=db.query_one("SELECT s.language_a,s.language_b,s.voice_alias,j.source_language AS actual_source,j.target_language AS actual_target,CASE WHEN t.status='COMPLETED' AND (j.status='COMPLETED' OR (j.status='PROCESSING' AND substr(j.provider_id,1,11)='clauses-v1:')) AND j.content_origin='live_session' THEN j.id ELSE NULL END AS id FROM kilas_live_translator_sessions s LEFT JOIN kilas_live_translator_turns t ON t.session_id=s.id AND t.operation_key=? LEFT JOIN kilas_audio_jobs j ON j.id=t.audio_job_id AND j.user_id=s.user_id WHERE s.id=? AND s.user_id=? AND s.status='ACTIVE' AND (s.expires_at='' OR s.expires_at>?)",(key,ident,session['user_id'],usage._now().isoformat()))
    if not row:abort(404)
    sessions.require_pair(row['language_a'],row['language_b'],voice=row['voice_alias'])
    if row['id'] is None:abort(404)
    # Playback checks the original selected mode and the completed job's actual
    # direction. It never consults a provider or creates/replaces audio.
    try:sessions.require_pair(row['actual_source'],row['actual_target'],voice=row['voice_alias'])
    except store.AudioError:abort(404)
    if row['language_a']=='auto':
        if row['actual_target']!=row['language_b']:abort(404)
    elif {row['actual_source'],row['actual_target']}!={row['language_a'],row['language_b']}:abort(404)
    output=temporary.get(session['user_id'],ident,key)
    if not output or output['job']!=row['id'] or not output['raw']:return {'code':'session_output_expired'},410,{'Cache-Control':'private, no-store'}
    response=send_file(io.BytesIO(output['raw']),mimetype='audio/mpeg')
    response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
    return response


@audio_bp.get('/live/sessions/<ident>/turns/<key>/audio/progress')
def live_translator_progress(ident,key):
    # GET-only relay of one already reserved/dispatched whole-script TTS call.
    # No long-lived web-worker stream and no provider action on playback.
    from . import live_translator_store as sessions,live_translator_output as temporary
    if not re.fullmatch(r'live-[a-f0-9]{32}',key):abort(404)
    value=request.args.get('offset','')
    if not re.fullmatch(r'0|[1-9][0-9]{0,7}',value):abort(400)
    row=db.query_one("SELECT s.language_a,s.language_b,s.voice_alias,j.id,j.source_language,j.target_language FROM kilas_live_translator_sessions s JOIN kilas_live_translator_turns t ON t.session_id=s.id AND t.operation_key=? JOIN kilas_audio_jobs j ON j.id=t.audio_job_id AND j.user_id=s.user_id WHERE s.id=? AND s.user_id=? AND s.status='ACTIVE' AND (s.expires_at='' OR s.expires_at>?) AND t.status IN ('PROCESSING','COMPLETED') AND j.status IN ('PROCESSING','COMPLETED') AND j.content_origin='live_session'",(key,ident,session['user_id'],usage._now().isoformat()))
    if not row:abort(404)
    sessions.require_pair(row['language_a'],row['language_b'],voice=row['voice_alias'])
    try:sessions.require_pair(row['source_language'],row['target_language'],voice=row['voice_alias'])
    except store.AudioError:abort(404)
    if {row['source_language'],row['target_language']}!={row['language_a'],row['language_b']}:abort(404)
    entry=temporary.get(session['user_id'],ident,key)
    if not entry or entry['job']!=row['id']:abort(404)
    part=temporary.progress_read(session['user_id'],ident,key,int(value))
    if part is None:return {'code':'session_output_expired'},410,{'Cache-Control':'private, no-store'}
    raw,size,complete,digest=part
    return Response(raw,status=200 if raw else 204,headers={'Content-Type':'audio/mpeg','Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','X-Audio-Offset':value,'X-Audio-Size':str(size),'X-Audio-Complete':'1' if complete else '0','X-Audio-SHA256':digest or ''})
