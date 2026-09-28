"""Kilas AI account routes; the flag and role gate apply to every private action."""
import os
import json
import re
from flask import Blueprint, Response, abort, redirect, render_template, request, session, stream_with_context, url_for

import security

ai_bp = Blueprint("kilas_ai", __name__, url_prefix="/kilas-ai")


def enabled():
    return os.environ.get("KILAS_AI_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


@ai_bp.before_request
def require_access():
    if not enabled():
        abort(404)
    if not session.get("user_id"):
        return redirect(url_for("auth.login_page"))
    user = security.current_user()
    if not user or user["role"] != "CLIENT_OWNER":
        abort(404)


@ai_bp.get("")
def home():
    from . import store
    return render_template("kilas_ai/home.html", threads=store.list_threads(session["user_id"]), selected=None, messages=[])


@ai_bp.post("/threads")
def new_thread():
    from . import store
    mode = (request.form.get("mode") or "SMART").upper()
    if mode not in store.MODES:
        abort(400)
    thread_id = store.create_thread(session["user_id"], mode)
    return redirect(url_for("kilas_ai.thread_page", thread_id=thread_id), code=303)


@ai_bp.get("/threads/<int:thread_id>")
def thread_page(thread_id):
    from . import store
    selected = store.thread(session["user_id"], thread_id)
    if not selected:
        abort(404)
    return render_template("kilas_ai/home.html", threads=store.list_threads(session["user_id"]),
                           selected=selected, messages=store.messages(session["user_id"], thread_id))


@ai_bp.post("/threads/<int:thread_id>/rename")
def rename(thread_id):
    from . import store
    try:
        changed = store.rename_thread(session["user_id"], thread_id, request.form.get("title"))
    except ValueError:
        abort(400)
    if not changed:
        abort(404)
    return redirect(url_for("kilas_ai.thread_page", thread_id=thread_id), code=303)


@ai_bp.post("/threads/<int:thread_id>/delete")
def delete(thread_id):
    from . import store
    if not store.delete_thread(session["user_id"], thread_id):
        abort(404)
    return redirect(url_for("kilas_ai.home"), code=303)


def _sse(event, payload):
    return "event: " + event + "\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


@ai_bp.post("/threads/<int:thread_id>/send")
def send(thread_id):
    from . import providers, store
    user_id = session["user_id"]
    if not store.thread(user_id, thread_id):
        abort(404)
    body = request.get_json(silent=True) or {}
    content = (body.get("content") or "").strip()
    mode = str(body.get("mode") or "SMART").upper()
    key = str(body.get("operation_key") or "")
    if not content or len(content) > 12000 or mode not in store.MODES or not re.fullmatch(r"[a-zA-Z0-9_-]{16,96}", key):
        abort(400)
    _, created = store.append_user_once(user_id, thread_id, content, mode, key)
    if not created:
        prior = store.operation(user_id, thread_id, key + ":assistant")
        if prior:
            return Response(_sse("delta", {"text": prior["content"]}) + _sse("done", {"cached": True}),
                            mimetype="text/event-stream")
        return Response(_sse("busy", {"message": "Permintaan ini sedang diproses."}),
                        status=409, mimetype="text/event-stream")
    context = store.context(user_id, thread_id)

    def generate():
        pieces = []
        size = 0
        provider = model = None
        usage = {"input_tokens": 0, "output_tokens": 0}
        finished = False
        persisted = False
        reason = None
        try:
            for event in providers.stream(mode, context):
                if event["type"] == "provider":
                    provider, model = event["provider"], event["model"]
                elif event["type"] == "delta":
                    pieces.append(event["text"])
                    size += len(event["text"])
                    if size > 30000:
                        raise providers.ProviderError("response_too_long")
                    yield _sse("delta", {"text": event["text"]})
                elif event["type"] == "usage":
                    usage.update({k: int(v or 0) for k, v in event.items() if k in usage})
                elif event["type"] == "finish":
                    reason = event["reason"]
            if pieces:
                finished = True
                store.append_assistant(user_id, thread_id, "".join(pieces), mode, provider, model, key,
                                       {"status": "complete", "finish_reason": reason, "usage": usage})
                persisted = True
                yield _sse("done", {"finish_reason": reason or "stop"})
            else:
                yield _sse("error", {"message": "AI sedang tidak tersedia. Coba lagi."})
        except providers.ProviderError:
            yield _sse("error", {"message": "AI sedang tidak tersedia. Coba lagi."})
        finally:
            if pieces and not persisted:
                store.append_assistant(user_id, thread_id, "".join(pieces), mode, provider, model, key,
                                       {"status": "interrupted",
                                        "finish_reason": reason, "usage": usage})

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response
