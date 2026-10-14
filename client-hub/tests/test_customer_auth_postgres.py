"""Native PG18 auth schema and revocation, only on a disposable loopback database."""
import os,sys,time,json
from urllib.parse import urlsplit
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
url=urlsplit(os.environ.get('DATABASE_URL',''))
if url.hostname not in ('127.0.0.1','localhost') or url.path!='/auth_qa':raise RuntimeError('disposable_auth_database_required')
import db,customer_auth as auth,customer_auth_schema as schema
from flask import Flask,session
app=Flask('native-auth-qa');app.secret_key='native-isolated-test-only';app.session_interface=auth.CustomerCookieSessionInterface()
db.execute('CREATE TABLE IF NOT EXISTS users(id BIGSERIAL PRIMARY KEY,password_hash TEXT NOT NULL,role TEXT NOT NULL)')
db.execute('CREATE TABLE IF NOT EXISTS finance_qa_sentinel(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
db.execute("INSERT INTO finance_qa_sentinel VALUES (1,'untouched') ON CONFLICT(id) DO NOTHING")
before=db.query_all('SELECT * FROM finance_qa_sentinel');schema.apply();schema.apply()
owner=db.insert_returning_id("INSERT INTO users(password_hash,role) VALUES ('synthetic','CLIENT_OWNER')")
with app.test_request_context():
 user=db.query_one('SELECT * FROM users WHERE id=?',(owner,));token=auth.create(user);session.update(user_id=owner,role=user['role']);session[auth.SID]=token
 assert auth.validate()
 row=db.query_one('SELECT * FROM customer_auth_sessions WHERE user_id=?',(owner,));assert row['token_hash']!=token and len(row['token_hash'])==64
 auth.revoke_current();assert not auth.validate()
 session[auth.SID]=auth.create(user);assert auth.validate()
 db.execute("UPDATE users SET password_hash='changed' WHERE id=?",(owner,));assert not auth.validate()
 user=db.query_one('SELECT * FROM users WHERE id=?',(owner,));session[auth.SID]=auth.create(user);assert auth.validate()
 auth.set_account_disabled(owner);assert not auth.validate();auth.set_account_disabled(owner,False);assert not auth.validate()
 session[auth.SID]=auth.create(user);assert auth.validate();auth.revoke_all(owner);assert not auth.validate()
 session[auth.SID]=auth.create(user);db.execute("UPDATE users SET role='KILAS_ADMIN' WHERE id=?",(owner,));assert not auth.validate()
assert db.query_all('SELECT * FROM finance_qa_sentinel')==before
version=db.query_one('SHOW server_version')['server_version']
print(json.dumps({'result':'PASS','postgres_version':version,'idempotent_additive_schema':True,'hash_only_session_storage':True,'logout_password_disable_role_server_revocation':'PASS','finance_sentinel_unchanged':True,'paid_calls':0,'production_mutations':0}))
