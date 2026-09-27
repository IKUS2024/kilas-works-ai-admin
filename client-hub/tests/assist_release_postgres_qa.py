"""Explicit disposable loopback PostgreSQL rehearsal. Never accepts a remote database.

Run in the same process environment as the local PG server with DATABASE_URL set.
The random schema is removed on exit; financial assertions compare exact seeded rows.
"""
import os
import json
import uuid
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
import sys

target=urlsplit(os.environ.get('DATABASE_URL',''))
if os.environ.get('KILAS_ASSIST_POSTGRES_QA') != '1' or target.hostname not in ('localhost','127.0.0.1'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db,repo,assist_schema,assist_demo,assist_journey
import finance_service as finance


def main():
    schema='assist_qa_'+uuid.uuid4().hex
    control=db.psycopg2.connect(db.DATABASE_URL)
    control.autocommit=True
    with control.cursor() as cur:
        cur.execute('CREATE SCHEMA '+schema)
        cur.execute('SELECT version()')
        print(cur.fetchone()[0].split(' on ')[0],flush=True)
    original_options=db._postgres_connect_kwargs
    def options():
        value=original_options()
        return dict(value,options=value['options']+' -c search_path='+schema)
    try:
        with patch.object(db,'_postgres_connect_kwargs',side_effect=options):
            # Build a synthetic baseline only. Production never replays this historical chain.
            baseline=[pair for pair in db.MIGRATIONS if not pair[0].startswith(('0066','0067','0068','0069','0070'))]
            with patch.object(db,'MIGRATIONS',baseline):db.init_schema()
            uid=repo.create_user('owner@synthetic.invalid','unused')
            bid=repo.create_business(uid,'Synthetic protected ledger','AI_ADMIN')
            other=repo.create_business(uid,'Second synthetic business','AI_ADMIN')
            finance.ensure_finance_defaults(bid,actor_user_id=uid)
            account=finance.create_account(bid,'Synthetic bank',opening_balance_minor=12345,actor_user_id=uid)
            category=finance.list_categories(bid,'INCOME',actor_user_id=uid)[0]['id']
            finance.create_transaction(bid,'INCOME',6789,account,category,'2026-09-27',actor_user_id=uid)
            tables=[r['table_name'] for r in db.query_all("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name LIKE ? ORDER BY table_name",('finance_%',))]
            def snapshot():
                return {table:sorted(json.dumps(row,sort_keys=True,default=str) for row in db.query_all('SELECT * FROM '+table)) for table in tables}
            before=snapshot();db.reset_connection_for_new_db_path()
            original_read=Path.read_text
            def invalid_final(path,*args,**kwargs):
                if path.name=='0070_assist_business_media_postgres.sql':return 'SELECT nonexistent_migration_function();'
                return original_read(path,*args,**kwargs)
            try:
                with patch.object(Path,'read_text',invalid_final):assist_schema.apply_release()
            except db.psycopg2.Error:pass
            else:raise AssertionError('failed migration must roll back')
            assert db.query_one("SELECT to_regclass('kw_assist_demo_sessions') AS name")['name'] is None
            assert snapshot()==before
            db.reset_connection_for_new_db_path()
            assert assist_schema.apply_release()==list(assist_schema.MIGRATIONS)
            assert assist_schema.apply_release()==[]
            assert snapshot()==before
            import assist_business_media as media
            fid=repo.save_business_file(bid,'synthetic.png','image/png',3,b'qa!','Synthetic item Rp123',uid)
            db.execute('''INSERT INTO kw_assist_business_media
                (file_id,business_id,summary,knowledge,usage_instruction,approved_send,version,actor_id)
                VALUES (?,?,?,?,?,1,?,?)''',(fid,bid,'Synthetic item','Synthetic item Rp123','On request','v1',uid))
            assert bytes(media.get(bid,fid,content=True)['content'])==b'qa!'
            assert media.get(other,fid,content=True) is None
            foreign_file=repo.save_business_file(other,'foreign.pdf','application/pdf',3,b'qa!','Other item',uid)
            try:
                db.execute('''INSERT INTO kw_assist_business_media
                    (file_id,business_id,summary,knowledge,usage_instruction,approved_send,version,actor_id)
                    VALUES (?,?,?,?,?,1,?,?)''',(foreign_file,bid,'Foreign','Foreign','Never','v2',uid))
            except db.psycopg2.IntegrityError:pass
            else:raise AssertionError('cross-tenant original FK must reject')
            media.remove(bid,fid,uid)
            assert media.files(bid)==[]
            assert repo.get_business_file_content(foreign_file,other) is not None
            assert snapshot()==before
            from public_chat import schema as chat_schema
            from kilas_core import customer_schema,job_schema,operation_schema,finance_bridge_schema,whatsapp_schema
            for installer in (chat_schema,customer_schema,job_schema,operation_schema,finance_bridge_schema,whatsapp_schema):
                installer.apply_schema()
            import assist_costs,platform_control
            assert assist_costs.customer_usage(bid)['replies']==0
            assert platform_control.overview(platform_control.businesses())['Businesses']==2
            assert platform_control.economics()['revenue']==0
            assert platform_control.system()['Finance bridge']=='Tables reachable'
            assert snapshot()==before
            state=dict(ready=True,connected=False,demo_active=True,paid=False,onboarding_complete=True,
                       demo_expires_at=datetime.now(timezone.utc)+timedelta(days=7))
            with patch.object(assist_journey,'state',return_value=state):
                sid,code=assist_demo.launch(bid,uid)
                assert assist_demo.launch(bid,uid,code)==(sid,code)
                second,second_code=assist_demo.begin(other,uid)
            bound=assist_demo.resolve('628111111111',code)
            assert bound['business_id']==bid
            # Native transactions must reuse the binding without lock loss or rebind.
            with patch.object(assist_journey,'state',return_value=state), \
                    patch.object(assist_demo,'begin',side_effect=AssertionError('do not rebind')):
                assert assist_demo.launch(bid,uid)==(sid,None)
            import assist_training
            with patch.object(assist_training.ai_onboarding,'_call_claude',return_value=(json.dumps(
                    dict(reply='Harga terbaru Rp175.000.',knowledge='Harga sekarang Rp175.000.')), 'end_turn', None)):
                assist_training.teach(repo.get_business(bid),uid,'Harga sekarang Rp175.000.')
            assist_training.ready(repo.get_business(bid),uid)
            assert assist_demo.active_binding(bid)['id']==sid
            assert '175.000' in str(assist_training.context(bid))
            assert repo.get_ai_settings(bid)['ai_status']=='DONE'
            assert assist_demo.binding(other) is None
            try:assist_demo.resolve('628222222222',code)
            except ValueError:pass
            else:raise AssertionError('token already bound must reject different sender')
            moved=assist_demo.resolve('628111111111',second_code)
            assert moved['business_id']==other
            assert not db.query_one('SELECT active FROM kw_assist_demo_sessions WHERE id=?',(sid,))['active']
            assert snapshot()==before
            db.reset_connection_for_new_db_path()
            print('PASS: atomic migration rollback, additive apply, idempotent retry, exact Finance preservation, tenant binding/rebind isolation',flush=True)
    finally:
        db.reset_connection_for_new_db_path()
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+schema+' CASCADE')
        control.close()


if __name__=='__main__':main()
