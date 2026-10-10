"""Exact worker endpoint isolation; owner routes keep session and global CSRF."""
from flask import request
import os
import security
from werkzeug.exceptions import RequestEntityTooLarge
from . import control, bridge, btc_analysis
from .bridge_routes import response, limited
from .routes import bp

@bp.record_once
def install(state):state.app.before_request_funcs.setdefault(None,[]).insert(0,transport)

def action(function):
    try:return response(function())
    except bridge.Rejected as exc:return response({'outcome':exc.code},exc.status)
    except RequestEntityTooLarge:return response({'outcome':'PAYLOAD_TOO_LARGE'},413)
    except Exception:return response({'outcome':'CONTROL_UNAVAILABLE'},503)

def transport():
    if request.endpoint not in ('kilas_trading.control_sync','kilas_trading.btc_analysis_worker','kilas_trading.btc_evidence_worker'):return None
    def perform():
        bridge.require(control.enabled(),'DISABLED',404)
        if request.endpoint in ('kilas_trading.btc_analysis_worker','kilas_trading.btc_evidence_worker'):
            bridge.require(btc_analysis.enabled(),'BTC_ANALYSIS_DISABLED',404)
        if request.endpoint=='kilas_trading.btc_evidence_worker':
            bridge.require(os.environ.get('KILAS_TRADING_BTC_EVIDENCE_ENABLED')=='true','EVIDENCE_DISABLED',404)
        bridge.require(request.mimetype=='application/json','JSON_REQUIRED',415)
        bridge.require(not request.args and not request.headers.get('Cookie'),'COOKIE_OR_QUERY_NOT_ALLOWED',400)
        bridge.require(limited(),'REQUEST_RATE_LIMIT',429)
        header=request.headers.get('Authorization','');bridge.require(header.startswith('Bearer ') and len(header)==71,'INVALID_CREDENTIAL',401)
        request.max_content_length=8192
        if request.endpoint=='kilas_trading.btc_evidence_worker':
            return btc_analysis.accepted_sources.ingest(header[7:],bridge.parse(request.get_data(cache=False)))
        if request.endpoint=='kilas_trading.btc_analysis_worker':
            return btc_analysis.analyze(header[7:],bridge.parse(request.get_data(cache=False)))
        return control.sync(header[7:],bridge.parse(request.get_data(cache=False)))
    return action(perform)

@bp.post('/control/sync')
def control_sync():return response({'outcome':'CONTROL_UNAVAILABLE'},503)

@bp.post('/control/btc-analysis')
def btc_analysis_worker():return response({'outcome':'BTC_ANALYSIS_UNAVAILABLE'},503)

@bp.post('/control/btc-evidence')
def btc_evidence_worker():return response({'outcome':'BTC_EVIDENCE_UNAVAILABLE'},503)

@bp.post('/control/desired')
def control_desired():
    def perform():
        bridge.require(not request.args and request.mimetype=='application/json','JSON_REQUIRED',415)
        return control.desired(security.current_user()['id'],bridge.parse(request.get_data(cache=False)))
    return action(perform)

@bp.get('/control/status')
def control_status():
    def perform():
        bridge.require(not request.args)
        return control.status(security.current_user()['id'])
    return action(perform)
