"""Conversational Agent front end over the existing account-owned task engine."""
import json
import re
import time
from datetime import datetime, timezone

from flask import abort, redirect, render_template, request, session, url_for

from . import agent_planner, agent_store, automation_schedule as schedule, automation_store as store, usage
from .routes import ai_bp, automation_enabled


@ai_bp.before_request
def require_agent_flag():
    if request.endpoint and request.endpoint.startswith("kilas_ai.agent_") and not automation_enabled():
        abort(404)


def _owner():
    return session["user_id"]


def _tasks():
    tasks = []
    for status in ("ACTIVE", "PAUSED"):
        page = 1
        while page <= 25:
            rows, more = store.list_for_owner(_owner(), status, page)
            tasks.extend(dict(row) for row in rows)
            if not more:
                break
            page += 1
    return tasks


def _reply(message):
    agent_store.append(_owner(), "assistant", message[:2400])


def _preview(item_id, spec):
    session["automation_preview"] = {"automation_id": item_id, "created": int(time.time()),
                                     "spec": {**spec, "next_run_at": spec["next_run_at"].isoformat()}}
    session["automation_preview_origin"] = "agent"
    session.modified = True


@ai_bp.get("/agent", endpoint="agent_home")
def agent_home():
    view = request.args.get("view", "chat")
    if view not in ("chat", "tasks", "activity", "connections"):
        view = "chat"
    owner = _owner()
    tasks = _tasks()
    for item in tasks:
        item["schedule_label"] = schedule.describe(json.loads(item["schedule_json"]), item["timezone"])
        item["next_label"] = (usage._as_utc(item["next_run_at"]).astimezone(schedule.ZoneInfo(item["timezone"]))
                              .strftime("%d/%m/%Y %H.%M") if item["next_run_at"] else None)
        item["status_label"] = ("Dijeda" if item["status"] == "PAUSED" else
                                "Kapasitas habis" if item["status"] == "PAUSED_QUOTA" else
                                "Selesai" if not item["next_run_at"] and item["last_success_at"] else "Aktif")
    pending = session.get("automation_preview")
    if pending and int(time.time()) - pending.get("created", 0) > 1800:
        session.pop("automation_preview", None)
        session.pop("automation_preview_origin", None)
        pending = None
    preview = None
    if pending and session.get("automation_preview_origin") == "agent":
        spec = pending["spec"]
        preview = {"id": pending["automation_id"], "title": spec["title"],
                   "instruction": spec["instruction"],
                   "schedule": schedule.describe(spec["schedule"], spec["timezone"]),
                   "next_run": datetime.fromisoformat(spec["next_run_at"]).astimezone(
                       schedule.ZoneInfo(spec["timezone"])).strftime("%d/%m/%Y %H.%M"),
                   "kind": spec["automation_type"]}
    action = session.get("agent_pending_action")
    if action and int(time.time()) - action.get("created", 0) > 900:
        session.pop("agent_pending_action", None)
        action = None
    return render_template("kilas_ai/agent.html", view=view, messages=agent_store.messages(owner),
                           tasks=tasks, activity=agent_store.activity(owner), preview=preview,
                           action=action, capacity=store.usage_summary(owner),
                           unread=store.unread_count(owner), error=request.args.get("error"),
                           prefill=request.args.get("message", "")[:1200])


@ai_bp.post("/agent/chat", endpoint="agent_chat")
def agent_chat():
    text = " ".join(str(request.form.get("message") or "").split())
    if not 1 <= len(text) <= 1200:
        return redirect(url_for("kilas_ai.agent_home", error="message"), code=303)
    owner = _owner()
    history = agent_store.messages(owner, 12)
    tasks = _tasks()
    agent_store.append(owner, "user", text)
    session.pop("automation_preview", None)
    session.pop("automation_preview_origin", None)
    session.pop("agent_pending_action", None)
    connection = (None if re.search(r"\b(?:pause|jeda|resume|lanjutkan|aktifkan)\b", text, re.I)
                  else agent_planner.required_connection(text))
    if connection:
        _reply(f"Kilas butuh akses {connection} untuk menjalankan tugas ini. Koneksi {connection} belum tersedia, "
               "jadi tugas belum dibuat atau dijalankan. Lihat statusnya di Koneksi.")
        return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)
    try:
        plan = agent_planner.propose(owner, text, history, tasks)
    except agent_planner.PlanUnavailable:
        _reply("Aku belum bisa menyiapkan tugas dari chat saat ini. Coba lagi sebentar, atau gunakan formulir tugas untuk memilih jadwal sendiri.")
        return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)
    kind = plan["action"]
    if kind in ("CREATE", "EDIT"):
        item_id = plan["task_id"] if kind == "EDIT" else None
        item = store.get(owner, item_id) if item_id else None
        if kind == "EDIT" and not item:
            _reply("Aku belum yakin tugas mana yang ingin diubah. Pilih tugas di daftar, lalu buka Edit.")
        elif agent_planner.required_connection(plan["schedule_text"]):
            _reply("Tugas ini membutuhkan koneksi yang belum tersedia. Aku belum membuat atau mengaktifkannya.")
        elif kind == "CREATE" and not schedule.TIME.search(text) and not re.search(r"\bsetiap\s+\d+\s+jam\b", text, re.I):
            _reply("Jam berapa tugas ini perlu dijalankan? Tulis waktu yang jelas, atau pilih tanggal dan jam di formulir tugas.")
        else:
            try:
                spec = schedule.parse(plan["schedule_text"][:1200], store.setting(owner))
                if item:
                    spec["title"] = item["title"]
                _preview(item_id, spec)
                _reply("Aku siapkan pratinjau tugasnya. Periksa tindakan dan jadwal di bawah sebelum mengaktifkan.")
            except schedule.ScheduleError:
                _reply("Jadwalnya belum cukup jelas untuk dijalankan. Sebutkan waktu yang tepat, atau atur lewat formulir tugas.")
    elif kind in ("PAUSE", "RESUME"):
        item = store.get(owner, plan["task_id"]) if plan["task_id"] else None
        if not item:
            _reply("Aku belum yakin tugas mana yang kamu maksud. Buka daftar tugas dan pilih yang ingin diubah.")
        elif re.search(r"\b(?:sampai|until|hingga)\b", text, re.I) and kind == "PAUSE":
            _reply("Aku bisa menjeda tugas itu sekarang, tetapi belum bisa mengaktifkannya otomatis pada tanggal tertentu. Jeda lewat daftar tugas, lalu aktifkan kembali saat siap.")
        else:
            session["agent_pending_action"] = {"id": item["id"], "title": item["title"],
                                               "action": kind.lower(), "created": int(time.time())}
            _reply(f"Periksa dulu: {item['title']} akan {'dijeda' if kind == 'PAUSE' else 'diaktifkan kembali'} setelah kamu konfirmasi.")
    else:
        _reply(plan["reply"].strip()[:1200] or "Ceritakan tugas yang ingin Kilas kerjakan dan kapan harus dijalankan.")
    return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)


@ai_bp.post("/agent/action", endpoint="agent_action")
def agent_action():
    pending = session.pop("agent_pending_action", None)
    if not pending or int(time.time()) - pending.get("created", 0) > 900:
        return redirect(url_for("kilas_ai.agent_home", error="expired"), code=303)
    item = store.get(_owner(), pending["id"])
    if not item or pending["action"] not in ("pause", "resume"):
        abort(404)
    try:
        store.set_status(_owner(), item["id"], pending["action"])
    except store.AutomationError:
        return redirect(url_for("kilas_ai.agent_home", error="action"), code=303)
    _reply(f"{item['title']} sudah {'dijeda' if pending['action'] == 'pause' else 'diaktifkan kembali'}.")
    return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)
