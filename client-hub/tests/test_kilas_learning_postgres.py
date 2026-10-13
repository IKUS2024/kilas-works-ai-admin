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
            # Fixed-end shared sponsorship: additive checksum + zero-balance job,
            # expiry settlement and a simultaneous service-funding admission.
            from kilas_ai import free_test, audio_transcription_budget as budget
            audio_schema.apply_release('0095_kilas_free_test');audio_schema.apply_release('0095_kilas_free_test')
            env={'KILAS_APP_FREE_TEST_ENABLED':'true','KILAS_APP_FREE_TEST_END_AT':free_test.END_AT.isoformat(),
                 'KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'true','KILAS_VO_STT_USAGE_MODE':'owner',
                 'KILAS_VO_STT_ALLOWED_OWNER_ID':str(owner),'KILAS_VO_STT_CAMPAIGN':'pg-trial',
                 'KILAS_VO_STT_GLOBAL_BUDGET_MICRO_USD':'100','KILAS_VO_STT_ACCOUNT_BUDGET_MICRO_USD':'100',
                 'KILAS_VO_STT_PRICE_VERSION':budget.PRICE_VERSION,'ELEVENLABS_API_KEY':'synthetic-only'}
            from datetime import datetime,timezone
            class Clock(datetime):
                @classmethod
                def now(cls,tz=None):return datetime(2026,10,13,12,tzinfo=timezone.utc)
            with patch.dict(os.environ,env),patch.object(free_test,'datetime',Clock),patch.object(budget,'datetime',Clock):
                assert free_test.eligible(other) and usage.qa_exempt(other)
                assert audio_store.require_balance(other)['exempt']
                job,new=audio_store.create(other,'trial-pg-zero-balance','voiceover','Synthetic','id','en','syntheticVoice','Kilas Male','Hello',0,None,2,10)
                assert new and audio_store.start(other,job)
                # Completion preserves sponsorship after the feature admission window.
                with patch.dict(os.environ,{'KILAS_APP_FREE_TEST_ENABLED':'false'}):
                    assert audio_store.finish(other,job,b'synthetic-mp3',2400)
                    assert not audio_store.finish(other,job,b'synthetic-mp3',2400)
                    result=audio_store.get(other,job)
                    assert result['actual_ms']==2400 and result['seconds_charged']==0
                    assert audio_store.get(owner,job) is None
                from kilas_ai import live_translator_realtime_check as proof
                with patch.object(proof,'verified',return_value=True):
                    def funded_claim(user):
                        try:
                            try:
                                _,lease=budget.claim(user,'dictate-pg-race-'+str(user),'a'*64,1000)
                                return lease
                            except budget.BudgetError as error:return error.code
                        finally:db._discard_cached_connection()
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        results=list(executor.map(funded_claim,(owner,other)))
                    # Each reserves62 microUSD; the existing100 allowance admits one.
                    leases=[value for value in results if isinstance(value,budget.Reservation)]
                    assert len(leases)==1 and 'budget_limit' in results,results
                    budget.cancel(leases[0].owner,leases[0].key)
                print('PASS: shared PostgreSQL checksum-idempotent sponsorship, zero balance, post-expiry settlement, tenant fences, atomic funding admission')
            print('PASS: Learning PostgreSQL additive/idempotent schema, concurrent claim, continued sessions, bounded context, stale recovery, owner fences, End')
    finally:
        db._discard_cached_connection()
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+isolated+' CASCADE')
        control.close()


if __name__=='__main__':main()
