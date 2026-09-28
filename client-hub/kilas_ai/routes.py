"""Kilas AI account routes; the flag and role gate apply to every private action."""
import os
import json
import re
from flask import Blueprint, Response, abort, redirect, render_template, request, send_file, session, stream_with_context, url_for
import io

import security

ai_bp = Blueprint("kilas_ai", __name__, url_prefix="/kilas-ai")


def enabled():
    return os.environ.get("KILAS_AI_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


@ai_bp.before_request
def require_access():
    if not enabled():
        abort(404)
    if request.endpoint == "kilas_ai.shared":
        return None
    if not session.get("user_id"):
        return redirect(url_for("auth.login_page"))
    user = security.current_user()
    if not user or user["role"] != "CLIENT_OWNER":
        abort(404)


@ai_bp.get("")
def home():
    from . import store
    return render_template("kilas_ai/home.html", threads=store.list_threads(session["user_id"]), selected=None, messages=[])


@ai_bp.get("/usage")
def usage_page():
    from . import billing, usage
    return render_template("kilas_ai/usage.html", state=usage.snapshot(session["user_id"]),
                           plans=usage.PLANS, invoices=billing.owner_invoices(session["user_id"]))


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
    rows = store.messages(session["user_id"], thread_id)
    for row in rows:
        try:
            row["metadata"] = json.loads(row["metadata_json"] or "{}")
        except ValueError:
            row["metadata"] = {}
    return render_template("kilas_ai/home.html", threads=store.list_threads(session["user_id"]),
                           selected=selected, messages=rows,
                           attachments=store.attachment_list(session["user_id"], thread_id))


@ai_bp.get("/threads/<int:thread_id>/attachments/<int:attachment_id>")
def attachment_download(thread_id, attachment_id):
    from . import store
    item = store.attachment(session["user_id"], thread_id, attachment_id)
    if not item:
        abort(404)
    inline = request.args.get("inline") == "1" and item["mime_type"].startswith("image/")
    response = send_file(io.BytesIO(bytes(item["content"])), mimetype=item["mime_type"],
                         as_attachment=not inline, download_name=item["filename"])
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


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


@ai_bp.post("/threads/<int:thread_id>/share")
def share(thread_id):
    from . import store
    token = store.share_thread(session["user_id"], thread_id)
    if not token:
        abort(404)
    return render_template("kilas_ai/share_ready.html",
                           share_url=url_for("kilas_ai.shared", token=token, _external=True),
                           thread_id=thread_id)


@ai_bp.post("/threads/<int:thread_id>/revoke")
def revoke(thread_id):
    from . import store
    if not store.revoke_share(session["user_id"], thread_id):
        abort(404)
    return redirect(url_for("kilas_ai.thread_page", thread_id=thread_id), code=303)


@ai_bp.get("/shared/<token>")
def shared(token):
    from . import store
    view = store.shared_messages(token)
    if not view:
        abort(404)
    response = Response(render_template("kilas_ai/shared.html", view=view), mimetype="text/html")
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, noarchive"
    return response


def _sse(event, payload):
    return "event: " + event + "\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


@ai_bp.post("/threads/<int:thread_id>/regenerate")
def regenerate(thread_id):
    from . import providers, store, usage as ai_usage
    user_id = session["user_id"]
    if not store.thread(user_id, thread_id):
        abort(404)
    body = request.get_json(silent=True) or {}
    key = str(body.get("operation_key") or "")
    mode = str(body.get("mode") or "SMART").upper()
    if mode not in store.MODES or not re.fullmatch(r"[a-zA-Z0-9_-]{16,96}", key):
        abort(400)
    if not store.last_user_message(user_id, thread_id):
        abort(400)
    context = store.context(user_id, thread_id)
    while context and context[-1]["role"] == "assistant":
        context.pop()
    try:
        plan, operations = ai_usage.reserve(user_id, thread_id, key, mode, "CHAT")
    except ai_usage.UsageLimit as error:
        return {"error": str(error)}, 429
    if plan is None:
        prior = store.operation(user_id, thread_id, key + ":assistant")
        if prior and prior["content"]:
            return Response(_sse("delta", {"text": prior["content"]}) + _sse("done", {"cached": True}),
                            mimetype="text/event-stream")
        return Response(_sse("busy", {"message": "Jawaban sedang dibuat."}), status=409,
                        mimetype="text/event-stream")
    message_id, created = store.reserve_regeneration(user_id, thread_id, mode, key)
    if not created:
        ai_usage.finish(user_id, key, operations, success=False)
        prior = store.operation(user_id, thread_id, key + ":assistant")
        if prior and prior["content"]:
            return Response(_sse("delta", {"text": prior["content"]}) + _sse("done", {"cached": True}),
                            mimetype="text/event-stream")
        return Response(_sse("busy", {"message": "Jawaban sedang dibuat."}), status=409,
                        mimetype="text/event-stream")

    def generate():
        pieces = []
        size = 0
        provider = model = None
        usage = {"input_tokens": 0, "output_tokens": 0}
        completed = False
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
            completed = bool(pieces)
            if not completed:
                yield _sse("error", {"message": "AI sedang tidak tersedia. Coba lagi."})
        except providers.ProviderError:
            yield _sse("error", {"message": "AI sedang tidak tersedia. Coba lagi."})
        finally:
            store.finish_regeneration(user_id, thread_id, message_id, "".join(pieces), provider, model,
                                      {"status": "complete" if completed else "interrupted" if pieces else "failed",
                                       "usage": usage, "regenerated": True})
            ai_usage.finish(user_id, key, operations, success=completed, provider=provider, model=model, usage=usage)
        if completed:
            yield _sse("done", {"finish_reason": "stop"})

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@ai_bp.post("/threads/<int:thread_id>/send")
def send(thread_id):
    from . import attachments, providers, store, usage as ai_usage
    user_id = session["user_id"]
    if not store.thread(user_id, thread_id):
        abort(404)
    body = (request.get_json(silent=True) or {}) if request.is_json else request.form
    files = request.files.getlist("attachments") if not request.is_json else []
    content = (body.get("content") or "").strip()
    mode = str(body.get("mode") or "SMART").upper()
    tool = str(body.get("tool") or "CHAT").upper()
    key = str(body.get("operation_key") or "")
    if not content and files:
        content = "Tolong jelaskan lampiran ini."
    if not content or len(content) > 12000 or mode not in store.MODES or tool not in ("CHAT", "WEB", "IMAGE_GENERATE", "IMAGE_EDIT") or not re.fullmatch(r"[a-zA-Z0-9_-]{16,96}", key):
        abort(400)
    try:
        prepared = attachments.prepare_many(files)
    except attachments.AttachmentError as error:
        return {"error": str(error)}, 400
    if tool == "IMAGE_EDIT" and not any(item["mime_type"].startswith("image/") for item in prepared):
        return {"error": "Tambahkan gambar yang ingin diedit."}, 400
    if tool == "WEB" and any(item["mime_type"].startswith("image/") for item in prepared):
        return {"error": "Gunakan mode chat untuk menganalisis gambar."}, 400
    prior = store.operation(user_id, thread_id, key)
    if prior:
        answer = store.operation(user_id, thread_id, key + ":assistant")
        if answer and answer["content"]:
            return Response(_sse("delta", {"text": answer["content"]}) + _sse("done", {"cached": True}),
                            mimetype="text/event-stream")
        return Response(_sse("busy", {"message": "Permintaan ini sedang diproses."}), status=409,
                        mimetype="text/event-stream")
    try:
        plan, operations = ai_usage.reserve(user_id, thread_id, key, mode, tool)
    except ai_usage.UsageLimit as error:
        return {"error": str(error)}, 429
    if plan is None:
        return Response(_sse("busy", {"message": "Permintaan ini sedang diproses."}), status=409,
                        mimetype="text/event-stream")
    message_id, created = store.append_user_once(user_id, thread_id, content, mode, key)
    if not created:
        ai_usage.finish(user_id, key, operations, success=False)
        prior = store.operation(user_id, thread_id, key + ":assistant")
        if prior:
            return Response(_sse("delta", {"text": prior["content"]}) + _sse("done", {"cached": True}),
                            mimetype="text/event-stream")
        return Response(_sse("busy", {"message": "Permintaan ini sedang diproses."}),
                        status=409, mimetype="text/event-stream")
    store.save_attachments(user_id, thread_id, message_id, prepared)
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
            if tool != "CHAT":
                from . import tools as ai_tools
                try:
                    if tool == "WEB":
                        result = ai_tools.web_search(context)
                        provider, model = "openai", result["model"]
                        usage.update(result["usage"])
                        text = result["text"]
                        store.append_assistant(user_id, thread_id, text, mode, provider, model, key,
                            {"status": "complete", "tool": "web", "citations": result["citations"],
                             "usage": result["usage"]})
                        finished = True
                        yield _sse("delta", {"text": text})
                        yield _sse("sources", {"citations": result["citations"]})
                        yield _sse("done", {"finish_reason": "stop"})
                        return
                    source = next((item for item in prepared if item["mime_type"].startswith("image/")), None)
                    result = ai_tools.image(content, source if tool == "IMAGE_EDIT" else None)
                    provider, model = "openai", result["model"]
                    usage.update({k: int(v or 0) for k, v in result["usage"].items() if k in usage})
                    label = "Gambar selesai diedit." if tool == "IMAGE_EDIT" else "Gambar selesai dibuat."
                    assistant_id = store.append_assistant(user_id, thread_id, label, mode, provider, model, key,
                        {"status": "complete", "tool": tool.lower(), "usage": result["usage"]})
                    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[result["mime"]]
                    image_id = store.save_attachments(user_id, thread_id, assistant_id, [{"filename": "kilas-ai-image." + extension,
                        "mime_type": result["mime"], "byte_size": len(result["raw"]), "content": result["raw"],
                        "extracted_text": None}])[0]
                    path = url_for("kilas_ai.attachment_download", thread_id=thread_id, attachment_id=image_id)
                    finished = True
                    yield _sse("delta", {"text": label})
                    yield _sse("image", {"url": path, "preview_url": path + "?inline=1"})
                    yield _sse("done", {"finish_reason": "stop"})
                    return
                except ai_tools.ToolUnavailable as error:
                    yield _sse("error", {"message": str(error)})
                    return
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
            ai_usage.finish(user_id, key, operations, success=finished, provider=provider, model=model, usage=usage)

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response
