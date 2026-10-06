"""Owner-only authenticated paper workspace under the existing Service area."""
import uuid
from flask import Blueprint, abort, render_template, request, jsonify, redirect, url_for, flash
import security
from . import access, store, engine

bp = Blueprint('kilas_trading', __name__, url_prefix='/products/services/trading')


@bp.before_request
@security.login_required
def authorize():
    if not access.is_pilot():
        abort(404)
    if request.content_length and request.content_length > 8192:
        abort(413)


@bp.get('')
def home():
    try:
        state = store.snapshot(security.current_user()['id'])
    except PermissionError:
        abort(404)
    except Exception:
        return render_template('kilas_trading.html', state=None), 503
    bars = state['candles']
    low, high = min(b['low'] for b in bars), max(b['high'] for b in bars)
    state['chart'] = [dict(b, x=25+i*17, yo=20+(high-b['open'])*180/(high-low),
                         yc=20+(high-b['close'])*180/(high-low),
                         yh=20+(high-b['high'])*180/(high-low), yl=20+(high-b['low'])*180/(high-low)) for i,b in enumerate(bars)]
    return render_template('kilas_trading.html', state=state, new_key=lambda: uuid.uuid4().hex)


@bp.post('/<action>')
def action(action):
    data = request.get_json(silent=True) if request.is_json else request.form.to_dict()
    if not isinstance(data, dict) or any(not isinstance(v, (str, int)) for v in data.values()):
        abort(400)
    try:
        result = store.act(security.current_user()['id'], action, data)
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
