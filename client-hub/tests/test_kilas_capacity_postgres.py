"""Real shared-capacity locks/settlement in an isolated disposable PostgreSQL schema."""
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

if os.environ.get('KILAS_AI_POSTGRES_QA') != '1' or urlsplit(os.environ.get('DATABASE_URL', '')).hostname not in ('localhost','127.0.0.1'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import db,repo
from kilas_ai import usage,capacity,topups,model_policy


def main():
    isolated='capacity_qa_'+uuid.uuid4().hex
    control=db.psycopg2.connect(db.DATABASE_URL);control.autocommit=True
    with control.cursor() as cur:cur.execute('CREATE SCHEMA '+isolated)
    original=db._postgres_connect_kwargs
    def options():
        settings=original()
        return dict(settings,options=settings['options']+' -c search_path='+isolated)
    try:
        with patch.object(db,'_postgres_connect_kwargs',side_effect=options):
            db.init_schema()
            owner=repo.create_user('capacity@example.test','hash')
            now=usage._now()
            db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES(?,'PLUS','ACTIVE',?,?)",(owner,now-timedelta(days=1),now+timedelta(days=29)))
            db.execute("INSERT INTO kilas_ai_usage(user_id,operation_key,operation_type,mode,status,estimated_cost_usd,created_at) VALUES(?,'prior','CHAT','SMART','COMPLETE',?,?)",(owner,str(capacity.allowance()-Decimal('0.13')),now-timedelta(hours=1)))
            def reserve(key):
                try:return bool(usage.reserve(owner,None,key,'FAST','WEB')[1])
                except usage.UsageLimit:return False
            with ThreadPoolExecutor(2) as pool:assert sum(pool.map(reserve,['pg-race-a','pg-race-b']))==1
            usage.reserve(owner,None,'agent-chat-pg-normal-chat','FAST','CHAT')
            order=topups.create_order(owner,'MINI')
            db.execute('INSERT INTO kilas_ai_topup_credits(order_id,user_id,total_micro,expires_at) VALUES(?,?,?,?)',(order,owner,1000000,now+timedelta(days=90)))
            _,ops=usage.reserve(owner,None,'pg-topup','SMART','CHAT')
            usage.finish(owner,'pg-topup',ops,success=False,model=model_policy.SOL,usage={'input_tokens':1000,'output_tokens':1000})
            debit=db.query_one("SELECT charged_micro,status FROM kilas_ai_topup_debits WHERE user_id=? AND operation_key='pg-topup'",(owner,))
            assert debit['charged_micro']==12000 and debit['status']=='FAILED'
            usage.finish(owner,'pg-topup',ops,success=False,model=model_policy.SOL,usage={'input_tokens':9999,'output_tokens':9999})
            assert debit==db.query_one("SELECT charged_micro,status FROM kilas_ai_topup_debits WHERE user_id=? AND operation_key='pg-topup'",(owner,))
            db.execute('UPDATE kilas_ai_subscriptions SET period_end=? WHERE user_id=?',(now-timedelta(seconds=1),owner))
            before=topups.balance(owner)
            try:usage.reserve(owner,None,'pg-expired','FAST','IMAGE_GENERATE')
            except usage.UsageLimit:pass
            else:raise AssertionError('Expired subscription must not consume retained topup')
            assert before==topups.balance(owner)
            print('PASS PostgreSQL atomic shared capacity, normal Chat, billed failure, replay, expired subscription credit preservation')
    finally:
        conn=getattr(db._local,'conn',None)
        if conn:conn.close();db._local.conn=None
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+isolated+' CASCADE')
        control.close()


if __name__=='__main__':main()
