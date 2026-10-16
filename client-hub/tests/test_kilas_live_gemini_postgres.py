"""Native ledger/dispatch rehearsal; disposable loopback PostgreSQL ONLY."""
import os
import hashlib
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
                # Distinct renewal keys cannot bypass owner concurrency across
                # processes: admission holds the same PostgreSQL advisory lock.
                def admit_distinct(n):
                    try:
                        return budget.claim(owner,ident,'live-'+str(n)*32)
                    except budget.ledger.BudgetError as error:
                        return error.code
                    finally:
                        db._discard_cached_connection()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    distinct=list(pool.map(admit_distinct,(1,2)))
                capabilities=[r for r in distinct if isinstance(r,budget.ledger.Reservation)]
                assert len(capabilities)==1 and 'already_processing' in distinct, distinct
                budget.dispatch(capabilities[0]);budget.finish(capabilities[0],False)
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
                remaining=dict(configured,remaining=True)
                try:smoke.once(remaining)
                except ValueError as error:assert str(error)=='remaining_test_not_available'
                else:raise AssertionError('Remaining session without failed first admitted')
                ident=sessions.create(owner,'id','en',native.VOICE)
                key='live-'+hashlib.sha256((smoke.RUN+'id'+'en').encode()).hexdigest()[:32]
                with patch.object(native.Thread,'start'):relay=native.start(owner,ident,key)
                class InvalidSetup:
                    def send(self,raw):pass
                    def recv(self):return '{"unrecognized":true}'
                    def shutdown(self):pass
                with patch.object(native,'connect',return_value=InvalidSetup()):relay.run()
                native.cancel(owner,ident);sessions.end(owner,ident)
                db.execute("UPDATE kilas_vo_stt_operations SET status='DISPATCHED',finished_at=NULL,created_at=? WHERE user_id=? AND operation_key=?",
                           ((datetime.now(timezone.utc)-timedelta(minutes=3)).isoformat(),owner,key+'-gm'))
                assert smoke.once(remaining)
                assert not smoke.once(remaining)
                recovered=db.query_one('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(owner,key+'-gm'))
                assert recovered['status']=='UNKNOWN' and recovered['charge_micro']==1000
                # Standing owner policy includes historical QA, even after
                # campaign rotation; admission still uses the PG global lock.
                prior=db.query_one('SELECT SUM(charge_micro) AS n FROM kilas_vo_stt_operations WHERE campaign LIKE ?',('gml-%',))['n']
                lifetime={'KILAS_LIVE_GEMINI_POLICY':'owner_lifetime',
                          'KILAS_LIVE_GEMINI_IDR_CEILING_VERIFIED':'yes',
                          'KILAS_LIVE_GEMINI_IDR_PER_USD_CEILING':'25000',
                          'KILAS_LIVE_GEMINI_TOTAL_IDR':'500000',
                          'KILAS_LIVE_GEMINI_CAMPAIGN':'pg-standing',
                          'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD':str(prior+100000),
                          'KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD':'100000',
                          'KILAS_LIVE_GEMINI_EXPIRES_AT':''}
                with patch.dict(os.environ,lifetime):
                    standing=budget.claim(owner,'c'*48,'live-'+'c'*32)
                    budget.dispatch(standing);budget.finish(standing,False)
                    assert budget.policy()['expires_at']=='owner-lifetime-v1'
                    with patch.dict(os.environ,{'KILAS_LIVE_GEMINI_CAMPAIGN':'pg-standing-rotated'}):
                        try:budget.claim(owner,'d'*48,'live-'+'d'*32)
                        except budget.ledger.BudgetError as error:assert error.code=='budget_limit'
                        else:raise AssertionError('Standing cap reset by campaign rotation')
                # Explicit internal assumptions need no fabricated verified FX.
                # The guard is inclusive of every historical native campaign.
                historical=db.query_one('SELECT SUM(charge_micro) AS n FROM kilas_vo_stt_operations WHERE campaign LIKE ?',('gml-%',))['n']
                internal={'KILAS_LIVE_GEMINI_POLICY':'owner_lifetime',
                          'KILAS_LIVE_GEMINI_IDR_VALUATION_MODE':'conservative_internal',
                          'KILAS_LIVE_GEMINI_INTERNAL_VALUATION_ACK':'yes',
                          'KILAS_LIVE_GEMINI_IDR_CEILING_VERIFIED':'',
                          'KILAS_LIVE_GEMINI_IDR_PER_USD_INTERNAL':'25000',
                          'KILAS_LIVE_GEMINI_INTERNAL_GUARD_IDR':'250000',
                          'KILAS_LIVE_GEMINI_TOTAL_IDR':'500000',
                          'KILAS_LIVE_GEMINI_CAMPAIGN':'pg-conservative-internal',
                          'KILAS_LIVE_GEMINI_BUDGET_MICRO_USD':str(historical+250000),
                          'KILAS_LIVE_GEMINI_LEASE_RESERVE_MICRO_USD':'250000'}
                with patch.dict(os.environ,internal):
                    snapshot=budget.status(owner)
                    assert snapshot['charged_micro_usd']==historical and snapshot['remaining_leases']==1, snapshot
                    conservative=budget.claim(owner,'e'*48,'live-'+'e'*32)
                    budget.dispatch(conservative);budget.finish(conservative,False)
                    assert budget.status(owner)['reason']=='budget_limit'
                    with patch.dict(os.environ,{'KILAS_LIVE_GEMINI_CAMPAIGN':'pg-conservative-rotated'}):
                        try:budget.claim(owner,'f'*48,'live-'+'f'*32)
                        except budget.ledger.BudgetError as error:assert error.code=='budget_limit'
                        else:raise AssertionError('Internal allowance reset by campaign rotation')
                # Two authenticated accounts contend for one final GLOBAL
                # reserve. Funding ownership does not make this cap per user.
                member=repo.create_user('native-member-pg@example.test','unused',role='CLIENT_MEMBER')
                admin=repo.create_user('native-admin-pg@example.test','unused',role='KILAS_ADMIN')
                prior_shared=db.query_one('SELECT SUM(charge_micro) AS n FROM kilas_vo_stt_operations WHERE campaign LIKE ?',('gml-%',))['n']
                shared=dict(internal,KILAS_LIVE_GEMINI_CAMPAIGN='pg-authenticated-shared',
                            KILAS_LIVE_GEMINI_BUDGET_MICRO_USD=str(prior_shared+250000),
                            KILAS_LIVE_GEMINI_AUDIENCE='authenticated')
                with patch.dict(os.environ,shared):
                    shared_policy=budget.policy()
                    assert shared_policy['allowed_owner']==owner
                    assert budget.allowed(member) and budget.allowed(admin)
                    assert not budget.allowed(True) and not budget.allowed(10**9)
                    with patch.dict(os.environ,{'KILAS_LIVE_GEMINI_AUDIENCE':'owner'}):
                        private_policy=budget.policy()
                        assert private_policy['id']==shared_policy['id']
                        assert private_policy['price_version']==shared_policy['price_version']
                        assert not budget.allowed(member) and not budget.allowed(admin)
                    def contend(user):
                        try:return budget.claim(user,'9'*48,'live-'+format(user,'032x'))
                        except budget.ledger.BudgetError as error:return error.code
                        finally:db._discard_cached_connection()
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        raced=list(pool.map(contend,(member,admin)))
                    winners=[item for item in raced if isinstance(item,budget.ledger.Reservation)]
                    assert len(winners)==1 and 'budget_limit' in raced, raced
                    winner=winners[0]
                    loser=admin if winner.owner==member else member
                    forged=budget.ledger.Reservation(loser,winner.key,winner.lease)
                    for action in (lambda:budget.dispatch(forged),lambda:budget.finish(forged,False)):
                        try:action()
                        except budget.ledger.BudgetError as error:assert error.code=='invalid_reservation'
                        else:raise AssertionError('Cross-account nonce accepted')
                    try:budget.claim(winner.owner,'9'*48,'live-'+'9'*32)
                    except budget.ledger.BudgetError as error:assert error.code=='already_processing'
                    else:raise AssertionError('Two active native operations for one user')
                    budget.dispatch(winner)
                    db.execute('INSERT INTO customer_auth_account_state(user_id,disabled) VALUES (?,1) ON CONFLICT(user_id) DO UPDATE SET disabled=1',(winner.owner,))
                    assert not budget.allowed(winner.owner)
                    with patch.dict(os.environ,{'KILAS_LIVE_GEMINI_ENABLED':'false','KILAS_LIVE_GEMINI_AUDIENCE':'owner'}):
                        assert not budget.finish(winner,False)
                    assert budget.status(loser)['reason']=='budget_limit'
                    retained=db.query_one('SELECT status,charge_micro FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(winner.owner,winner.key))
                    assert retained['status']=='UNKNOWN' and retained['charge_micro']==250000
                    assert budget.status(loser)['charged_micro_usd']==prior_shared+250000
            print('PASS Gemini PostgreSQL: serialized owner/cross-account admission, one global lifetime cap, authenticated roles and disabled-account fences, nonce ownership, historical accounting, durable unknown dispatch cost, unchanged customer balance/history')
    finally:
        db._discard_cached_connection()
        with control.cursor() as cur:
            cur.execute('DROP SCHEMA '+isolated+' CASCADE')
        control.close()


if __name__=='__main__':
    main()
