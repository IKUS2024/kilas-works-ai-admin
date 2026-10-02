"""0079 production-shaped additive migration/backfill rehearsal on isolated local PG."""
import os
from pathlib import Path
import sys
import uuid
from unittest.mock import patch
from urllib.parse import urlsplit
if os.environ.get('KILAS_AI_POSTGRES_QA')!='1' or urlsplit(os.environ.get('DATABASE_URL','')).hostname not in ('localhost','127.0.0.1'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db
from kilas_ai import agent_conversation_schema as schema, agent_store as chats, autonomous_store as jobs, usage


def main():
    isolated='chat_qa_'+uuid.uuid4().hex
    control=db.psycopg2.connect(db.DATABASE_URL);control.autocommit=True
    with control.cursor() as cur:cur.execute('CREATE SCHEMA '+isolated)
    original=db._postgres_connect_kwargs
    def options():
        settings=original()
        return dict(settings,options=settings['options']+' -c search_path='+isolated)
    try:
        with patch.object(db,'_postgres_connect_kwargs',side_effect=options):
            with patch.object(db,'MIGRATIONS',[m for m in db.MIGRATIONS if not m[0].startswith('0079_')]):db.init_schema()
            with jobs.transaction() as conn:
                owner=usage._query(conn,"INSERT INTO users(email,password_hash,role) VALUES('history@example.test','hash','CLIENT_OWNER') RETURNING id",one=True)[0]
            db.execute("INSERT INTO kilas_ai_agent_messages(user_id,role,content) VALUES(?,'user','Historical message')",(owner,))
            old_job=jobs.create(owner,'Existing task')
            before={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert schema.apply_release()==[schema.NAME]
            assert schema.apply_release()==[]
            after={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert after-before=={'kilas_ai_conversations','kilas_agent_chat_requests','kilas_agent_conversation_releases'}
            historical=chats.recent_conversations(owner)[0]['id']
            assert chats.messages(owner,conversation_id=historical)[0]['content']=='Historical message'
            assert jobs.get(owner,old_job)['status']=='PLANNING'
            new=chats.new_conversation(owner)
            assert chats.messages(owner,conversation_id=new)==[]
            chats.append(owner,'user','New conversation message',new)
            assert chats.claim_request(owner,new,'operation-12345678')
            assert not chats.claim_request(owner,new,'operation-12345678')
            linked=jobs.create(owner,'New linked task',conversation_id=new)
            assert jobs.get(owner,linked)['origin_conversation_id']==new
            origin=chats.messages(owner,conversation_id=new)[0]['id']
            chats.append(owner,'user','Later unrelated message',new)
            db.execute("UPDATE kilas_agent_jobs SET status='COMPLETED' WHERE id=?",(linked,))
            assert [j['id'] for j in jobs.conversation_jobs(owner,new,[origin])]==[linked]
            db.execute("UPDATE kilas_agent_jobs SET checkpoint_json='{}' WHERE id=?",(linked,))
            assert [j['id'] for j in jobs.conversation_jobs(owner,new,[origin])]==[linked]
            assert jobs.conversation_jobs(owner+100000,new,[origin])==[]
            assert jobs.get(owner,old_job)['origin_conversation_id'] is None
            db.init_schema()
            assert chats.messages(owner,conversation_id=new)[0]['content']=='New conversation message'
            assert chats.messages(owner,conversation_id=historical)[0]['content']=='Historical message'
            assert jobs.get(owner,linked)['origin_conversation_id']==new
    finally:
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+isolated+' CASCADE')
        control.close()
    print('PASS: PostgreSQL 0079 additive/checksum/idempotency/history backfill/task preservation/owner links/duplicate request')


if __name__=='__main__':main()
