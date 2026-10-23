"""Native PG concurrency and additive-release rehearsal, disposable loopback only."""
import os
from pathlib import Path
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit
if os.environ.get('KILAS_CHAT_RECOVERY_POSTGRES_QA')!='1' or urlsplit(os.environ.get('DATABASE_URL','')).hostname not in ('localhost','127.0.0.1'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db
from flask import Flask,session
from werkzeug.exceptions import TooManyRequests
from kilas_ai import usage,agent_store,agent_context_checkpoint as checkpoint,chat_models_schema as schema
from kilas_ai import autonomous_store as jobs,workspace_streams as streams


def main():
    name='chat_recovery_'+uuid.uuid4().hex
    control=db.psycopg2.connect(db.DATABASE_URL);control.autocommit=True
    with control.cursor() as cur:cur.execute('CREATE SCHEMA '+name)
    original=db._postgres_connect_kwargs
    def options():
        settings=original();return dict(settings,options=settings['options']+' -c search_path='+name)
    release=threading.Event()
    try:
        with patch.object(db,'_postgres_connect_kwargs',side_effect=options):
            # Rehearse a baseline DB, apply only this targeted additive release twice.
            with patch.object(db,'MIGRATIONS',[m for m in db.MIGRATIONS if not m[0].startswith('0111_')]):db.init_schema()
            before={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            schema.apply_release('0111_kilas_chat_recovery');schema.apply_release('0111_kilas_chat_recovery')
            after={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert after-before=={'kilas_chat_request_payloads','kilas_chat_context_checkpoints','kilas_ai_chat_model_releases'}
            with jobs.transaction() as conn:
                owner=usage._query(conn,"INSERT INTO users(email,password_hash,role) VALUES ('recovery@example.test','hash','CLIENT_OWNER') RETURNING id",one=True)[0]
            conversation=agent_store.new_conversation(owner);barrier=threading.Barrier(2)
            def claim():barrier.wait();return agent_store.claim_request(owner,conversation,'native_claim_00000000001','a'*64)
            with ThreadPoolExecutor(2) as pool:
                futures=[pool.submit(claim) for _ in range(2)];assert sorted(f.result() for f in futures)==[False,True]
            try:agent_store.claim_request(owner,conversation,'native_claim_00000000001','b'*64)
            except agent_store.RequestConflict:pass
            else:raise AssertionError('Changed payload accepted')
            agent_store.append(owner,'user','Ingat keputusan awal unik. Budget 200 juta.',conversation)
            for i in range(110):agent_store.append(owner,'user',f'Obrolan {i}',conversation)
            agent_store.append(owner,'user','Koreksi budget 150 juta.',conversation)
            summary=checkpoint.before(owner,conversation,2**62)
            assert 'keputusan awal unik' in summary and summary.index('200 juta')<summary.index('150 juta') and len(summary)<=3000
            # Stale stream from another conversation no longer blocks admission.
            stale=jobs.stamp(jobs.now()-timedelta(minutes=20))
            db.execute('INSERT INTO kilas_workspace_streams(user_id,conversation_id,operation_key,created_at,updated_at) VALUES (?,?,?,?,?)',(owner,conversation,'native_stale_00000000001',stale,stale))
            newer=agent_store.new_conversation(owner);app=Flask(__name__);app.secret_key='synthetic-only';barrier=threading.Barrier(2);calls=[];entered=threading.Event()
            def output():calls.append(1);entered.set();yield {'type':'activity','label':'Synthetic'};release.wait(5);yield {'type':'delta','text':'Finished'}
            def start(index):
                with app.test_request_context('/kilas-ai/agent/chat'):
                    session['user_id']=owner;barrier.wait()
                    try:streams.start(owner,newer,'native_start_'+str(index).zfill(16),output()).close();return 200
                    except TooManyRequests:return 429
            with ThreadPoolExecutor(2) as pool:
                futures=[pool.submit(start,i) for i in range(2)];assert sorted(f.result() for f in futures)==[200,429]
            assert db.query_one('SELECT state FROM kilas_workspace_streams WHERE operation_key=?',('native_stale_00000000001',))['state']=='INTERRUPTED'
            assert entered.wait(2) and len(calls)==1
            release.set()
            for _ in range(100):
                if not db.query_one("SELECT id FROM kilas_workspace_streams WHERE user_id=? AND state='RUNNING'",(owner,)):break
                threading.Event().wait(.02)
            # Old application-shaped reads still see original history after migration.
            assert db.query_one('SELECT content FROM kilas_ai_agent_messages WHERE user_id=? ORDER BY id LIMIT 1',(owner,))['content'].startswith('Ingat keputusan')
    finally:
        release.set()
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+name+' CASCADE')
        control.close()
    print('PASS: native PostgreSQL additive/checksum/replay payload/concurrent claims/concurrent stream admission/long context')

if __name__=='__main__':main()
