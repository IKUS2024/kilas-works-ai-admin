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
    explicit = re.search(r'\b(?:pekerjaan|task|tugas)\s*#?(\d+)\b', text, re.I)
    controls = agent_intents.CONTROL.fullmatch(text.strip())
    feedback = agent_intents.FEEDBACK.search(text)
    if controls or explicit or feedback:
        jobs = store.list_jobs(user_id, active_only=True)
        focused = session.get('autonomous_job_id')
        focused_job = store.get(user_id, focused) if focused else None
        if focused_job and focused_job['status'] in store.TERMINAL:
            focused_job = None
        if not jobs and not explicit and not focused_job:
            return False
        job = store.get(user_id, int(explicit[1])) if explicit else focused_job or (jobs[0] if len(jobs) == 1 else None)
        if not job:
            agent_store.append(user_id, 'assistant', 'Ada beberapa pekerjaan. Pilih salah satu di Active Tasks agar instruksi diterapkan ke pekerjaan yang tepat.')
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
        job_id = store.create(user_id, text, mode=spec['mode'], constraints=[text],
                              wake_at=spec['wake_at'], interval=spec['interval'],
                              conversation_id=conversation_id, schedule=spec['schedule'])
        if market_request(text) and market_worker.provider is None:
            message = 'Pekerjaan pemantauan tersimpan. Data market real-time belum tersedia; Kilas belum memantau harga atau menghasilkan sinyal.'
        elif spec['wake_at']:
            message = 'Pekerjaan tersimpan dan dijadwalkan mulai ' + agent_presentation.time_label(spec['wake_at'], spec['schedule'].get('timezone', 'Asia/Jakarta')) + '. Kamu boleh keluar dari aplikasi.'
        else:
            message = 'Kilas menyiapkan pekerjaan di background. Kamu boleh keluar dari aplikasi; kemajuan dan hasil tetap tersimpan di Active Tasks.'
        agent_store.append(user_id, 'assistant', message)
    except (ValueError, TypeError):
        agent_store.append(user_id, 'assistant', 'Pekerjaan belum dibuat. Periksa jadwal dan batas pekerjaan aktif, lalu coba lagi.')
    return True


@ai_bp.get('/agent/jobs/<int:job_id>', endpoint='autonomous_detail')
def detail(job_id):
    job = owned(job_id)
    session['autonomous_job_id'] = job_id
    events = db.query_all('SELECT * FROM kilas_agent_events WHERE job_id=? ORDER BY id DESC LIMIT 100', (job_id,))
    from .agent_presentation import time_label as label
    calendar = json.loads(job.get('schedule_json') or '{}')
    events = [{**dict(e), 'time_label': label(e['created_at'], calendar.get('timezone', 'Asia/Jakarta')),
               'summary': 'Data market real-time belum tersedia.' if e['summary']=='Market data provider is not configured.' else e['summary']} for e in events]
    artifacts = db.query_all("SELECT id,name FROM kilas_agent_artifacts WHERE job_id=? AND name!='_workspace.json' ORDER BY id DESC LIMIT 50", (job_id,))
    approvals = [dict(r) for r in db.query_all("SELECT * FROM kilas_agent_approvals WHERE job_id=? AND status='PENDING' AND expires_at>?", (job_id, store.stamp()))]
    for item in approvals:
        item['payload'] = json.loads(item['payload_json'])
    job_steps = store.steps(job_id)
    for step in job_steps:
        output = json.loads(step['output_json'])
        step['result_text'] = output.get('text') or output.get('test_output') or output.get('diff') or ''
        step['citations'] = output.get('citations') or []
        step['reason_label'] = {'provider_not_configured': 'Data market real-time belum tersedia.', 'adapter_not_configured': 'Kemampuan eksternal belum tersedia.', 'sandbox_not_configured': 'Sandbox pengujian belum tersedia.', 'repository_not_configured': 'Repository belum dikonfigurasi.', 'unsupported_format': 'Format file belum didukung.'}.get(output.get('reason'), '')
        step['signal'] = output.get('signal')
    return render_template('kilas_ai/autonomous_detail.html', job=job, steps=job_steps,
                           events=list(reversed(events)), artifacts=artifacts, approvals=approvals,
                           constraints=json.loads(job['constraints_json']))


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
    row = db.query_one('SELECT name,content FROM kilas_agent_artifacts WHERE id=? AND job_id=?', (artifact_id, job_id))
    if not row:
        abort(404)
    return send_file(io.BytesIO(row['content'].encode()), mimetype='text/plain', as_attachment=True, download_name=row['name'])
