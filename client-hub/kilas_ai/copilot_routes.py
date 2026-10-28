"""Copilot uses the existing blueprint's authentication, tenant and CSRF gates."""
import json
from queue import Queue, Empty, Full
from threading import BoundedSemaphore, Event, Thread
from flask import abort, current_app, render_template, request, session, Response, stream_with_context, url_for
from .routes import ai_bp
from . import copilot
from ui_i18n import translate as ui_t, translate_ui_message

_slots = BoundedSemaphore(2)


def page(ident=None):
    from .home_tasks import context
    selected = copilot.owned(session['user_id'], ident) if ident else None
    names = copilot.translator_languages.localized_names()
    names['id'] = ui_t('Bahasa Indonesia')
    return render_template('kilas_ai/copilot.html', selected=selected, home_ai=context(session['user_id']),
                           turns=copilot.turns(session['user_id'], ident) if ident else [],
                           copilot_languages=copilot.LANGUAGES, copilot_language_names=names, provider_ready=copilot.configured())


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

    if not _slots.acquire(blocking=False):
        return {'code': 'server_busy'}, 503
    app = current_app._get_current_object()
    queue, stopped, done = Queue(maxsize=32), Event(), Event()

    def publish(event):
        while not stopped.is_set():
            try:
                queue.put(event, timeout=.2)
                return
            except Full:
                continue

    def run():
        # Provider waits must not prevent the WSGI writer from detecting a
        # disconnected browser on Render's existing single synchronous worker.
        with app.app_context():
            factory = copilot.process(owner, ident, operation_key, raw, silent, style, target)
            try:
                for event in factory:
                    if stopped.is_set():
                        break
                    publish(event)
            except copilot.CopilotError as error:
                publish({'type': 'error', 'code': str(error)})
            except Exception:
                publish({'type': 'error', 'code': 'provider_failed'})
            finally:
                try:
                    factory.close()
                finally:
                    done.set()
                    _slots.release()

    def events():
        terminal = False
        try:
            Thread(target=run, name='copilot-turn', daemon=True).start()
            yield ': Copilot\n\n'
            while not done.is_set() or not queue.empty():
                try:
                    event = queue.get(timeout=.5)
                except Empty:
                    yield ': heartbeat\n\n'
                    continue
                if event['type'] in ('complete', 'error'):
                    terminal = True
                if event['type'] == 'status':
                    # Request-scoped UI projection only. Provider deltas, source,
                    # translations and user-derived titles stay byte-for-byte.
                    event = {**event, 'text': translate_ui_message(event['text'])}
                yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
        finally:
            stopped.set()
            if not terminal:
                # Does not depend on a cancel POST being served concurrently.
                # A tombstone also fences a worker that has not claimed yet.
                try:
                    copilot.cancel(owner, ident, operation_key)
                except (LookupError, copilot.CopilotError):
                    pass  # Deleted session or an already-terminal operation.
    return Response(stream_with_context(events()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'private, no-store', 'X-Accel-Buffering': 'no'})
