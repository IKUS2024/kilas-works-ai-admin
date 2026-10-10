"""Private Video product on the existing authenticated, CSRF-protected AI blueprint."""
import io
import json
import re
import secrets
import time
import logging
import requests
from werkzeug.exceptions import HTTPException
from flask import abort, redirect, render_template, request, session, send_file, url_for
from .routes import ai_bp
from . import attachments, usage, video_store as store, video_director as director, video_adapters as adapters, video_brief, video_entitlement


def owner():return session['user_id']


def owned(project):
    row=store.get(owner(),project)
    if not row:abort(404)
    return row


def output(row):
    spec=json.loads(row['spec_json']) if row['version'] else None
    controls={k:v for k,v in json.loads(row['options_json']).items() if not k.startswith('_')}
    active_refs=json.loads(row['options_json']).get('_brief',{}).get('use_references',True)
    return dict(project=row,spec=spec,controls=controls,package=adapters.package(spec,controls.get('tool','Universal')) if spec else None,
                references=store.references(owner(),row['id']) if active_refs else [])


@ai_bp.get('/video',endpoint='video_home')
@ai_bp.get('/video/projects/<int:project>',endpoint='video_project')
def home(project=None):
    from .content_projects import draft
    content_draft = draft(owner())
    area=request.args.get('area','plan')
    if area in ('learn','workflow','tools'):return redirect(url_for('kilas_ai.video_home'),code=302)
    if area!='plan':abort(404)
    try:page=max(1,min(10000,int(request.args.get('page',1))))
    except ValueError:abort(400)
    row=owned(project) if project else None
    rows=store.history(owner(),page)
    controls=json.loads(row['options_json']) if row else {}
    retry=controls.pop('_retry',None) if row and row['status']=='ERROR' else None
    if retry:controls.update(retry['controls'])
    return render_template('kilas_video/home.html',content_draft=content_draft,retry=retry,video_entitlement=video_entitlement.state(owner()),area=area,history=rows[:20],more=len(rows)>20,page=page,
        plan_types=('Product','UGC','Ads','Cinematic','Social Content','Education','Fashion','Food','Travel','Other'),
        target_tools=director.TOOLS,operation_key=secrets.token_hex(16),
        project=row,controls=controls,**({k:v for k,v in output(row).items() if k not in ('project','controls')} if row else {'spec':None,'package':None,'references':[]}))


@ai_bp.post('/video/plan',endpoint='video_generate')
def generate():
    requested_project=request.form.get('project_id','')
    if requested_project:
        if not requested_project.isdigit():abort(400)
        owned(int(requested_project))  # Ownership still wins over a quota response.
    gate=video_entitlement.state(owner())
    if not gate['allowed']:
        return {'error':gate['message'],'code':'video_quota_'+gate['reason'],'purchase_url':url_for('kilas_ai.usage_page')},402
    deadline=time.monotonic()+75  # Leave headroom below the observed 90s production worker limit.
    text=str(request.form.get('idea','')).strip()
    key=str(request.form.get('operation_key',''))
    generation=request.form.get('generation','all')
    if generation not in ('all','storyboard','video'):abort(400)
    if not 3<=len(text)<=2400 or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',key):return {'error':'Tulis ide atau revisi hingga 2.400 karakter, lalu coba lagi.'},400
    row=None
    try:
        try:controls=director.options(request.form)
        except ValueError as error:
            message=('Maksimal 8 klip per rencana. Kurangi total durasi atau pilih klip lebih panjang.'
                     if str(error)=='too_many_video_parts' else 'Pilihan rencana tidak valid. Pilih kembali lalu coba lagi.')
            return {'error':message},400
        raw_project=request.form.get('project_id','')
        if raw_project:
            if not raw_project.isdigit():abort(400)
            row=owned(int(raw_project))
            controls={**json.loads(row['options_json']),**controls}
            if generation=='video':
                tool=controls.get('tool','Universal')
                controls={**json.loads(row['options_json']),'tool':tool}
                text='Buat ulang prompt video berdasarkan storyboard aktif. Pertahankan semua scene, subjek, identitas, dan durasi.'
            controls=director.resolve(text,controls)
            if request.form.get('version')!=str(row['version']):return {'error':'Rencana berubah di tab lain. Buka ulang rencana sebelum merevisi.'},409
            if request.files.getlist('references'):return {'error':'Referensi awal dipertahankan saat revisi. Buat rencana baru untuk referensi lain.'},400
        else:
            uploads=[f for f in request.files.getlist('references') if f.filename]
            if any(f.filename.rsplit('.',1)[-1].lower() not in ('jpg','jpeg','png','webp') for f in uploads):raise attachments.AttachmentError('Gunakan referensi JPG, PNG, atau WebP.')
            images=attachments.prepare_many(uploads,usage.attachment_plan(owner()))
            controls=director.resolve(text,controls)
            project=store.create(owner(),text,controls,key,images)
            row=owned(project)
            if row['version']:return response(row)
            text=row['idea'];controls=json.loads(row['options_json'])
        previous=json.loads(row['spec_json']) if row['version'] else None
        if generation!='all' and not previous:return failure('Buat rencana terlebih dahulu.',400,row)
        if generation=='video' and any(not s.get('image_prompt') for s in previous['scenes']):
            return failure('Perbarui storyboard terlebih dahulu untuk membuat prompt gambar.',400,row)
        try:brief=video_brief.build(text,controls,previous,row['version'],row['id'])
        except ValueError as error:
            message=('Maksimal 8 klip per rencana. Kurangi total durasi atau pilih klip lebih panjang.'
                     if str(error)=='too_many_video_parts' else 'Pilihan rencana tidak valid. Pilih kembali lalu coba lagi.')
            return failure(message,400,row)
        if not store.claim(owner(),row['id'],row['version']):return {'error':'Sedang menyusun Video Plan...','processing':True,'url':url_for('kilas_ai.video_project',project=row['id'])},409
        try:
            if brief.get('plan_mode')=='multi':
                controls.update(total_duration=brief['total_duration'],duration='Custom storyboard')
            refs=store.references(owner(),row['id']) if brief.get('use_references',True) else []
            spec=director.generate(owner(),key,text,controls,previous,refs,brief=brief,deadline=deadline,generation=generation)
            controls['_brief']=video_brief.commit(brief,spec)
            controls.pop('_retry',None)
            store.save(owner(),row['id'],row['version'],spec,controls,text)
        except Exception:
            store.fail(owner(),row['id'],row['version'],text,controls,generation);raise
        return response(owned(row['id']))
    except HTTPException:raise
    except (usage.UsageLimit,attachments.AttachmentError) as error:return failure(str(error),400,row)
    except Exception as error:
        # No provider payload, secret, system instructions or user image enters logs/UI.
        category='timeout' if isinstance(error,requests.Timeout) else 'provider' if isinstance(error,requests.RequestException) else 'invalid_response' if isinstance(error,(ValueError,KeyError,TypeError)) else 'persistence_or_render'
        logging.getLogger(__name__).warning('Video request failed category=%s project=%s',category,row['id'] if row else None)
        data,status=failure('Video Plan belum berhasil dibuat.',503,row)
        data.update(detail='Ide dan pengaturanmu tetap tersimpan. Coba lagi.',code='video_'+category)
        return data,status


def failure(message,status,row):
    data={'error':message}
    if row:data.update(id=row['id'],version=row['version'],url=url_for('kilas_ai.video_project',project=row['id']))
    return data,status


def response(row):
    data=output(row)
    return {'id':row['id'],'version':row['version'],'title':row['title'],'controls':data['controls'],
            'url':url_for('kilas_ai.video_project',project=row['id']),
            'html':render_template('kilas_video/_result.html',**data),
            'manage_html':render_template('kilas_video/_manage.html',**data)}


@ai_bp.post('/video/projects/<int:project>/<action>',endpoint='video_action')
def action(project,action):
    owned(project)
    if action=='rename':
        title=' '.join(request.form.get('title','').split())
        if not 1<=len(title)<=60:abort(400)
        store.rename(owner(),project,title)
    elif action=='delete':
        if request.form.get('confirm')!='delete':abort(400)
        store.delete(owner(),project)
        return redirect(url_for('kilas_ai.video_home'),code=303)
    elif action=='duplicate':
        project=store.duplicate(owner(),project,secrets.token_hex(16))
    else:abort(404)
    return redirect(url_for('kilas_ai.video_project',project=project),code=303)


@ai_bp.get('/video/projects/<int:project>/references/<int:reference>',endpoint='video_reference')
def reference(project,reference):
    owned(project)
    item=next((r for r in store.references(owner(),project) if r['id']==reference),None)
    if not item:abort(404)
    response=send_file(io.BytesIO(bytes(item['content'])),mimetype=item['mime_type'],download_name=item['filename'])
    response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
    return response
