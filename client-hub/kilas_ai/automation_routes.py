"""Owner-only Automation pages inside the existing Kilas AI product."""
import json
import time

from flask import abort, redirect, render_template, request, session, url_for

from . import automation_schedule as schedule, automation_store as store, usage
from .routes import ai_bp, automation_enabled


@ai_bp.before_request
def require_automation_flag():
    if request.endpoint and request.endpoint.startswith("kilas_ai.automation_") and not automation_enabled():
        abort(404)


def _owner():
    return session["user_id"]


def _page(template, **values):
    values.setdefault("unread", store.usage_summary(_owner())["unread"])
    return render_template("kilas_ai/" + template, **values)


def _local_text(value, zone):
    return (usage._as_utc(value).astimezone(schedule.ZoneInfo(zone)).strftime("%d/%m/%Y %H.%M")
            if value else None)


@ai_bp.get("/automation", endpoint="automation_home")
def automation_home():
    selected = request.args.get("filter", "ACTIVE").upper()
    if selected not in ("ACTIVE", "PAUSED", "UNREAD"):
        selected = "ACTIVE"
    page = request.args.get("page", "1")
    try:
        page = max(1, min(int(page), 10000))
    except ValueError:
        page = 1
    raw_rows, more = store.list_for_owner(_owner(), selected, page)
    rows = [dict(item) for item in raw_rows]
    for item in rows:
        item["schedule_label"] = schedule.describe(json.loads(item["schedule_json"]), item["timezone"])
        item["next_label"] = _local_text(item["next_run_at"], item["timezone"])
        item["last_label"] = _local_text(item["last_run_at"], item["timezone"])
    return _page("automation.html", rows=rows, more=more, page=page, selected=selected,
                 timezone_name=store.setting(_owner()), detect_timezone=not store.has_setting(_owner()),
                 quota=store.usage_summary(_owner()), error=request.args.get("error"))


@ai_bp.post("/automation/timezone", endpoint="automation_timezone")
def automation_timezone():
    try:
        store.set_timezone(_owner(), request.form.get("timezone"))
    except schedule.ScheduleError:
        return redirect(url_for("kilas_ai.automation_home", error="timezone"), code=303)
    return redirect(url_for("kilas_ai.automation_home"), code=303)


@ai_bp.get("/automation/new", endpoint="automation_new")
def automation_new():
    return _page("automation_form.html", item=None, instruction=request.args.get("instruction", "")[:1200],
                 timezone_name=store.setting(_owner()), detect_timezone=not store.has_setting(_owner()),
                 title="", preview=None, error=None)


@ai_bp.get("/automation/<int:automation_id>/edit", endpoint="automation_edit")
def automation_edit(automation_id):
    item = store.get(_owner(), automation_id)
    if not item:
        abort(404)
    return _page("automation_form.html", item=item, instruction=item["instruction"],
                 timezone_name=item["timezone"], title=item["title"], preview=None, error=None)


@ai_bp.post("/automation/preview", endpoint="automation_preview")
def automation_preview():
    raw_id = request.form.get("automation_id", "")
    try:
        item_id = int(raw_id) if raw_id else None
    except ValueError:
        abort(400)
    item = store.get(_owner(), item_id) if item_id else None
    if item_id and not item:
        abort(404)
    instruction = str(request.form.get("instruction") or "").strip()[:1200]
    title = str(request.form.get("title") or "").strip()[:90]
    timezone_name = request.form.get("timezone") or store.setting(_owner())
    try:
        spec = schedule.parse(instruction, timezone_name)
    except schedule.ScheduleError as error:
        return _page("automation_form.html", item=item, instruction=instruction,
                     timezone_name=timezone_name, title=title, preview=None, error=str(error)), 400
    if title:
        spec["title"] = title
    if not store.has_setting(_owner()):
        store.set_timezone(_owner(), schedule.validate_timezone(timezone_name))
    session["automation_preview"] = {"instruction": instruction, "timezone": timezone_name,
                                     "automation_id": item_id, "title": title, "created": int(time.time())}
    session.modified = True
    return _page("automation_form.html", item=item, instruction=instruction, timezone_name=timezone_name,
                 preview={"title": spec["title"], "kind": spec["automation_type"],
                          "schedule": schedule.describe(spec["schedule"], spec["timezone"]),
                          "next_run": spec["next_run_at"].astimezone(schedule.ZoneInfo(spec["timezone"])),
                          "timezone": spec["timezone"]}, error=None)


@ai_bp.post("/automation/activate", endpoint="automation_activate")
def automation_activate():
    preview = session.pop("automation_preview", None)
    if not preview or int(time.time()) - preview["created"] > 1800:
        return redirect(url_for("kilas_ai.automation_new"), code=303)
    raw_id = request.form.get("automation_id", "")
    item_id = int(raw_id) if raw_id.isdigit() else None
    if item_id != preview["automation_id"]:
        abort(400)
    if item_id and not store.get(_owner(), item_id):
        abort(404)
    spec = schedule.parse(preview["instruction"], preview["timezone"])
    if preview.get("title"):
        spec["title"] = preview["title"]
    try:
        if item_id:
            store.edit(_owner(), item_id, spec)
        else:
            store.create(_owner(), spec)
    except store.AutomationError as error:
        return _page("automation_form.html", item=store.get(_owner(), item_id) if item_id else None,
                     instruction=preview["instruction"], timezone_name=preview["timezone"],
                     title=preview.get("title", ""), preview=None, error=str(error)), 400
    return redirect(url_for("kilas_ai.automation_home"), code=303)


@ai_bp.post("/automation/<int:automation_id>/<action>", endpoint="automation_action")
def automation_action(automation_id, action):
    if action not in ("pause", "resume", "delete"):
        abort(404)
    if not store.get(_owner(), automation_id):
        abort(404)
    try:
        store.set_status(_owner(), automation_id, action)
    except store.AutomationError as error:
        return redirect(url_for("kilas_ai.automation_home", error=str(error)[:80]), code=303)
    return redirect(url_for("kilas_ai.automation_home"), code=303)


@ai_bp.get("/automation/<int:automation_id>/results", endpoint="automation_results")
def automation_results(automation_id):
    item = store.get(_owner(), automation_id)
    if not item:
        abort(404)
    page = request.args.get("page", "1")
    try:
        page = max(1, min(int(page), 10000))
    except ValueError:
        page = 1
    rows = [dict(row) for row in store.results(_owner(), automation_id, page)]
    for row in rows:
        row["completed_label"] = _local_text(row["completed_at"], item["timezone"])
    return _page("automation_results.html", item=item, rows=rows, page=page)


@ai_bp.get("/automation/results/<int:run_id>", endpoint="automation_result")
def automation_result(run_id):
    result = store.result(_owner(), run_id)
    if not result or not result["result_text"]:
        abort(404)
    result = dict(result)
    result["completed_label"] = _local_text(result["completed_at"], result["timezone"])
    store.mark_read(_owner(), run_id)
    try:
        metadata = json.loads(result["result_metadata_json"] or "{}")
    except ValueError:
        metadata = {}
    return _page("automation_result.html", result=result, citations=metadata.get("citations", []))
