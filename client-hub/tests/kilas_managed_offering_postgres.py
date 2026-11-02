"""Additive sponsorship migration + real PG account locking, disposable loopback only."""
import os,sys,uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
from decimal import Decimal
if os.environ.get('KILAS_MANAGED_POSTGRES_QA')!='1' or urlsplit(os.environ.get('DATABASE_URL','')).hostname not in ('localhost','127.0.0.1'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db,repo
from kilas_ai import usage,chat_models_schema,chat_offering as offering


def main():
    name='managed_'+uuid.uuid4().hex
    control=db.psycopg2.connect(db.DATABASE_URL);control.autocommit=True
    with control.cursor() as cur:cur.execute('CREATE SCHEMA '+name)
    original=db._postgres_connect_kwargs
    def options():
        settings=original();return dict(settings,options=settings['options']+' -c search_path='+name)
    try:
        with patch.object(db,'_postgres_connect_kwargs',side_effect=options):
            with patch.object(db,'MIGRATIONS',[m for m in db.MIGRATIONS if not m[0].startswith('0113_')]):db.init_schema()
            owner=repo.create_user('managed@example.test','hash')
            db.execute("INSERT INTO kilas_ai_usage(user_id,operation_key,operation_type,mode,status,estimated_cost_usd,created_at) VALUES(?,'legacy','CHAT','FAST','COMPLETE','0.05',?)",(owner,usage._now().isoformat()))
            chat_models_schema.apply_release('0113_kilas_chat_sponsorship');chat_models_schema.apply_release('0113_kilas_chat_sponsorship')
            assert db.query_one("SELECT customer_charge_exempt,estimated_cost_usd FROM kilas_ai_usage WHERE operation_key='legacy'")['customer_charge_exempt']==0
            with patch.dict(os.environ,{offering.CHAT_FREE_FLAG:'true',offering.IMAGE_FREE_FLAG:'true'}),patch('kilas_ai.topups.settle',side_effect=AssertionError('customer debit')):
                def claim(_):return usage.reserve(owner,None,'same_operation','FAST','CHAT')
                with ThreadPoolExecutor(4) as pool:results=list(pool.map(claim,range(4)))
                assert sum(bool(ops) for _,ops in results)==1,results
                assert db.query_one("SELECT COUNT(*) AS n FROM kilas_ai_usage WHERE operation_key='same_operation'")['n']==1
                usage.finish(owner,'same_operation',('CHAT',),success=True,provider='openai',model=offering.CHAT_MODEL,usage={'selected_model':offering.CHAT_MODEL,'input_tokens':100,'output_tokens':50})
                row=db.query_one("SELECT customer_charge_exempt,estimated_cost_usd FROM kilas_ai_usage WHERE operation_key='same_operation'")
                assert row['customer_charge_exempt']==1 and Decimal(row['estimated_cost_usd'])>0
                assert usage.snapshot(owner)['usage']['Chat']['used']==1 # only the legacy billed row
            print('PASS: additive migration twice, legacy cost preserved, 4 concurrent claims one reservation, sponsored cost/no customer settlement')
    finally:
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+name+' CASCADE')
        control.close()

if __name__=='__main__':main()
