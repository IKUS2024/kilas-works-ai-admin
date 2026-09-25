"""Release-only rehearsal on an EMPTY loopback PostgreSQL 18 database.

Historical SQL builds a synthetic pre-release fixture only. The upgrade sequence
never calls init_schema or the historical migration runner. No production target
or copied customer data is accepted.
"""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
HUB = ROOT / 'client-hub'
ROLLBACK = '05d50a8bdf14ede2b1ec588f1fe78619f7387f0c'
target = urlsplit(os.environ.get('DATABASE_URL', ''))
if (os.environ.get('KILAS_PHASE10_POSTGRES_QA') != '1'
        or target.hostname not in ('127.0.0.1', 'localhost')
        or target.path != '/kilas_phase10'):
    raise SystemExit('Explicit disposable loopback kilas_phase10 QA target required')
baseline = Path(os.environ['KILAS_PHASE10_BASELINE_DIR']).resolve()
actual = subprocess.check_output(['git', '-C', str(baseline), 'rev-parse', 'HEAD'], text=True).strip()
if actual != ROLLBACK:
    raise SystemExit('Baseline must match the recorded production rollback SHA')

import psycopg2
from psycopg2 import sql


def connect():
    return psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=10,
        options='-c statement_timeout=30000 -c lock_timeout=5000')


def execute_script(content):
    connection = connect()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(content)
    finally:
        connection.close()


def query(statement):
    connection = connect()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(statement)
                return cursor.fetchall()
    finally:
        connection.close()


assert query('SHOW server_version_num')[0][0].startswith('18'), 'PostgreSQL 18 required'
assert not query("SELECT tablename FROM pg_tables WHERE schemaname='public'"), 'Empty QA database required'
# Fixture creation ONLY, from the exact rollback checkout. No init_schema call.
tree = ast.parse((baseline / 'client-hub/db.py').read_text())
registry = next(ast.literal_eval(node.value) for node in tree.body
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'MIGRATIONS' for t in node.targets))
assert all(int(name[:4]) < 55 for _, name in registry)
for _, name in registry:
    execute_script((baseline / 'client-hub/migrations' / name).read_text())

env = dict(os.environ, RUN_MIGRATIONS_ON_BOOT='false', KILAS_FINANCE_ACCESS_MODE='internal_beta',
           KILAS_FINANCE_BETA='on', KILAS_FINANCE_EMERGENCY_DISABLE='false')
seed = '''
import json,repo,finance_service as f,finance_branches as branches
uid=repo.create_user('release-fixture@example.test','unused')
bid=repo.create_business(uid,'Synthetic release fixture',package='NONE')
f.ensure_finance_defaults(bid,actor_user_id=uid)
branch=branches.list_branches(bid,uid)[0]['id']
with branches.scope(bid,branch,uid):
 account=f.create_account(bid,'QA bank','BANK',currency='IDR',opening_balance_minor=100000,actor_user_id=uid)
 income=f.list_categories(bid,'INCOME',actor_user_id=uid)[0]['id']
 expense=f.list_categories(bid,'EXPENSE',actor_user_id=uid)[0]['id']
 f.create_transaction(bid,'INCOME',12300,account,income,'2026-09-10',actor_user_id=uid)
 f.create_transaction(bid,'EXPENSE',2300,account,expense,'2026-09-10',actor_user_id=uid)
 customer=f.create_customer(bid,'Synthetic customer',actor_user_id=uid)
 invoice=f.create_finance_invoice(bid,customer,'2026-09-01','2026-09-30',
   [dict(description='QA service',quantity=1,unit_price_minor=50000)],actor_user_id=uid)
 f.issue_finance_invoice(bid,invoice,actor_user_id=uid)
 f.record_invoice_payment(bid,invoice,20000,'2026-09-10',account,income,
   actor_user_id=uid,idempotency_key='phase10-synthetic-payment')
 f.create_recurring_expense(bid,'Synthetic bill',1000,account,expense,'MONTHLY','2026-10-01',actor_user_id=uid)
print(json.dumps(dict(uid=uid,bid=bid,branch=branch,invoice=invoice)))
'''
result = subprocess.check_output([sys.executable, '-c', seed], cwd=baseline / 'client-hub',
    env=dict(env, PYTHONPATH=str(baseline / 'client-hub')), text=True)
identity = json.loads(result.strip().splitlines()[-1])
legacy_tables = [r[0] for r in query("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]


def snapshot():
    # Compare all pre-existing table rows, not just balances or row counts.
    # 0059 adds only a default-zero column to existing Finance rows.
    return {table: query(sql.SQL("SELECT (to_jsonb(t)-'relocation_version')::text FROM {} t ORDER BY 1")
                        .format(sql.Identifier(table))) for table in legacy_tables}


before = snapshot()
modules = ['public_chat.schema', 'kilas_core.customer_schema', 'kilas_core.job_schema',
           'kilas_core.operation_schema', None, 'kilas_core.finance_bridge_schema',
           'kilas_core.whatsapp_schema']
for repetition in (1, 2):
    for module in modules:
        if module is None:
            # Exact 0059 file, entire dollar-quoted SQL in ONE transaction.
            execute_script((HUB / 'migrations/0059_finance_workspace_corrections_postgres.sql').read_text())
        else:
            subprocess.run([sys.executable, '-m', module, '--apply'], cwd=HUB,
                env=dict(env, PYTHONPATH=str(HUB)), check=True)
    assert snapshot() == before, 'Upgrade changed pre-existing data'
    assert query('SELECT COUNT(*) FROM finance_transactions WHERE relocation_version<>0')[0][0] == 0
    assert query('SELECT COUNT(*) FROM finance_recurring_expenses WHERE relocation_version<>0')[0][0] == 0
    print(f'Exact 0055 -> 0056 -> 0057 -> 0058 -> 0059 -> 0060 -> 0061 sequence PASS, repetition {repetition}')

# Prove that the original production code can read this upgraded database.
readback = '''
import json,os,finance_service as f,finance_branches as branches
x=json.loads(os.environ['KILAS_PHASE10_FIXTURE'])
with branches.scope(x['bid'],x['branch'],x['uid']):
 invoice=f.get_finance_invoice(x['bid'],x['invoice'],actor_user_id=x['uid'])
 totals=f.get_invoice_totals(x['bid'],x['invoice'],actor_user_id=x['uid'])
 assert invoice['status']=='PARTIALLY_PAID'
 assert totals['total_minor']==50000 and totals['outstanding_minor']==30000
 assert len(f.list_transactions(x['bid'],actor_user_id=x['uid']))==3
print('Finance authoritative readback PASS')
'''
for checkout in (baseline / 'client-hub', HUB):
    subprocess.run([sys.executable, '-c', readback], cwd=checkout,
        env=dict(env, PYTHONPATH=str(checkout), KILAS_PHASE10_FIXTURE=json.dumps(identity)), check=True)
assert snapshot() == before
# A rollback must also retain writes, not merely render existing invoices.
# Use a NEW synthetic business so none of the pre-upgrade fixtures are edited.
rollback_seed = seed.replace('release-fixture@example.test', 'rollback-write@example.test')
rollback_result = subprocess.check_output([sys.executable, '-c', rollback_seed],
    cwd=baseline / 'client-hub', env=dict(env, PYTHONPATH=str(baseline / 'client-hub')), text=True)
rollback_identity = json.loads(rollback_result.strip().splitlines()[-1])
for checkout in (baseline / 'client-hub', HUB):
    subprocess.run([sys.executable, '-c', readback], cwd=checkout,
        env=dict(env, PYTHONPATH=str(checkout), KILAS_PHASE10_FIXTURE=json.dumps(rollback_identity)), check=True)
after_rollback_write = snapshot()
assert all(set(rows) <= set(after_rollback_write[table]) for table, rows in before.items()), 'Rollback write changed legacy fixtures'
print('Phase 10 migration rehearsal PASS: legacy rows preserved; old/new Finance readback; repeat installation; rollback-code Finance writes')
