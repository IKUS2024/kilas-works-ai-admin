"""Atomic diagnostic admission on disposable loopback PostgreSQL; no inference."""
import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

if os.environ.get('KILAS_VISION_POSTGRES_QA') != '1' or urlsplit(os.environ.get('DATABASE_URL','')).hostname not in ('localhost','127.0.0.1'):
    raise SystemExit('Explicit disposable loopback PostgreSQL required')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db
import repo
from kilas_ai import store, vision_experiment as experiment, chat_models_schema


def main():
    name = 'vision_'+uuid.uuid4().hex
    control = db.psycopg2.connect(db.DATABASE_URL);control.autocommit=True
    with control.cursor() as cur:cur.execute('CREATE SCHEMA '+name)
    original = db._postgres_connect_kwargs
    def options():
        config = original()
        return dict(config, options=config['options']+' -c search_path='+name)
    try:
        with patch.object(db,'_postgres_connect_kwargs',side_effect=options), \
             patch('requests.sessions.Session.request',side_effect=AssertionError('No provider traffic')):
            with patch.object(db,'MIGRATIONS',[m for m in db.MIGRATIONS if not m[0].startswith('0114_')]):db.init_schema()
            owner = repo.create_user('vision@example.test','hash')
            other = repo.create_user('other-vision@example.test','hash')
            db.execute("INSERT INTO kilas_ai_usage(user_id,operation_key,operation_type,mode,status,estimated_cost_usd,created_at) VALUES(?,'retained','CHAT','FAST','COMPLETE','0.05',?)",(owner,datetime.now(timezone.utc).isoformat()))
            chat_models_schema.apply_release('0114_kilas_vision_eval')
            chat_models_schema.apply_release('0114_kilas_vision_eval')
            now = datetime.now(timezone.utc)
            raw = {'owner_id':owner,'batch':uuid.uuid4().hex,'question':'Identify this object.',
                'starts_at':(now-timedelta(minutes=1)).isoformat().replace('+00:00','Z'),
                'expires_at':(now+timedelta(minutes=20)).isoformat().replace('+00:00','Z')}
            with patch.dict(os.environ,{experiment.FLAG:json.dumps(raw)}):config=experiment.configured()
            def thread(user=owner, question=raw['question']):
                ident=store.create_thread(user)
                store.append_user_once(user,ident,question,'SMART','vision_'+uuid.uuid4().hex)
                return ident
            cases=[thread() for _ in range(12)]
            with ThreadPoolExecutor(12) as pool:
                slots=list(pool.map(lambda ident:experiment._claim(config,owner,ident),cases))
            assert sorted(s for s in slots if s is not None)==list(range(1,9)),slots
            accepted=[(ident,slot) for ident,slot in zip(cases,slots) if slot]
            ident,slot=accepted[0]
            assert experiment._claim(config,owner,ident)==slot
            assert experiment._claim(config,owner,thread(other)) is None
            assert experiment._claim(config,other,thread(other)) is None
            changed={**raw,'owner_id':other}
            with patch.dict(os.environ,{experiment.FLAG:json.dumps(changed)}):replacement=experiment.configured()
            assert experiment._claim(replacement,other,thread(other)) is None
            with patch.object(experiment,'_now',return_value=config['_end']):
                assert experiment._claim(config,owner,thread()) is None
            store.delete_thread(owner,ident)
            assert experiment._claim(config,owner,thread()) is None
            assert db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_vision_eval_claims')['n']==8
            row=db.query_one("SELECT status,estimated_cost_usd FROM kilas_ai_usage WHERE operation_key='retained'")
            assert row['status']=='COMPLETE' and row['estimated_cost_usd']=='0.05'
            assert db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_usage')['n']==1
            print('PASS: migration twice;12 concurrent claims admit8 stable slots;idempotent;owner/expiry/cap fences;chat deletion does not replenish;existing usage untouched;zero provider calls')
    finally:
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+name+' CASCADE')
        control.close()


if __name__=='__main__':main()
