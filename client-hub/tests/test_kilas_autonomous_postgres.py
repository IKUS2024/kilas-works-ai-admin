"""Disposable PG additive migration + real concurrent claims and fenced recovery."""
import os
from pathlib import Path
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

if os.environ.get('KILAS_AI_POSTGRES_QA') != '1' or urlsplit(os.environ.get('DATABASE_URL', '')).hostname not in ('localhost', '127.0.0.1'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db
from kilas_ai import autonomous_schema as schema, autonomous_store as store, usage
from kilas_ai import autonomous_planner as planner, autonomous_runner as runner


def main():
    isolated = 'autonomous_qa_' + uuid.uuid4().hex
    control = db.psycopg2.connect(db.DATABASE_URL)
    control.autocommit = True
    with control.cursor() as cur:
        cur.execute('CREATE SCHEMA ' + isolated)
    original = db._postgres_connect_kwargs
    def options():
        settings = original()
        return dict(settings, options=settings['options'] + ' -c search_path=' + isolated)
    try:
        with patch.object(db, '_postgres_connect_kwargs', side_effect=options):
            with patch.object(db, 'MIGRATIONS', [m for m in db.MIGRATIONS if not m[0].startswith(('0078_', '0079_', '0080_', '0081_'))]):
                db.init_schema()
            before = {r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert schema.apply_release() == [schema.NAME]
            assert schema.apply_release() == []
            after = {r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert after - before == {'kilas_agent_jobs','kilas_agent_steps','kilas_agent_events','kilas_agent_artifacts','kilas_agent_approvals','kilas_autonomous_schema_releases'}
            with store.transaction() as conn:
                user = usage._query(conn, "INSERT INTO users(email,password_hash,role) VALUES ('autonomous-pg@example.test','hash','CLIENT_OWNER') RETURNING id", one=True)[0]
            job = store.create(user, 'Research objective')
            with ThreadPoolExecutor(2) as pool:
                claims = list(pool.map(lambda _: store.claim_due(1), range(2)))
            assert sum(len(r) for r in claims) == 1
            old = next(r[0] for r in claims if r)
            db.execute('UPDATE kilas_agent_jobs SET lease_until=? WHERE id=?', (store.stamp(store.now()-timedelta(seconds=1)), job))
            new = store.claim_due(1)[0]
            assert old[1] != new[1]
            with store.transaction() as conn:
                assert not store.locked(conn, job, old[1])
                assert store.locked(conn, job, new[1])
            store.release(*old)
            assert store.get(user, job)['lease_token'] == new[1]
            raw = {'objective': 'Verified file', 'mode': 'ONE_SHOT', 'stop_condition': 'File available', 'next_action': 'Create file',
                   'steps': [{'worker': 'FILE', 'action': 'create', 'instruction': 'Prepare file', 'input_json': '{"name":"verified.txt","format":"txt","content":"Actual result"}', 'completion_criteria': 'Artifact persisted', 'requires_approval': False}]}
            assert store.install_plan(store.get(user, job), new[1], planner.validate(raw, 'ONE_SHOT'))
            store.release(*new)
            runner.execute(*store.claim_due(1)[0])
            assert store.get(user, job)['status'] == 'COMPLETED'
            assert db.query_one('SELECT COUNT(*) AS n FROM kilas_agent_artifacts WHERE job_id=?', (job,))['n'] == 1
            # Additive binary storage is idempotent and round-trips native BYTEA.
            from kilas_ai import pdf,work_artifacts
            with store.transaction() as conn:
                for _ in range(2):conn.cursor().execute((Path(__file__).parents[1]/'migrations/0080_kilas_work_artifact_files_postgres.sql').read_text())
                file=pdf.render('# Proposal Test\n\n## Lingkup\nDokumen verifikasi penyimpanan biner.\n')
                step=store.steps(job)[0]
                work_artifacts.persist(conn,store.get(user,job),step,file)
            assert work_artifacts.listing(user,job_id=job)[0]['media_type']=='application/pdf'
            assert bytes(db.query_one('SELECT content FROM kilas_agent_artifact_files LIMIT 1')['content']).startswith(b'%PDF')
            with store.transaction() as conn:
                for _ in range(2):conn.cursor().execute((Path(__file__).parents[1]/'migrations/0081_kilas_work_push_postgres.sql').read_text())
            from kilas_ai import work_push
            assert db.query_one('SELECT COUNT(*) AS n FROM kilas_work_push_subscriptions')['n']==0
            # Real concurrent cross-owner registration cannot replace another account's keys.
            import base64
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import serialization
            point=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
            encoded=lambda value:base64.urlsafe_b64encode(value).decode().rstrip('=')
            subscription={'endpoint':'https://fcm.googleapis.com/fcm/send/isolated-pg-qa','keys':{'p256dh':encoded(point),'auth':encoded(b'1234567890123456')}}
            with store.transaction() as conn:
                other=usage._query(conn,"INSERT INTO users(email,password_hash,role) VALUES ('other-pg@example.test','hash','CLIENT_OWNER') RETURNING id",one=True)[0]
            def register(owner):
                try:return owner,work_push.register(owner,subscription)
                except ValueError:return owner,None
            with ThreadPoolExecutor(2) as pool:registrations=list(pool.map(register,(user,other)))
            winners=[r for r in registrations if r[1] is not None]
            assert len(winners)==1
            assert db.query_one('SELECT user_id FROM kilas_work_push_subscriptions')['user_id']==winners[0][0]
            # Native TIMESTAMPTZ must serialize in the durable reminder checkpoint.
            from kilas_ai import agent_store,work_push
            with store.transaction() as conn:
                conn.cursor().execute((Path(__file__).parents[1]/'migrations/0079_kilas_agent_conversations_postgres.sql').read_text())
            conversation=agent_store.new_conversation(user)
            due=store.now()-timedelta(minutes=2)
            reminder=store.create(user,'Ingatkan cek QA',mode='SCHEDULED',wake_at=due,conversation_id=conversation,checkpoint={'reminder':{'subject':'cek QA'}})
            with patch.object(work_push,'configured',return_value=False):
                for _ in range(2):runner.execute(*store.claim_due(1)[0])
            assert store.get(user,reminder)['status']=='COMPLETED'
            assert db.query_one("SELECT COUNT(*) AS n FROM kilas_agent_events WHERE job_id=? AND kind='REMINDER'",(reminder,))['n']==1
            assert sum(m['content']=='Pengingat: cek QA' for m in agent_store.messages(user,conversation_id=conversation))==1
            assert store.claim_due(1)==[]
            import json
            assert json.loads(store.get(user,reminder)['checkpoint_json'])['reminder']['scheduled_for']==store.stamp(due)
            job = store.create(user, 'Stopped work')
            store.control(user, job, 'stop')
            assert store.claim_due(1) == []
    finally:
        with control.cursor() as cur:
            cur.execute('DROP SCHEMA ' + isolated + ' CASCADE')
        control.close()
    print('PASS: 0078/0080/0081 additive/idempotent + PostgreSQL concurrent claim, lease fencing, BYTEA, push ownership and terminal stop')


if __name__ == '__main__':
    main()
