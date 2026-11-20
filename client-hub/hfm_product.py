"""Authenticated product setup on the app host. No trading credential in the browser HTML."""
from pathlib import Path
import os
import time
from flask import abort, flash, redirect, render_template, request, send_file, url_for, Response
from functools import wraps
import db
import security
from kilas_trading import access, hfm_sol


def pilot_only(view):
    @security.login_required
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not access.is_pilot():
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def register(bp):
    @bp.get('/products/robot-trading')
    @pilot_only
    def hfm_product():
        user=security.current_user()['id']
        state=db.query_one('SELECT login,expires,calls,quota_day FROM hfm_sol_devices WHERE user_id=?',(user,))
        now=int(time.time())
        linked=bool(state and state['expires']>now)
        calls=state['calls'] if state and state['quota_day']==now//86400 else 0
        return render_template('hfm_robot.html',linked=linked,calls=calls,limit=hfm_sol.MAX_CALLS,
                               key_present=bool(os.environ.get('OPENAI_API_KEY','').strip()))

    @bp.get('/products/robot-trading/download')
    @pilot_only
    def hfm_download():
        return send_file(Path(__file__).resolve().parent/'hfm_robot'/'Kilas_HFM_Sol.ex5',
                         as_attachment=True,download_name='Kilas_HFM_Sol.ex5',max_age=0)

    @bp.post('/products/robot-trading/pair')
    @pilot_only
    def hfm_pair():
        login=request.form.get('login','').strip()
        try:
            token=hfm_sol.issue(security.current_user()['id'],login)
        except ValueError:
            abort(400)
        return Response(login+'\r\n'+token+'\r\n',mimetype='application/octet-stream',
            headers={'Content-Disposition':'attachment; filename="kilas-hfm-sol.key"','Cache-Control':'no-store'})

    @bp.post('/products/robot-trading/revoke')
    @pilot_only
    def hfm_revoke():
        db.execute('UPDATE hfm_sol_devices SET expires=0 WHERE user_id=?',(security.current_user()['id'],)).close()
        flash('Akses analisis MT5 telah diputus.')
        return redirect(url_for('products.hfm_product'),303)
