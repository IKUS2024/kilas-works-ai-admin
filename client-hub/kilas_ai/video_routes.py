"""Private Video product on the existing authenticated, CSRF-protected AI blueprint."""
import io
import json
import re
import secrets
from werkzeug.exceptions import HTTPException
from flask import abort, redirect, render_template, request, session, send_file, url_for
from .routes import ai_bp
from . import attachments, usage, video_store as store, video_director as director, video_adapters as adapters, video_content


def owner():return session['user_id']


def owned(project):
    row=store.get(owner(),project)
    if not row:abort(404)
    return row


def output(row):
    spec=json.loads(row['spec_json']) if row['version'] else None
    controls=json.loads(row['options_json'])
    return dict(project=row,spec=spec,controls=controls,package=adapters.package(spec,controls.get('tool','Universal')) if spec else None,
                references=store.references(owner(),row['id']))


@ai_bp.get('/video',endpoint='video_home')
@ai_bp.get('/video/projects/<int:project>',endpoint='video_project')
def home(project=None):
    area=request.args.get('area','plan')
    if area not in ('plan','learn','workflow','tools'):abort(404)
    try:page=max(1,min(10000,int(request.args.get('page',1))))
    except ValueError:abort(400)
    row=owned(project) if project else None
    rows=store.history(owner(),page)
    return render_template('kilas_video/home.html',area=area,history=rows[:20],more=len(rows)>20,page=page,
        tools=video_content.TOOLS,lessons=video_content.LESSONS,workflows=video_content.WORKFLOWS,
        plan_types=('Product','UGC','Ads','Cinematic','Social Content','Education','Fashion','Food','Travel','Other'),
        target_tools=director.TOOLS,operation_key=secrets.token_hex(16),
        project=row,controls=json.loads(row['options_json']) if row else {},**({k:v for k,v in output(row).items() if k not in ('project','controls')} if row else {'spec':None,'package':None,'references':[]}))


@ai_bp.post('/video/plan',endpoint='video_generate')
def generate():
    text=str(request.form.get('idea','')).strip()
    key=str(request.form.get('operation_key',''))
    if not 3<=len(text)<=2400 or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}',key):return {'error':'Tulis ide atau revisi hingga 2.400 karakter, lalu coba lagi.'},400
    row=None
    try:
        try:controls=director.options(request.form)
        except ValueError:return {'error':'Pilihan rencana tidak valid. Pilih kembali lalu coba lagi.'},400
        raw_project=request.form.get('project_id','')
        if raw_project:
            if not raw_project.isdigit():abort(400)
            row=owned(int(raw_project))
            controls={**json.loads(row['options_json']),**controls}
            controls=director.resolve(text,controls)
            if request.form.get('version')!=str(row['version']):return {'error':'Rencana berubah di tab lain. Buka ulang rencana sebelum merevisi.'},409
            if request.files.getlist('references'):return {'error':'Referensi awal dipertahankan saat revisi. Buat rencana baru untuk referensi lain.'},400
        else:
            uploads=[f for f in request.files.getlist('references') if f.filename]
            if any(f.filename.rsplit('.',1)[-1].lower() not in ('jpg','jpeg','png','webp') for f in uploads):raise attachments.AttachmentError('Gunakan referensi JPG, PNG, atau WebP.')
            images=attachments.prepare_many(uploads,usage.effective_plan(owner())['plan'])
            controls=director.resolve(text,controls)
            project=store.create(owner(),text,controls,key,images)
            row=owned(project)
            if row['version']:return response(row)
            text=row['idea'];controls=json.loads(row['options_json'])
        if not store.claim(owner(),row['id'],row['version']):return {'error':'Rencana sedang disusun. Tunggu, lalu buka ulang rencana.','url':url_for('kilas_ai.video_project',project=row['id'])},409
        try:
            spec=director.generate(owner(),key,text,controls,json.loads(row['spec_json']) if row['version'] else None,store.references(owner(),row['id']))
            store.save(owner(),row['id'],row['version'],spec,controls,text)
        except Exception:
            store.fail(owner(),row['id'],row['version']);raise
        return response(owned(row['id']))
    except HTTPException:raise
    except (usage.UsageLimit,attachments.AttachmentError) as error:return failure(str(error),400,row)
    except Exception:
        # No provider payload, secret, system instructions or user image enters logs/UI.
        return failure('Rencana belum berhasil disusun. Ide dan rencana sebelumnya tetap tersimpan di riwayat. Coba lagi atau buka ulang rencana.',503,row)


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
