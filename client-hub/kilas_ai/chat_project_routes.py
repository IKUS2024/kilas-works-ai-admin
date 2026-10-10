"""Real project linkage and reviewed scripts, separately gated from chat demos."""
import secrets
from flask import Response, abort, redirect, render_template, request, session, url_for
from .routes import ai_bp, automation_enabled
from . import chat_projects as store, content_projects as projects


@ai_bp.before_request
def gate_chat_projects():
    if (request.endpoint or '').startswith('kilas_ai.chat_project_') and (not projects.enabled() or not automation_enabled()):
        abort(404)


def complete(owner, conversation_id, version=None):
    if request.headers.get('Accept') == 'application/json':
        data = store.context(owner, conversation_id, version)
        return {'panel_html': render_template('kilas_content/_chat_project_panel.html', chat_project=data, project_key=secrets.token_hex(16)),
                'script_version': data['script']['version'] if data['script'] else None}, 200, {'Cache-Control': 'private, no-store'}
    return redirect(url_for('kilas_ai.agent_home', conversation=conversation_id, chat_script_version=version), code=303)


@ai_bp.post('/agent/conversations/<int:conversation_id>/content-project/<operation>', endpoint='chat_project_mutate')
def mutate(conversation_id, operation):
    owner = session['user_id']
    version = None
    try:
        store.conversation(owner, conversation_id)
        if operation == 'choose':
            ident = request.form.get('project_id', type=int)
            if request.form.get('project_id') and ident is None:
                raise ValueError('project_id_invalid')
            store.choose(owner, conversation_id, ident, request.form.get('expected_project_id', type=int), request.form.get('operation_key', ''), request.form.get('title', ''), request.form.get('brief', ''))
        elif operation == 'script':
            version = store.save_script(owner, conversation_id, request.form.get('project_id', type=int), request.form.get('version', type=int), request.form.get('script', ''), request.form.get('operation_key', ''), request.form.get('reviewed') == 'yes')
        else:
            abort(404)
    except projects.Conflict:
        return 'Proyek atau naskah berubah. Muat ulang chat sebelum menyimpan.', 409
    except LookupError:
        abort(404)
    except (ValueError, TypeError):
        abort(400, description='Periksa proyek, versi dan persetujuan pemeriksaan naskah.')
    return complete(owner, conversation_id, version)


@ai_bp.get('/agent/conversations/<int:conversation_id>/content-project/<int:ident>/scripts/<int:version>.txt', endpoint='chat_project_download')
def download(conversation_id, ident, version):
    try:
        chosen = store.owned_script(session['user_id'], conversation_id, ident, version)
    except LookupError:
        abort(404)
    return Response(chosen['content'], mimetype='text/plain', headers={
        'Content-Disposition': f'attachment; filename="naskah-proyek-{ident}-v{version}.txt"',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
    })
