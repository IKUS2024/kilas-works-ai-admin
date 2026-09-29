"""Signed, account-scoped transport to the isolated Work browser process."""
import hashlib
import hmac
import json
import os
import time
import base64
from urllib.parse import urlparse

import requests


class BrowserUnavailable(RuntimeError):
    pass


def _base():
    value = os.environ.get("KILAS_WORK_BROWSER_URL", "").rstrip("/")
    parsed = urlparse(value)
    private_http = parsed.scheme == "http" and (parsed.hostname or "").endswith(".internal")
    if not (parsed.scheme == "https" or private_http) or not parsed.hostname or parsed.username or parsed.password:
        raise BrowserUnavailable("Browser Work belum tersedia.")
    return value


def _secret():
    secret = os.environ.get("KILAS_WORK_BROWSER_SECRET", "")
    if len(secret) < 32:
        raise BrowserUnavailable("Browser Work belum tersedia.")
    return secret


def call(owner_id, method, path, payload=None):
    if not path.startswith("/sessions/") or ".." in path:
        raise BrowserUnavailable("Permintaan browser tidak valid.")
    raw = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")).encode() if payload is not None else b""
    timestamp = str(int(time.time()))
    digest = hashlib.sha256(raw).hexdigest()
    signed = "\n".join((method.upper(), path, digest, timestamp, str(int(owner_id)))).encode()
    signature = hmac.new(_secret().encode(), signed, hashlib.sha256).hexdigest()
    try:
        response = requests.request(method.upper(), _base() + path, data=raw,
                    headers={"Content-Type": "application/json", "X-Work-Owner": str(int(owner_id)),
                             "X-Work-Time": timestamp, "X-Work-Signature": signature}, timeout=(5, 25))
        if response.status_code >= 400:
            raise BrowserUnavailable("Sesi browser belum tersedia. Coba lagi atau mulai pekerjaan baru.")
        return response.json()
    except (requests.RequestException, ValueError):
        raise BrowserUnavailable("Browser Work belum tersedia. Coba lagi nanti.") from None


def create(owner_id, job_id, url):
    return call(owner_id, "POST", f"/sessions/{int(job_id)}", {"url": url})


def snapshot(owner_id, job_id):
    return call(owner_id, "GET", f"/sessions/{int(job_id)}")


def actions(owner_id, job_id, call_id, items):
    return call(owner_id, "POST", f"/sessions/{int(job_id)}/actions",
                {"call_id": call_id, "actions": items})


def manual(owner_id, job_id, call_id, items):
    return call(owner_id, "POST", f"/sessions/{int(job_id)}/manual",
                {"call_id": call_id, "actions": items})


def close(owner_id, job_id):
    return call(owner_id, "DELETE", f"/sessions/{int(job_id)}")


def upload(owner_id, job_id, filename, mime_type, raw):
    return call(owner_id, "POST", f"/sessions/{int(job_id)}/upload",
                {"filename": filename, "mime_type": mime_type,
                 "content": base64.b64encode(bytes(raw)).decode("ascii")})


def download(owner_id, job_id, index):
    result = call(owner_id, "POST", f"/sessions/{int(job_id)}/downloads/{int(index)}", {})
    try:
        raw = base64.b64decode(result["content"], validate=True)
    except (KeyError, ValueError):
        raise BrowserUnavailable("Unduhan browser tidak valid.") from None
    return {"filename": result["filename"], "content": raw}
