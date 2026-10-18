"""Actual Chat composer → existing bounded PROJECT worker, scoped by thread.

No generated program runs here. Durable one-shot jobs reuse the existing native
provider, quota, remote execution and validated artifact publication boundaries.
"""
import io
import json
import re
import secrets
from flask import abort, request, session, Response, send_file, url_for
import db
from . import autonomous_store as jobs, usage, store, work_artifacts


def requested(text):
    if re.search(r"(?i)^(?:apa|bagaimana|jelaskan|what|how|explain|can you|could you|kamu bisa|bisakah|puedes|cómo)\b",text.strip()):return False
    if re.search(r"(?i)\b(?:jangan|tanpa|do not|don't|without|no)\s+(?:buat\w*|bikin\w*|create|generate|make|run|execute|jalankan|eksekusi|files?|artifacts?)\b|不要(?:创建|生成|运行)",text):return False
    action=re.search(r'(?i)\b(?:buat\w*|bikin\w*|siapkan|jadikan|create|build|generate|write|make|crear|crea|genera|escribe)\b|(?:创建|生成|制作)',text)
    output=re.search(r'(?i)\b(?:zip|html|csv|website|web app|source code|kode sumber|project|proyek)\b|网站|项目|压缩包|ZIP',text)
    from .workspace_execution_worker import requested as run_requested
    return bool(action and output) or run_requested(text)


def needs_run(text):
    from .workspace_execution_worker import requested as run_requested
    return run_requested(text) or bool(re.search(r'(?i)\b(?:laporan|report|sales|penjualan|spreadsheet|csv|informe|ventas)\b|报告|销售',text))


def owned(owner,thread_id,job_id):
    if not store.thread(owner,thread_id):abort(404)
    job=jobs.get(owner,job_id)
    if not job or json.loads(job['checkpoint_json']).get('origin_thread_id')!=thread_id:abort(404)
    return job


def enqueue(owner,thread_id,text,key,mode,model,prepared):
    from . import autonomous_runner, workspace_execution, workspace_large_outputs
    from .routes import automation_enabled
    if not automation_enabled() or not autonomous_runner.enabled():raise ValueError('Pembuatan file belum tersedia. Tidak ada permintaan dikirim.')
    if needs_run(text) and not workspace_execution.capability(owner)['available']:raise ValueError('Eksekusi belum tersedia untuk akun ini. Tidak ada permintaan dikirim.')
    if workspace_large_outputs.requested(text) and not workspace_large_outputs.capability(owner)['available']:raise ValueError('Ekspor dokumen besar belum lolos verifikasi sandbox. File kecil tetap tersedia.')
    from . import chat_models
    if not model or not chat_models.check(model)['available']:raise ValueError('Model pilihan tidak tersedia. Permintaan tidak dialihkan ke model lain.')
    # Snapshot the conversation before this turn, never another thread/tab.
    context=store.context(owner,thread_id,selected_model=model)[-8:]
    checkpoint={'origin_thread_id':thread_id,'author_model':model,'request_full':text,
                'thread_context':json.dumps(context,ensure_ascii=False)[-12000:],
                'generate_outputs':needs_run(text),'thread_operation_key':key}
    with jobs.transaction() as conn:
        suffix=' FOR UPDATE' if db.BACKEND=='postgres' else ''
        if not usage._query(conn,'SELECT id FROM kilas_ai_threads WHERE id=? AND user_id=?'+suffix,(thread_id,owner),one=True):abort(404)
        prior=usage._query(conn,'SELECT metadata_json FROM kilas_ai_messages WHERE thread_id=? AND operation_key=?',(thread_id,key),one=True)
        if prior:
            ident=json.loads(prior[0]).get('workspace_job_id')
            if not ident:raise ValueError('Permintaan ini sudah diterima.')
            return ident
        count=usage._query(conn,"SELECT COUNT(*) FROM kilas_agent_jobs WHERE user_id=? AND status NOT IN ('COMPLETED','FAILED','STOPPED')",(owner,),one=True)[0]
        if count>=20:raise ValueError('Masih ada permintaan yang diproses. Tunggu jawabannya lalu coba lagi.')
        message=usage._query(conn,"INSERT INTO kilas_ai_messages(thread_id,role,content,mode,operation_key) VALUES (?,'user',?,?,?) RETURNING id",(thread_id,text,mode,key),one=True)[0]
        checkpoint['origin_thread_message_id']=message
        ident=usage._query(conn,"INSERT INTO kilas_agent_jobs(user_id,title,instruction,mode,status,constraints_json,next_wake_at,checkpoint_json,max_steps,max_attempts) VALUES (?,?,?,'ONE_SHOT','RUNNING','[]',?,?,1,1) RETURNING id",(owner,' '.join(text.split())[:90],text[:1200],jobs.stamp(),jobs.encode(checkpoint)),one=True)[0]
        payload=jobs.encode({'request':text})
        usage._query(conn,"INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,input_json,idempotency_key,status) VALUES (?,1,'PROJECT','create','Membuat struktur dan kode…',?,?,'PENDING')",(ident,payload,secrets.token_hex(24)))
        meta=json.dumps({'workspace_job_id':ident,'status':'processing'})
        usage._query(conn,'UPDATE kilas_ai_messages SET metadata_json=? WHERE id=?',(meta,message))
        usage._query(conn,"INSERT INTO kilas_ai_messages(thread_id,role,content,mode,provider,model,operation_key,metadata_json) VALUES (?,'assistant','Menyiapkan jawaban…',?,?,?,?,?)",(thread_id,mode,chat_models.spec(model)['provider'],model,key+':assistant',meta))
        for item in prepared:
            usage._query(conn,'INSERT INTO kilas_ai_attachments(user_id,thread_id,message_id,filename,mime_type,byte_size,content,extracted_text) VALUES (?,?,?,?,?,?,?,?)',(owner,thread_id,message,item['filename'],item['mime_type'],item['byte_size'],item['content'],item['extracted_text']))
        usage._query(conn,"UPDATE kilas_ai_threads SET title=CASE WHEN title='Chat baru' THEN ? ELSE title END,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",(' '.join(text.split())[:68],thread_id,owner))
        jobs.event(conn,ident,'CREATED','Pekerjaan tersimpan.',unread=False)
    return ident


def files(owner,thread_id,job_id):
    owned(owner,thread_id,job_id)
    return [{'id':row['id'],'filename':row['name'],'mime_type':row['media_type'],'byte_size':row['byte_size'],
             'url':url_for('kilas_ai.thread_project_download',thread_id=thread_id,job_id=job_id,artifact_id=row['id'])}
            for row in work_artifacts.listing(owner,job_id=job_id)]


def response(thread_id,job_id):
    from .routes import _sse
    from ui_i18n import translate
    base=url_for('kilas_ai.thread_project_status',thread_id=thread_id,job_id=job_id)
    return Response(_sse('delta',{'text':translate('Menyiapkan jawaban…')})+_sse('job',{'id':job_id,'url':base})+_sse('done',{}),mimetype='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})


def persist_result(conn,job,result,state):
    checkpoint=json.loads(job['checkpoint_json'])
    thread_id=checkpoint.get('origin_thread_id')
    if not thread_id or state not in ('COMPLETED','FAILED','WAITING','NEEDS_APPROVAL'):return
    meta={'workspace_job_id':job['id'],'status':'complete' if state=='COMPLETED' else 'failed',
          'model_metadata':result.output.get('model_provenance',{})}
    usage._query(conn,"UPDATE kilas_ai_messages SET content=?,metadata_json=? WHERE thread_id=? AND role='assistant' AND operation_key=? AND EXISTS (SELECT 1 FROM kilas_ai_threads t WHERE t.id=? AND t.user_id=?)",(result.summary,json.dumps(meta),thread_id,checkpoint['thread_operation_key']+':assistant',thread_id,job['user_id']))


def register(bp):
    @bp.get('/threads/<int:thread_id>/jobs/<int:job_id>',endpoint='thread_project_status')
    def status(thread_id,job_id):
        owner=session['user_id'];job=owned(owner,thread_id,job_id)
        after=max(0,request.args.get('after',0,type=int))
        from .work_runtime import LABELS
        events=db.query_all('SELECT id,kind FROM kilas_agent_events WHERE job_id=? AND id>? ORDER BY id LIMIT 100',(job_id,after))
        answer=store.operation(owner,thread_id,json.loads(job['checkpoint_json'])['thread_operation_key']+':assistant')
        return {'job_id':job_id,'state':job['status'],'text':answer['content'] if answer else '',
                'events':[{'id':e['id'],'label':LABELS.get(e['kind'],'Menyiapkan jawaban…')} for e in events],
                'files':files(owner,thread_id,job_id)},200,{'Cache-Control':'private, no-store'}

    @bp.post('/threads/<int:thread_id>/jobs/<int:job_id>/start',endpoint='thread_project_start')
    def start(thread_id,job_id):
        job=owned(session['user_id'],thread_id,job_id)
        from .routes import automation_enabled
        if not automation_enabled():abort(404)
        if job['status'] not in jobs.TERMINAL and json.loads(job['checkpoint_json']).get('generate_outputs'):
            from . import workspace_execution
            if not workspace_execution.capability(session['user_id'])['available']:
                from ui_i18n import translate
                return {'error':translate('Eksekusi belum tersedia untuk akun ini. Tidak ada permintaan dikirim.')},429
        from .work_routes import work_start
        return work_start(job_id)

    @bp.post('/threads/<int:thread_id>/jobs/<int:job_id>/stop',endpoint='thread_project_stop')
    def stop(thread_id,job_id):
        job=owned(session['user_id'],thread_id,job_id)
        if job['status'] not in jobs.TERMINAL:jobs.control(session['user_id'],job_id,'stop')
        return {},200

    @bp.get('/threads/<int:thread_id>/jobs/<int:job_id>/files/<int:artifact_id>',endpoint='thread_project_download')
    def download(thread_id,job_id,artifact_id):
        owned(session['user_id'],thread_id,job_id)
        row=db.query_one('SELECT a.name,a.media_type,f.content FROM kilas_agent_artifacts a JOIN kilas_agent_artifact_files f ON f.artifact_id=a.id WHERE a.id=? AND a.job_id=?',(artifact_id,job_id))
        if not row:abort(404)
        response=send_file(io.BytesIO(bytes(row['content'])),mimetype=row['media_type'],as_attachment=True,download_name=row['name'],max_age=0)
        response.headers.update({'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox; base-uri 'none'; form-action 'none'"})
        return response
