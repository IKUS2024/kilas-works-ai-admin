"""Copilot uses the existing blueprint's authentication, tenant and CSRF gates."""
import json
from flask import abort, render_template, request, session, Response, stream_with_context, url_for
from .routes import ai_bp
from . import copilot


def page(ident=None):
    from .home_tasks import context
    selected = copilot.owned(session['user_id'], ident) if ident else None
    return render_template('kilas_ai/copilot.html', selected=selected, home_ai=context(session['user_id']),
                           turns=copilot.turns(session['user_id'], ident) if ident else [],
                           copilot_languages=copilot.LANGUAGES, provider_ready=copilot.configured())


@ai_bp.get('/copilot', endpoint='copilot_home')
def home():
    return page(), 200, {'Cache-Control': 'private, no-store'}


@ai_bp.get('/copilot/sessions/<int:ident>', endpoint='copilot_session')
def selected(ident):
    try:
        return page(ident), 200, {'Cache-Control': 'private, no-store'}
    except LookupError:
        abort(404)


@ai_bp.post('/copilot/sessions', endpoint='copilot_create')
def create():
    ident = copilot.create(session['user_id'])
    return {'id': ident, 'url': url_for('kilas_ai.copilot_session', ident=ident)}, 201, {'Cache-Control': 'no-store'}


@ai_bp.post('/copilot/sessions/<int:ident>/<operation_key>/cancel', endpoint='copilot_cancel')
def cancel(ident, operation_key):
    try:
        copilot.cancel(session['user_id'], ident, operation_key)
        return {'cancelled': True}, 200, {'Cache-Control': 'no-store'}
    except LookupError:
        abort(404)
    except copilot.CopilotError as error:
        return {'code': str(error)}, error.status


@ai_bp.post('/copilot/sessions/<int:ident>/<operation_key>/process', endpoint='copilot_process')
def process(ident, operation_key):
    owner = session['user_id']
    try:
        copilot.owned(owner, ident)
        copilot.key(operation_key)
        if request.form.get('consent') != 'yes':
            raise copilot.CopilotError('consent_required', 400)
        raw, silent = copilot.audio(request.files.get('audio'))
        target = request.form.get('target') if request.form.get('translate') == 'yes' else None
        style = request.form.get('style', 'santai')
        if style not in ('santai', 'profesional') or (target is not None and target not in copilot.LANGUAGES):
            raise copilot.CopilotError('invalid_options', 400)
    except LookupError:
        abort(404)
    except copilot.CopilotError as error:
        return {'code': str(error)}, error.status

    def events():
        try:
            yield ': Copilot\n\n'
            for event in copilot.process(owner, ident, operation_key, raw, silent, style, target):
                yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
        except copilot.CopilotError as error:
            yield 'data: ' + json.dumps({'type': 'error', 'code': str(error)}) + '\n\n'
    return Response(stream_with_context(events()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'private, no-store', 'X-Accel-Buffering': 'no'})
