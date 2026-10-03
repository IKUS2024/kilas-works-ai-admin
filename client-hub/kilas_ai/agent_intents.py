"""Conservative natural-language lifecycle inference. No model-invented schedules."""
import re
from . import automation_schedule as schedule

CONTROL = re.compile(r'(?i)^(pause|jeda(?: dulu)?|resume|lanjut(?:kan)?|stop|berhenti|batalkan)(?:\s+(?:task|tugas|pekerjaan)(?:\s+ini|\s*#?\d+)?)?[.!]?$')
FEEDBACK = re.compile(r"(?i)^(?:jangan |do not |don't |ubah caranya|coba pendekatan lain|try another approach|gunakan pendekatan lain|tambahkan .*langkah|stop (?:setelah|after)|ubah target)")
WORK = re.compile(r'(?i)\b(?:kerjain|kerjakan|kerja(?:kan)? terus|terus kerjain|riset|research|pantau|monitor|watch|perbaiki|fix|buatkan|siapkan|upload|publish|work on|keep working|do this)\b')
QUESTION = re.compile(r'(?i)^(?:apa(?: itu)?|what|why|how|mengapa|kenapa|jelaskan|explain|bagaimana|berapa)\b')
RESEARCH = re.compile(r'(?i)\b(?:riset|research)\b|^(?:(?:bantu (?:aku|saya)|tolong|coba)\s+)?(?:cari|carikan)\s+.*(?:kompetitor|pesaing|tren|trend|viral|ramai|terbaru|sumber)\b')


def broad_trends(text):
    return bool(RESEARCH.search(text) and re.search(r'(?i)\b(?:viral|tren|trend|ramai)\b', text))


def research_instruction(text):
    if not broad_trends(text):
        return text
    scope = '' if re.search(r'(?i)\b(?:di|in|global|dunia|worldwide|internasional)\b', text) else ' Cakupan awal: Indonesia.'
    guidance = scope + ' Gunakan sumber publik web/berita terbaru dan sinyal publik yang tersedia; jangan mengklaim ranking live resmi platform.'
    return text + '\n' + guidance.strip() if len(text)+len(guidance)+1 <= 1200 else text


def infer(text, now=None):
    if QUESTION.search(text):
        return None
    # "Pada foto yang saya upload, apa ...?" refers to an existing attachment,
    # not authorization to upload/publish or create a background job.
    if re.search(r'(?i)^(?:pada|di|dalam|dari|tentang)\b.*\b(?:gambar|foto|image|photo|lampiran|dokumen|file)\b.*\b(?:apa|what|which|berapa|bagaimana|how)\b',text):
        return None
    # Existing reminders and connectors retain their own engine/approval path.
    if re.search(r'(?i)\b(?:ingatkan|ingetin|remind|gmail|email|calendar|kalender|drive|contacts|kontak|whatsapp|finance)\b', text):
        return None
    scheduled = re.search(r'(?i)\b(?:setiap|tiap|every|besok|tomorrow|lusa|tanggal)\b', text)
    if not WORK.search(text) and not RESEARCH.search(text) and not scheduled and not re.search(r'(?i)sampai (?:selesai|semua test pass)', text):
        return None
    until_stopped = bool(re.search(r'(?i)(?:sampai|until).{0,25}(?:saya|aku|i).{0,15}(?:stop|berhenti)', text))
    until_complete = bool(re.search(r'(?i)(?:sampai|until).{0,20}(?:selesai|complete|test pass|tests pass)', text))
    continuous = until_stopped or (not until_complete and bool(re.search(r'(?i)\b(?:terus|continuously)\b', text)))
    watch = bool(re.search(r'(?i)\b(?:pantau|monitor|watch)\b', text))
    mode = 'CONTINUOUS' if continuous else 'CONDITION_WATCH' if watch else 'ONE_SHOT'
    spec = {'mode': mode, 'interval': 3600, 'wake_at': None, 'schedule': {}, 'clarify': None}
    frequency = re.search(r'(?i)\b(?:setiap|tiap|every)\s+(\d+)\s+(menit|minutes?|jam|hours?|hari|days?)\b', text)
    if frequency:
        n, unit = int(frequency[1]), frequency[2].lower()
        interval = n * (60 if unit.startswith(('menit', 'minute')) else 3600 if unit.startswith(('jam', 'hour')) else 86400)
        if not 300 <= interval <= 2592000:
            spec['clarify'] = 'Pilih frekuensi antara 5 menit dan 30 hari.'
            return spec
        spec['interval'] = interval
        if not watch and not continuous:
            spec['mode'] = 'RECURRING'
    elif scheduled:
        # Do not use the schedule parser's inferred morning hour for "setiap pagi".
        if not (schedule.TIME.search(text) or schedule.HALF.search(text)):
            spec['clarify'] = 'Jam berapa pekerjaan ini perlu dijalankan? Gunakan waktu WIB, misalnya jam 8 pagi.'
            return spec
        try:
            parsed = schedule.parse(text, 'Asia/Jakarta', now=now)
            spec.update(mode='SCHEDULED' if parsed['schedule']['kind'] == 'once' else 'RECURRING',
                        wake_at=parsed['next_run_at'], schedule={'timezone': parsed['timezone'], 'schedule': parsed['schedule']})
        except schedule.ScheduleError:
            spec['clarify'] = 'Tanggal atau jamnya belum jelas. Sebutkan waktu yang kamu inginkan dalam WIB.'
    if watch and re.search(r'(?i)\b(?:target saya|targetku|di bawah target|di atas target)\b', text) and not re.search(r'(?i)(?:di bawah|di atas|target)\s+(?:Rp\s*)?\d', text):
        spec['clarify'] = 'Berapa target dan satuan yang kamu maksud? Misalnya di bawah 900 juta rupiah.'
    if watch and not re.search(r'(?i)\b(?:sampai|until|terus|continuously|perubahan|change|above|below|di bawah|di atas)\b', text):
        spec['clarify'] = 'Kondisi apa yang perlu dipantau, atau ingin memantau terus sampai kamu menghentikannya?'
    return spec
