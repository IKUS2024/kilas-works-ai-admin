"""Native ledger/dispatch rehearsal; disposable loopback PostgreSQL ONLY."""
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

if os.environ.get('KILAS_AI_POSTGRES_QA') != '1' or urlsplit(os.environ.get('DATABASE_URL','')).hostname not in ('localhost','127.0.0.1'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db
import repo
from kilas_ai import audio_schema, audio_store, live_translator_store as sessions
from kilas_ai import live_gemini as native, live_gemini_budget as budget, live_gemini_smoke as smoke


def main():
    isolated = 'gemini_qa_'+uuid.uuid4().hex
    control = db.psycopg2.connect(db.DATABASE_URL)
    control.autocommit = True
    with control.cursor() as cur:
        cur.execute('CREATE SCHEMA '+isolated)
    original = db._postgres_connect_kwargs
    def options():
        values = original()
        return dict(values,options=values['options']+' -c search_path='+isolated)
    try:
        with patch.object(db,'_postgres_connect_kwargs',side_effect=options):
            excluded=('0083_','0084_','0085_','0086_','0090_','0091_','0092_','0095_','0098_')
            with patch.object(db,'MIGRATIONS',[m for m in db.MIGRATIONS if not m[0].startswith(excluded)]):
                db.init_schema()
            for name in (audio_schema.NAME,'0084_kilas_personal_voice','0085_kilas_voice_preview','0086_kilas_voice_library',
                         '0090_kilas_audio_script_edit','0091_kilas_voice_script_transcription','0092_kilas_live_translator',
                         '0095_kilas_free_test','0098_kilas_live_session_output'):
                audio_schema.apply_release(name)
            owner = repo.create_user('native-pg@example.test','unused')
            db.execute('INSERT INTO kilas_audio_balances(user_id,seconds) VALUES (?,?)',(owner,300))
            config={'GEMINI_API_KEY':'synthetic-only', 'KILAS_LIVE_GEMINI_ENABLED':'true',
                    'KILAS_LIVE_GEMINI_BILLING_VERIFIED':'yes','KILAS_LIVE_GEMINI_ALLOWED_OWNER_ID':str(owner),
                    'KILAS_LIVE_GEMINI_CAMPAIGN':'pg-synthetic','KILAS_LIVE_GEMINI_BUDGET_MICRO_USD':'5000',
                    'KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD':'1000',
                    'KILAS_LIVE_GEMINI_EXPIRES_AT':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
                    'KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS':'600','KILAS_APP_FREE_TEST_ENABLED':'false'}
            with patch.dict(os.environ,config):
                ident = sessions.create(owner,'id','en',native.VOICE)
                key='live-'+'a'*32
                def admit(_):
                    try:
                        return budget.claim(owner,ident,key)
                    except budget.ledger.BudgetError as error:
                        return error.code
                    finally:
                        db._discard_cached_connection()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results=list(pool.map(admit,range(2)))
                reservations=[r for r in results if isinstance(r,budget.ledger.Reservation)]
                assert len(reservations)==1 and 'duplicate_turn' in results, results
                capability=reservations[0]
                budget.dispatch(capability)
                assert not budget.finish(capability,False)
                row=db.query_one('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE operation_key=?',(key+'-gm',))
                assert row['status']=='UNKNOWN' and row['charge_micro']==1000
                assert not budget.finish(capability,True)
                sessions.end(owner,ident)
                ident=sessions.create(owner,'id','en',native.VOICE)
                key='live-'+'b'*32
                with patch.object(native.Thread,'start'):
                    relay=native.start(owner,ident,key)
                with patch.object(native,'connect',side_effect=OSError('synthetic failed handshake')):
                    relay.run()
                row=db.query_one('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE operation_key=?',(key+'-gm',))
                assert row['status']=='UNKNOWN' and row['charge_micro']==1000
                assert audio_store.balance(owner)['available']==300
                assert audio_store.history_page(owner,kind='voiceover')['history_total']==0
                native.cancel(owner,ident);sessions.end(owner,ident)
                assert db.query_one('SELECT COUNT(*) AS n FROM kilas_audio_jobs WHERE source_content IS NOT NULL OR result_content IS NOT NULL OR original_script IS NOT NULL')['n']==0
                configured={'owner':owner,'email':'native-pg@example.test'}
                with ThreadPoolExecutor(max_workers=2) as pool:
                    def mark(_):
                        try:return smoke.once(configured)
                        finally:db._discard_cached_connection()
                    assert sorted(pool.map(mark,range(2)))==[False,True]
                assert not smoke.once(configured)
                marker=db.query_one('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE operation_key=?',('gemini-qa-'+smoke.RUN,))
                assert marker['status']=='CANCELLED' and marker['charge_micro']==0
                wrong_owner={'owner':owner,'email':'other@example.test'}
                try:smoke.once(wrong_owner)
                except ValueError as error:assert str(error)=='owner_mismatch'
                else:raise AssertionError('Owner mismatch admitted')
            print('PASS Gemini PostgreSQL: serialized admission, duplicate exclusion, durable unknown dispatch cost, idempotent settlement, unchanged customer balance, private native history')
    finally:
        db._discard_cached_connection()
        with control.cursor() as cur:
            cur.execute('DROP SCHEMA '+isolated+' CASCADE')
        control.close()


if __name__=='__main__':
    main()
