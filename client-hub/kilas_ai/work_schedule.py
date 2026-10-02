"""Natural Work time parsing using authoritative UTC and existing calendar semantics."""
import re
from datetime import timedelta
from . import automation_schedule as calendar, autonomous_store as store

REMINDER = re.compile(r'(?i)\b(?:ingatkan|ingetin|remind|reminder|pengingat)\b')
CAPABILITY = re.compile(r'(?i)^(?:kamu|lu|lo|anda|kilas|can you|could you)\s+(?:bisa|can|able)|^(?:bisa(?:kah)?|apakah|apa itu|jelaskan|what|how|can you)\b')


def parse(text, zone='Asia/Jakarta', now=None):
    now = now or store.now()
    zone = calendar.timezone_from_instruction(text, calendar.validate_timezone(zone))
    relative = re.search(r'(?i)\b(\d+)\s*(menit|minutes?|jam|hours?)\s+lagi\b|\bin\s+(\d+)\s+(minutes?|hours?)\b', text)
    if relative:
        n = int(relative[1] or relative[3]); unit = relative[2] or relative[4]
        seconds = n * (3600 if unit.lower().startswith(('jam','hour')) else 60)
        if not 60 <= seconds <= 365*86400: raise calendar.ScheduleError('Pilih waktu pengingat antara satu menit dan satu tahun.')
        at = now + timedelta(seconds=seconds)
        return {'timezone':zone,'schedule':{'kind':'once','at':store.stamp(at)},'next_run_at':at}
    value = text
    if REMINDER.search(value):value=calendar.FORBIDDEN.sub('',value)
    local=now.astimezone(calendar.ZoneInfo(zone))
    if re.search(r'(?i)\b(?:nanti|later)\b',value) and not re.search(r'(?i)\b(?:besok|tomorrow|tanggal)\b',value):value+=' hari ini'
    short_date=re.search(r'(?i)\b(?:tanggal|tgl)\s+(\d{1,2})(?!\d|\s+[a-z]+\s+\d{4})\b',value)
    named_date=re.search(r'(?i)\b\d{1,2}\s+(?:'+'|'.join(calendar.MONTHS)+r')\b',value)
    if short_date and not named_date and not re.search(r'\b\d+/\d+/\d+\b',value) and not re.search(r'(?i)(?:setiap|tiap|every)\s+(?:tanggal|tgl)',value):
        day=int(short_date[1]);month=local.month;year=local.year
        if day<local.day:month+=1
        if month==13:month=1;year+=1
        value=re.sub(r'(?i)\b(?:tanggal|tgl)\s+\d+\b',f'tanggal {day}/{month}/{year}',value,count=1)
    if re.search(r'(?i)\b(?:bulan depan|next month)\b',value):
        month=local.month%12+1;year=local.year+(local.month==12);day=min(local.day,calendar.calendar.monthrange(year,month)[1])
        value=re.sub(r'(?i)\b(?:bulan depan|next month)\b',f'tanggal {day}/{month}/{year}',value)
    spec = calendar.parse(value, zone, now)
    return {'timezone':spec['timezone'],'schedule':spec['schedule'],'next_run_at':spec['next_run_at']}


def subject(text):
    text = REMINDER.sub('',text)
    text = re.sub(r'(?i)^(?:ubah|ganti|ulang)\s*','',text)
    text = re.sub(r'(?i)\b(?:aku|saya|me|tolong|untuk|to)\b','',text)
    text = re.sub(r'(?i)\b(?:besok|tomorrow|nanti|today|hari ini|minggu depan|next week|bulan depan|next month)\b','',text)
    text = re.sub(r'(?i)\b\d+\s+(?:menit|jam)\s+lagi\b|\bin\s+\d+\s+(?:minutes?|hours?)\b','',text)
    text = re.sub(r'(?i)\b(?:setiap|tiap|every)\s+(?:hari\s+)?(?:hari|pagi|day|tanggal\s+\d+|'+ '|'.join(calendar.WEEKDAYS)+r')\b','',text)
    text = calendar.TIME.sub('',text)
    text = re.sub(r'(?i)\b(?:tanggal|tgl)?\s*\d{1,2}\s+(?:'+'|'.join(calendar.MONTHS)+r')(?:\s+\d{4})?\b','',text)
    text = re.sub(r'(?i)\b(?:tanggal|tgl)\s+\d+(?:/\d+/\d+)?\b|\b(?:'+ '|'.join(calendar.WEEKDAYS)+r')\s+depan\b','',text)
    text = re.sub(r'(?i)\b(?:pagi|siang|sore|malam|morning|evening|night)\b','',text)
    text = re.sub(r'(?i)\b(?:WIB|WITA|WIT|ICT)\b|[A-Za-z_]+/[A-Za-z_+-]+','',text)
    return ' '.join(text.split()).strip(' .,!?')[:240]


def clarification(text):
    return len(text)<500 and bool(re.match(r'(?i)^(?:mau dibuatkan apa|apa yang (?:ingin|perlu)|what (?:would|do) you|boleh (?:jelaskan|sebutkan)|bisa (?:jelaskan|sebutkan)|tolong (?:sebutkan|berikan))\b',text.strip()))
