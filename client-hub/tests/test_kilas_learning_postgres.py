"""Learning additive schema and owner fences on disposable loopback PG only."""
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

if os.environ.get('KILAS_AI_POSTGRES_QA')!='1' or urlsplit(os.environ.get('DATABASE_URL','')).hostname not in ('localhost','127.0.0.1'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db
from kilas_ai import learning_schema as schema, learning_store as store
from kilas_ai import audio_schema, audio_store, usage


def main():
    isolated='learning_qa_'+uuid.uuid4().hex
    control=db.psycopg2.connect(db.DATABASE_URL);control.autocommit=True
    with control.cursor() as cur:cur.execute('CREATE SCHEMA '+isolated)
    original=db._postgres_connect_kwargs
    def options():
        values=original();return dict(values,options=values['options']+' -c search_path='+isolated)
    try:
        with patch.object(db,'_postgres_connect_kwargs',side_effect=options):
            db.init_schema()
            audio_schema.apply_release()
            before={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            schema.apply_release();schema.apply_release()
            after={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert after-before=={'kilas_learning_releases','kilas_learning_sessions','kilas_learning_cancelled_starts','kilas_learning_turns','kilas_learning_clips','kilas_learning_inputs','kilas_learning_input_chunks'}
            with audio_store.locked(0) as conn:
                owner=usage._query(conn,"INSERT INTO users(email,password_hash,role) VALUES ('learning@example.test','hash','CLIENT_OWNER') RETURNING id",one=True)[0]
                other=usage._query(conn,"INSERT INTO users(email,password_hash,role) VALUES ('other@example.test','hash','CLIENT_OWNER') RETURNING id",one=True)[0]
            sid=store.create(owner,'learning-pg-start-1234','en','id','beginner','kilas-male')[0]
            def claim():
                try:return store.claim(owner,sid,'learning-pg-turn-1234','realtime')
                finally:db._discard_cached_connection()
            with ThreadPoolExecutor(max_workers=2) as executor:
                assert sorted(executor.map(lambda _:claim(),range(2)))==[False,True]
            store.finish(owner,sid,'learning-pg-turn-1234','Explain in Spanish','example',{})
            db.execute('UPDATE kilas_learning_sessions SET expires_at=? WHERE id=?',((usage._now()-timedelta(days=1)).isoformat(),sid))
            for index in range(44):
                key='learning-pg-long-turn-'+str(index)
                assert store.claim(owner,sid,key,'realtime')
                store.finish(owner,sid,key,'practice','example',{})
            assert not store.state(owner,sid)['ended']
            assert store.current(owner)==sid
            assert store.context(owner,sid)[0]['content']=='Explain in Spanish'
            assert len(store.context(owner,sid))==18
            assert store.claim(owner,sid,'learning-pg-stale-turn','realtime')
            db.execute('UPDATE kilas_learning_turns SET created_at=? WHERE id=?',((usage._now()-timedelta(minutes=4)).isoformat(),'learning-pg-stale-turn'))
            assert store.claim(owner,sid,'learning-pg-recovered-turn','realtime')
            assert store.state(owner,sid,'learning-pg-stale-turn')['status']=='FAILED'
            try:store.state(other,sid);raise AssertionError('Foreign session accepted')
            except store.Error as error:assert error.status==404
            store.end(owner,sid)
            assert store.state(owner,sid)['status']=='CANCELLED'
            print('PASS: Learning PostgreSQL additive/idempotent schema, concurrent claim, continued sessions, bounded context, stale recovery, owner fences, End')
    finally:
        db._discard_cached_connection()
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+isolated+' CASCADE')
        control.close()


if __name__=='__main__':main()
