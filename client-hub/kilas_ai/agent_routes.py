"""Conversational Agent front end over the existing account-owned task engine."""
import json
import logging
import re
import time
from datetime import datetime, timezone

import db
from flask import abort, redirect, render_template, request, session, url_for

from . import agent_planner, agent_store, automation_schedule as schedule, automation_store as store, usage
from . import connectors, google_connection, connector_flow, connector_planner
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
                   "kind": spec["automation_type"],
                   "connector_draft": bool(spec.get("condition", {}).get("connector_read") and
                                           connector_flow.DRAFT_WORDS.search(spec["instruction"]))}
    action = session.get("agent_pending_action")
    if action and int(time.time()) - action.get("created", 0) > 900:
        session.pop("agent_pending_action", None)
        action = None
    google = google_connection.configuration()
    google_row = connectors.google_connection(owner)
    google_services = {name: bool(google["ready"] and google_row and google_row["status"] == "CONNECTED" and
                             set(scopes).issubset(set(json.loads(google_row["scopes_json"]))))
                       for name, scopes in connectors.GOOGLE_SCOPES.items()}
    internal_connections = connectors.business_connections(owner)
    approval_rows = [connectors._row(row) for row in db.query_all(
        "SELECT id,tool,target,payload_json,business_id,expires_at FROM kilas_ai_action_approvals "
        "WHERE user_id=? AND status='PENDING' AND expires_at>? ORDER BY id DESC LIMIT 20",
        (owner, connectors.stamp()))]
    for approval_row in approval_rows:
        approval_row["payload"] = json.loads(approval_row["payload_json"])
    return render_template("kilas_ai/agent.html", view=view, messages=agent_store.messages(owner),
                           tasks=tasks, activity=agent_store.activity(owner), preview=preview,
                           action=action, capacity=store.usage_summary(owner),
                           google=google, google_connection=google_row,
                           google_services=google_services,
                           internal_connections=internal_connections, connector_approvals=approval_rows,
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
    connection = (None if re.search(r"\b(?:pause|jeda|resume|lanjutkan|aktifkan|ingatkan|remind|recuérdame)\b|提醒", text, re.I)
                  else agent_planner.required_connection(text))
    connector_context = session.get("agent_connector_context")
    if connector_context and (int(time.time()) - int(session.get("agent_connector_context_at", 0)) > 600
                              or len(text) > 120
                              or re.search(r"\b(?:pause|jeda|resume|lanjutkan|aktifkan|cari berita|search news)\b", text, re.I)):
        session.pop("agent_connector_context", None)
        session.pop("agent_connector_context_at", None)
        connector_context = None
    if connection or connector_context:
        enabled_tools = connectors.available_tools(owner)
        family = ({"Gmail": "gmail.", "Google Calendar": "calendar.", "Google Drive": "drive.",
                   "Google Contacts": "contacts.", "WhatsApp": "whatsapp.",
                   "Kilas Finance": "finance."}.get(connection) if connection else None)
        if family and not any(tool.startswith(family) for tool in enabled_tools):
            session["connector_pending_intent"] = text
            _reply(f"Kilas butuh akses {connection}. Koneksi belum terhubung atau belum memberi izin yang diperlukan. "
                   "Permintaanmu disimpan untuk dilanjutkan setelah koneksi tersedia.")
            return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)
        connector_schedule = (re.search(r"\b(?:setiap|tiap|every|cada)\b|每周|每天|每月", text, re.I) or
            (connector_flow.SCHEDULE_WORDS.match(text) and
             re.search(r"\b(?:cek|periksa|check|cari|search|pantau|monitor|rangkum|summarize)\b", text, re.I)))
        if connection and connector_schedule:
            try:
                spec = schedule.parse(text, store.setting(owner))
                spec["condition"]["connector_read"] = True
                _preview(None, spec)
                _reply("Siap. Tugas ini hanya membaca akses yang tersedia dan menyimpan hasil di Aktivitas. "
                       "Periksa jadwal sebelum mengaktifkan.")
            except schedule.ScheduleError:
                try:
                    normalized = agent_planner.propose(owner, text, history, tasks, store.setting(owner))
                    if normalized["action"] != "CREATE":
                        _reply(normalized["reply"].strip()[:1200] or "Kapan tugas ini perlu dijalankan?")
                    else:
                        spec = schedule.parse(normalized["schedule_text"][:1200], store.setting(owner))
                        spec["instruction"] = text
                        spec["title"] = text[:90]
                        spec["condition"]["connector_read"] = True
                        _preview(None, spec)
                        _reply("Siap. Periksa jadwal dan batas izin sebelum tugas diaktifkan.")
                except (agent_planner.PlanUnavailable, schedule.ScheduleError, ValueError):
                    _reply("Jam atau tanggalnya belum cukup jelas. Sebutkan waktu yang kamu inginkan.")
            return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)
        try:
            result = connector_flow.handle(owner, text, history, store.setting(owner))
            _reply(result["message"])
            session["agent_connector_context"] = connection or connector_context
            session["agent_connector_context_at"] = int(time.time())
        except ValueError as error:
            code = str(error)
            if isinstance(error, usage.UsageLimit):
                _reply(code)
                return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)
            # Log only fixed diagnostic codes, never message content or credentials.
            if code in {"invalid_event", "invalid_payload", "invalid_business_scope", "invalid_target",
                        "invalid_approval_expiry", "approval_not_required", "ambiguous_event",
                        "planner_unavailable", "permission_missing", "recipient_unverified"}:
                logging.getLogger(__name__).warning("Agent connector rejected: %s", code)
            if code in ("not_connected", "permission_missing", "provider_not_configured"):
                session["connector_pending_intent"] = text
            _reply({"choose_business": "Bisnis mana yang dimaksud? Sebutkan nama bisnisnya.",
                    "not_connected": "Koneksi belum tersedia. Buka Koneksi untuk menghubungkan akun.",
                    "permission_missing": "Izin untuk tindakan ini belum diberikan. Hubungkan ulang layanan dengan izin yang sesuai.",
                    "reauth_required": "Izin koneksi sudah berakhir. Hubungkan kembali layanan melalui Koneksi.",
                    "planner_unavailable": "Agent belum bisa memahami permintaan ini sekarang. Coba lagi sebentar.",
                    "provider_unavailable": "Layanan belum merespons. Tidak ada tindakan yang diklaim berhasil.",
                    "rate_limited": "Layanan sedang membatasi permintaan. Coba lagi nanti.",
                    "invalid_target": "Tujuan itu tidak ditemukan pada koneksi ini. Periksa nama atau ID-nya.",
                    "recipient_not_in_thread": "Penerima tidak cocok dengan thread email yang dipilih. Periksa percakapannya dulu.",
                    "recipient_unverified": "Alamat email penerima belum terverifikasi. Sebutkan alamatnya atau hubungkan Google Contacts.",
                    "ambiguous_contact": "Ada beberapa kontak yang cocok. Sebutkan alamat email penerima yang tepat.",
                    "business_not_connected": "Bisnis itu tidak terhubung pada akun ini."}.get(code,
                    "Permintaan belum bisa diproses dengan aman. Periksa tujuan dan izin lalu coba lagi."))
        return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)

    # Clear create commands should not depend on the model deciding whether to ask another
    # unnecessary question. The deterministic schedule parser is authoritative; the model
    # remains responsible for ambiguous conversational follow-ups and task edits.
    edit_words = re.search(r"\b(?:ubah|ganti|edit|pause|jeda|resume|lanjutkan|aktifkan kembali|hapus|delete)\b", text, re.I)
    if not edit_words and (schedule.TIME.search(text) or schedule.HALF.search(text) or re.search(r"\b(?:setiap|tiap|every)\s+\d+\s+(?:jam|hours?)\b", text, re.I)):
        try:
            spec = schedule.parse(text, store.setting(owner))
            _preview(None, spec)
            label = schedule.describe(spec["schedule"], spec["timezone"])
            _reply(f"Siap. Aku baca jadwalnya sebagai {label}. Cek pratinjau di bawah sebelum tugas diaktifkan.")
            return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)
        except schedule.ScheduleError:
            pass

    try:
        plan = agent_planner.propose(owner, text, history, tasks, store.setting(owner))
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
        elif kind == "CREATE" and not (schedule.TIME.search(plan["schedule_text"]) or schedule.HALF.search(plan["schedule_text"])) and not re.search(
                r"\b(?:setiap|tiap|every)\s+\d+\s+(?:jam|hours?)\b", plan["schedule_text"], re.I):
            _reply("Jam berapa tugas ini perlu dijalankan? Tulis waktu yang jelas, atau pilih tanggal dan jam di formulir tugas.")
        else:
            try:
                spec = schedule.parse(plan["schedule_text"][:1200], store.setting(owner))
                if item:
                    spec["title"] = item["title"]
                _preview(item_id, spec)
                label = schedule.describe(spec["schedule"], spec["timezone"])
                _reply(f"Siap. Aku baca jadwalnya sebagai {label}. Cek pratinjau di bawah sebelum tugas diaktifkan.")
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
