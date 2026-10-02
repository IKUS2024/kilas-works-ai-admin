"""Owner-facing task labels; storage remains UTC and existing enums unchanged."""
import json
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
    suffix = {'Asia/Jakarta': 'WIB', 'Asia/Makassar': 'WITA', 'Asia/Jayapura': 'WIT'}.get(zone, local.tzname())
    return f'{local.day} {MONTHS[local.month-1]} {local.year}, {local:%H.%M} {suffix}'


def duration(seconds):
    seconds = int(seconds)
    for divisor, label in ((86400, 'hari'), (3600, 'jam'), (60, 'menit')):
        if seconds % divisor == 0:
            return f'Setiap {seconds // divisor} {label}'
    return 'Kurang dari 1 menit' if seconds < 60 else f'Setiap {round(seconds / 60)} menit'


def job_card(job):
    job = dict(job)
    schedule = json.loads(job.get('schedule_json') or '{}')
    zone = schedule.get('timezone', 'Asia/Jakarta')
    job.update(status_label=STATUS[job['status']], wake_label=time_label(job['next_wake_at'], zone),
               updated_label=time_label(job['updated_at'], zone), frequency_label=duration(job['interval_seconds']))
    job['capability_label'] = {'provider_not_configured': 'Data market real-time belum tersedia.',
                               'sandbox_not_configured': 'Pengujian kode belum tersedia.',
                               'adapter_not_configured': 'Kemampuan eksternal belum tersedia.'}.get(job.get('last_error'), '')
    return job
