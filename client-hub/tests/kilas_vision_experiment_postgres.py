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
from contextlib import ExitStack
from types import SimpleNamespace

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
            # Exercise the actual automatic blueprint hook; leave older releases
            # outside this focused test and execute the new checksum helper for real.
            from kilas_ai import chat_model_routes
            from kilas_ai.routes import ai_bp
            prepare_chat_models=next(callback for callback in ai_bp.deferred_functions if callback.__name__=='prepare_chat_models')
            real_apply=chat_models_schema.apply_release
            applied=[]
            def narrow(name='0102_kilas_chat_models'):
                applied.append(name)
                if name=='0114_kilas_vision_eval':real_apply(name)
            with ExitStack() as stack:
                stack.enter_context(patch.object(db,'init_schema',side_effect=AssertionError('No broad boot migration')))
                stack.enter_context(patch.object(chat_models_schema,'apply_release',side_effect=narrow))
                stack.enter_context(patch.dict(os.environ,{'KILAS_AI_ENABLED':'true','RUN_MIGRATIONS_ON_BOOT':'false',experiment.FLAG:''}))
                for target in ('kilas_ai.workspace_execution_proof.maybe_start','kilas_ai.workspace_execution_access.log_readiness',
                               'kilas_ai.workspace_large_proof.maybe_start','kilas_ai.workspace_document_runtime.maybe_start'):
                    stack.enter_context(patch(target))
                prepare_chat_models(SimpleNamespace(first_registration=True,app=SimpleNamespace(testing=True)))
            assert applied.count('0114_kilas_vision_eval')==1
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
            print('PASS: actual startup hook installs0114 without broad migration;checksum apply twice;12 concurrent claims admit8 stable slots;idempotent;owner/expiry/cap fences;chat deletion does not replenish;existing usage untouched;zero provider calls')
    finally:
        with control.cursor() as cur:cur.execute('DROP SCHEMA '+name+' CASCADE')
        control.close()


if __name__=='__main__':main()
