"""Opt-in disposable PostgreSQL only. Synthetic finite IDs; no private snapshot.
KILAS_CLEANUP_TEST_DATABASE_URL must target loopback kilas_cleanup_fixture.
"""
import hashlib,importlib.util,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import psycopg2
from urllib.parse import urlsplit
SPEC=importlib.util.spec_from_file_location('approved_cleanup',Path(__file__).parents[1]/'tools/finance_approved33_cleanup.py')
cleanup=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(cleanup)
URL=os.environ.get('KILAS_CLEANUP_TEST_DATABASE_URL','')

@unittest.skipUnless(URL,'disposable PostgreSQL not configured')
class ApprovedCleanupPostgresTests(unittest.TestCase):
 def setUp(self):
  parsed=urlsplit(URL)
  if parsed.hostname not in ('127.0.0.1','localhost') or parsed.path!='/kilas_cleanup_fixture':raise RuntimeError('local disposable database required')
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.directory=Path(self.tmp.name);self.directory.chmod(0o700)
  self.mock=patch.object(cleanup,'connect',side_effect=lambda:psycopg2.connect(URL));self.mock.start();self.addCleanup(self.mock.stop)
  with psycopg2.connect(URL) as conn,conn.cursor() as cur:
   cur.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public')
   cur.execute('CREATE TABLE businesses(id bigint PRIMARY KEY);CREATE TABLE users(id bigint PRIMARY KEY);INSERT INTO businesses VALUES(2),(10);INSERT INTO users VALUES(2),(9)')
   cur.execute('CREATE TABLE finance_categories(id bigint PRIMARY KEY,business_id bigint NOT NULL,direction text NOT NULL,name text NOT NULL,UNIQUE(business_id,id,direction))')
   cur.execute('CREATE TABLE finance_category_workspace_settings(business_id bigint,scope_key text,category_id bigint REFERENCES finance_categories(id),workspace_type text,owner_user_id bigint,display_name text,is_active boolean,PRIMARY KEY(business_id,scope_key,category_id))')
   cur.execute('CREATE TABLE finance_catalog_items(business_id bigint,scope_key text,canonical_key text,category_id bigint REFERENCES finance_categories(id),sort_order int,builtin_name text,PRIMARY KEY(business_id,scope_key,canonical_key))')
   cur.execute('CREATE TABLE finance_category_preferences(business_id bigint,scope_key text,category_id bigint REFERENCES finance_categories(id),icon_key text,sort_order int,PRIMARY KEY(business_id,scope_key,category_id))')
   cur.execute('CREATE TABLE finance_category_hierarchy(business_id bigint,parent_category_id bigint REFERENCES finance_categories(id),child_category_id bigint REFERENCES finance_categories(id),PRIMARY KEY(business_id,child_category_id))')
   cur.execute('CREATE TABLE finance_category_catalog_versions(business_id bigint,scope_key text,version int,changes_json text,PRIMARY KEY(business_id,scope_key,version))')
   cur.execute('CREATE TABLE finance_branch_workspaces(business_id bigint,branch_id bigint,owner_user_id bigint,workspace_type text)')
   cur.execute('CREATE TABLE finance_transactions(id bigint PRIMARY KEY,business_id bigint,category_id bigint,direction text,amount_minor bigint,FOREIGN KEY(business_id,category_id,direction) REFERENCES finance_categories(business_id,id,direction));CREATE TABLE finance_accounts(id bigint PRIMARY KEY,balance bigint);CREATE TABLE audit_log(id bigint PRIMARY KEY,action text)')
   for table in ('finance_expense_allocations','finance_budgets','finance_recurring_expenses','finance_installment_plans'):cur.execute('CREATE TABLE '+table+'(id bigint PRIMARY KEY,category_id bigint REFERENCES finance_categories(id))')
   rows={r['id']:r for r in cleanup.APPROVED['targets']}
   for r in cleanup.APPROVED['targets']:
    parent=r['parent_category_id']
    if parent is not None and parent not in rows:rows[parent]=dict(r,id=parent,storage_name='synthetic-retained-'+str(parent),builtin_name='Retained parent',canonical_key='retained.'+str(parent))
   rows[99999]=dict(id=99999,business_id=2,scope_key='PERSONAL:2',owner_user_id=2,storage_name='custom unrelated',builtin_name='__customer_owned__',canonical_key='custom.99999')
   for ident,r in rows.items():
    cur.execute('INSERT INTO finance_categories VALUES(%s,%s,\'EXPENSE\',%s)',(ident,r['business_id'],r['storage_name']))
    cur.execute('INSERT INTO finance_category_workspace_settings VALUES(%s,%s,%s,\'PERSONAL\',%s,%s,true)',(r['business_id'],r['scope_key'],ident,r['owner_user_id'],r['builtin_name']))
    cur.execute('INSERT INTO finance_catalog_items VALUES(%s,%s,%s,%s,0,%s)',(r['business_id'],r['scope_key'],r['canonical_key'],ident,r['builtin_name']))
   for r in cleanup.APPROVED['targets']:
    if r['parent_category_id'] is not None:cur.execute('INSERT INTO finance_category_hierarchy VALUES(%s,%s,%s)',(r['business_id'],r['parent_category_id'],r['id']))
   for r in cleanup.APPROVED['targets'][:26]:cur.execute('INSERT INTO finance_category_preferences VALUES(%s,%s,%s,\'category\',0)',(r['business_id'],r['scope_key'],r['id']))
   for group in cleanup.APPROVED['groups']:
    cur.execute('INSERT INTO finance_category_catalog_versions VALUES(%s,%s,3,\'[]\')',(group['business_id'],group['scope_key']))
    cur.execute('INSERT INTO finance_branch_workspaces VALUES(%s,%s,%s,\'PERSONAL\')',(group['business_id'],group['branch_id'],group['owner_id']))
   cur.execute("INSERT INTO finance_transactions VALUES(1,2,99999,'EXPENSE',10001);INSERT INTO finance_accounts VALUES(1,54321);INSERT INTO audit_log VALUES(1,'historical')")
 def mutate(self,sql,args=None):
  with psycopg2.connect(URL) as c,c.cursor() as cur:cur.execute(sql,args)
 def remaining(self):
  with psycopg2.connect(URL) as c,c.cursor() as cur:cur.execute('SELECT count(*) FROM finance_categories WHERE id=ANY(%s)',(cleanup.IDS,));return cur.fetchone()[0]
 def reviewed(self):
  p=self.directory/'reviewed.json';result=cleanup.snapshot_only(p);self.assertEqual(p.stat().st_mode&0o777,0o600);return p,result['snapshot_sha256']
 def apply(self,p,sha):return cleanup.apply(self.directory/'execution.json',p,sha,True)
 def test_exact33_atomic_commit_and_replay_denied(self):
  p,sha=self.reviewed();result=self.apply(p,sha);self.assertEqual(result['deleted'],cleanup.COUNTS);self.assertEqual(result['by_owner'],{'2':29,'9':4});self.assertEqual(self.remaining(),0)
  with psycopg2.connect(URL) as c,c.cursor() as cur:
   cur.execute('SELECT amount_minor FROM finance_transactions');self.assertEqual(cur.fetchone()[0],10001)
   cur.execute('SELECT balance FROM finance_accounts');self.assertEqual(cur.fetchone()[0],54321)
   cur.execute('SELECT count(*) FROM finance_category_catalog_versions');self.assertEqual(cur.fetchone()[0],2)
   cur.execute('SELECT name FROM finance_categories WHERE id=99999');self.assertEqual(cur.fetchone()[0],'custom unrelated')
  with self.assertRaisesRegex(cleanup.Stop,'already_absent'):cleanup.snapshot_only(self.directory/'repeat.json')
 def test_all_five_financial_reference_types_fail_closed(self):
  for table in ('finance_transactions','finance_expense_allocations','finance_budgets','finance_recurring_expenses','finance_installment_plans'):
   with self.subTest(table=table):
    if table=='finance_transactions':self.mutate("INSERT INTO finance_transactions VALUES(2,10,18482,'EXPENSE',1)")
    else:self.mutate('INSERT INTO '+table+' VALUES(2,18482)')
    with self.assertRaisesRegex(cleanup.Stop,'new_financial_reference'):cleanup.snapshot_only(self.directory/(table+'.json'))
    self.assertEqual(self.remaining(),33);self.mutate('DELETE FROM '+table+' WHERE id=2')
 def test_scope_foreign_name_and_provenance_rejected(self):
  for sql,restore,reason in [
   ("UPDATE finance_categories SET name='changed' WHERE id=18482","UPDATE finance_categories SET name=%s WHERE id=18482",'storage_identity'),
   ("UPDATE finance_catalog_items SET builtin_name='__customer_owned__' WHERE category_id=18482","UPDATE finance_catalog_items SET builtin_name=%s WHERE category_id=18482",'catalog_identity'),
   ("UPDATE finance_category_workspace_settings SET owner_user_id=2 WHERE category_id=18482","UPDATE finance_category_workspace_settings SET owner_user_id=%s WHERE category_id=18482",'scope_or_name')]:
   self.mutate(sql)
   with self.assertRaisesRegex(cleanup.Stop,reason):cleanup.snapshot_only(self.directory/(reason+'.json'))
   r=next(r for r in cleanup.APPROVED['targets'] if r['id']==18482);self.mutate(restore,(r['storage_name'] if reason=='storage_identity' else r['builtin_name'] if reason=='catalog_identity' else r['owner_user_id'],))
  self.assertEqual(self.remaining(),33)
 def test_v3_required_and_outside_children_rejected(self):
  self.mutate('DELETE FROM finance_category_catalog_versions WHERE business_id=10')
  with self.assertRaisesRegex(cleanup.Stop,'v3_initialization_required'):cleanup.snapshot_only(self.directory/'missing-v3.json')
  self.mutate("INSERT INTO finance_category_catalog_versions VALUES(10,'PERSONAL:9',3,'[]');INSERT INTO finance_category_hierarchy VALUES(2,18544,99999)")
  with self.assertRaisesRegex(cleanup.Stop,'metadata_counts_changed'):cleanup.snapshot_only(self.directory/'outside.json')
 def test_new_fk_or_cascade_schema_rejected(self):
  self.mutate('CREATE TABLE unexpected_refs(id int,category_id bigint REFERENCES finance_categories(id) ON DELETE CASCADE)')
  with self.assertRaisesRegex(cleanup.Stop,'reference_schema_changed'):cleanup.snapshot_only(self.directory/'new-fk.json')
  self.assertEqual(self.remaining(),33)
 def test_changed_reviewed_snapshot_and_missing_ack_do_not_delete(self):
  p,sha=self.reviewed()
  with self.assertRaisesRegex(cleanup.Stop,'off_host_backup_ack'):cleanup.apply(self.directory/'bad.json',p,sha,False)
  with self.assertRaisesRegex(cleanup.Stop,'checksum_mismatch'):self.apply(p,'0'*64)
  self.mutate("UPDATE finance_category_preferences SET icon_key='care' WHERE category_id=18482")
  with self.assertRaisesRegex(cleanup.Stop,'snapshot_changed'):self.apply(p,sha)
  self.assertEqual(self.remaining(),33)
 def test_postcheck_failure_rolls_back_all_deletes(self):
  p,sha=self.reviewed();original=cleanup.protected;calls=[]
  def mismatch(cur):
   value=original(cur);calls.append(1)
   if len(calls)>1:value['forced-test-failure']=(1,'x')
   return value
  with patch.object(cleanup,'protected',side_effect=mismatch),self.assertRaisesRegex(cleanup.Stop,'integrity_failed'):self.apply(p,sha)
  self.assertEqual(self.remaining(),33)
 def test_target_row_lock_blocks_concurrent_reference_until_commit(self):
  from concurrent.futures import ThreadPoolExecutor
  from threading import Event
  p,sha=self.reviewed();started=Event();original=cleanup.write_backup
  def attempt():
   with psycopg2.connect(URL) as c,c.cursor() as cur:
    cur.execute("SET lock_timeout='250ms'");started.set()
    try:cur.execute("INSERT INTO finance_transactions VALUES(2,10,18482,'EXPENSE',1)")
    except psycopg2.errors.LockNotAvailable:return 'blocked_by_target_lock'
    return 'unexpected_insert'
  with ThreadPoolExecutor(max_workers=1) as pool:
   def backup(path,payload):
    original(path,payload);future=pool.submit(attempt);self.assertTrue(started.wait(2));self.assertEqual(future.result(3),'blocked_by_target_lock')
   with patch.object(cleanup,'write_backup',side_effect=backup):self.apply(p,sha)
  self.assertEqual(self.remaining(),0)
 def test_real_operator_cli_dry_run_and_apply(self):
  import subprocess,sys
  environment=dict(os.environ,DATABASE_URL=URL,PYTHONDONTWRITEBYTECODE='1')
  path=self.directory/'cli-reviewed.json'
  result=subprocess.run([sys.executable,cleanup.__file__,'snapshot','--backup-output',str(path)],env=environment,capture_output=True,text=True,timeout=10,check=True)
  report=json.loads(result.stdout);self.assertEqual(report['deleted'],0);self.assertEqual(self.remaining(),33)
  result=subprocess.run([sys.executable,cleanup.__file__,'apply','--backup-output',str(self.directory/'cli-execution.json'),'--reviewed-snapshot',str(path),'--reviewed-snapshot-sha256',report['snapshot_sha256'],'--protected-off-host-backup-confirmed'],env=environment,capture_output=True,text=True,timeout=10,check=True)
  self.assertEqual(json.loads(result.stdout)['deleted'],cleanup.COUNTS);self.assertEqual(self.remaining(),0)
 def test_lost_commit_ack_is_unknown_and_never_retried(self):
  p,sha=self.reviewed();real=psycopg2.connect(URL);commits=[]
  class LostAck:
   def cursor(self):return real.cursor()
   def rollback(self):raise psycopg2.OperationalError('synthetic broken connection')
   def close(self):return real.close()
   def commit(self):
    commits.append(1);real.commit();raise psycopg2.OperationalError('synthetic lost acknowledgement')
  with patch.object(cleanup,'connect',return_value=LostAck()),self.assertRaisesRegex(cleanup.Stop,'commit_outcome_unknown_no_retry'):self.apply(p,sha)
  self.assertEqual(len(commits),1);self.assertEqual(self.remaining(),0)
if __name__=='__main__':unittest.main()
