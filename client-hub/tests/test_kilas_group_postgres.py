"""Explicit disposable loopback PostgreSQL: migration and locking rehearsal.
Run as a script, separately from the SQLite application integration suite.
"""
import os,sys,uuid,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

def main():
    url=os.environ.get('DATABASE_URL','')
    if os.environ.get('KILAS_GROUP_POSTGRES_QA')!='1' or urlsplit(url).hostname not in ('127.0.0.1','localhost'):
        raise SystemExit('Explicit disposable loopback PostgreSQL required')
    import db
    from kilas_ai import group_chat as groups,group_schema,providers,usage
    schema='group_qa_'+uuid.uuid4().hex
    control=db.psycopg2.connect(url);control.autocommit=True
    with control.cursor() as cur:cur.execute('CREATE SCHEMA '+schema)
    original=db._postgres_connect_kwargs
    def options():
        value=original();return dict(value,options=value['options']+' -c search_path='+schema)
    try:
        with patch.object(db,'_postgres_connect_kwargs',side_effect=options),patch('requests.sessions.Session.request',side_effect=AssertionError('offline only')):
            db.execute('CREATE TABLE users(id BIGSERIAL PRIMARY KEY,email TEXT,full_name TEXT)')
            db.execute('CREATE TABLE customer_auth_account_state(user_id BIGINT PRIMARY KEY,disabled INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE finance_qa_sentinel(id INTEGER PRIMARY KEY,value TEXT)')
            db.execute("INSERT INTO finance_qa_sentinel VALUES (1,'preserved')")
            for name in ('0071_kilas_ai_v1','0072_kilas_ai_usage_status','0073_kilas_ai_topups'):
                db.execute((Path('migrations')/(name+'_postgres.sql')).read_text())
            script=(Path('migrations')/(group_schema.NAME+'_postgres.sql')).read_text()
            with patch.object(group_schema.Path,'read_text',return_value=script+'\nSELECT nonexistent_group_qa_function();'):
                try:group_schema.apply_release();raise AssertionError('failure required')
                except db.psycopg2.Error:pass
            assert db.query_one("SELECT to_regclass('kilas_chat_groups') AS name")['name'] is None
            assert group_schema.apply_release()==[group_schema.NAME]
            assert group_schema.apply_release()==[]
            with patch.object(group_schema.Path,'read_text',return_value=script+'\n-- changed'):
                try:group_schema.apply_release();raise AssertionError('checksum failure required')
                except RuntimeError as error:assert str(error)=='group_schema_checksum_mismatch'
            owner=db.insert_returning_id("INSERT INTO users(email,full_name) VALUES ('owner@example.test','Owner')")
            member=db.insert_returning_id("INSERT INTO users(email,full_name) VALUES ('member@example.test','Member')")
            outsider=db.insert_returning_id("INSERT INTO users(email,full_name) VALUES ('other@example.test','Other')")
            ident=groups.create(owner,'Native group');token=groups.invitation(owner,ident);groups.join(member,token)
            for user in (owner,member):assert groups.state(user,ident)['messages']==[]
            try:groups.state(outsider,ident);raise AssertionError('membership required')
            except groups.GroupError as error:assert error.status==404
            operation=uuid.uuid4().hex
            with ThreadPoolExecutor(max_workers=6) as pool:
                results=list(pool.map(lambda _:groups.send(member,ident,'Concurrent plain text',operation),range(6)))
            assert sum(bool(r.get('cached')) for r in results)==5
            assert len(groups.state(owner,ident)['messages'])==1
            started=threading.Event();release=threading.Event()
            def provider(*a,**kw):
                started.set();assert release.wait(5)
                yield from [{'type':'provider','provider':'openai','model':'gpt-6-luna'},{'type':'delta','text':'Group only.'},{'type':'usage','input_tokens':100,'output_tokens':10},{'type':'finish','reason':'stop'}]
            operation=uuid.uuid4().hex
            with patch.object(providers,'stream',side_effect=provider) as mock,ThreadPoolExecutor(max_workers=2) as pool:
                first=pool.submit(groups.send,member,ident,'@Kilas answer',operation)
                assert started.wait(5)
                duplicate=pool.submit(groups.send,member,ident,'@Kilas answer',operation).result(5)
                assert duplicate['cached'] and duplicate['status']=='DISPATCHED'
                try:groups.send(owner,ident,'AI',uuid.uuid4().hex,'ASK');raise AssertionError('AI mutex required')
                except groups.GroupError as error:assert error.code=='ai_busy'
                release.set();assert first.result(5)['status']=='COMPLETE';assert mock.call_count==1
            assert db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE user_id=?',(owner,))['n']==1
            assert db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE user_id=?',(member,))['n']==0
            groups.manage(owner,ident,'remove',target=member)
            try:groups.state(member,ident);raise AssertionError('removal required')
            except groups.GroupError as error:assert error.status==404
            groups.invitation(owner,ident,revoke=True);assert not groups.preview(token)
            assert db.query_all('SELECT * FROM finance_qa_sentinel')==[{'id':1,'value':'preserved'}]
            assert group_schema.apply_release()==[]
            print('PASS PostgreSQL: atomic rollback, additive apply/retry, checksum guard, ordered durable messages, membership/isolation, concurrent idempotency, one AI dispatch/owner ledger charge, removal/revocation, existing-row preservation')
    finally:
        db.reset_connection_for_new_db_path()
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+schema+' CASCADE')
        control.close()

if __name__=='__main__':main()
