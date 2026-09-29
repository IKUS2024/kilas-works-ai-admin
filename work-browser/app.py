"""Private browser process for Kilas Work; no product database or provider key."""
import base64
import hashlib
import hmac
import os
import sys
import time
from pathlib import Path

from flask import Flask, abort, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "client-hub"))
from kilas_work.browser_runtime import BrowserRuntimeError, runtime  # noqa: E402
from kilas_work.browser_safety import BrowserSafetyError  # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.before_request
def authenticate():
    if request.path == "/healthz":
        return None
    secret = os.environ.get("KILAS_WORK_BROWSER_SECRET", "")
    if len(secret) < 32:
        abort(503)
    owner = request.headers.get("X-Work-Owner", "")
    timestamp = request.headers.get("X-Work-Time", "")
    signature = request.headers.get("X-Work-Signature", "")
    if not owner.isdigit() or not timestamp.isdigit() or not signature:
        abort(403)
    if abs(time.time() - int(timestamp)) > 60:
        abort(403)
    digest = hashlib.sha256(request.get_data()).hexdigest()
    signed = "\n".join((request.method, request.path, digest, timestamp, owner)).encode()
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        abort(403)


@app.after_request
def private(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def owner():
    return int(request.headers["X-Work-Owner"])


@app.errorhandler(BrowserRuntimeError)
@app.errorhandler(BrowserSafetyError)
def safe_error(error):
    return {"error": str(error)}, 400


@app.post("/sessions/<int:job_id>")
def create(job_id):
    payload = request.get_json(silent=True) or {}
    return runtime.create(owner(), job_id, str(payload.get("url") or ""))


@app.get("/sessions/<int:job_id>")
def snapshot(job_id):
    return runtime.snapshot(owner(), job_id)


@app.post("/sessions/<int:job_id>/actions")
def actions(job_id):
    payload = request.get_json(silent=True) or {}
    return runtime.actions(owner(), job_id, payload.get("actions"), call_id=payload.get("call_id"))


@app.post("/sessions/<int:job_id>/manual")
def manual(job_id):
    payload = request.get_json(silent=True) or {}
    return runtime.actions(owner(), job_id, payload.get("actions"),
                           call_id=payload.get("call_id"), manual=True)


@app.post("/sessions/<int:job_id>/upload")
def upload(job_id):
    payload = request.get_json(silent=True) or {}
    try:
        raw = base64.b64decode(payload.get("content") or "", validate=True)
    except (ValueError, TypeError):
        abort(400)
    return runtime.upload(owner(), job_id, str(payload.get("filename") or ""), raw,
                          str(payload.get("mime_type") or "application/octet-stream"))


@app.post("/sessions/<int:job_id>/downloads/<int:index>")
def download(job_id, index):
    item = runtime.download(owner(), job_id, index)
    return jsonify({"filename": item["name"], "content": base64.b64encode(item["content"]).decode("ascii")})


@app.delete("/sessions/<int:job_id>")
def close(job_id):
    return {"closed": runtime.close(owner(), job_id)}
