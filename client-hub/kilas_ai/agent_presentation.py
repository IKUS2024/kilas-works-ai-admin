"""Owner-facing task labels; storage remains UTC and existing enums unchanged."""
import json
import db
from zoneinfo import ZoneInfo
from . import usage

STATUS = {'PLANNING': 'Menyiapkan rencana', 'RUNNING': 'Sedang bekerja',
          'WAITING': 'Menunggu', 'NEEDS_APPROVAL': 'Perlu persetujuan', 'PAUSED': 'Dijeda',
          'COMPLETED': 'Selesai', 'FAILED': 'Perlu perhatian', 'STOPPED': 'Dihentikan'}
MONTHS = ('Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli', 'Agustus',
          'September', 'Oktober', 'November', 'Desember')


def time_label(value, zone='Asia/Jakarta'):
    if not value:
        return None
    local = usage._as_utc(value).astimezone(ZoneInfo(zone))
    suffix = {'Asia/Jakarta': 'WIB', 'Asia/Makassar': 'WITA', 'Asia/Jayapura': 'WIT', 'Asia/Bangkok': 'ICT'}.get(zone, local.tzname())
    return f'{local.day} {MONTHS[local.month-1]} {local.year}, {local:%H.%M} {suffix}'


def duration(seconds):
    seconds = int(seconds)
    for divisor, label in ((86400, 'hari'), (3600, 'jam'), (60, 'menit')):
        if seconds % divisor == 0:
            return f'Setiap {seconds // divisor} {label}'
    return 'Kurang dari 1 menit' if seconds < 60 else f'Setiap {round(seconds / 60)} menit'


def job_card(job):
    from .agent_results import task_title, step_label
    job = dict(job)
    schedule = json.loads(job.get('schedule_json') or '{}')
    zone = schedule.get('timezone', 'Asia/Jakarta')
    job.update(status_label=STATUS[job['status']], wake_label=time_label(job['next_wake_at'], zone),
               updated_label=time_label(job['updated_at'], zone), frequency_label=duration(job['interval_seconds']))
    job['capability_label'] = {'provider_not_configured': 'Data market real-time belum tersedia.',
                               'sandbox_not_configured': 'Pengujian kode belum tersedia.',
                               'image_not_configured': 'Pembuatan gambar belum tersedia.',
                               'adapter_not_configured': 'Kemampuan eksternal belum tersedia.'}.get(job.get('last_error'), '')
    checkpoint=json.loads(job.get('checkpoint_json') or '{}')
    reminder=checkpoint.get('reminder')
    job['title'] = reminder['subject'] if reminder else task_title(job['instruction'])
    job['waiting_question']=checkpoint.get('waiting_question','') if job.get('last_error')=='waiting_input' else ''
    if job['waiting_question']:job['status_label']='Menunggu jawabanmu'
    if (job['status']=='PLANNING' or (reminder and job['status']=='RUNNING')) and job['next_wake_at'] and usage._as_utc(job['next_wake_at'])>usage._now():job['status_label']='Terjadwal'
    if schedule.get('schedule',{}).get('kind') not in (None,'once'):
        from .automation_schedule import describe
        job['frequency_label']=describe(schedule['schedule'],zone)
    latest=db.query_one('SELECT kind FROM kilas_agent_events WHERE job_id=? ORDER BY id DESC LIMIT 1',(job['id'],))
    from .work_runtime import LABELS
    job['phase_label']=LABELS.get(latest['kind'],'Sedang mengerjakan') if latest else 'Pekerjaan tersimpan'
    job['live']=job['status'] in ('PLANNING','RUNNING','WAITING') and not job['waiting_question']
    job['due']=job['live'] and job['next_wake_at'] and usage._as_utc(job['next_wake_at'])<=usage._now()

    job['current_step'] = step_label({'worker':job.get('current_worker'),'action':job.get('current_action'),'instruction':job.get('current_step') or ''}) if job.get('current_step') else ''
    job['result_hint'] = 'Hasil pekerjaan siap dibuka.' if job['status']=='COMPLETED' else 'Pekerjaan dihentikan.' if job['status']=='STOPPED' else ''
    from . import work_artifacts
    job['artifacts']=work_artifacts.listing(job['user_id'],job_id=job['id'])
    if job['artifacts']:
        job['title']=json.loads(job['artifacts'][0]['content']).get('title') or job['title']
        if job['status']=='COMPLETED':job['result_hint']='Hasil selesai dan siap digunakan.'
    job['failure_label'] = job['capability_label'] or ('Batas eksekusi harian tercapai.' if job.get('last_error')=='daily_execution_limit' else 'Pekerjaan belum selesai. Buka detail untuk meninjau hasil dan instruksi.')
    return job
