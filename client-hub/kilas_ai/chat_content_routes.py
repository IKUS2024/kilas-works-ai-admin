"""Explicit synthetic content actions; mounted only on existing owner chat."""
import secrets
from flask import Response, abort, redirect, render_template, request, session, url_for
from .routes import ai_bp, automation_enabled
from . import chat_content as store, content_projects as projects


@ai_bp.before_request
def gate_chat_demo():
    if (request.endpoint or '').startswith('kilas_ai.chat_demo_') and (not store.enabled() or not automation_enabled()):
        abort(404)


def complete(owner, conversation_id, selected=None, version=None):
    if request.headers.get('Accept') == 'application/json':
        data = store.context(owner, conversation_id, selected, version)
        return {'panel_html': render_template('kilas_content/_chat_content_panel.html', chat_content=data, demo_key=secrets.token_hex(16))}
    return redirect(url_for('kilas_ai.agent_home', conversation=conversation_id, demo_recording=selected, demo_version=version), code=303)


@ai_bp.post('/agent/conversations/<int:conversation_id>/content-demo/<operation>', endpoint='chat_demo_mutate')
def mutate(conversation_id, operation):
    owner = session['user_id']
    selected = None
    try:
        store.conversation(owner, conversation_id)
        selected = request.form.get('recording_id', type=int)
        key = request.form.get('operation_key', '')
        if operation == 'recording':
            selected = store.create_recording(owner, conversation_id, request.form.get('label', ''), request.form.get('fixture', ''), key, request.form.get('consent') == 'yes')
        elif operation == 'transcript':
            store.edit_transcript(owner, conversation_id, selected, request.form.get('version', type=int), request.form.get('transcript', ''), key)
        elif operation == 'action':
            store.run_mock(owner, conversation_id, selected, request.form.get('version', type=int), request.form.get('kind', ''), request.form.get('language', ''), key, request.form.get('source_action', type=int), request.form.get('voice', ''), request.form.get('project_version', type=int))
        elif operation == 'cancel':
            store.cancel(owner, conversation_id, request.form.get('action_id', type=int))
        elif operation == 'project':
            ident = request.form.get('project_id', type=int)
            if request.form.get('project_id') and ident is None:
                raise ValueError('project_id_invalid')
            if not ident:
                ident = projects.create(owner, request.form.get('title', ''), request.form.get('brief', ''), key)
            store.attach_project(owner, conversation_id, ident)
        else:
            abort(404)
    except projects.Conflict:
        return 'Versi atau permintaan berubah. Muat ulang chat sebelum melanjutkan.', 409
    except LookupError:
        abort(404)
    except (ValueError, TypeError):
        abort(400, description='Periksa pilihan artefak, versi, persetujuan, dan bahasa demo.')
    return complete(owner, conversation_id, selected, request.form.get('version', type=int) if operation == 'action' else None)


@ai_bp.get('/agent/conversations/<int:conversation_id>/content-demo/recordings/<int:ident>/transcript/<int:version>.txt', endpoint='chat_demo_transcript_download')
def transcript_download(conversation_id, ident, version):
    try:
        chosen = store.transcript(session['user_id'], conversation_id, ident, version)
    except LookupError:
        abort(404)
    return Response(chosen['content'], mimetype='text/plain', headers={
        'Content-Disposition': f'attachment; filename="transkrip-sintetis-{ident}-v{version}.txt"',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
    })
