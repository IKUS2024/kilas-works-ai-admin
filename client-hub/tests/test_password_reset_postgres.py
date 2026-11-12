"""Native PostgreSQL reset concurrency, disposable loopback DB only."""
import os, sys, threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import urlsplit
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
url = urlsplit(os.environ.get('DATABASE_URL', ''))
if url.hostname not in ('127.0.0.1', 'localhost') or url.path != '/auth_qa':
    raise RuntimeError('disposable_auth_database_required')
import db, repo, customer_auth_schema

db.execute('CREATE TABLE users(id BIGSERIAL PRIMARY KEY,password_hash TEXT NOT NULL,role TEXT NOT NULL)')
db.execute('CREATE TABLE password_reset_tokens(id BIGSERIAL PRIMARY KEY,user_id BIGINT REFERENCES users(id),token_hash TEXT UNIQUE,expires_at TIMESTAMPTZ,used_at TIMESTAMPTZ)')
db.execute('CREATE TABLE audit_log(id BIGSERIAL PRIMARY KEY,actor_user_id BIGINT,business_id BIGINT,action TEXT,detail TEXT)')
customer_auth_schema.apply()
owner = db.insert_returning_id("INSERT INTO users(password_hash,role) VALUES ('original','CLIENT_OWNER')")
expires = (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
for digest in ('first', 'second'):
    db.execute('INSERT INTO password_reset_tokens(user_id,token_hash,expires_at) VALUES (?,?,?)', (owner,digest,expires))
barrier = threading.Barrier(2); state = threading.local(); original = repo.get_valid_reset_token
def candidate(*args):
    row = original(*args)
    if not getattr(state, 'seen', False):
        state.seen = True
        barrier.wait(timeout=10)
    return row
def reset(digest):
    try:
        return repo.complete_password_reset(digest, 'synthetic-'+digest)
    finally:
        db.get_connection().close(); db._local.conn = None
with patch.object(repo, 'get_valid_reset_token', side_effect=candidate):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reset, ('first','second')))
assert results.count(owner)==1 and results.count(None)==1, results
assert db.query_one('SELECT COUNT(*) AS n FROM audit_log')['n']==1
assert db.query_one('SELECT COUNT(*) AS n FROM password_reset_tokens WHERE used_at IS NULL')['n']==0
before = repo.get_user_by_id(owner)['password_hash']
db.execute('INSERT INTO password_reset_tokens(user_id,token_hash,expires_at) VALUES (?,?,?)',(owner,'rollback',expires))
with patch.object(repo,'write_audit_no_business',side_effect=RuntimeError('synthetic rollback')):
    try: repo.complete_password_reset('rollback','should-not-persist')
    except RuntimeError: pass
    else: raise AssertionError('missing rollback exception')
assert repo.get_user_by_id(owner)['password_hash']==before
assert original('rollback',datetime.now(timezone.utc).isoformat()) is not None
print('PASS PostgreSQL atomic reset: concurrent links single winner; failure rolls back; replay rejected')
