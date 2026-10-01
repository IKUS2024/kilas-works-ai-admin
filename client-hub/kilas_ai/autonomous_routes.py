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
    return usage._as_utc(value).astimezone(automation_schedule.ZoneInfo(automation_store.setting(user_id))).strftime('%d/%m/%Y %H.%M %Z') if value else None


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
    """Conservative routing: preserve existing scheduled Automation and Gmail flows."""
    if not runner.enabled():
        return False
    selected_mode = request.form.get('autonomous_mode', '')
    if selected_mode:
        try:
            wake = None
            if selected_mode == 'SCHEDULED':
                wake = datetime.fromisoformat(request.form.get('wake_at', '')).replace(tzinfo=timezone.utc)
                if wake <= store.now():
                    raise ValueError('invalid_schedule')
            job_id = store.create(user_id, text, mode=selected_mode, constraints=[text], wake_at=wake,
                                  interval=int(request.form.get('interval_seconds') or 3600))
            agent_store.append(user_id, 'assistant', f'Pekerjaan #{job_id} tersimpan. Rencana, hasil, dan kontrol tersedia di Tugas aktif.')
        except (ValueError, TypeError):
            agent_store.append(user_id, 'assistant', 'Pekerjaan belum dibuat. Periksa mode, jadwal UTC, dan interval minimal 5 menit.')
        return True
    explicit = re.search(r'\b(?:pekerjaan|task|tugas)\s*#?(\d+)\b', text, re.I)
    controls = re.fullmatch(r'(?i)(?:pause|jeda|resume|lanjutkan|stop|berhenti|batalkan)(?:\s+(?:task|tugas|pekerjaan)(?:\s+ini|\s*#?\d+)?)?[.!]?', text.strip())
    feedback_words = re.search(r'(?i)^(?:jangan |gunakan pendekatan lain|tambahkan .*langkah|stop setelah|ubah target)', text)
    if controls or explicit or feedback_words:
        jobs = [j for j in store.list_jobs(user_id) if j['status'] not in store.TERMINAL]
        focused = session.get('autonomous_job_id')
        job = store.get(user_id, int(explicit[1])) if explicit else store.get(user_id, focused) if focused else jobs[0] if len(jobs) == 1 else None
        if not job:
            agent_store.append(user_id, 'assistant', 'Pilih pekerjaan di Tugas aktif agar instruksi diterapkan ke pekerjaan yang tepat.')
            return True
        verb = text.lower().split()[0]
        action = 'pause' if verb in ('pause', 'jeda') else 'resume' if verb in ('resume', 'lanjutkan') else 'stop' if verb in ('stop', 'berhenti', 'batalkan') else None
        try:
            if action:
                store.control(user_id, job['id'], action)
            else:
                store.feedback(user_id, job['id'], text)
            agent_store.append(user_id, 'assistant', 'Instruksi pekerjaan tersimpan. Lihat status dan hasilnya di Tugas aktif.')
        except ValueError:
            agent_store.append(user_id, 'assistant', 'Pekerjaan tidak dapat diubah pada status ini.')
        return True
    # No ambiguous capture of the existing REMINDER/SEARCH schedules or connector requests.
    if not re.search(r'(?i)\b(?:kerjain|kerjakan|riset.*sampai selesai|pantau.*(?:terus|sampai))\b', text):
        return False
    mode = 'CONDITION_WATCH' if re.search(r'(?i)\bpantau\b', text) else 'CONTINUOUS' if re.search(r'(?i)\bterus\b', text) else 'ONE_SHOT'
    try:
        job_id = store.create(user_id, text, mode=mode, constraints=[text])
        agent_store.append(user_id, 'assistant', f'Pekerjaan #{job_id} tersimpan di server. Kilas menyiapkan langkah yang dibatasi; kemampuan yang belum tersedia akan ditampilkan dengan jelas. Lihat Tugas aktif untuk menjeda, menghentikan, atau menambahkan instruksi.')
    except ValueError:
        agent_store.append(user_id, 'assistant', 'Pekerjaan belum dapat dibuat. Periksa batas tugas aktif.')
    return True


@ai_bp.get('/agent/jobs/<int:job_id>', endpoint='autonomous_detail')
def detail(job_id):
    job = owned(job_id)
    session['autonomous_job_id'] = job_id
    events = db.query_all('SELECT * FROM kilas_agent_events WHERE job_id=? ORDER BY id DESC LIMIT 100', (job_id,))
    events = [{**dict(e), 'time_label': time_label(e['created_at'], session['user_id'])} for e in events]
    artifacts = db.query_all('SELECT id,name FROM kilas_agent_artifacts WHERE job_id=? ORDER BY id DESC LIMIT 50', (job_id,))
    approvals = [dict(r) for r in db.query_all("SELECT * FROM kilas_agent_approvals WHERE job_id=? AND status='PENDING' AND expires_at>?", (job_id, store.stamp()))]
    for item in approvals:
        item['payload'] = json.loads(item['payload_json'])
    job_steps = store.steps(job_id)
    for step in job_steps:
        output = json.loads(step['output_json'])
        step['result_text'] = output.get('text') or output.get('test_output') or output.get('diff') or ''
        step['citations'] = output.get('citations') or []
        step['reason_label'] = {'provider_not_configured': 'Market data provider is not configured.', 'adapter_not_configured': 'Kemampuan eksternal belum tersedia.', 'sandbox_not_configured': 'Sandbox pengujian belum tersedia.', 'repository_not_configured': 'Repository belum dikonfigurasi.', 'unsupported_format': 'Format file belum didukung.'}.get(output.get('reason'), '')
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
