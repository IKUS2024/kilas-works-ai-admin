"""Revocable customer logins; no idle or server lifetime logout.

The bearer identifier remains inside the existing signed HttpOnly cookie.
Only its hash is stored. Browser cookie retention is finite and browser-owned.
"""
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime,timedelta,timezone
from flask import current_app,session,request
from flask.sessions import SecureCookieSessionInterface
from itsdangerous import BadSignature
import db

COOKIE_DAYS=400
SID='_customer_session'


class AccountDisabled(ValueError):
    pass


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _password_stamp(value):
    key=current_app.secret_key
    if isinstance(key,str):key=key.encode()
    return hmac.new(key,('customer-auth-password-v1|'+value).encode(),hashlib.sha256).hexdigest()


def create(user):
    if user['role']=='KILAS_ADMIN':raise ValueError('admin_auth_separate')
    db.execute('INSERT INTO customer_auth_account_state(user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING',(user['id'],))
    account=db.query_one('SELECT disabled,generation FROM customer_auth_account_state WHERE user_id=?',(user['id'],))
    if not account or account['disabled']:raise AccountDisabled('account_disabled')
    token=secrets.token_hex(32)
    db.execute('INSERT INTO customer_auth_sessions(token_hash,user_id,role,password_stamp,account_generation,created_at) VALUES (?,?,?,?,?,?)',
               (_token_hash(token),user['id'],user['role'],_password_stamp(user['password_hash']),account['generation'],int(time.time())))
    return token


def revoke_current():
    token=session.get(SID)
    if isinstance(token,str) and re.fullmatch('[a-f0-9]{64}',token):
        db.execute('UPDATE customer_auth_sessions SET revoked_at=? WHERE token_hash=? AND user_id=? AND revoked_at IS NULL',
                   (int(time.time()),_token_hash(token),session.get('user_id')))


def revoke_all(user_id):
    # The generation also fences a login INSERT racing this revocation.
    db.execute('INSERT INTO customer_auth_account_state(user_id,generation) VALUES (?,1) ON CONFLICT(user_id) DO UPDATE SET generation=customer_auth_account_state.generation+1',(user_id,))
    db.execute('UPDATE customer_auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',(int(time.time()),user_id))


def set_account_disabled(user_id,disabled=True):
    """Server/operator hook only; disabling never changes tenant/Finance records."""
    db.execute('INSERT INTO customer_auth_account_state(user_id,disabled,generation) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET disabled=excluded.disabled,generation=customer_auth_account_state.generation+excluded.generation',
               (user_id,int(bool(disabled)),int(bool(disabled))))
    if disabled:db.execute('UPDATE customer_auth_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL',(int(time.time()),user_id))


def validate():
    token=session.get(SID);owner=session.get('user_id')
    if type(owner) is not int or not isinstance(token,str) or not re.fullmatch('[a-f0-9]{64}',token):return False
    row=db.query_one('''SELECT s.role,s.password_stamp,s.revoked_at,u.role AS current_role,u.password_hash,
                       a.disabled,s.account_generation,a.generation FROM customer_auth_sessions s
                       JOIN users u ON u.id=s.user_id JOIN customer_auth_account_state a ON a.user_id=u.id
                       WHERE s.token_hash=? AND s.user_id=?''',(_token_hash(token),owner))
    if not row or row['revoked_at'] is not None:return False
    valid=(not row['disabled'] and row['account_generation']==row['generation']
           and row['role']==row['current_role']==session.get('role')
           and row['current_role']!='KILAS_ADMIN'
           and hmac.compare_digest(row['password_stamp'],_password_stamp(row['password_hash'])))
    if not valid:revoke_current()
    return valid


class CustomerCookieSessionInterface(SecureCookieSessionInterface):
    def should_set_cookie(self,app,state):
        if request.endpoint in ('static','healthz') and state.get(SID) and state.get('role')!='KILAS_ADMIN':
            return state.modified
        return super().should_set_cookie(app,state)

    def open_session(self,app,request):
        value=request.cookies.get(self.get_cookie_name(app))
        if value:
            serializer=self.get_signing_serializer(app)
            if serializer:
                try:
                    data=serializer.loads(value)  # Server record, not cookie age, is authoritative.
                    if isinstance(data,dict) and data.get(SID) and data.get('role')!='KILAS_ADMIN':
                        return self.session_class(data)
                except BadSignature:pass
        # Admin and legacy cookies retain Flask's existing signature-age rules.
        return super().open_session(app,request)

    def get_expiration_time(self,app,state):
        if state.get(SID) and state.get('role')!='KILAS_ADMIN':
            return datetime.now(timezone.utc)+timedelta(days=COOKIE_DAYS)
        return super().get_expiration_time(app,state)
