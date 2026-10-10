"""Owner-initiated model catalog GET only; no inference or control authority."""
import os
from datetime import datetime, timezone
from flask import jsonify, request, render_template
from . import analysis
from .routes import bp


@bp.get('/model/diagnostics')
def model_diagnostics():
    response=render_template('kilas_trading_model_diagnostics.html')
    return response,200,{'Cache-Control':'no-store'}


@bp.post('/model/catalog-preflight')
def model_catalog_preflight():
    # Existing blueprint pilot/login/host checks and global CSRF apply unchanged.
    # Accept only an empty object: destination, model and credentials are server owned.
    if request.args or request.mimetype != 'application/json' or request.get_data().strip() != b'{}':
        return jsonify({'outcome':'INVALID_PREFLIGHT_REQUEST'}),400
    credential=os.environ.get('OPENAI_API_KEY','').strip()
    result=dict(credential='PRESENT' if credential else 'MISSING',http_status=None,
                model_id_match=False,checked_at=None)
    if credential:
        def status(value):
            if type(value) is int and 100<=value<=599:result['http_status']=value
        try:
            catalog=analysis._http('GET',analysis.MODEL_URL,credential,
                                   status_sink=status,timeout=(5,10))
            result['model_id_match']=isinstance(catalog,dict) and catalog.get('id')==analysis.budget.MODEL
        except Exception:
            # Never expose provider headers/body, credential or exception text.
            pass
    result['checked_at']=datetime.now(timezone.utc).isoformat()
    response=jsonify(result)
    response.headers['Cache-Control']='no-store'
    return response
