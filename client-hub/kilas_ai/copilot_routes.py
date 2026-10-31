"""Copilot uses the existing blueprint's authentication, tenant and CSRF gates."""
import json
import hashlib
from threading import BoundedSemaphore
from flask import abort, current_app, render_template, request, session, url_for
from .routes import ai_bp
from . import copilot, copilot_jobs
from ui_i18n import translate as ui_t, translate_ui_message

_slots = BoundedSemaphore(2)


def page(ident=None):
    from .home_tasks import context
    selected = copilot.owned(session['user_id'], ident) if ident else None
    names = copilot.translator_languages.localized_names()
    names['id'] = ui_t('Bahasa Indonesia')
    return render_template('kilas_ai/copilot.html', selected=selected, home_ai=context(session['user_id']),
                           turns=copilot.turns(session['user_id'], ident) if ident else [],
                           copilot_languages=copilot.LANGUAGES, copilot_language_names=names, provider_ready=copilot.configured(),
                           copilot_preferences=copilot.preferences(session['user_id'], ident) if ident else {'style':'santai','target':'id','translate':False})


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
        copilot_jobs.cancel(session['user_id'], ident, operation_key)
        result={'cancelled':True}
        row=copilot.operation(session['user_id'],ident,operation_key)
        meta=json.loads(row['metadata_json'] or '{}') if row else {}
        original=meta.get('fingerprint','').split(':',1)[1] if str(meta.get('fingerprint','')).startswith('translation:') else operation_key
        try:result['turn']=copilot.saved_turn(session['user_id'],ident,original)
        except LookupError:pass
        return result,200,{'Cache-Control':'no-store'}
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
        if not copilot.configured():raise copilot.CopilotError('provider_unavailable',503)
    except LookupError:
        abort(404)
    except copilot.CopilotError as error:
        return {'code': str(error)}, error.status

    if not _slots.acquire(blocking=False):
        return {'code': 'server_busy'}, 503
    app = current_app._get_current_object()
    claimed=False
    try:
        copilot.claim(owner, ident, operation_key, hashlib.sha256(raw).hexdigest());claimed=True
        preferred=request.form.get('target','id')
        copilot.preferences(owner,ident,{'style':style,'target':preferred if preferred in copilot.LANGUAGES else 'id','translate':target is not None})
        copilot_jobs.start(app,owner,ident,operation_key,
                           lambda cancelled:copilot.process(owner,ident,operation_key,raw,silent,style,target,claimed=True,cancelled=cancelled),_slots.release)
        return {'status_url':url_for('kilas_ai.copilot_status',ident=ident,operation_key=operation_key)},202,{'Cache-Control':'no-store'}
    except (copilot.CopilotError,LookupError) as error:
        try:
            if claimed:copilot.update(owner,ident,operation_key,'failed')
        finally:_slots.release()
        if isinstance(error,LookupError):abort(404)
        return {'code':str(error)},error.status
    except Exception:
        try:
            if claimed:copilot.update(owner,ident,operation_key,'failed')
        finally:_slots.release()
        return {'code':'provider_failed'},503


@ai_bp.get('/copilot/sessions/<int:ident>/<operation_key>/status', endpoint='copilot_status')
def status(ident, operation_key):
    try:
        row=copilot.operation(session['user_id'],ident,operation_key)
        if not row:abort(404)
        view=copilot_jobs.snapshot(session['user_id'],ident,operation_key)
        if view is None:
            meta=json.loads(row['metadata_json'] or '{}')
            if meta.get('status') in ('complete','primary_complete') and meta.get('copilot_turn'):
                view={'state':'complete','result':copilot.finish_event(session['user_id'],ident,operation_key)}
            elif meta.get('status')=='complete' and str(meta.get('fingerprint','')).startswith('translation:'):
                view={'state':'complete','result':copilot.finish_event(session['user_id'],ident,meta['fingerprint'].split(':',1)[1])}
            else:
                # No cross-process/raw-audio replay. Interrupted jobs require a
                # fresh user action; valid primary data remains in owned history.
                view={'state':'failed','code':'interrupted_operation'}
        if 'status_text' in view:view['status_text']=translate_ui_message(view['status_text'])
        if 'statuses' in view:view['statuses']=[translate_ui_message(text) for text in view['statuses']]
        return view,200,{'Cache-Control':'private, no-store'}
    except (LookupError,copilot.CopilotError):abort(404)


@ai_bp.post('/copilot/sessions/<int:ident>/preferences', endpoint='copilot_preferences')
def preferences(ident):
    try:
        copilot.preferences(session['user_id'],ident,{'style':request.form.get('style'),'target':request.form.get('target'),'translate':request.form.get('translate')=='yes'})
        return {'saved':True},200,{'Cache-Control':'no-store'}
    except LookupError:abort(404)
    except copilot.CopilotError as error:return {'code':str(error)},error.status


@ai_bp.post('/copilot/sessions/<int:ident>/<original>/translation/<operation_key>', endpoint='copilot_translation_recovery')
def translation_recovery(ident,original,operation_key):
    owner=session['user_id']
    try:
        turn=copilot.saved_turn(owner,ident,original)
        copilot.key(operation_key)
        if not turn.get('target') or turn.get('reply_translation') and not turn.get('translation_error'):raise copilot.CopilotError('invalid_options',400)
        if not copilot.configured():raise copilot.CopilotError('provider_unavailable',503)
    except LookupError:abort(404)
    except copilot.CopilotError as error:return {'code':str(error)},error.status
    if not _slots.acquire(blocking=False):return {'code':'server_busy'},503
    claimed=False
    try:
        copilot.claim(owner,ident,operation_key,'translation:'+original,recovery=True);claimed=True
        copilot_jobs.start(current_app._get_current_object(),owner,ident,operation_key,
                           lambda cancelled:copilot.recovery(owner,ident,original,operation_key,claimed=True,cancelled=cancelled),_slots.release)
        return {'status_url':url_for('kilas_ai.copilot_status',ident=ident,operation_key=operation_key)},202,{'Cache-Control':'no-store'}
    except (copilot.CopilotError,LookupError) as error:
        try:
            if claimed:copilot.update(owner,ident,operation_key,'failed')
        finally:_slots.release()
        if isinstance(error,LookupError):abort(404)
        return {'code':str(error)},error.status
    except Exception:
        try:
            if claimed:copilot.update(owner,ident,operation_key,'failed')
        finally:_slots.release()
        return {'code':'provider_failed'},503
