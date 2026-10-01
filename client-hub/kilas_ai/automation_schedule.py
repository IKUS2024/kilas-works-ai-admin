"""Bounded, explicit natural-language schedules for Kilas AI Automation."""
import calendar
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = {"senin": 0, "monday": 0, "selasa": 1, "tuesday": 1,
            "rabu": 2, "wednesday": 2, "kamis": 3, "thursday": 3,
            "jumat": 4, "jum'at": 4, "friday": 4, "sabtu": 5, "saturday": 5,
            "minggu": 6, "sunday": 6}
MONTHS = {
    "januari": 1, "january": 1, "jan": 1,
    "februari": 2, "february": 2, "feb": 2,
    "maret": 3, "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mei": 5, "may": 5,
    "juni": 6, "june": 6, "jun": 6,
    "juli": 7, "july": 7, "jul": 7,
    "agustus": 8, "august": 8, "agu": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "october": 10, "okt": 10, "oct": 10,
    "november": 11, "nov": 11,
    "desember": 12, "december": 12, "des": 12, "dec": 12,
}
ZONE_LABELS = {"Asia/Jakarta": "Jakarta (WIB)", "Asia/Bangkok": "Bangkok (ICT)", "Asia/Makassar": "Makassar (WITA)",
               "Asia/Jayapura": "Jayapura (WIT)", "Asia/Singapore": "Singapore",
               "Asia/Tokyo": "Tokyo", "Europe/London": "London",
               "America/New_York": "New York", "America/Los_Angeles": "Los Angeles"}
ZONE_ALIASES = {"new york": "America/New_York", "los angeles": "America/Los_Angeles",
                "jakarta": "Asia/Jakarta", "makassar": "Asia/Makassar", "jayapura": "Asia/Jayapura",
                "singapore": "Asia/Singapore", "bangkok": "Asia/Bangkok", "tokyo": "Asia/Tokyo", "london": "Europe/London"}
ZONE_SHORT_ALIASES = {"wib": "Asia/Jakarta", "wita": "Asia/Makassar", "wit": "Asia/Jayapura",
                      "ict": "Asia/Bangkok"}
TIME = re.compile(r"\b(?:(?:jam|at)\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(pagi|siang|sore|malam|am|pm)\b|\b(?:jam|at)\s+(\d{1,2})(?:[:.](\d{2}))?\b|\b(\d{1,2}):(\d{2})\b", re.I)
HALF = re.compile(r"\bjam\s+setengah\s+(\d{1,2})\b", re.I)
FORBIDDEN = re.compile(r"\b(?:login|log in|masuk ke akun|klik|click|isi formulir|fill (?:a |the )?form|"
                       r"beli|purchase|checkout|bayar lewat|send email|kirim email|send whatsapp|"
                       r"kirim whatsapp|submit|unggah ke situs|upload to)\b", re.I)


class ScheduleError(ValueError):
    pass


def validate_timezone(value):
    value = str(value or "").strip()
    if len(value) > 80 or not re.fullmatch(r"[A-Za-z_]+(?:/[A-Za-z_+-]+)+|UTC", value):
        raise ScheduleError("Pilih zona waktu yang valid.")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ScheduleError("Pilih zona waktu yang valid.") from None
    return value


def _task_kind_and_condition(text):
    value = text.lower()
    kind = ("WATCH" if re.search(r"\b(?:pantau|monitor|kabari kalau|beri tahu kalau|alert when|watch)\b", value)
            else "REMINDER" if re.search(r"\b(?:ingatkan|ingetin|remind|pengingat)\b", value)
            else "SEARCH" if re.search(r"\b(?:cari|search|berita terbaru|lowongan terbaru|riset)\b", value)
            else "AI_TASK")
    if any(kind != "REMINDER" or match.group(0).lower() not in ("beli", "purchase")
           for match in FORBIDDEN.finditer(text)):
        raise ScheduleError("Automation belum bisa mengendalikan website atau mengirim pesan. Coba Reminder atau Search.")
    condition = {}
    if kind == "WATCH":
        match = re.search(r"\b(di bawah|kurang dari|below|under|di atas|lebih dari|above|over)\s+(?:rp\s*)?([\d.,]+)", value)
        if match:
            number = re.sub(r"[^\d]", "", match.group(2))
            if not number:
                raise ScheduleError("Sebutkan nilai kondisi yang jelas.")
            condition = {"operator": "lt" if match.group(1) in ("di bawah", "kurang dari", "below", "under") else "gt",
                         "threshold": int(number)}
        elif re.search(r"\b(?:berubah|perubahan|new|baru|change)\b", value):
            condition = {"operator": "change"}
        else:
            raise ScheduleError("Sebutkan kondisi Watch yang jelas, misalnya 'di bawah Rp1.800.000'.")
    return kind, condition


def parse_structured(instruction, timezone_name, mode, *, date=None, time=None, weekday=None, day=None, now=None):
    """Use the existing canonical schedule format for explicit create/edit controls."""
    text = " ".join(str(instruction or "").split())
    if not 8 <= len(text) <= 1200:
        raise ScheduleError("Tulis tugas Automation yang jelas (maksimal 1.200 karakter).")
    zone = validate_timezone(timezone_name)
    kind, condition = _task_kind_and_condition(text)
    mode = str(mode or "").lower()
    if mode not in ("once", "daily", "weekly", "monthly"):
        raise ScheduleError("Pilih pengulangan Automation yang valid.")
    clock = re.fullmatch(r"(\d{2}):(\d{2})", str(time or ""))
    if not clock:
        raise ScheduleError("Pilih jam dan menit yang valid.")
    hour, minute = map(int, clock.groups())
    if hour > 23 or minute > 59:
        raise ScheduleError("Jam tidak valid.")
    schedule = {"kind": mode, "hour": hour, "minute": minute}
    if mode == "once":
        try:
            chosen = datetime.strptime(str(date or ""), "%Y-%m-%d").date()
        except ValueError:
            raise ScheduleError("Pilih tanggal yang valid.") from None
        schedule.update(year=chosen.year, month=chosen.month, day=chosen.day)
    elif mode == "weekly":
        if str(weekday or "") not in tuple(str(index) for index in range(7)):
            raise ScheduleError("Pilih hari dalam seminggu.")
        schedule["weekday"] = int(weekday)
    elif mode == "monthly":
        if not str(day or "").isdigit() or not 1 <= int(day) <= 31:
            raise ScheduleError("Pilih tanggal bulanan dari 1 sampai 31.")
        schedule["day"] = int(day)
    next_run = next_occurrence(schedule, zone, now or datetime.now(timezone.utc))
    if not next_run:
        raise ScheduleError("Jadwal sudah lewat atau tidak valid.")
    return {"title": (text[0].upper() + text[1:])[:90], "instruction": text,
            "automation_type": kind, "timezone": zone, "schedule": schedule,
            "condition": condition, "next_run_at": next_run}


def timezone_from_instruction(text, default):
    value = (text or "").lower()
    for alias, zone in ZONE_SHORT_ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", value):
            return zone
    for phrase, zone in ZONE_ALIASES.items():
        if re.search(r"\b(?:waktu|time|timezone|zona waktu)\s+" + re.escape(phrase) + r"\b", value):
            return zone
    match = re.search(r"\b(?:waktu|timezone|zona waktu)\s+([A-Za-z_]+/[A-Za-z_+-]+)\b", text or "", re.I)
    return validate_timezone(match.group(1)) if match else validate_timezone(default)


def _clock(text):
    half = HALF.search(text)
    if half:
        hour = int(half.group(1)) - 1
        if hour < 0 or hour > 23:
            raise ScheduleError("Jam tidak valid.")
        if re.search(r"\b(?:sore|malam|pm)\b", text[half.end():half.end()+10], re.I) and hour < 12:
            hour += 12
        return hour, 30
    match = TIME.search(text)
    if not match:
        for period, default_hour in (("pagi", 8), ("morning", 8), ("siang", 12),
                                     ("afternoon", 13), ("sore", 17), ("evening", 18),
                                     ("malam", 20), ("night", 20), ("tonight", 20)):
            if re.search(r"\b" + period + r"\b", text, re.I):
                return default_hour, 0
        raise ScheduleError("Sebutkan jam yang jelas, misalnya 'jam 8 pagi'.")
    hour, minute = int(match.group(1) or match.group(4) or match.group(6)), int(match.group(2) or match.group(5) or match.group(7) or 0)
    part = (match.group(3) or "").lower()
    if not part:
        nearby = text[max(0, match.start() - 18):min(len(text), match.end() + 18)]
        context_period = re.search(r"\b(?:pagi|morning|siang|afternoon|sore|evening|malam|night|tonight)\b", nearby, re.I)
        part = context_period.group(0).lower() if context_period else ""
    if part in ("pm", "siang", "afternoon", "sore", "evening", "malam", "night", "tonight") and hour < 12:
        hour += 12
    if part in ("am", "pagi", "morning") and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        raise ScheduleError("Jam tidak valid.")
    return hour, minute


def parse(instruction, default_timezone="Asia/Jakarta", now=None):
    text = " ".join(str(instruction or "").split())
    if not 8 <= len(text) <= 1200:
        raise ScheduleError("Tulis instruksi Automation yang jelas (maksimal 1.200 karakter).")
    zone = timezone_from_instruction(text, default_timezone)
    local_now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(zone))
    value = text.lower()
    kind, condition = _task_kind_and_condition(text)
    interval = re.search(r"\b(?:setiap|tiap|every)\s+(\d{1,3})\s+(?:jam|hours?)\b", value)
    weekly = re.search(r"\b(?:setiap|tiap|every)\s+(?:hari\s+)?(" + "|".join(re.escape(day) for day in WEEKDAYS) + r")\b", value)
    next_weekday = re.search(r"\b(?:hari\s+)?(" + "|".join(re.escape(day) for day in WEEKDAYS) + r")\s+(?:ini|depan)\b|\bnext\s+(" + "|".join(re.escape(day) for day in WEEKDAYS) + r")\b", value)
    monthly = re.search(r"\b(?:setiap|tiap|every)\s+(?:tanggal|tgl|date)\s+(\d{1,2})\b", value)
    daily = re.search(r"\b(?:setiap|tiap|every)\s+(?:hari|pagi|siang|sore|malam|day|morning|evening|night)\b", value)
    weekdays = re.search(r"\b(?:senin\s+sampai\s+jumat|monday\s+(?:to|through)\s+friday|weekdays?)\b", value)
    if interval:
        hours = int(interval.group(1))
        if hours < 1 or hours > 720:
            raise ScheduleError("Interval harus antara 1 dan 720 jam.")
        schedule = {"kind": "interval", "hours": hours, "anchor": local_now.astimezone(timezone.utc).isoformat()}
    elif monthly:
        day = int(monthly.group(1))
        if day < 1 or day > 31:
            raise ScheduleError("Tanggal bulanan tidak valid.")
        hour, minute = _clock(value)
        schedule = {"kind": "monthly", "day": day, "hour": hour, "minute": minute}
    elif weekdays:
        hour, minute = _clock(value)
        schedule = {"kind": "weekdays", "hour": hour, "minute": minute}
    elif weekly:
        hour, minute = _clock(value)
        schedule = {"kind": "weekly", "weekday": WEEKDAYS[weekly.group(1)], "hour": hour, "minute": minute}
    elif daily:
        hour, minute = _clock(value)
        schedule = {"kind": "daily", "hour": hour, "minute": minute}
    elif next_weekday:
        hour, minute = _clock(value)
        weekday = WEEKDAYS[next_weekday.group(1) or next_weekday.group(2)]
        gap = (weekday - local_now.weekday()) % 7
        if "depan" in next_weekday.group(0) or "next" in next_weekday.group(0):
            gap = gap or 7
        day = local_now.date() + timedelta(days=gap)
        if gap == 0 and datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(zone)) <= local_now:
            day += timedelta(days=7)
        schedule = {"kind": "once", "year": day.year, "month": day.month, "day": day.day,
                    "hour": hour, "minute": minute}
    elif re.search(r"\b(?:minggu depan|next week)\b", value):
        hour, minute = _clock(value)
        day = local_now.date() + timedelta(days=7 - local_now.weekday())
        schedule = {"kind": "once", "year": day.year, "month": day.month, "day": day.day,
                    "hour": hour, "minute": minute}
    elif re.search(r"\b(?:malam ini|tonight)\b", value):
        hour, minute = _clock(value)
        day = local_now.date()
        schedule = {"kind": "once", "year": day.year, "month": day.month, "day": day.day,
                    "hour": hour, "minute": minute}
    elif re.search(r"\b(?:hari ini|today)\b", value):
        hour, minute = _clock(value)
        day = local_now.date()
        schedule = {"kind": "once", "year": day.year, "month": day.month, "day": day.day,
                    "hour": hour, "minute": minute}
    elif re.search(r"\b(?:lusa|day after tomorrow)\b", value):
        hour, minute = _clock(value)
        day = local_now.date() + timedelta(days=2)
        schedule = {"kind": "once", "year": day.year, "month": day.month, "day": day.day,
                    "hour": hour, "minute": minute}
    elif re.search(r"\b(?:besok|tomorrow)\b", value):
        hour, minute = _clock(value)
        day = local_now.date() + timedelta(days=1)
        schedule = {"kind": "once", "year": day.year, "month": day.month, "day": day.day,
                    "hour": hour, "minute": minute}
    else:
        hour, minute = _clock(value)
        date_match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", value)
        named_match = re.search(
            r"\b(?:tanggal|tgl|date)?\s*(\d{1,2})\s+(" +
            "|".join(sorted((re.escape(name) for name in MONTHS), key=len, reverse=True)) +
            r")(?:\s+(\d{4}))?\b", value)
        if date_match:
            year, month, day = int(date_match.group(3)), int(date_match.group(2)), int(date_match.group(1))
        elif named_match:
            day = int(named_match.group(1))
            month = MONTHS[named_match.group(2)]
            year = int(named_match.group(3)) if named_match.group(3) else local_now.year
            if not named_match.group(3):
                try:
                    candidate = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(zone))
                except ValueError:
                    candidate = None
                if candidate and candidate <= local_now:
                    year += 1
        else:
            raise ScheduleError(
                "Sebutkan tanggal dan jam yang jelas, misalnya 'tanggal 1 Oktober 2026 jam 5 pagi'.")
        schedule = {"kind": "once", "year": year, "month": month, "day": day,
                    "hour": hour, "minute": minute}
    if kind != "REMINDER" and schedule["kind"] == "interval" and schedule["hours"] < 1:
        raise ScheduleError("Automation AI dan Search minimal setiap 1 jam.")
    next_run = next_occurrence(schedule, zone, local_now.astimezone(timezone.utc))
    if not next_run:
        raise ScheduleError("Jadwal sudah lewat atau tidak valid.")
    title = re.sub(r"\b(?:setiap|tiap|every|besok|tomorrow)\b.*$", "", text, flags=re.I).strip(" .,-")
    title = title or text
    title = (title[0].upper() + title[1:])[:90]
    return {"title": title, "instruction": text, "automation_type": kind, "timezone": zone,
            "schedule": schedule, "condition": condition, "next_run_at": next_run}


def next_occurrence(schedule, timezone_name, after):
    zone = ZoneInfo(validate_timezone(timezone_name))
    after = after.astimezone(timezone.utc)
    kind = schedule["kind"]
    if kind == "interval":
        anchor = datetime.fromisoformat(schedule["anchor"]).astimezone(timezone.utc)
        hours = int(schedule["hours"])
        if hours < 1:
            raise ScheduleError("Interval tidak valid.")
        steps = max(1, int((after - anchor).total_seconds() // (hours * 3600)) + 1)
        return anchor + timedelta(hours=hours * steps)
    local = after.astimezone(zone)
    if kind == "once":
        try:
            naive = datetime(schedule["year"], schedule["month"], schedule["day"], schedule["hour"], schedule["minute"])
        except (ValueError, KeyError, TypeError):
            return None
        return _valid_local(naive, zone, after)
    if kind not in ("daily", "weekly", "monthly", "weekdays"):
        raise ScheduleError("Jadwal tidak dikenal.")
    for offset in range(370):
        day = local.date() + timedelta(days=offset)
        if kind == "weekly" and day.weekday() != schedule["weekday"]:
            continue
        if kind == "weekdays" and day.weekday() >= 5:
            continue
        if kind == "monthly" and (schedule["day"] > calendar.monthrange(day.year, day.month)[1]
                                  or day.day != schedule["day"]):
            continue
        naive = datetime(day.year, day.month, day.day, schedule["hour"], schedule["minute"])
        result = _valid_local(naive, zone, after)
        if result:
            return result
    return None


def _valid_local(naive, zone, after):
    candidate = naive.replace(tzinfo=zone).astimezone(timezone.utc)
    if candidate.astimezone(zone).replace(tzinfo=None) != naive:
        return None  # A spring-forward gap is skipped; never invent a local time.
    return candidate if candidate > after else None


def describe(schedule, zone):
    clock = f"{schedule.get('hour', 0):02d}.{schedule.get('minute', 0):02d}"
    kind = schedule["kind"]
    if kind == "once":
        text = f"{schedule['day']:02d}/{schedule['month']:02d}/{schedule['year']} · {clock}"
    elif kind == "daily":
        text = "Setiap hari · " + clock
    elif kind == "weekly":
        text = "Setiap " + ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")[schedule["weekday"]] + " · " + clock
    elif kind == "weekdays":
        text = "Senin–Jumat · " + clock
    elif kind == "monthly":
        text = f"Setiap tanggal {schedule['day']} · {clock}"
    else:
        text = f"Setiap {schedule['hours']} jam"
    return text + " · " + ZONE_LABELS.get(zone, zone)
