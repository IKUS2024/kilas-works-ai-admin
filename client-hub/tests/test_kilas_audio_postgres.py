"""Native additive Audio rehearsal and concurrent accounting on disposable loopback PG only."""
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

if os.environ.get('KILAS_AI_POSTGRES_QA')!='1' or urlsplit(os.environ.get('DATABASE_URL','')).hostname not in ('localhost','127.0.0.1'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db
from kilas_ai import audio_schema as schema, audio_store as store, audio_billing as billing, usage
from kilas_ai import audio_personal_voice as personal, audio_provider as provider, audio_media as media


def main():
    isolated='audio_qa_'+uuid.uuid4().hex
    control=db.psycopg2.connect(db.DATABASE_URL);control.autocommit=True
    with control.cursor() as cur:cur.execute('CREATE SCHEMA '+isolated)
    original=db._postgres_connect_kwargs
    def options():
        values=original();return dict(values,options=values['options']+' -c search_path='+isolated)
    try:
        with patch.object(db,'_postgres_connect_kwargs',side_effect=options):
            with patch.object(db,'MIGRATIONS',[m for m in db.MIGRATIONS if not m[0].startswith(('0083_','0084_'))]):db.init_schema()
            before={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert schema.apply_release()==[schema.NAME];assert schema.apply_release()==[]
            after={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert after-before=={'kilas_audio_balances','kilas_audio_orders','kilas_audio_jobs','kilas_audio_releases'}
            assert schema.apply_release('0084_kilas_personal_voice')==['0084_kilas_personal_voice']
            assert schema.apply_release('0084_kilas_personal_voice')==[]
            with store.locked(0) as conn:
                user=usage._query(conn,"INSERT INTO users(email,password_hash,role) VALUES ('audio@example.test','hash','CLIENT_OWNER') RETURNING id",one=True)[0]
                admin=usage._query(conn,"INSERT INTO users(email,password_hash,role) VALUES ('audio-admin@example.test','hash','KILAS_ADMIN') RETURNING id",one=True)[0]
            with patch.object(media,'voice_sample',return_value=b'synthetic-voice'),patch.object(provider,'clone_voice',return_value='privatePostgres123') as clone:
                personal.create(user,'postgres-personal-key-1234',None)
                personal.create(user,'postgres-personal-key-1234',None)
                clone.assert_called_once()
                assert personal.get(user)=='privatePostgres123' and personal.get(admin)==''
            with patch.object(media,'voice_sample',return_value=b'synthetic-voice'),patch.object(provider,'clone_voice',side_effect=provider.ProviderError()):
                try:personal.create(user,'postgres-replace-key-1234',None,True)
                except provider.ProviderError:pass
                else:raise AssertionError('replacement failure was not surfaced')
                assert personal.get(user)=='privatePostgres123'
            order=billing.create(user,'MINUTE');db.execute("UPDATE kilas_audio_orders SET status='UNDER_REVIEW' WHERE id=?",(order,))
            with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:billing.review(order,admin,'VERIFIED'),range(2)))
            assert store.balance(user)['seconds']==60
            def create(i):
                try:return store.create(user,'postgres-key-123456-'+str(i),'translate','QA','auto','en','','','',37000,b'synthetic-pcm',37,37)[0]
                except store.AudioError:return None
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(create,range(2)))
            assert sum(x is not None for x in results)==1
            ident=next(x for x in results if x is not None);assert store.start(user,ident)
            assert bytes(store.payload(user,ident)['source_content'])==b'synthetic-pcm'
            store.submitted(user,ident,'provider123');store.finish(user,ident,b'synthetic-mp3',36500)
            assert store.balance(user)['seconds']==23
            assert store.finish(user,ident,b'duplicate',36500) is False
            assert store.get(user+999,ident) is None
            assert schema.apply_release()==[];assert store.balance(user)['seconds']==23
            assert usage.effective_plan(user)['plan']=='FREE'
    finally:
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+isolated+' CASCADE')
        control.close()
    print('PASS Audio PostgreSQL additive/checksum/concurrent purchase/reservation/bytea/settlement/isolation')


if __name__=='__main__':main()
