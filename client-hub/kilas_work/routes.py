"""Kilas Work owner workspace and separate admin verification."""
import io
import os
import secrets
import base64
import re

from flask import Blueprint, abort, redirect, render_template, request, send_file, session, url_for

import payment_service
import security
from kilas_ai import attachments as shared_attachments
from kilas_ai import pdf as shared_pdf
from kilas_ai import tools as shared_tools
from . import artifacts, billing, browser_jobs, browser_client, engine, quota, store

work_bp = Blueprint("kilas_work", __name__, url_prefix="/kilas-work")
admin_bp = Blueprint("kilas_work_admin", __name__, url_prefix="/admin/kilas-work")


def enabled():
    return os.environ.get("KILAS_WORK_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


@work_bp.before_request
def owner_access():
    if not enabled():
        abort(404)
    if not session.get("user_id"):
        return redirect(url_for("auth.login_page"))
    user = security.current_user()
    if not user or user["role"] != "CLIENT_OWNER":
        abort(404)


@admin_bp.before_request
def admin_access():
    if not enabled():
        abort(404)
    if not session.get("user_id"):
        return redirect(url_for("auth.login_page"))
    user = security.current_user()
    if not user or user["role"] != "KILAS_ADMIN":
        abort(404)


@work_bp.get("")
def home():
    user_id = session["user_id"]
    return render_template("kilas_work/home.html", threads=store.threads(user_id), selected=None,
                           messages=[], files=[], jobs=[], quota=quota.snapshot(user_id))


@work_bp.get("/threads/<int:thread_id>")
def thread_page(thread_id):
    user_id = session["user_id"]
    selected = store.thread(user_id, thread_id)
    if not selected:
        abort(404)
    jobs = store.jobs(user_id, thread_id)
    for job in jobs:
        if job["status"] in ("QUEUED", "RUNNING"):
            browser_jobs.reconcile(user_id, job["id"])
    return render_template("kilas_work/home.html", threads=store.threads(user_id), selected=selected,
                           messages=store.messages(user_id, thread_id), files=store.files(user_id, thread_id),
                           jobs=store.jobs(user_id, thread_id), quota=quota.snapshot(user_id),
                           manual_call_id=secrets.token_hex(16))


@work_bp.post("/threads")
def new_thread():
    title = (request.form.get("message") or "").strip()
    if not title or len(title) > 12000:
        abort(400)
    thread_id = store.create_thread(session["user_id"], title[:80])
    return _send(thread_id, title)


@work_bp.post("/threads/<int:thread_id>/send")
def send(thread_id):
    if not store.thread(session["user_id"], thread_id):
        abort(404)
    return _send(thread_id, (request.form.get("message") or "").strip())


def _send(thread_id, text):
    user_id = session["user_id"]
    uploads = [item for item in request.files.getlist("attachments") if item.filename]
    if (not text and not uploads) or len(text) > 12000:
        abort(400)
    try:
        files = shared_attachments.prepare_many(uploads)
    except shared_attachments.AttachmentError as error:
        return {"error": str(error)}, 400
    operation, model = engine.route(text)
    if operation == "BROWSER":
        if files:
            message_id = store.add_message(user_id, thread_id, "user", text,
                                           metadata={"attachments": [item["filename"] for item in files]})
            for item in files:
                store.add_file(user_id, thread_id, message_id, item)
        else:
            store.add_message(user_id, thread_id, "user", text)
        try:
            browser_jobs.start(user_id, thread_id, text, model)
        except browser_jobs.JobError as error:
            store.add_message(user_id, thread_id, "activity", str(error))
        return redirect(url_for("kilas_work.thread_page", thread_id=thread_id), code=303)
    key = secrets.token_hex(16)
    try:
        source = quota.reserve(user_id, thread_id, key, operation, model)
    except quota.QuotaError as error:
        return {"error": str(error)}, 429
    try:
        user_message = store.add_message(user_id, thread_id, "user", text,
                                         metadata={"attachments": [item["filename"] for item in files]})
        for item in files:
            store.add_file(user_id, thread_id, user_message, item)
        if operation == "IMAGE":
            original = next((item for item in files if item["mime_type"].startswith("image/")), None)
            output = shared_tools.image(text, original)
            prepared = {"filename": "Kilas-Work-Image.png", "mime_type": output["mime"],
                        "content": output["raw"], "extracted_text": None}
            message = store.add_message(user_id, thread_id, "assistant", "Gambar siap diunduh.",
                                        model=output["model"])
            store.add_file(user_id, thread_id, message, prepared)
            quota.finish(user_id, key, success=True, actual_micro=quota.estimate_micro(model, image_count=1))
        else:
            prior = store.messages(user_id, thread_id) or []
            context = [(row["role"], row["content"]) for row in prior[:-1]
                       if row["role"] in ("user", "assistant")]
            prompt = text
            if operation == "PDF":
                prompt += ("\n\nTulis isi dokumen lengkap dalam Markdown yang rapi. Berikan dokumen itu sendiri, "
                           "bukan instruksi cara membuat PDF. Jangan mengarang fakta.")
            result = engine.respond(context, prompt, files, model, "WEB" if operation == "WEB" else "CHAT")
            message = store.add_message(user_id, thread_id, "assistant", result["answer"], model=model,
                                        metadata={"citations": result["citations"]})
            if operation == "PDF":
                rendered = shared_pdf.render(result["answer"])
                store.add_file(user_id, thread_id, message, rendered)
            else:
                artifact = artifacts.from_answer(text, result["answer"])
                if artifact:
                    store.add_file(user_id, thread_id, message, artifact)
            used = result["usage"]
            quota.finish(user_id, key, success=True, actual_micro=result["charged_micro"],
                         input_tokens=used.get("input_tokens", 0), output_tokens=used.get("output_tokens", 0),
                         tool_calls=result["web_calls"])
    except (engine.EngineError, shared_tools.ToolUnavailable, ValueError) as error:
        quota.finish(user_id, key, success=False)
        store.add_message(user_id, thread_id, "activity", str(error)[:240])
    except Exception:
        quota.finish(user_id, key, success=False)
        store.add_message(user_id, thread_id, "activity", "Pekerjaan belum selesai. Coba lagi nanti.")
    return redirect(url_for("kilas_work.thread_page", thread_id=thread_id), code=303)


@work_bp.get("/threads/<int:thread_id>/files/<int:file_id>")
def download(thread_id, file_id):
    item = store.file(session["user_id"], thread_id, file_id)
    if not item:
        abort(404)
    response = send_file(io.BytesIO(bytes(item["content"])), mimetype=item["mime_type"],
                         as_attachment=True, download_name=item["filename"])
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@work_bp.get("/jobs/<int:job_id>/screenshot")
def job_screenshot(job_id):
    item = store.job(session["user_id"], job_id)
    if not item or item["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
        abort(404)
    try:
        captured = browser_client.snapshot(session["user_id"], job_id)
        raw = base64.b64decode(captured["screenshot"], validate=True)
    except (browser_client.BrowserUnavailable, ValueError, KeyError):
        abort(404)
    response = send_file(io.BytesIO(raw), mimetype="image/png")
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@work_bp.get("/jobs/<int:job_id>/status")
def job_status(job_id):
    item = browser_jobs.reconcile(session["user_id"], job_id)
    if not item:
        abort(404)
    return {"status": item["status"], "updated_at": str(item["updated_at"]),
            "current_url": item["current_url"]}


@work_bp.post("/jobs/<int:job_id>/resume")
def job_resume(job_id):
    item = store.job(session["user_id"], job_id)
    if not item:
        abort(404)
    try:
        browser_jobs.resume(session["user_id"], job_id)
    except (browser_jobs.JobError, browser_client.BrowserUnavailable) as error:
        return {"error": str(error)}, 409
    return redirect(url_for("kilas_work.thread_page", thread_id=item["thread_id"]), code=303)


@work_bp.post("/jobs/<int:job_id>/confirm")
def job_confirm(job_id):
    item = store.job(session["user_id"], job_id)
    if not item:
        abort(404)
    try:
        browser_jobs.confirm(session["user_id"], job_id)
    except (browser_jobs.JobError, browser_client.BrowserUnavailable) as error:
        return {"error": str(error)}, 409
    return redirect(url_for("kilas_work.thread_page", thread_id=item["thread_id"]), code=303)


@work_bp.post("/jobs/<int:job_id>/cancel")
def job_cancel(job_id):
    item = store.job(session["user_id"], job_id)
    if not item:
        abort(404)
    try:
        browser_jobs.cancel(session["user_id"], job_id)
    except browser_jobs.JobError as error:
        return {"error": str(error)}, 409
    return redirect(url_for("kilas_work.thread_page", thread_id=item["thread_id"]), code=303)


@work_bp.post("/jobs/<int:job_id>/manual")
def job_manual(job_id):
    item = store.job(session["user_id"], job_id)
    if not item:
        abort(404)
    kind = request.form.get("action")
    if kind == "click":
        try:
            x, y = int(request.form.get("x", "")), int(request.form.get("y", ""))
        except ValueError:
            abort(400)
        if not 0 <= x < 1280 or not 0 <= y < 800:
            abort(400)
        action = {"type": "click", "button": "left", "x": x, "y": y}
    elif kind == "type":
        value = request.form.get("text") or ""
        if not value or len(value) > 2000:
            abort(400)
        action = {"type": "type", "text": value}
    elif kind == "keypress":
        key = request.form.get("key")
        if key not in ("Tab", "Enter", "Backspace"):
            abort(400)
        action = {"type": "keypress", "keys": [key]}
    else:
        abort(400)
    call_id = request.form.get("call_id") or ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,96}", call_id):
        abort(400)
    try:
        browser_jobs.manual(session["user_id"], job_id, call_id, [action])
    except (browser_jobs.JobError, browser_client.BrowserUnavailable) as error:
        return {"error": str(error)}, 409
    return redirect(url_for("kilas_work.thread_page", thread_id=item["thread_id"]), code=303)


@work_bp.post("/jobs/<int:job_id>/upload/<int:file_id>")
def job_upload(job_id, file_id):
    item = store.job(session["user_id"], job_id)
    if not item or item["status"] != "PAUSED_USER":
        abort(404)
    selected = store.file(session["user_id"], item["thread_id"], file_id)
    if not selected:
        abort(404)
    try:
        browser_client.upload(session["user_id"], job_id, selected["filename"],
                              selected["mime_type"], selected["content"])
    except browser_client.BrowserUnavailable as error:
        return {"error": str(error)}, 409
    return redirect(url_for("kilas_work.thread_page", thread_id=item["thread_id"]), code=303)


@work_bp.get("/usage")
def usage_page():
    return render_template("kilas_work/usage.html", quota=quota.snapshot(session["user_id"]),
                           plans=quota.PLANS, topups=quota.TOPUPS,
                           orders=billing.owner_orders(session["user_id"]))


@work_bp.post("/checkout")
def checkout():
    try:
        order_id = billing.create_order(session["user_id"], request.form.get("kind"), request.form.get("sku"))
    except billing.BillingError as error:
        return {"error": str(error)}, 400
    return redirect(url_for("kilas_work.invoice", order_id=order_id), code=303)


@work_bp.get("/orders/<int:order_id>")
def invoice(order_id):
    item = billing.order(session["user_id"], order_id)
    if not item:
        abort(404)
    return render_template("kilas_work/invoice.html", order=item, bank=payment_service.BANK_DETAILS)


@work_bp.post("/orders/<int:order_id>/proof")
def proof(order_id):
    if not billing.order(session["user_id"], order_id):
        abort(404)
    try:
        billing.submit_proof(session["user_id"], order_id, request.files.get("proof"))
    except billing.BillingError as error:
        return {"error": str(error)}, 400
    return redirect(url_for("kilas_work.invoice", order_id=order_id), code=303)


@admin_bp.get("/payments")
def payments():
    return render_template("kilas_work/admin_payments.html", orders=billing.review_queue())


@admin_bp.get("/orders/<int:order_id>/proof")
def admin_proof(order_id):
    item = billing.admin_proof(order_id)
    if not item or not item["proof_content"]:
        abort(404)
    response = send_file(io.BytesIO(bytes(item["proof_content"])), mimetype=item["proof_mime_type"],
                         as_attachment=False, download_name=item["proof_filename"])
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@admin_bp.post("/orders/<int:order_id>/review")
def admin_review(order_id):
    try:
        billing.review(order_id, session["user_id"], (request.form.get("decision") or "").upper(),
                       request.form.get("note"))
    except billing.BillingError as error:
        return {"error": str(error)}, 400
    return redirect(url_for("kilas_work_admin.payments"), code=303)
