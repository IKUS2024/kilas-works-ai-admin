"""Separate Trading on the existing service. No shared-domain cookies or OAuth changes."""
from flask import request,redirect,url_for,abort
from runtime_environment import is_production

TRADING_HOST='trading.kilasworks.id'
APP_HOST='app.kilasworks.id'
SERVICE_HOST='kilas-works-client-hub.onrender.com'


def is_trading_host():return request.host.split(':',1)[0].lower()==TRADING_HOST


def install(app):
    app.config['TRUSTED_HOSTS']=[APP_HOST,TRADING_HOST,SERVICE_HOST,'localhost','127.0.0.1']
    app.jinja_env.globals['trading_host']=is_trading_host
    def guard():
        endpoint=request.endpoint or ''
        local=request.host.split(':',1)[0].lower() in ('localhost','127.0.0.1')
        if is_trading_host():
            if endpoint=='index' or endpoint=='products.product_start':
                if request.method not in ('GET','HEAD'):abort(404)
                return redirect(url_for('kilas_trading.home'),code=303)
            if endpoint=='static' or endpoint=='healthz' or endpoint in ('auth.login_page','auth.logout_page','set_ui_language') or endpoint.startswith('kilas_trading.'):
                return None
            abort(404)
        if endpoint.startswith('kilas_trading.') and not (local and not is_production()):
            if request.method not in ('GET','HEAD'):abort(404)
            return redirect('https://'+TRADING_HOST+'/',code=302)
    app.before_request_funcs.setdefault(None,[]).insert(0,guard)
