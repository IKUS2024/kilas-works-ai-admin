"""Kilas AI account routes; the flag and role gate apply to every private action."""
import os
import json
import re
from flask import Blueprint, Response, abort, redirect, render_template, request, send_file, session, stream_with_context, url_for
import io

import security
from . import free_test

ai_bp = Blueprint("kilas_ai", __name__, url_prefix="/kilas-ai")


def automation_enabled():
    return os.environ.get("KILAS_AI_AUTOMATION_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def enabled():
    return os.environ.get("KILAS_AI_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


@ai_bp.app_context_processor
def trial_context():
    return {'kilas_free_test_active':bool(session.get('user_id') and free_test.eligible(session['user_id']))}


@ai_bp.before_request
def require_access():
    if not enabled():
        abort(404)
    if request.endpoint in ("kilas_ai.shared", "kilas_ai.group_invitation"):
        return None
    if not session.get("user_id"):
        return redirect(url_for("auth.login_page"))
    user = security.current_user()
    if not user or session.get("role")!=user["role"] or (user["role"] != "CLIENT_OWNER" and not free_test.eligible(session["user_id"])):
        abort(404)


@ai_bp.get("")
def home(initial_brief=None):
    from . import model_policy, autonomous_runner
    from .home_tasks import context as home_context
    from .content_projects import draft
    content_draft = draft(session['user_id'])
    if initial_brief is None and not content_draft and automation_enabled() and autonomous_runner.enabled() and request.args.get('attachments') != '1' and not request.args.get('automation_result'):
        from .agent_routes import new_chat
        return new_chat()
    from . import attachments, store, usage
    current_plan = usage.effective_plan(session["user_id"])["plan"]
    from . import automation_store
    unread = automation_store.unread_count(session["user_id"]) if automation_enabled() else 0
    prefill = initial_brief if initial_brief is not None else content_draft['project']['brief'] if content_draft else ""
    if not content_draft and automation_enabled() and request.args.get("automation_result", "").isdigit():
        result = automation_store.result(session["user_id"], int(request.args["automation_result"]))
        if result and result["result_text"]:
            prefill = "Lanjutkan dari hasil Work berikut:\n\n" + result["result_text"][:4000]
    home_ui = home_context(session['user_id'])
    if request.args.get('attachments') == '1':home_ui['threads'] = store.list_threads(session['user_id'])
    return render_template("kilas_ai/home.html", threads=store.list_threads(session["user_id"]), selected=None,
                           messages=[], current_plan=current_plan, attachment_limits=attachments.limits(usage.attachment_plan(session["user_id"])),
                           automation_enabled=automation_enabled(), automation_unread=unread, prefill=prefill, content_draft=content_draft,
                           home_ai=home_ui)


@ai_bp.get("/usage")
def usage_page():
    from . import billing, topups, usage, capacity, audio_store
    import db
    previous = db.query_one('SELECT period_end FROM kilas_ai_subscriptions WHERE user_id=?', (session['user_id'],))
    expired = bool(previous and previous['period_end'] and usage._as_utc(previous['period_end']) <= usage._now())
    return render_template("kilas_ai/usage.html", subscription=usage.effective_plan(session["user_id"]), subscription_expired=expired,
                           capacity=capacity.summary(session["user_id"]), view='settings',
                           audio_balance=audio_store.balance(session["user_id"]), audio_packs=audio_store.PACKS,
                           invoices=billing.owner_invoices(session["user_id"]),
                           topup_orders=topups.owner_orders(session["user_id"]))


@ai_bp.get("/capacity")
def capacity_state():
    from . import capacity
    return capacity.summary(session['user_id']), 200, {'Cache-Control': 'no-store'}


@ai_bp.post("/threads")
def new_thread():
    from . import routing, store
    body = (request.get_json(silent=True) or {}) if request.is_json else request.form
    if not request.is_json:
        return redirect(url_for("kilas_ai.home"), code=303)
    first_message = str(body.get("first_message") or "").strip()
    if not first_message or len(first_message) > 12000:
        abort(400)
    from . import chat_models
    selected_model=body.get('selected_model')
    selected_image=body.get('selected_image_model')
    if selected_image:
        from . import image_models
        try:
            if not image_models.check(selected_image)['available']:raise chat_models.SelectionError('Model gambar belum tersedia.')
        except chat_models.SelectionError as error:return {'error':str(error)},400
    if selected_model:
        try:
            if not chat_models.check(selected_model)['available']:raise chat_models.SelectionError('Model belum tersedia.')
        except chat_models.SelectionError as error:return {'error':str(error)},400
    thread_id = store.create_thread(session["user_id"], routing.mode_for(first_message))
    if selected_model:chat_models.choose(session['user_id'],'thread',thread_id,selected_model)
    if selected_image:image_models.choose(session['user_id'],'thread',thread_id,selected_image)
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
    from . import automation_store
    from .home_tasks import context as home_context
    unread = automation_store.unread_count(session["user_id"]) if automation_enabled() else 0
    return render_template("kilas_ai/home.html", threads=store.list_threads(session["user_id"]),
                           selected=selected, messages=rows,
                           attachments=store.attachment_list(session["user_id"], thread_id),
                           current_plan=current_plan, attachment_limits=attachments.limits(usage.attachment_plan(session["user_id"])),
                           automation_enabled=automation_enabled(), automation_unread=unread,
                           home_ai=home_context(session['user_id']))


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
    if request.accept_mimetypes.best=="application/json":return {"id":thread_id,"title":store.thread(session["user_id"],thread_id)["title"]}
    return redirect(url_for("kilas_ai.thread_page", thread_id=thread_id), code=303)


@ai_bp.post("/threads/<int:thread_id>/delete")
def delete(thread_id):
    from . import store
    if not store.delete_thread(session["user_id"], thread_id):
        abort(404)
    if request.accept_mimetypes.best=="application/json":return {"deleted":True,"next_url":url_for("kilas_ai.home")}
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
    from . import model_policy, providers, routing, store, chat_quality, usage as ai_usage
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
    if routing.tool_for(last_user['content']) != 'CHAT' or routing.visual_result_requested(last_user['content']):
        return {'error':'Kirim permintaan baru untuk membuat ulang gambar, dokumen, atau pekerjaan.'},400
    mode = routing.mode_for(last_user["content"])
    context = store.context(user_id, thread_id)
    while context and context[-1]["role"] == "assistant":
        context.pop()
    from . import chat_models
    try:
        selected_model=chat_models.request_model(user_id,'thread',thread_id,body.get('selected_model'))
        if selected_model:
            context=store.context(user_id,thread_id,selected_model=selected_model)
            while context and context[-1]['role']=='assistant':context.pop()
            chat_models.bind(context,selected_model)
            chat_models.validate_messages(selected_model,context)
    except chat_models.SelectionError as error:return {'error':str(error)},400
    try:
        plan, operations = ai_usage.reserve(user_id, thread_id, key, mode, "CHAT", profile=model_policy.chat_profile(context))
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
        usage = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens":0, "cache_write_input_tokens":0}
        model_metadata = {}
        completed = False
        quality_source = None
        try:
            yield _sse("activity", {"label": providers.model_policy.chat_profile(context)["activity"]})
            quality_source = chat_quality.ChatQualityStream(user_id, thread_id, key, mode, operations, context)
            for event in quality_source:
                if event["type"] == "provider":
                    provider, model = event["provider"], event["model"]
                elif event["type"] == "model_metadata":
                    model_metadata.update(event)
                    yield _sse('model',event)
                elif event["type"] == "delta":
                    pieces.append(event["text"])
                    size += len(event["text"])
                    if size > (120000 if selected_model else 60000):
                        raise providers.ProviderError("response_too_long")
                    yield _sse("delta", {"text": event["text"]})
                elif event["type"] == "reset":
                    pieces.clear()
                    size = 0
                    yield _sse("reset", {})
                elif event["type"] == "activity":
                    yield _sse("activity", {"label": event["label"]})
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
                                       "usage": usage, "model_metadata":model_metadata, "regenerated": True,
                                       "reasoning_tier":providers.model_policy.chat_profile(context)['tier']})
            if selected_model:
                usage['selected_model']=selected_model
                if provider and not usage.get('input_tokens') and not usage.get('output_tokens'):usage['billing_unknown']=True
            if not quality_source or not quality_source.initial_finalized:
                ai_usage.finish(user_id, key, operations, success=completed, provider=provider, model=model, usage=usage)
        if completed:
            yield _sse("done", {"finish_reason": "stop"})

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@ai_bp.post("/threads/<int:thread_id>/voice-script")
def voice_script_send(thread_id):
    """Text-only script assistance through the existing authorized chat pipeline."""
    return send(thread_id, script_only=True)


@ai_bp.post("/threads/<int:thread_id>/send")
def send(thread_id, *, script_only=False):
    from . import model_policy, attachments, pdf as ai_pdf, providers, routing, store, chat_quality, usage as ai_usage
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
    if script_only:
        if files or len(content) > 4000:abort(400)
        script_mode = str(body.get("script_mode") or "generate")
        if script_mode not in {"generate", "tidy"}:abort(400)
        if script_mode == "tidy":
            instruction = "Rapikan naskah berikut: perbaiki ejaan dan alur tanpa mengubah maksud atau menambahkan fakta. "
        else:
            instruction = "Tulis atau rapikan naskah Voice Over sesuai arahan di bawah. "
        content = (instruction + 'Balas hanya naskah siap dibaca, maksimal 4000 karakter, tanpa pengantar. '
                   'Jangan membuat audio, gambar, dokumen atau menggunakan pencarian. '
                   'Jangan menambahkan fakta yang tidak diberikan.\n\nArahan pengguna:\n' + content)
    try:
        prepared = attachments.prepare_many(files, plan=ai_usage.attachment_plan(user_id))
    except attachments.AttachmentError as error:
        return {"error": str(error)}, 400
    mode = routing.mode_for(content, prepared)
    search = str(body.get("search") or "").lower() in ("1", "true", "on")
    previous_document = store.latest_generated_document(user_id, thread_id)
    prior_answer = ""
    for row in reversed(store.messages(user_id, thread_id, 6) or []):
        if row["role"] != "assistant":
            continue
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except ValueError:
            metadata = {}
        if metadata.get("status", "complete") == "complete" and metadata.get("tool") not in ("pdf", "image_generate", "image_edit"):
            prior_answer = row["content"]
        break
    prior_image = (store.recent_image(user_id, thread_id)
                   if not script_only and not any(item["mime_type"].startswith("image/") for item in prepared) and routing.may_edit_image(content)
                   else None)
    tool = 'CHAT' if script_only else routing.tool_for(content, prepared + ([prior_image] if prior_image else []), search=search,
                            pdf_request=ai_pdf.is_request(content, previous_document),
                            has_previous_content=bool(prior_answer or previous_document), previous_answer=prior_answer)
    previous_request=next((row['content'] for row in reversed(store.messages(user_id,thread_id,6) or []) if row['role']=='user'),'')
    previous_requests=[row['content'] for row in store.messages(user_id,thread_id,12) if row['role']=='user']
    lookup_topic=routing.lookup_topic(content,previous_requests)
    no_search_current = not script_only and routing.no_search_requested(content) and (
        routing.fresh_information(content,respect_no_search=False) or routing.fresh_followup(content,previous_request,respect_no_search=False))
    if not script_only and tool=='CHAT' and lookup_topic:
        tool='WEB'
    if tool == "IMAGE_EDIT" and not any(item["mime_type"].startswith("image/") for item in prepared) and not prior_image:
        return {"error": "Upload gambar terlebih dahulu untuk diedit."}, 400
    if tool == "WEB" and any(item["mime_type"].startswith("image/") for item in prepared):
        return {"error": "Pencarian web belum membaca gambar yang dilampirkan. Sebutkan nama atau rincian yang ingin diperiksa."}, 400
    prior = store.operation(user_id, thread_id, key)
    if prior:
        job_id=json.loads(prior['metadata_json'] or '{}').get('workspace_job_id')
        if job_id:
            from . import thread_projects
            thread_projects.owned(user_id,thread_id,job_id)
            return thread_projects.response(thread_id,job_id)
        answer = store.operation(user_id, thread_id, key + ":assistant")
        if answer and answer["content"]:
            return Response(_sse("delta", {"text": answer["content"]}) + _sse("done", {"cached": True}),
                            mimetype="text/event-stream")
        return Response(_sse("busy", {"message": "Permintaan ini sedang diproses."}), status=409,
                        mimetype="text/event-stream")
    from . import chat_models
    selected_model=None
    selected_image=None
    from . import image_models
    if not script_only:
        try:selected_image=image_models.requested(user_id,'thread',thread_id,body.get('selected_image_model'),required=tool in ('IMAGE_GENERATE','IMAGE_EDIT') and 'selected_image_model' in body)
        except chat_models.SelectionError as error:return {'error':str(error)},400
    preview=model_policy.ChatContext(store.context(user_id,thread_id)+[{'role':'user','content':attachments.prompt_content(content,prepared)}])
    try:
        if not script_only:
            selected_model=chat_models.request_model(user_id,'thread',thread_id,body.get('selected_model'))
            if selected_model:
                preview=model_policy.ChatContext(store.context(user_id,thread_id,selected_model=selected_model)+[{'role':'user','content':attachments.prompt_content(content,prepared)}])
                chat_models.bind(preview,selected_model)
                if tool not in ('IMAGE_GENERATE','IMAGE_EDIT'):chat_models.validate_messages(selected_model,preview)
    except chat_models.SelectionError as error:return {'error':str(error)},400
    from . import thread_projects
    if not script_only and not search and tool=='CHAT' and thread_projects.requested(content):
        try:
            job_id=thread_projects.enqueue(user_id,thread_id,content,key,mode,selected_model,prepared)
            return thread_projects.response(thread_id,job_id)
        except (ValueError,ai_usage.UsageLimit) as error:
            from ui_i18n import translate
            return {'error':translate(str(error))},429
    try:
        plan, operations = ai_usage.reserve(user_id, thread_id, key, mode, tool,
            profile={'image_model':selected_image} if selected_image and tool in ('IMAGE_GENERATE','IMAGE_EDIT') else model_policy.chat_profile(preview) if tool=='CHAT' or selected_model and tool in ('WEB','PDF') else None)
    except ai_usage.UsageLimit as error:
        from .chat_web import UNVERIFIED
        return {"error": str(error) + (' ' + UNVERIFIED if tool == 'WEB' else '')}, 429
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
    context = store.context(user_id, thread_id,selected_model=selected_model)
    if selected_model:chat_models.bind(context,selected_model)

    def generate():
        pieces = []
        size = 0
        provider = model = None
        usage = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens":0, "cache_write_input_tokens":0}
        model_metadata = {}
        finished = False
        quality_source = None
        persisted = False
        reason = None
        try:
            if no_search_current:
                from .chat_web import NO_SEARCH
                store.append_assistant(user_id,thread_id,NO_SEARCH,mode,None,None,key,{'status':'complete','tool':'chat'})
                finished = persisted = True
                yield _sse('delta',{'text':NO_SEARCH})
                yield _sse('done',{'finish_reason':'stop'})
                return
            if tool in ("WORK", "CLARIFY", "FILE"):
                if tool == "WORK":
                    yield _sse("activity", {"label": "Menyiapkan pekerjaan…"})
                    if automation_enabled():
                        path = url_for("kilas_ai.agent_home", message=content[:1200])
                        text = "Pekerjaan ini perlu berjalan di background. [Lanjutkan di Work](" + path + ") untuk memulainya dan mengikuti kemajuannya."
                    else:
                        text = "Work belum tersedia sekarang. Pekerjaan belum dimulai."
                elif tool == "FILE":
                    text = "Format file itu belum tersedia. Saya bisa menyiapkan isi dokumennya, atau membuat PDF jika kamu meminta PDF."
                else:
                    text = "Apa yang ingin kamu buat atau ubah?"
                store.append_assistant(user_id, thread_id, text, mode, None, None, key,
                    {"status": "complete", "tool": tool.lower()})
                finished = persisted = True
                yield _sse("delta", {"text": text})
                yield _sse("done", {"finish_reason": "stop"})
                return
            if tool == "PDF":
                yield _sse("activity", {"label": "Menyusun dokumen…"})
                document_context = ai_pdf.document_context(context, previous_document["extracted_text"] if previous_document else None)
                if selected_model:
                    document_context=chat_models.bind(model_policy.ChatContext(document_context),selected_model)
                document_finish=None
                for event in providers.stream(mode, document_context):
                    if event["type"] == "provider":
                        provider, model = event["provider"], event["model"]
                    elif event["type"] == "model_metadata":
                        model_metadata.update(event)
                        yield _sse('model',event)
                    elif event["type"] == "delta":
                        pieces.append(event["text"])
                        size += len(event["text"])
                        if size > ai_pdf.MAX_MARKDOWN:
                            raise providers.ProviderError("document_too_long")
                    elif event["type"] == "usage":
                        usage.update({k: int(v or 0) for k, v in event.items() if k in usage})
                    elif event["type"]=="finish":document_finish=event["reason"]
                if selected_model and document_finish!="stop":raise providers.ProviderError("incomplete_document")
                if not pieces:
                    raise providers.ProviderError("empty_document")
                if not routing.response_safe(content, "".join(pieces)):
                    raise providers.ProviderError("invalid_document_markup")
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
                    {"status": "complete", "tool": "pdf", "usage": usage,"model_metadata":model_metadata})
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
                        research = ai_tools.research_requested(context)
                        yield _sse("activity", {"label": "Mencari sumber terbaru…"})
                        result = None
                        for update in ai_tools.web_search_steps(context, mode=mode, plan=plan,
                                max_calls=ai_usage.web_call_budget(user_id, plan) if research else 1,verify_currency=True,minimal_query=True):
                            if "activity" in update:
                                yield _sse("activity", {"label": update["activity"]})
                            else:
                                result = update["result"]
                        yield _sse("activity", {"label": "Memeriksa sumber…"})
                        from . import chat_model_tools
                        provider, model = "openai", result["model"]
                        usage.update(result["usage"])
                        result=chat_model_tools.compose(result,context)
                        provider,model=result.get('provider','openai'),result['model']
                        model_metadata.update(result.get('model_metadata') or {})
                        if model_metadata:yield _sse('model',model_metadata)
                        usage.update(result['usage'])
                        text = result["text"]
                        store.append_assistant(user_id, thread_id, text, mode, provider, model, key,
                            {"status": "complete", "tool": "web", "citations": result["citations"],
                             "search_calls": result.get("search_calls", 1), "usage": result["usage"], "model_metadata":model_metadata})
                        finished = True
                        yield _sse("delta", {"text": text})
                        yield _sse("sources", {"citations": result["citations"]})
                        yield _sse("done", {"finish_reason": "stop"})
                        return
                    source = next((item for item in prepared if item["mime_type"].startswith("image/")), None) or prior_image
                    yield _sse("activity", {"label": "Mengedit gambar…" if tool == "IMAGE_EDIT" else "Membuat gambar…"})
                    prompt = routing.enhance_image_prompt(routing.image_prompt(content, prior_answer), content) if tool == "IMAGE_GENERATE" else content
                    result = ai_tools.image(prompt, source if tool == "IMAGE_EDIT" else None,**({'selected_model':selected_image} if selected_image else {}))
                    if result.get('model_provenance'):yield _sse('model',result['model_provenance'])
                    provider, model = result.get("provider","openai"), result["model"]
                    if selected_image:usage.update(result["usage"])
                    else:usage.update({k: int(v or 0) for k, v in result["usage"].items() if k in usage})
                    label = "Gambar selesai diedit." if tool == "IMAGE_EDIT" else "Gambar selesai dibuat."
                    assistant_id = store.append_assistant(user_id, thread_id, label, mode, provider, model, key,
                        {"status": "complete", "tool": tool.lower(), "usage": result["usage"], "model_metadata":result.get("model_provenance")})
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
                    if error.model:
                        provider, model = (image_models.spec(selected_image)['provider'] if selected_image and error.model==selected_image else chat_models.spec(selected_model)['provider'] if selected_model and error.model==selected_model else 'openai'), error.model
                        usage.update(error.usage)
                    from .chat_web import search_failure_message
                    if tool == 'WEB': ai_tools.log_search_failure(error)
                    message="Gambar belum dapat dibuat sekarang. Coba lagi sebentar." if tool in ("IMAGE_GENERATE", "IMAGE_EDIT") else search_failure_message(error)
                    if tool=='WEB':
                        store.append_assistant(user_id,thread_id,message,mode,provider,model,key,
                            {'status':'failed','tool':'web','failure_code':getattr(error,'code','search_unavailable'),'usage':usage,'model_metadata':model_metadata})
                        persisted=True
                    yield _sse("error", {"message":message})
                    return
            yield _sse("activity", {"label": "Menganalisis gambar…" if any(item["mime_type"].startswith("image/") for item in prepared)
                          else "Membaca dokumen…" if any(item["extracted_text"] for item in prepared)
                          else providers.model_policy.chat_profile(context)["activity"]})
            quality_source = chat_quality.ChatQualityStream(user_id, thread_id, key, mode, operations, context)
            for event in quality_source:
                if event["type"] == "provider":
                    provider, model = event["provider"], event["model"]
                elif event["type"] == "model_metadata":
                    model_metadata.update(event)
                    yield _sse('model',event)
                elif event["type"] == "delta":
                    pieces.append(event["text"])
                    size += len(event["text"])
                    if size > (120000 if selected_model else 60000):
                        raise providers.ProviderError("response_too_long")
                    if not routing.visual_result_requested(content):
                        yield _sse("delta", {"text": event["text"]})
                elif event["type"] == "reset":
                    pieces.clear()
                    size = 0
                    yield _sse("reset", {})
                elif event["type"] == "activity":
                    yield _sse("activity", {"label": event["label"]})
                elif event["type"] == "usage":
                    usage.update({k: int(v or 0) for k, v in event.items() if k in usage})
                elif event["type"] == "finish":
                    reason = event["reason"]
            if pieces:
                if not routing.response_safe(content, "".join(pieces)):
                    raise providers.ProviderError("invalid_visual_markup")
                if routing.visual_result_requested(content):
                    yield _sse("delta", {"text": "".join(pieces)})
                finished = True
                store.append_assistant(user_id, thread_id, "".join(pieces), mode, provider, model, key,
                                       {"status": "complete", "finish_reason": reason, "usage": usage, "model_metadata":model_metadata,
                                        "reasoning_tier":providers.model_policy.chat_profile(context)['tier']})
                persisted = True
                yield _sse("done", {"finish_reason": reason or "stop"})
            else:
                yield _sse("error", {"message": "AI sedang tidak tersedia. Coba lagi."})
        except providers.ProviderError:
            yield _sse("error", {"message": "AI sedang tidak tersedia. Coba lagi."})
        finally:
            if pieces and not persisted and tool != "PDF" and routing.response_safe(content, "".join(pieces)):
                store.append_assistant(user_id, thread_id, "".join(pieces), mode, provider, model, key,
                                       {"status": "interrupted",
                                        "finish_reason": reason, "usage": usage})
            if selected_model:
                usage['selected_model']=selected_model
                if provider and not usage.get('input_tokens') and not usage.get('output_tokens'):usage['billing_unknown']=True
            if not quality_source or not quality_source.initial_finalized:
                ai_usage.finish(user_id, key, operations, success=finished, provider=provider, model=model, usage=usage)

    response = Response(stream_with_context(generate()), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response

# Registers only Chat selection; existing product authorization/CSRF still wraps it.
from . import chat_model_routes
from . import thread_projects
thread_projects.register(ai_bp)
