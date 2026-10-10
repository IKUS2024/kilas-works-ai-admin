"""Content-only project hub on the existing authenticated AI blueprint."""
import secrets
from flask import abort, redirect, render_template, request, session, url_for
from .routes import ai_bp, automation_enabled
from . import content_projects as projects


@ai_bp.before_request
def content_gate():
    if (request.endpoint or '').startswith('kilas_ai.content_') and not projects.enabled():
        abort(404)


def owned(ident):
    item = projects.get(session['user_id'], ident)
    if not item:
        abort(404)
    return item


@ai_bp.errorhandler(projects.Conflict)
def conflict(error):
    return 'Naskah berubah di tab lain. Muat ulang proyek sebelum menyimpan.', 409


@ai_bp.get('/content-projects', endpoint='content_home')
def home():
    return render_template('kilas_content/home.html', projects=projects.listing(session['user_id']), operation_key=secrets.token_hex(16))


@ai_bp.post('/content-projects', endpoint='content_create')
def create():
    try:
        ident = projects.create(session['user_id'], request.form.get('title', ''), request.form.get('brief', ''), request.form.get('operation_key', ''))
    except projects.Conflict:
        raise
    except ValueError:
        abort(400)
    return redirect(url_for('kilas_ai.content_project', ident=ident), code=303)


@ai_bp.get('/content-projects/<int:ident>', endpoint='content_project')
def detail(ident):
    project = owned(ident)
    owner = session['user_id']
    return render_template('kilas_content/project.html', chat_endpoint='kilas_ai.agent_home' if automation_enabled() else 'kilas_ai.home', project=project, active_script=projects.script(owner, ident, project['script_version']), links=projects.links(owner, ident), choices=projects.choices(owner), operation_key=secrets.token_hex(16))


@ai_bp.post('/content-projects/<int:ident>/script', endpoint='content_script')
def save_script(ident):
    owned(ident)
    try:
        projects.save_script(session['user_id'], ident, int(request.form['version']), request.form.get('script', ''), request.form.get('operation_key', ''), request.form.get('source', 'manual'), request.form.get('source_id', type=int))
    except LookupError:
        abort(404)
    except projects.Conflict:
        raise
    except (KeyError, ValueError, TypeError):
        abort(400)
    return redirect(url_for('kilas_ai.content_project', ident=ident), code=303)


@ai_bp.post('/content-projects/<int:ident>/links', endpoint='content_link')
def link(ident):
    owned(ident)
    try:
        kind, target = request.form['target'].split(':', 1)
        projects.link(session['user_id'], ident, kind, int(target), int(request.form['script_version']))
    except LookupError:
        abort(404)
    except (KeyError, ValueError, TypeError):
        abort(400)
    return redirect(url_for('kilas_ai.content_project', ident=ident), code=303)
