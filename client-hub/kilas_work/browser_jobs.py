"""Durable Work computer-call loop; one bounded, account-owned job at a time."""
import json
import io
import mimetypes
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from werkzeug.datastructures import FileStorage
from kilas_ai import attachments as shared_attachments

from . import browser_client, quota, store
from .browser_safety import BrowserSafetyError

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kilas-work-browser")
_running = {}
_lock = threading.Lock()
MAX_STEPS = 24


class JobError(ValueError):
    pass


def _initial_url(goal):
    found = re.search(r"https?://[^\s<>\"']+", goal, re.I)
    if found:
        return found.group(0).rstrip(".,;)")
    return "https://www.bing.com/"


def _checkpoint(item):
    try:
        return json.loads(item["checkpoint_json"] or "{}")
    except (ValueError, TypeError):
        return {}


def _save_downloads(user_id, job_id, thread_id, observation):
    entries = sorted(observation.get("downloads") or [], key=lambda entry: int(entry["index"]), reverse=True)
    for entry in entries:
        try:
            result = browser_client.download(user_id, job_id, entry["index"])
            claimed = mimetypes.guess_type(result["filename"])[0] or "application/octet-stream"
            upload = FileStorage(stream=io.BytesIO(result["content"]), filename=result["filename"],
                                 content_type=claimed)
            prepared = shared_attachments.prepare(upload)
            message_id = store.add_message(user_id, thread_id, "assistant", "File dari website siap diunduh.")
            store.add_file(user_id, thread_id, message_id, prepared)
        except (browser_client.BrowserUnavailable, shared_attachments.AttachmentError, KeyError, ValueError):
            store.add_message(user_id, thread_id, "activity",
                              "Satu file dari website tidak dapat disimpan. Gunakan PDF, DOCX, CSV, TXT, atau gambar hingga 2 MB.")


def start(user_id, thread_id, goal, model):
    if not os.environ.get("KILAS_WORK_BROWSER_URL"):
        raise JobError("Pekerjaan browser belum tersedia.")
    job_id = store.create_job(user_id, thread_id, goal)
    try:
        observation = browser_client.create(user_id, job_id, _initial_url(goal))
        store.update_job(user_id, job_id, "QUEUED", "RUNNING",
                         checkpoint={"phase": "MODEL", "step": 0, "model": model},
                         current_url=observation["url"])
        _submit(user_id, job_id)
        return job_id
    except Exception:
        store.update_job(user_id, job_id, "QUEUED", "FAILED",
                         checkpoint={"phase": "FAILED"}, error_code="browser_unavailable")
        raise JobError("Website belum dapat dibuka. Coba lagi nanti.") from None


def _submit(user_id, job_id):
    key = (user_id, job_id)
    with _lock:
        prior = _running.get(key)
        if prior and not prior.done():
            return
        _running[key] = _pool.submit(_drive, user_id, job_id)


def active(user_id, job_id):
    with _lock:
        future = _running.get((user_id, job_id))
        return bool(future and not future.done())


def _model_call(model, goal, response_id=None, call_id=None, screenshot=None):
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise JobError("Kilas Work belum siap.")
    payload = {"model": model, "tools": [{"type": "computer"}], "max_output_tokens": 1800,
               "reasoning": {"effort": "medium" if model == "gpt-6-sol" else "none"}}
    if response_id:
        if not call_id or not screenshot:
            raise JobError("Checkpoint browser tidak lengkap.")
        payload["previous_response_id"] = response_id
        payload["input"] = [{"type": "computer_call_output", "call_id": call_id,
                             "output": {"type": "computer_screenshot",
                                        "image_url": "data:image/png;base64," + screenshot,
                                        "detail": "original"}}]
    else:
        payload["instructions"] = ("You are Kilas Work. Use the computer tool to perform the user's authorized "
            "web task. The browser is open at a public website. Do not type credentials, solve CAPTCHA, "
            "bypass 2FA/OTP, or submit purchases, deletes, public posts, sensitive messages, or consequential "
            "forms without explicit user confirmation. Pause and explain when user interaction is needed. "
            "Observe the browser before acting. Keep steps concise and never reveal hidden reasoning.")
        payload["input"] = goal[:12000]
    try:
        response = requests.post("https://api.openai.com/v1/responses",
                    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                    json=payload, timeout=(10, 120))
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError):
        raise JobError("Pekerjaan browser belum dapat dilanjutkan.") from None
    calls = [item for item in result.get("output", []) if item.get("type") == "computer_call"]
    if len(calls) > 1:
        raise JobError("Langkah browser tidak dapat diproses dengan aman.")
    answer = "\n".join(block.get("text", "") for item in result.get("output", [])
                       if item.get("type") == "message" for block in item.get("content", [])
                       if block.get("type") == "output_text").strip()
    usage = result.get("usage") or {}
    return {"id": result.get("id"), "call": calls[0] if calls else None,
            "answer": answer, "usage": usage}


def _drive(user_id, job_id):
    for _ in range(MAX_STEPS * 2):
        item = store.job(user_id, job_id)
        if not item or item["status"] != "RUNNING":
            return
        cp = _checkpoint(item)
        step = int(cp.get("step") or 0)
        if step >= MAX_STEPS:
            store.update_job(user_id, job_id, "RUNNING", "PAUSED_USER", checkpoint=cp,
                             response_id=item["last_response_id"], current_url=item["current_url"],
                             error_code="step_limit")
            return
        model = cp.get("model") if cp.get("model") in ("gpt-6-luna", "gpt-6-sol") else "gpt-6-luna"
        operation_key = f"work-browser-{job_id}-{step}-{cp.get('phase','MODEL').lower()}"
        try:
            if cp.get("phase") == "ACTION":
                if quota.reserve(user_id, item["thread_id"], operation_key, "BROWSER", model, job_id) is None:
                    raise JobError("Langkah browser sebelumnya perlu diperiksa.")
                started = time.monotonic()
                pending = cp.get("pending_call") or {}
                observation = browser_client.actions(user_id, job_id, pending["call_id"], pending["actions"])
                _save_downloads(user_id, job_id, item["thread_id"], observation)
                elapsed = max(1, int(time.monotonic() - started))
                quota.finish(user_id, operation_key, success=True,
                             actual_micro=quota.estimate_micro(model, browser_seconds=elapsed))
                if observation["decision"] in ("HANDOFF", "CONFIRM"):
                    cp.update(phase="MODEL", blocked_action=pending["actions"][observation["next_action"]],
                              blocked_index=observation["next_action"])
                    status = "PAUSED_USER" if observation["decision"] == "HANDOFF" else "PAUSED_CONFIRM"
                    store.update_job(user_id, job_id, "RUNNING", status, checkpoint=cp,
                                     response_id=item["last_response_id"], current_url=observation["url"])
                    return
                cp["phase"] = "MODEL"
                store.update_job(user_id, job_id, "RUNNING", "RUNNING", checkpoint=cp,
                                 response_id=item["last_response_id"], current_url=observation["url"])
                continue
            if cp.get("phase") != "MODEL":
                raise JobError("Checkpoint perlu ditinjau sebelum melanjutkan.")
            if quota.reserve(user_id, item["thread_id"], operation_key, "BROWSER", model, job_id) is None:
                raise JobError("Hasil langkah sebelumnya perlu diperiksa.")
            pending = cp.get("pending_call") or {}
            observation = browser_client.snapshot(user_id, job_id)
            response = _model_call(model, item["goal"], item["last_response_id"],
                                   pending.get("call_id"), observation["screenshot"])
            usage = response["usage"]
            actual = quota.estimate_micro(model, usage.get("input_tokens", 0),
                                           usage.get("output_tokens", 0), browser_seconds=1)
            quota.finish(user_id, operation_key, success=True, actual_micro=actual,
                         input_tokens=usage.get("input_tokens", 0),
                         output_tokens=usage.get("output_tokens", 0), tool_calls=int(bool(response["call"])))
            cp["step"] = step + 1
            if response["call"]:
                call = response["call"]
                if not response["id"] or not call.get("call_id") or not isinstance(call.get("actions"), list):
                    raise JobError("Langkah browser tidak lengkap.")
                cp.update(phase="ACTION", pending_call={"call_id": call["call_id"],
                                                       "actions": call["actions"]})
                store.update_job(user_id, job_id, "RUNNING", "RUNNING", checkpoint=cp,
                                 response_id=response["id"], current_url=observation["url"])
                continue
            if response["answer"]:
                store.add_message(user_id, item["thread_id"], "assistant", response["answer"], model=model)
            cp["phase"] = "DONE"
            store.update_job(user_id, job_id, "RUNNING", "COMPLETED", checkpoint=cp,
                             response_id=response["id"], current_url=observation["url"])
            browser_client.close(user_id, job_id)
            return
        except quota.QuotaError:
            store.update_job(user_id, job_id, "RUNNING", "PAUSED_QUOTA", checkpoint=cp,
                             response_id=item["last_response_id"], current_url=item["current_url"],
                             error_code="quota")
            return
        except (browser_client.BrowserUnavailable, BrowserSafetyError, JobError, KeyError, IndexError):
            quota.finish(user_id, operation_key, success=False)
            store.update_job(user_id, job_id, "RUNNING", "PAUSED_USER", checkpoint=cp,
                             response_id=item["last_response_id"], current_url=item["current_url"],
                             error_code="inspection_required")
            return
        except Exception:
            quota.finish(user_id, operation_key, success=False)
            store.update_job(user_id, job_id, "RUNNING", "PAUSED_USER", checkpoint=cp,
                             response_id=item["last_response_id"], current_url=item["current_url"],
                             error_code="inspection_required")
            return
    item = store.job(user_id, job_id)
    if item and item["status"] == "RUNNING":
        store.update_job(user_id, job_id, "RUNNING", "PAUSED_USER", checkpoint=_checkpoint(item),
                         response_id=item["last_response_id"], current_url=item["current_url"],
                         error_code="step_limit")


def resume(user_id, job_id):
    item = store.job(user_id, job_id)
    if not item or item["status"] not in ("PAUSED_USER", "PAUSED_QUOTA"):
        raise JobError("Pekerjaan tidak dapat dilanjutkan.")
    cp = _checkpoint(item)
    if cp.get("phase") not in ("MODEL", "ACTION") or (item["status"] != "PAUSED_QUOTA" and not cp.get("pending_call")):
        raise JobError("Pekerjaan memerlukan tinjauan ulang agar tidak mengulang tindakan.")
    browser_client.snapshot(user_id, job_id)
    if not store.update_job(user_id, job_id, item["status"], "RUNNING", checkpoint=cp,
                            response_id=item["last_response_id"], current_url=item["current_url"]):
        raise JobError("Status pekerjaan berubah. Muat ulang halaman.")
    _submit(user_id, job_id)


def cancel(user_id, job_id):
    item = store.job(user_id, job_id)
    if not item or item["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
        raise JobError("Pekerjaan tidak dapat dibatalkan.")
    if not store.update_job(user_id, job_id, item["status"], "CANCELLED",
                            checkpoint=_checkpoint(item), response_id=item["last_response_id"],
                            current_url=item["current_url"]):
        raise JobError("Status pekerjaan berubah. Muat ulang halaman.")
    try:
        browser_client.close(user_id, job_id)
    except browser_client.BrowserUnavailable:
        pass


def manual(user_id, job_id, call_id, actions):
    item = store.job(user_id, job_id)
    if not item or item["status"] != "PAUSED_USER":
        raise JobError("Pekerjaan sedang tidak menunggu tindakan kamu.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,96}", str(call_id or "")):
        raise JobError("Identitas tindakan tidak valid.")
    return browser_client.manual(user_id, job_id, call_id, actions)


def confirm(user_id, job_id):
    item = store.job(user_id, job_id)
    if not item or item["status"] != "PAUSED_CONFIRM":
        raise JobError("Tidak ada tindakan menunggu konfirmasi.")
    cp = _checkpoint(item)
    action = cp.get("blocked_action")
    if not action or not cp.get("pending_call"):
        raise JobError("Tindakan perlu diperiksa ulang.")
    key = f"confirm-{job_id}-{cp.get('step')}"
    observation = browser_client.manual(user_id, job_id, key, [action])
    cp["phase"] = "MODEL"
    cp.pop("blocked_action", None)
    cp.pop("blocked_index", None)
    if not store.update_job(user_id, job_id, "PAUSED_CONFIRM", "RUNNING", checkpoint=cp,
                            response_id=item["last_response_id"], current_url=observation["url"]):
        raise JobError("Status pekerjaan berubah. Muat ulang halaman.")
    _submit(user_id, job_id)
