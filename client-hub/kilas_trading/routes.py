"""Owner-only authenticated paper workspace under the existing Service area."""
import uuid
from flask import Blueprint, abort, render_template, request, jsonify, redirect, url_for, flash
import security
from . import access, store, engine, analysis, observation

bp = Blueprint('kilas_trading', __name__, url_prefix='/products/services/trading')


@bp.before_request
@security.login_required
def authorize():
    if not access.is_pilot():
        abort(404)
    if request.content_length and request.content_length > (16384 if request.endpoint == 'kilas_trading.upload' else 8192):
        abort(413)


@bp.get('')
def home():
    try:
        state = store.snapshot(security.current_user()['id'])
        state['ai_analysis'] = analysis.availability()
        state['observation'] = observation.view(security.current_user()['id'])
        from . import bridge
        state['bridge'] = bridge.status(security.current_user()['id'])
    except PermissionError:
        abort(404)
    except engine.TradingError as exc:
        return render_template('kilas_trading.html', state=None, unavailable_reason=str(exc)), 503
    except Exception:
        return render_template('kilas_trading.html', state=None), 503
    bars = state['candles']
    low, high = min(b['low'] for b in bars), max(b['high'] for b in bars)
    state['chart'] = [dict(b, x=25+i*17, yo=20+(high-b['open'])*180/(high-low),
                         yc=20+(high-b['close'])*180/(high-low),
                         yh=20+(high-b['high'])*180/(high-low), yl=20+(high-b['low'])*180/(high-low)) for i,b in enumerate(bars)]
    return render_template('kilas_trading.html', state=state, new_key=lambda: uuid.uuid4().hex)


@bp.post('/observations/upload')
def upload():
    try:
        if request.mimetype != 'multipart/form-data' or set(request.files) != {'observation'} or len(request.files.getlist('observation')) != 1 or set(request.form) - {'csrf_token'}:
            raise engine.TradingError('Pilih satu file JSON market-only; field upload lain ditolak.')
        result = observation.ingest(security.current_user()['id'], request.files['observation'].stream.read(observation.MAX_FILE_BYTES + 1))
    except PermissionError:
        abort(404)
    except engine.TradingError as exc:
        result = dict(outcome='REJECTED', message=str(exc))
    except Exception:
        result = dict(outcome='ERROR', message='Snapshot belum dapat disimpan. Periksa tampilan sebelum mengulang; tidak ada AI/order.')
    if 'application/json' in request.headers.get('Accept', ''):
        return jsonify(result), 200 if result['outcome'] == 'OK' else 409 if result['outcome'] == 'REJECTED' else 503
    flash(result['message'], 'success' if result['outcome'] == 'OK' else 'error')
    return redirect(url_for('kilas_trading.home'), code=303)


# Register isolated read-only bridge routes on the same protected Trading host.
from . import bridge_routes  # noqa: E402,F401
from . import model_preflight_routes  # noqa: E402,F401


@bp.post('/<action>')
def action(action):
    data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    if not isinstance(data, dict) or any(not isinstance(v, (str, int)) for v in data.values()):
        abort(400)
    try:
        if observation.FIELDS.intersection(data):
            raise engine.TradingError('Observasi market tidak boleh dipakai sebagai input AI/order paper.')
        result = analysis.analyze(security.current_user()['id'], data) if action == 'analyze' else store.act(security.current_user()['id'], action, data)
    except PermissionError:
        abort(404)
    except engine.TradingError as exc:
        result = {'outcome': 'REJECTED', 'message': str(exc)}
    except Exception:
        result = {'outcome': 'ERROR', 'message': 'Penyimpanan simulasi belum tersedia. Muat ulang; jangan ulangi order dengan kunci baru bila hasil belum pasti.'}
    if request.is_json or 'application/json' in request.headers.get('Accept', ''):
        return jsonify(result), 200 if result['outcome'] in ('OK', 'NO_SIGNAL') else 409 if result['outcome'] == 'REJECTED' else 503
    flash(result['message'], 'success' if result['outcome'] in ('OK', 'NO_SIGNAL') else 'error')
    return redirect(url_for('kilas_trading.home'), code=303)
