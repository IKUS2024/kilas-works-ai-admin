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
            with patch.object(db,'MIGRATIONS',[m for m in db.MIGRATIONS if not m[0].startswith(('0083_','0084_','0085_','0086_','0090_','0091_','0092_','0095_'))]):db.init_schema()
            before={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert schema.apply_release()==[schema.NAME];assert schema.apply_release()==[]
            after={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert after-before=={'kilas_audio_balances','kilas_audio_orders','kilas_audio_jobs','kilas_audio_releases'}
            assert schema.apply_release('0084_kilas_personal_voice')==['0084_kilas_personal_voice']
            assert schema.apply_release('0084_kilas_personal_voice')==[]
            assert schema.apply_release('0085_kilas_voice_preview')==['0085_kilas_voice_preview']
            assert schema.apply_release('0085_kilas_voice_preview')==[]
            assert schema.apply_release('0086_kilas_voice_library')==['0086_kilas_voice_library']
            assert schema.apply_release('0086_kilas_voice_library')==[]
            # A pre-release row remains untouched and cannot invent its source text.
            db.execute("INSERT INTO users(email,password_hash,role) VALUES ('pre-edit@example.test','hash','CLIENT_OWNER')")
            legacy_user=db.query_one("SELECT id FROM users WHERE email='pre-edit@example.test'")['id']
            db.execute("INSERT INTO kilas_audio_jobs(user_id,operation_key,fingerprint,mode,title,source_language,target_language,estimated_seconds,reserved_seconds,status,created_at,updated_at) VALUES (?,'pre-edit-key','synthetic','voiceover','Old title','id','en',2,0,'COMPLETED','2026-01-01','2026-01-01')",(legacy_user,))
            assert schema.apply_release('0090_kilas_audio_script_edit')==['0090_kilas_audio_script_edit']
            assert db.query_one('SELECT original_script FROM kilas_audio_jobs WHERE user_id=?',(legacy_user,))['original_script'] is None
            assert schema.apply_release('0090_kilas_audio_script_edit')==[]
            before_stt={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert schema.apply_release('0091_kilas_voice_script_transcription')==['0091_kilas_voice_script_transcription']
            assert schema.apply_release('0091_kilas_voice_script_transcription')==[]
            after_stt={r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
            assert after_stt-before_stt=={'kilas_vo_stt_campaigns','kilas_vo_stt_operations'}
            assert schema.apply_release('0092_kilas_live_translator')==['0092_kilas_live_translator']
            assert schema.apply_release('0092_kilas_live_translator')==[]
            assert schema.apply_release('0095_kilas_free_test')==['0095_kilas_free_test']
            assert schema.apply_release('0095_kilas_free_test')==[]
            with store.locked(0) as conn:
                user=usage._query(conn,"INSERT INTO users(email,password_hash,role) VALUES ('audio@example.test','hash','CLIENT_OWNER') RETURNING id",one=True)[0]
                admin=usage._query(conn,"INSERT INTO users(email,password_hash,role) VALUES ('audio-admin@example.test','hash','KILAS_ADMIN') RETURNING id",one=True)[0]
            from kilas_ai import live_translator_store as sessions, live_translator as live
            live_id=sessions.create(user,'id','en','kilas-male')
            def live_claim():
                try:sessions.claim(user,live_id,'live-'+'1'*32);return True
                except store.AudioError:return False
            with ThreadPoolExecutor(max_workers=2) as executor:assert sorted(executor.map(lambda _:live_claim(),range(2)))==[False,True]
            # Read fences must use the cached connection, never a new transaction
            # per translation token, while still seeing a separate worker's End.
            with patch.object(usage,'_connect',side_effect=AssertionError('Fresh read-fence connection')):
                for _ in range(20):assert sessions.check(user,live_id,'live-'+'1'*32)=={'language_a':'id','language_b':'en','voice_alias':'kilas-male'}
            assert db.get_connection().get_transaction_status()==db.psycopg2.extensions.TRANSACTION_STATUS_IDLE
            with patch.object(db,'query_one',wraps=db.query_one) as query:
                assert sessions.result(user,live_id,'live-'+'1'*32)['status']=='PROCESSING'
                assert query.call_count==1
            try:sessions.check(admin,live_id,'live-'+'1'*32);raise AssertionError('Foreign read fence accepted')
            except store.AudioError as error:assert error.code=='session_unavailable'
            try:sessions.check(user,live_id,'live-'+'2'*32);raise AssertionError('Missing turn accepted')
            except store.AudioError as error:assert error.code=='turn_cancelled'
            with ThreadPoolExecutor(max_workers=1) as executor:executor.submit(sessions.end,user,live_id).result(timeout=10)
            assert sessions.result(user,live_id,'live-'+'1'*32)['status']=='CANCELLED'
            try:sessions.check(user,live_id,'live-'+'1'*32);raise AssertionError('Ended session accepted')
            except store.AudioError:pass
            try:sessions.result(admin,live_id,'live-'+'1'*32);raise AssertionError('Foreign session accepted')
            except store.AudioError:pass
            # Actual driver: finite atomic cross-owner reservation and consistent cancel/submit locks.
            from kilas_ai import audio_transcription_budget as stt_budget
            from datetime import datetime,timezone,timedelta
            funded={'ELEVENLABS_API_KEY':'synthetic-only','KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'true','KILAS_VO_STT_CAMPAIGN':'native-pg-test','KILAS_VO_STT_GLOBAL_BUDGET_MICRO_USD':str(stt_budget.reserve_micro(2000)),'KILAS_VO_STT_ACCOUNT_BUDGET_MICRO_USD':str(stt_budget.reserve_micro(2000)),'KILAS_VO_STT_EXPIRES_AT':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'KILAS_VO_STT_PRICE_VERSION':stt_budget.PRICE_VERSION}
            with store.locked(0) as conn:
                another=usage._query(conn,"INSERT INTO users(email,password_hash,role) VALUES ('stt-other@example.test','hash','CLIENT_OWNER') RETURNING id",one=True)[0]
            def reserve_stt(owner):
                try:return stt_budget.claim(owner,'postgres-stt-operation-1234','a'*64,2000)[1]
                except stt_budget.BudgetError:return None
            with patch.dict(os.environ,funded):
                with ThreadPoolExecutor(max_workers=2) as pool:claims=list(pool.map(reserve_stt,(user,another)))
                assert sum(cap is not None for cap in claims)==1
                cap=next(cap for cap in claims if cap is not None)
                stt_budget.dispatch(cap,'a'*64,2000)
                with patch.dict(os.environ,{'KILAS_VOICE_VIDEO_SCRIPT_ENABLED':'false'}):assert stt_budget.finish(cap,True)
                assert db.query_one('SELECT charge_micro FROM kilas_vo_stt_operations WHERE user_id=?',(cap.owner,))['charge_micro']==stt_budget.reserve_micro(2000)
            # Real psycopg2 binding: percent wildcards belong in values, not SQL.
            # Cover both pre-STT allowance and owner-only Live admission queries.
            with store.locked(0) as conn:
                live_owner=usage._query(conn,"INSERT INTO users(email,password_hash,role) VALUES ('live-pg@example.test','hash','CLIENT_OWNER') RETURNING id",one=True)[0]
            live_funded=dict(funded,KILAS_VO_STT_CAMPAIGN='native-pg-live',KILAS_VO_STT_USAGE_MODE='owner',
                KILAS_VO_STT_ALLOWED_OWNER_ID=str(live_owner),KILAS_VO_STT_GLOBAL_BUDGET_MICRO_USD='90000',
                KILAS_VO_STT_ACCOUNT_BUDGET_MICRO_USD='60000',KILAS_LIVE_TRANSLATOR_USAGE_MODE='qa',
                KILAS_LIVE_TRANSLATOR_AUDIO_SECONDS='120')
            with patch.dict(os.environ,live_funded):
                live.require_audio_allowance(live_owner)
                for number in range(4):
                    key='live-'+str(number).zfill(32)
                    _,cap=stt_budget.claim(live_owner,key,'a'*64,2000)
                    assert cap is not None
                    stt_budget.cancel(live_owner,key)
                try:stt_budget.claim(live_owner,'live-'+'9'*32,'a'*64,2000);raise AssertionError('Live QA limit not enforced')
                except stt_budget.BudgetError as error:assert error.code=='attempt_limit'
            funded.update(KILAS_VO_STT_CAMPAIGN='native-pg-cancel',KILAS_VO_STT_GLOBAL_BUDGET_MICRO_USD='90000',KILAS_VO_STT_ACCOUNT_BUDGET_MICRO_USD='60000')
            with patch.dict(os.environ,funded):
                def race(action):
                    if action=='cancel':return stt_budget.cancel(another,'postgres-cancel-operation-1234')
                    return stt_budget.claim(another,'postgres-cancel-operation-1234','b'*64,2000)
                with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(race,('submit','cancel')))
                assert stt_budget.owned(another,'postgres-cancel-operation-1234')['status']=='CANCELLED'
                _,cap=stt_budget.claim(user,'postgres-overrun-operation-1234','c'*64,2000)
                stt_budget.dispatch(cap,'c'*64,2000)
                with store.locked(0) as conn:usage._query(conn,"UPDATE kilas_vo_stt_campaigns SET price_version='legacy-openai' WHERE id=?",('native-pg-cancel',))
                assert not stt_budget.finish(cap,True)
                assert db.query_one('SELECT charge_micro FROM kilas_vo_stt_operations WHERE user_id=? AND operation_key=?',(user,cap.key))['charge_micro']==stt_budget.reserve_micro(2000)
                assert db.query_one('SELECT blocked FROM kilas_vo_stt_campaigns WHERE id=?',('native-pg-cancel',))['blocked']==1
            with patch.object(media,'voice_sample',return_value=b'synthetic-voice'),patch.object(media,'personal_preview',return_value=b'private-preview'),patch.object(provider,'clone_voice',return_value='privatePostgres123') as clone:
                personal.create(user,'postgres-personal-key-1234',None)
                personal.create(user,'postgres-personal-key-1234',None)
                clone.assert_called_once()
                assert personal.get(user)=='privatePostgres123' and personal.get(admin)==''
                assert personal.preview(user)==b'private-preview' and personal.preview(admin) is None
            legacy=personal.saved_voices(user)
            assert len(legacy)==1 and len(personal.saved_voices(user))==1
            assert personal.saved(admin,legacy[0]['id']) is None
            with patch.object(media,'voice_sample',return_value=b'synthetic-voice'),patch.object(media,'personal_preview',return_value=b'named-preview'),patch.object(provider,'clone_voice',return_value='secondPostgresPrivate'):
                named=personal.save_named(user,'postgres-named-key-1234',None,'Narasi Kedua')
            assert personal.saved_preview(user,named['id'])==b'named-preview'
            assert personal.saved_preview(admin,named['id']) is None
            personal.rename_saved(user,named['id'],'Narasi Inggris')
            assert personal.saved(user,named['id'])['name']=='Narasi Inggris'
            with patch.object(provider,'request',return_value={}):personal.delete_saved(user,named['id'])
            assert personal.saved(user,named['id']) is None
            assert len(personal.saved_voices(user))==1
            with patch.object(media,'voice_sample',return_value=b'synthetic-voice'),patch.object(media,'personal_preview',return_value=b'replacement-preview'),patch.object(provider,'clone_voice',side_effect=provider.ProviderError()):
                try:personal.create(user,'postgres-replace-key-1234',None,True)
                except provider.ProviderError:pass
                else:raise AssertionError('replacement failure was not surfaced')
                assert personal.get(user)=='privatePostgres123'
                assert personal.preview(user)==b'private-preview'
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
            store.submitted(user,ident,'provider123')
            large=b'synthetic-video'*(1024*1024)
            original_query=usage._query
            def bounded_query(conn,sql,params=(),one=False):
                assert all(len(v)<=512*1024 for v in params if isinstance(v,bytes))
                return original_query(conn,sql,params,one)
            def interrupted_query(conn,sql,params=(),one=False):
                if 'result_content || ?' in sql:raise RuntimeError('synthetic interrupted save')
                return bounded_query(conn,sql,params,one)
            with patch.object(usage,'_query',side_effect=interrupted_query):
                try:store.finish(user,ident,large,36500)
                except RuntimeError:pass
                else:raise AssertionError('interrupted save did not fail')
            assert store.balance(user)['seconds']==60
            row=db.query_one('SELECT status,result_content,seconds_charged FROM kilas_audio_jobs WHERE id=?',(ident,))
            assert row['status']=='PROCESSING' and row['result_content'] is None and row['seconds_charged']==0
            with patch.object(usage,'_query',side_effect=bounded_query):
                assert store.finish(user,ident,large,36500)
            assert bytes(db.query_one('SELECT result_content FROM kilas_audio_jobs WHERE id=?',(ident,))['result_content'])==large
            assert store.balance(user)['seconds']==23
            assert store.finish(user,ident,b'duplicate',36500) is False
            assert store.get(user+999,ident) is None
            assert schema.apply_release()==[];assert store.balance(user)['seconds']==23
            assert usage.effective_plan(user)['plan']=='FREE'
            # Native psycopg2 + additive schema: exact original survives payload cleanup.
            assert db.query_one('SELECT original_script FROM kilas_audio_jobs WHERE id=?',(ident,))['original_script'] is None
            original_text='  ORIGINAL <script> is text\nBahasa asli  '
            voice,_=store.create(user,'postgres-edit-original-1234','voiceover','QA','id','en','voice','QA','Translated TTS',0,None,2,5,original_script=original_text)
            assert store.start(user,voice);store.submitted(user,voice,'synthetic-edit')
            payload=db.query_one('SELECT script,original_script FROM kilas_audio_jobs WHERE id=?',(voice,))
            assert payload['script'] is None and payload['original_script']==original_text
            assert store.edit_script(user,voice) is None
            assert store.finish(user,voice,b'ID3synthetic',2000)
            assert store.edit_script(user,voice)==original_text and store.edit_script(admin,voice) is None
            with db.psycopg2.connect(db.DATABASE_URL,**db._postgres_connect_kwargs()) as bounded:
                try:
                    with bounded.cursor() as cur:cur.execute('UPDATE kilas_audio_jobs SET original_script=%s WHERE id=%s',('x'*4001,voice))
                except db.psycopg2.errors.CheckViolation:bounded.rollback()
                else:raise AssertionError('original-script bound was not enforced by PostgreSQL')
            assert store.edit_script(user,voice)==original_text
            assert store.balance(user)['seconds']==21
            assert store.finish(user,voice,b'duplicate',2000) is False
            assert store.balance(user)['seconds']==21
            failed,_=store.create(user,'postgres-edit-failed-1234','voiceover','QA','id','en','voice','QA','TTS',0,None,2,5,original_script=original_text)
            store.fail(user,failed,'synthetic-failure')
            assert db.query_one('SELECT original_script FROM kilas_audio_jobs WHERE id=?',(failed,))['original_script']==original_text
            assert store.edit_script(user,failed)==original_text
            assert schema.apply_release('0090_kilas_audio_script_edit')==[]
    finally:
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+isolated+' CASCADE')
        control.close()
    print('PASS Audio PostgreSQL additive/checksum/concurrent purchase/reservation/bytea/settlement/isolation')


if __name__=='__main__':main()
