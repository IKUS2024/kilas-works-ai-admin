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
    from . import attachments, store, usage
    current_plan = usage.effective_plan(session["user_id"])["plan"]
    return render_template("kilas_ai/home.html", threads=store.list_threads(session["user_id"]), selected=None,
                           messages=[], current_plan=current_plan, attachment_limits=attachments.limits(current_plan))


@ai_bp.get("/usage")
def usage_page():
    from . import billing, usage
    return render_template("kilas_ai/usage.html", state=usage.snapshot(session["user_id"]),
                           plans=usage.PLANS, invoices=billing.owner_invoices(session["user_id"]))


@ai_bp.post("/threads")
def new_thread():
    from . import routing, store
    body = (request.get_json(silent=True) or {}) if request.is_json else request.form
    if not request.is_json:
        return redirect(url_for("kilas_ai.home"), code=303)
    first_message = str(body.get("first_message") or "").strip()
    if not first_message or len(first_message) > 12000:
        abort(400)
    thread_id = store.create_thread(session["user_id"], routing.mode_for(first_message))
    return {"thread_id": thread_id, "url": url_for("kilas_ai.thread_page", thread_id=thread_id)}, 201


@ai_bp.get("/threads/<int:thread_id>")
def thread_page(thread_id):
    from . import attachments, store, usage
    selected = store.thread(session["user_id"], thread_id)
    if not selected:
        abort(404)
    rows = store.messages(session["user_id"], thread_id)
    for row in rows:
        try:
            row["metadata"] = json.loads(row["metadata_json"] or "{}")
        except ValueError:
            row["metadata"] = {}
    current_plan = usage.effective_plan(session["user_id"])["plan"]
    return render_template("kilas_ai/home.html", threads=store.list_threads(session["user_id"]),
                           selected=selected, messages=rows,
                           attachments=store.attachment_list(session["user_id"], thread_id),
                           current_plan=current_plan, attachment_limits=attachments.limits(current_plan))


@ai_bp.get("/threads/<int:thread_id>/attachments/<int:attachment_id>")
def attachment_download(thread_id, attachment_id):
    from . import store
    item = store.attachment(session["user_id"], thread_id, attachment_id)
    if not item:
        abort(404)
    inline = request.args.get("inline") == "1" and (item["mime_type"].startswith("image/") or
                                                     item["mime_type"] == "application/pdf")
    response = send_file(io.BytesIO(bytes(item["content"])), mimetype=item["mime_type"],
                         as_attachment=not inline, download_name=item["filename"])
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    if item["mime_type"] == "application/pdf":
        response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
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
    from . import providers, routing, store, usage as ai_usage
    user_id = session["user_id"]
    if not store.thread(user_id, thread_id):
        abort(404)
    body = request.get_json(silent=True) or {}
    key = str(body.get("operation_key") or "")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{16,96}", key):
        abort(400)
    last_user = store.last_user_message(user_id, thread_id)
    if not last_user:
        abort(400)
    mode = routing.mode_for(last_user["content"])
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
            yield _sse("activity", {"label": "Berpikir lebih dalam…" if mode in ("SMART", "EXPERT") else "Berpikir…"})
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
    from . import attachments, pdf as ai_pdf, providers, routing, store, usage as ai_usage
    user_id = session["user_id"]
    if not store.thread(user_id, thread_id):
        abort(404)
    body = (request.get_json(silent=True) or {}) if request.is_json else request.form
    files = request.files.getlist("attachments") if not request.is_json else []
    content = (body.get("content") or "").strip()
    key = str(body.get("operation_key") or "")
    if not content and files:
        content = "Tolong jelaskan lampiran ini."
    if not content or len(content) > 12000 or not re.fullmatch(r"[a-zA-Z0-9_-]{16,96}", key):
        abort(400)
    try:
        prepared = attachments.prepare_many(files, plan=ai_usage.effective_plan(user_id)["plan"])
    except attachments.AttachmentError as error:
        return {"error": str(error)}, 400
    mode = routing.mode_for(content, prepared)
    search = str(body.get("search") or "").lower() in ("1", "true", "on")
    previous_document = store.latest_generated_document(user_id, thread_id)
    tool = routing.tool_for(content, prepared, search=search,
                            pdf_request=ai_pdf.is_request(content, previous_document))
    if tool == "IMAGE_EDIT" and not any(item["mime_type"].startswith("image/") for item in prepared):
        return {"error": "Upload gambar terlebih dahulu untuk diedit."}, 400
    if tool == "WEB" and any(item["mime_type"].startswith("image/") for item in prepared):
        return {"error": "Matikan Search untuk menganalisis gambar yang diunggah."}, 400
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
            if tool == "PDF":
                yield _sse("activity", {"label": "Menyusun dokumen…"})
                document_context = ai_pdf.document_context(context, previous_document["extracted_text"] if previous_document else None)
                for event in providers.stream(mode, document_context):
                    if event["type"] == "provider":
                        provider, model = event["provider"], event["model"]
                    elif event["type"] == "delta":
                        pieces.append(event["text"])
                        size += len(event["text"])
                        if size > ai_pdf.MAX_MARKDOWN:
                            raise providers.ProviderError("document_too_long")
                    elif event["type"] == "usage":
                        usage.update({k: int(v or 0) for k, v in event.items() if k in usage})
                if not pieces:
                    raise providers.ProviderError("empty_document")
                yield _sse("activity", {"label": "Membuat PDF…"})
                logo = next((item["content"] for item in prepared if item["mime_type"].startswith("image/")
                             and "logo" in content.lower()), None)
                try:
                    result = ai_pdf.render("".join(pieces), title_hint=content[:80], logo=logo,
                                           cover=bool(re.search(r"\b(?:cover|sampul)(?:nya)?\b", content.lower())))
                except Exception:
                    raise providers.ProviderError("pdf_render_failed") from None
                label = "PDF siap: " + result["title"]
                assistant_id = store.append_assistant(user_id, thread_id, label, mode, provider, model, key,
                    {"status": "complete", "tool": "pdf", "usage": usage})
                file_id = store.save_attachments(user_id, thread_id, assistant_id, [result])[0]
                path = url_for("kilas_ai.attachment_download", thread_id=thread_id, attachment_id=file_id)
                finished = persisted = True
                yield _sse("delta", {"text": label})
                yield _sse("file", {"url": path, "filename": result["filename"],
                                    "mime_type": result["mime_type"], "byte_size": result["byte_size"]})
                yield _sse("done", {"finish_reason": "stop"})
                return
            if tool != "CHAT":
                from . import tools as ai_tools
                try:
                    if tool == "WEB":
                        yield _sse("activity", {"label": "Mencari di web…"})
                        result = ai_tools.web_search(context, mode=mode)
                        yield _sse("activity", {"label": "Memeriksa sumber…"})
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
                    yield _sse("activity", {"label": "Mengedit gambar…" if tool == "IMAGE_EDIT" else "Membuat gambar…"})
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
            yield _sse("activity", {"label": "Menganalisis gambar…" if any(item["mime_type"].startswith("image/") for item in prepared)
                          else "Membaca dokumen…" if any(item["extracted_text"] for item in prepared)
                          else "Berpikir lebih dalam…" if mode in ("SMART", "EXPERT") else "Berpikir…"})
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
            if pieces and not persisted and tool != "PDF":
                store.append_assistant(user_id, thread_id, "".join(pieces), mode, provider, model, key,
                                       {"status": "interrupted",
                                        "finish_reason": reason, "usage": usage})
            ai_usage.finish(user_id, key, operations, success=finished, provider=provider, model=model, usage=usage)

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response
