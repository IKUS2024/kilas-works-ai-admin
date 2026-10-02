"""Existing Agent surface, account-owned persistent task controls and artifacts."""
import io
import json
import re
from datetime import datetime, timezone
from flask import abort, redirect, render_template, request, session, url_for, send_file
import db
from .routes import ai_bp, automation_enabled
from . import autonomous_runner as runner, autonomous_store as store, agent_store
from . import usage, automation_schedule, automation_store


def time_label(value, user_id):
    from .agent_presentation import time_label as label
    return label(value)


@ai_bp.before_request
def require_autonomous_flag():
    if request.endpoint and request.endpoint.startswith('kilas_ai.autonomous_') and not (automation_enabled() and runner.enabled()):
        abort(404)


def owned(job_id):
    job = store.get(session['user_id'], job_id)
    if not job:
        abort(404)
    return job


def chat(user_id, text):
    """Infer autonomous lifecycle without capturing normal Q&A or connector actions."""
    from . import agent_intents, agent_presentation
    from .agent_workers import market_request, market_worker
    if not runner.enabled():
        return False
    conversation_id = agent_store.current_conversation(user_id)
    from . import work_documents,work_artifacts
    previous=work_artifacts.latest_document(user_id,conversation_id)
    document_format=work_documents.intent(text,bool(previous))
    from . import routing
    image_inputs=[item for item in getattr(request,'work_attachments',[]) if item['mime_type'].startswith('image/')]
    image_previous=next((item for item in work_artifacts.listing(user_id,conversation_id=conversation_id) if item['media_type'].startswith('image/')),None)
    editing_image=routing.tool_for(text)== 'IMAGE_EDIT' or (image_inputs and routing.may_edit_image(text))
    if editing_image:document_format=None
    if editing_image and not image_inputs and not image_previous:
        agent_store.append(user_id,'assistant','Tambahkan gambar yang ingin diubah.')
        return True
    explicit = re.search(r'\b(?:pekerjaan|task|tugas)\s*#?(\d+)\b', text, re.I)
    controls = agent_intents.CONTROL.fullmatch(text.strip())
    feedback = agent_intents.FEEDBACK.search(text)
    if controls or explicit or (feedback and not document_format):
        jobs = store.list_jobs(user_id, active_only=True)
        focused = session.get('autonomous_job_id')
        focused_job = store.get(user_id, focused) if focused else None
        if focused_job and focused_job['status'] in store.TERMINAL:
            focused_job = None
        if not jobs and not explicit and not focused_job:
            return False
        job = store.get(user_id, int(explicit[1])) if explicit else focused_job or (jobs[0] if len(jobs) == 1 else None)
        if not job:
            agent_store.append(user_id, 'assistant', 'Ada beberapa pekerjaan. Pilih salah satu di Pekerjaan aktif agar instruksi diterapkan ke pekerjaan yang tepat.')
            return True
        verb = text.lower().split()[0]
        action = None if feedback else 'pause' if verb in ('pause', 'jeda') else 'resume' if verb in ('resume', 'lanjut', 'lanjutkan') else 'stop' if verb in ('stop', 'berhenti', 'batalkan') else None
        try:
            store.control(user_id, job['id'], action) if action else store.feedback(user_id, job['id'], text)
            agent_store.append(user_id, 'assistant', {'pause': 'Pekerjaan dijeda.', 'resume': 'Pekerjaan dilanjutkan.', 'stop': 'Pekerjaan dihentikan.'}.get(action, 'Instruksi baru tersimpan. Kilas akan menyesuaikan langkah berikutnya.'))
        except ValueError:
            agent_store.append(user_id, 'assistant', 'Pekerjaan tidak dapat diubah pada status ini.')
        return True
    pending = session.get('agent_work_clarification')
    if pending and pending.get('conversation_id') == conversation_id and re.fullmatch(r'(?i)(?:jam |pukul |di bawah |di atas |target |\d).{0,100}', text):
        text = pending['text'] + ' ' + text
    spec = agent_intents.infer(text)
    if (document_format or work_documents.image_request(text) or editing_image) and not spec:
        spec={'mode':'ONE_SHOT','wake_at':None,'interval':3600,'schedule':{},'clarify':None}
    selected_mode = request.form.get('autonomous_mode', '')
    if selected_mode:
        try:
            interval = int(request.form.get('interval_seconds') or 3600)
        except ValueError:
            agent_store.append(user_id, 'assistant', 'Pilih frekuensi pemeriksaan yang tersedia.')
            return True
        spec = {'mode': selected_mode, 'wake_at': None, 'interval': interval, 'schedule': {}, 'clarify': None}
        if selected_mode == 'SCHEDULED':
            try:
                wake = datetime.fromisoformat(request.form.get('wake_at', '')).replace(tzinfo=automation_schedule.ZoneInfo('Asia/Jakarta')).astimezone(timezone.utc)
                if wake <= store.now():
                    raise ValueError('past_schedule')
                spec['wake_at'] = wake
            except ValueError:
                spec['clarify'] = 'Pilih tanggal dan jam mulai yang akan datang dalam WIB.'
    if not spec:
        return False
    if spec['clarify']:
        session['agent_work_clarification'] = {'conversation_id': conversation_id, 'text': text[:1000]}
        agent_store.append(user_id, 'assistant', spec['clarify'])
        return True
    session.pop('agent_work_clarification', None)
    try:
        checkpoint={}
        if document_format and previous and work_documents.REVISE.search(text):checkpoint['document_source_id']=previous['id']
        if editing_image and not image_inputs:checkpoint['image_source_id']=image_previous['id']
        sources=getattr(request,'work_source_materials',None)
        if sources:checkpoint['source_materials']=sources
        job_id=store.create(user_id,agent_intents.research_instruction(text),mode=spec['mode'],constraints=[text],
            wake_at=spec['wake_at'],interval=spec['interval'],conversation_id=conversation_id,schedule=spec['schedule'],
            checkpoint=checkpoint,image_input=image_inputs[0] if editing_image and image_inputs else None)
        if market_request(text) and market_worker.provider is None:
            message = 'Pekerjaan pemantauan tersimpan. Data market real-time belum tersedia; Kilas belum memantau harga atau menghasilkan sinyal.'
        elif spec['wake_at']:
            message = 'Pekerjaan tersimpan dan dijadwalkan mulai ' + agent_presentation.time_label(spec['wake_at'], spec['schedule'].get('timezone', 'Asia/Jakarta')) + '. Kamu boleh keluar dari aplikasi.'
        elif agent_intents.broad_trends(text):
            region = ' di Indonesia' if 'Cakupan awal: Indonesia.' in agent_intents.research_instruction(text) else ''
            message = 'Siap, aku mulai cek topik yang sedang ramai' + region + ' dari sumber publik terbaru.'
        else:
            message = 'Kilas menyiapkan pekerjaan di background. Kamu boleh keluar dari aplikasi; kemajuan dan hasil tetap tersimpan di Pekerjaan aktif.'
        agent_store.append(user_id, 'assistant', message)
    except (ValueError, TypeError):
        agent_store.append(user_id, 'assistant', 'Pekerjaan belum dibuat. Periksa jadwal dan batas pekerjaan aktif, lalu coba lagi.')
    return True


@ai_bp.get('/agent/jobs/<int:job_id>', endpoint='autonomous_detail')
def detail(job_id):
    from .agent_presentation import job_card
    job = job_card(owned(job_id))
    # Opening a job/result acknowledges its notifications so a terminal result is
    # retained in History without being pinned again in the conversation.
    db.execute('UPDATE kilas_agent_events SET unread=0 WHERE job_id=?', (job_id,))
    from . import agent_results
    session['autonomous_job_id'] = job_id
    events = db.query_all('SELECT * FROM kilas_agent_events WHERE job_id=? ORDER BY id DESC LIMIT 100', (job_id,))
    from .agent_presentation import time_label as label
    calendar = json.loads(job.get('schedule_json') or '{}')
    from .work_runtime import LABELS
    events = [{**dict(e), 'time_label': label(e['created_at'], calendar.get('timezone', 'Asia/Jakarta')),
               'summary': e['summary'] if e['kind']=='REMINDER' else LABELS.get(e['kind'],'Pekerjaan diperbarui')} for e in events]
    artifacts = db.query_all("SELECT a.id,a.name,a.media_type,a.content,f.byte_size FROM kilas_agent_artifacts a LEFT JOIN kilas_agent_artifact_files f ON f.artifact_id=a.id WHERE a.job_id=? AND a.name!='_workspace.json' ORDER BY a.id DESC LIMIT 50", (job_id,))
    artifacts=[a for a in artifacts if not a['byte_size'] or not json.loads(a['content']).get('input')]
    approvals = [dict(r) for r in db.query_all("SELECT * FROM kilas_agent_approvals WHERE job_id=? AND status='PENDING' AND expires_at>?", (job_id, store.stamp()))]
    for item in approvals:
        item['payload'] = json.loads(item['payload_json'])
    job_steps = store.steps(job_id)
    result = agent_results.primary_result(job_steps)
    from . import work_artifacts
    files=work_artifacts.listing(session['user_id'],job_id=job_id)
    if files:job['title']=json.loads(files[0]['content']).get('title') or job['title']
    for step in job_steps:
        output = json.loads(step['output_json'])
        step['result_text'] = output.get('text') or output.get('test_output') or output.get('diff') or ''
        step['citations'] = agent_results.compact_sources(output.get('citations') or [])
        step['result_text'] = agent_results.readable_text(step['result_text'],step['citations'])
        step['display_label'] = agent_results.step_label(step)
        step['reason_label'] = {'provider_not_configured': 'Data market real-time belum tersedia.', 'adapter_not_configured': 'Kemampuan eksternal belum tersedia.', 'sandbox_not_configured': 'Sandbox pengujian belum tersedia.', 'repository_not_configured': 'Repository belum dikonfigurasi.', 'unsupported_format': 'Format file belum didukung.'}.get(output.get('reason'), '')
        step['signal'] = output.get('signal')
    return render_template('kilas_ai/autonomous_detail.html', job=job, waiting_question=job.get('waiting_question',''), steps=job_steps, result=result,
                           events=list(reversed(events)), artifacts=artifacts, approvals=approvals,
                           constraints=json.loads(job['constraints_json']),files=files)


@ai_bp.post('/agent/jobs/<int:job_id>/<action>', endpoint='autonomous_control')
def control(job_id, action):
    owned(job_id)
    try:
        if action == 'feedback':
            store.feedback(session['user_id'], job_id, request.form.get('message'))
        elif action == 'read':
            db.execute('UPDATE kilas_agent_events SET unread=0 WHERE job_id=?', (job_id,))
        else:
            store.control(session['user_id'], job_id, action)
    except ValueError:
        abort(409)
    conversation_id = request.form.get('return_conversation', type=int)
    if conversation_id and agent_store.conversation(session['user_id'], conversation_id):
        return redirect(url_for('kilas_ai.agent_home', conversation=conversation_id), code=303)
    return redirect(url_for('kilas_ai.autonomous_detail', job_id=job_id), code=303)


@ai_bp.post('/agent/jobs/<int:job_id>/approval/<int:approval_id>', endpoint='autonomous_approve')
def approve(job_id, approval_id):
    owned(job_id)
    try:
        store.approve(session['user_id'], job_id, approval_id, request.form.get('digest'))
    except ValueError:
        abort(409)
    return redirect(url_for('kilas_ai.autonomous_detail', job_id=job_id), code=303)


@ai_bp.get('/agent/jobs/<int:job_id>/artifacts/<int:artifact_id>', endpoint='autonomous_artifact')
def artifact(job_id, artifact_id):
    owned(job_id)
    db.execute('UPDATE kilas_agent_events SET unread=0 WHERE job_id=?', (job_id,))
    row = db.query_one('SELECT a.name,a.media_type,a.content,f.content AS binary_content FROM kilas_agent_artifacts a LEFT JOIN kilas_agent_artifact_files f ON f.artifact_id=a.id WHERE a.id=? AND a.job_id=?', (artifact_id, job_id))
    if not row:
        abort(404)
    raw=bytes(row['binary_content']) if row['binary_content'] is not None else row['content'].encode()
    response=send_file(io.BytesIO(raw),mimetype=row['media_type'],as_attachment=request.args.get('download')=='1' or row['binary_content'] is None,download_name=row['name'],max_age=0)
    response.headers['Cache-Control']='private, no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Content-Security-Policy']="default-src 'none'; sandbox"
    return response
