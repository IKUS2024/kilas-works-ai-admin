"""Conversational Agent front end over the existing account-owned task engine."""
import json
import logging
import re
import time
import secrets
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


def _clear_chat_context():
    for key in ('autonomous_job_id', 'agent_connector_context', 'agent_connector_context_at',
                'agent_work_clarification', 'agent_pending_action', 'automation_preview',
                'automation_preview_origin', 'connector_pending_intent'):
        session.pop(key, None)


@ai_bp.post('/agent/conversations', endpoint='agent_new_chat')
def new_chat():
    conversation_id = agent_store.new_conversation(_owner())
    _clear_chat_context()
    session['agent_conversation_id'] = conversation_id
    return redirect(url_for('kilas_ai.agent_home', conversation=conversation_id), code=303)


@ai_bp.post('/agent/conversations/<int:conversation_id>/rename', endpoint='agent_rename_chat')
def rename_chat(conversation_id):
    title = ' '.join(request.form.get('title', '').split())
    if not agent_store.conversation(_owner(), conversation_id):
        abort(404)
    if not 1 <= len(title) <= 60:
        abort(400)
    db.execute('UPDATE kilas_ai_conversations SET title=? WHERE id=? AND user_id=?', (title, conversation_id, _owner()))
    return redirect(url_for('kilas_ai.agent_home', conversation=conversation_id), code=303)


def _tasks():
    tasks = []
    for status in ("ACTIVE", "PAUSED"):
        rows, _ = store.list_for_owner(_owner(), status, 1)
        tasks.extend(dict(row) for row in rows)
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
    if view not in ("chat", "tasks", "activity", "connections", "history"):
        view = "chat"
    owner = _owner()
    selected = request.args.get('conversation', type=int)
    if selected is not None:
        if not agent_store.conversation(owner, selected):
            abort(404)
        if selected != session.get('agent_conversation_id'):
            _clear_chat_context()
        session['agent_conversation_id'] = selected
    conversation_id = agent_store.current_conversation(owner)
    conversation = agent_store.conversation(owner, conversation_id)
    from . import autonomous_runner, autonomous_store
    from .agent_presentation import job_card, time_label
    raw_autonomous_jobs = autonomous_store.list_jobs(owner, conversation_id=conversation_id if view == 'chat' else None) if autonomous_runner.enabled() and view in ('chat', 'tasks') else []
    if view == 'chat' and raw_autonomous_jobs:
        # Terminal results belong to the conversation only until the owner has actually viewed
        # that job/result. Once its events are read, keep history in the task/detail surfaces
        # instead of pinning stale "Selesai terbaru" cards under every later reply.
        unread_terminal = {row['job_id'] for row in db.query_all(
            "SELECT DISTINCT e.job_id FROM kilas_agent_events e "
            "JOIN kilas_agent_jobs j ON j.id=e.job_id "
            "WHERE j.user_id=? AND j.origin_conversation_id=? AND e.unread=1",
            (owner, conversation_id))}
        raw_autonomous_jobs = [job for job in raw_autonomous_jobs
                               if job['status'] not in autonomous_store.TERMINAL
                               or job['id'] in unread_terminal]
    autonomous_jobs = [job_card(j) for j in raw_autonomous_jobs]
    autonomous_unread = (db.query_one('SELECT COUNT(*) AS n FROM kilas_agent_events e JOIN kilas_agent_jobs j ON j.id=e.job_id WHERE j.user_id=? AND e.unread=1', (owner,))['n'] if autonomous_runner.enabled() else 0)
    tasks = _tasks() if view == 'tasks' else []
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
    google_services = {"gmail": google["ready"] and "gmail.send" in connectors.available_tools(owner)}
    internal_connections = connectors.business_connections(owner)
    approval_rows = [connectors._row(row) for row in db.query_all(
        "SELECT id,tool,target,payload_json,business_id,expires_at FROM kilas_ai_action_approvals "
        "WHERE user_id=? AND status='PENDING' AND expires_at>? ORDER BY id DESC LIMIT 20",
        (owner, connectors.stamp()))]
    approval_rows = [row for row in approval_rows if row["tool"] not in connectors.TOOLS or
                     connectors.TOOLS[row["tool"]][0] != "GOOGLE" or
                     (row["tool"] == "gmail.send" and '"draft_id"' not in row["payload_json"] and
                      '"thread_id"' not in row["payload_json"])]
    for approval_row in approval_rows:
        approval_row["payload"] = json.loads(approval_row["payload_json"])
    messages = agent_store.messages(owner, conversation_id=conversation_id, before=request.args.get('before', type=int)) if view == 'chat' else []
    older = db.query_one('SELECT id FROM kilas_ai_agent_messages WHERE user_id=? AND conversation_id=? AND id<? LIMIT 1', (owner, conversation_id, messages[0]['id'])) if messages else None
    activity = [{**dict(r), 'time_label': time_label(r['completed_at'] or r['scheduled_for'])} for r in agent_store.activity(owner)] if view == 'activity' else []
    history_page = max(1, min(request.args.get('page', 1, type=int), 10000))
    history_chats, more_chats = agent_store.conversation_page(owner, history_page) if view == 'history' else ([], False)
    return render_template("kilas_ai/agent.html", view=view, messages=messages,
                           conversation=conversation, recent_chats=agent_store.recent_conversations(owner),
                           older=bool(older), operation_key=secrets.token_urlsafe(24),
                           history_chats=history_chats, history_page=history_page, more_chats=more_chats,
                           tasks=tasks, activity=activity, preview=preview,
                           action=action, capacity=store.usage_summary(owner),
                           autonomous_jobs=autonomous_jobs, autonomous_unread=autonomous_unread,
                           autonomous_enabled=autonomous_runner.enabled(),
                           google=google, google_connection=google_row,
                           google_services=google_services,
                           internal_connections=internal_connections, connector_approvals=approval_rows,
                           unread=store.unread_count(owner), error=request.args.get("error"),
                           prefill=request.args.get("message", "")[:1200])


@ai_bp.post("/agent/chat", endpoint="agent_chat")
def agent_chat():
    text = str(request.form.get("message") or "").strip()
    if not 1 <= len(text) <= 1200:
        return redirect(url_for("kilas_ai.agent_home", error="message"), code=303)
    owner = _owner()
    files=[f for f in request.files.getlist('source_files') if f.filename]
    if files:
        from . import attachments,work_documents
        if not work_documents.intent(text):
            return {'error':'Lampiran ini dapat digunakan untuk membuat dokumen. Sebutkan dokumen yang ingin disiapkan.'},400
        try:
            prepared=attachments.prepare_many(files,usage.effective_plan(owner)['plan'])
            if any(not item['extracted_text'] for item in prepared):raise attachments.AttachmentError('Gunakan dokumen dengan teks yang dapat dibaca.')
            request.work_source_materials=[{'filename':item['filename'],'text':item['extracted_text'][:4000]} for item in prepared]
        except attachments.AttachmentError as error:
            return {'error':str(error)},400
    selected = request.form.get('conversation_id', type=int)
    if selected is not None:
        if not agent_store.conversation(owner, selected):
            abort(404)
        if selected != session.get('agent_conversation_id'):
            _clear_chat_context()
        session['agent_conversation_id'] = selected
    conversation_id = agent_store.current_conversation(owner)
    key = request.form.get('operation_key') or secrets.token_urlsafe(24)
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,96}', key):
        abort(400)
    if not agent_store.claim_request(owner, conversation_id, key):
        return {'error': 'Pesan ini sudah diterima. Buka kembali chat untuk melihat hasilnya.'}, 409
    history = agent_store.messages(owner, 12)
    tasks = _tasks()
    agent_store.append(owner, "user", text)
    from . import autonomous_routes
    if autonomous_routes.chat(owner, text):
        return redirect(url_for('kilas_ai.agent_home', view='chat'), code=303)
    session.pop("automation_preview", None)
    session.pop("automation_preview_origin", None)
    session.pop("agent_pending_action", None)
    connection = (None if re.search(r"\b(?:pause|jeda|resume|lanjutkan|aktifkan|ingatkan|remind|recuérdame)\b|提醒", text, re.I)
                  else agent_planner.required_connection(text))
    from . import agent_intents, agent_chat as chat_provider
    schedule_followup = len(text) <= 80 and any(re.search(r'(?i)\b(?:zona waktu(?:nya)?|jam berapa|kapan|tanggal)\b', r['content']) for r in history if r['role'] == 'assistant')
    if not connection and (agent_intents.QUESTION.search(text) or (not session.get('agent_connector_context') and not schedule_followup and not re.search(r'(?i)\b(?:ingatkan|ingetin|remind|setiap|tiap|every|besok|tanggal|ubah|ganti|pause|jeda|resume|lanjut|stop|aktifkan)\b', text))):
        response = chat_provider.ordinary(owner, conversation_id, key)
        return response if response is not None else redirect(url_for('kilas_ai.agent_home', view='chat'), code=303)
    connector_context = session.get("agent_connector_context")
    if connector_context and (int(time.time()) - int(session.get("agent_connector_context_at", 0)) > 600
                              or len(text) > 120
                              or re.search(r"\b(?:pause|jeda|resume|lanjutkan|aktifkan|cari berita|search news)\b", text, re.I)):
        session.pop("agent_connector_context", None)
        session.pop("agent_connector_context_at", None)
        connector_context = None
    if connection or connector_context:
        if connection in ("Google Calendar", "Google Drive", "Google Contacts"):
            _reply("Fitur Google tersebut belum tersedia. Saat ini koneksi Google hanya mendukung pengiriman Gmail setelah persetujuanmu.")
            return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)
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
        if connection == "Gmail" and connector_schedule:
            _reply("Tugas terjadwal yang membaca Gmail belum tersedia. Saat ini Google hanya mendukung pengiriman email setelah persetujuanmu.")
            return redirect(url_for("kilas_ai.agent_home", view="chat"), code=303)
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
                    "recipient_unverified": "Sebutkan alamat email penerima secara langsung agar Kilas bisa menyiapkan email untuk persetujuanmu.",
                    "google_tool_disabled": "Fitur Google tersebut belum tersedia. Saat ini hanya pengiriman Gmail setelah persetujuan yang didukung.",
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
