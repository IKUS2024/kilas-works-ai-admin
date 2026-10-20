"""Opt-in disposable LOCAL PostgreSQL; no external DB or paid provider permitted."""
import json,os,time,unittest,uuid
from contextlib import ExitStack,nullcontext
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
import psycopg2
from psycopg2 import sql,extensions
import test_kilas_live_translator as fixture
from kilas_ai import live_translator as live,live_translator_store as sessions,free_test
from kilas_ai import live_translator_realtime_check as proof,live_translator_realtime_account as account

DSN=os.environ.get('KILAS_TRANSLATOR_FENCE_PG_DSN','')
class TracedCursor(extensions.cursor):
 def execute(self,query,params=None):
  if isinstance(query,str) and query.lstrip().upper().startswith('SELECT '):self.connection.selects+=1
  return super().execute(query,params)
class TracedConnection(extensions.connection):
 def __init__(self,*a,**k):super().__init__(*a,**k);self.selects=0;self.wire_commits=0
 def cursor(self,*a,**k):k.setdefault('cursor_factory',TracedCursor);return super().cursor(*a,**k)
 def commit(self):
  if self.get_transaction_status()!=extensions.TRANSACTION_STATUS_IDLE:self.wire_commits+=1
  return super().commit()

@unittest.skipUnless(DSN,'Requires explicitly supplied local disposable PostgreSQL DSN')
class NativeFenceTests(unittest.TestCase):
 funded=fixture.LiveTranslatorTests.funded
 on=fixture.LiveTranslatorTests.on
 key=fixture.LiveTranslatorTests.key
 def setUp(self):
  if urlsplit(DSN).hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('Refusing non-loopback PostgreSQL')
  fixture.LiveTranslatorTests.setUp(self)
  self.stack=ExitStack();self.addCleanup(self.stack.close)
  self.admin=psycopg2.connect(DSN);self.admin.autocommit=True;self.schema='fence_'+uuid.uuid4().hex
  with self.admin.cursor() as cursor:cursor.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
  self.addCleanup(self.cleanup_pg)
  self.conn=psycopg2.connect(DSN,connection_factory=TracedConnection);self.conn.autocommit=True
  for connection in [self.admin,self.conn]:
   with connection.cursor() as cursor:cursor.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
  with self.admin.cursor() as cursor:
   cursor.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,role TEXT);CREATE TABLE kilas_live_translator_sessions(id TEXT PRIMARY KEY,user_id INTEGER,status TEXT,expires_at TEXT,language_a TEXT,language_b TEXT,voice_alias TEXT);CREATE TABLE kilas_live_translator_turns(operation_key TEXT PRIMARY KEY,session_id TEXT,status TEXT);CREATE TABLE kilas_realtime_checks(approval TEXT,status TEXT,accepted INTEGER,attributed INTEGER,after_used INTEGER,before_used INTEGER,after_limit INTEGER,before_limit INTEGER,prepaid_guard INTEGER,actual_wire_ms INTEGER,sent_pcm_ms INTEGER,result TEXT,user_id INTEGER,key_digest TEXT,source_digest TEXT,model TEXT,campaign TEXT);CREATE TABLE rollback_marker(id INTEGER)')
  self.stack.enter_context(self.funded());self.stack.enter_context(self.on());self.stack.enter_context(patch.dict(os.environ,{'KILAS_VO_STT_ALLOWED_OWNER_ID':str(self.user),'KILAS_VO_STT_USAGE_MODE':'owner','KILAS_APP_FREE_TEST_ENABLED':'true','KILAS_APP_FREE_TEST_END_AT':free_test.END_AT.isoformat()}))
  self.ident='a'*48;self.operation=self.key()
  with self.admin.cursor() as cursor:
   cursor.execute("INSERT INTO users VALUES (%s,'CLIENT_OWNER')",(self.user,));cursor.execute("INSERT INTO kilas_live_translator_sessions VALUES (%s,%s,'ACTIVE','','id','en','kilas-male')",(self.ident,self.user));cursor.execute("INSERT INTO kilas_live_translator_turns VALUES (%s,%s,'PROCESSING')",(self.operation,self.ident))
   cursor.execute("INSERT INTO kilas_realtime_checks VALUES (%s,'VERIFIED',1,1,2,1,100,100,1,1000,5000,'committed',%s,%s,%s,%s,%s)",(proof.APPROVAL,self.user,proof.digest(),proof.SOURCE,account.MODEL,live.budget.policy()['id']+'-rt-check'))
  self.conn.autocommit=False
  self.stack.enter_context(patch.object(live.db,'BACKEND','postgres'));self.cache=SimpleNamespace(conn=self.conn);self.stack.enter_context(patch.object(live.db,'_local',self.cache));self.stack.enter_context(patch.object(live.db,'get_connection',side_effect=lambda:self.conn))
 def cleanup_pg(self):
  if getattr(self,'conn',None):self.conn.close()
  with self.admin.cursor() as cursor:cursor.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
  self.admin.close()
 def check(self,owner=None,key=None):return live.check_session(self.user if owner is None else owner,self.ident,self.operation if key is None else key)
 def update(self,query,params=()):
  with self.admin.cursor() as cursor:cursor.execute(query,params)
 def test_same150_fresh_selects_remove150_wire_commits_without_caching_authority(self):
  result=[]
  for mode in ['baseline','optimized']:
   self.conn.selects=0;self.conn.wire_commits=0;began=time.monotonic()
   with patch.object(live,'_read_fence',nullcontext) if mode=='baseline' else nullcontext():
    for _ in range(50):self.assertEqual(self.check()['voice_alias'],'kilas-male')
   elapsed=(time.monotonic()-began)*1000
   result.append({'mode':mode,'fences':50,'selects':self.conn.selects,'wire_commits':self.conn.wire_commits,'local_elapsed_ms':round(elapsed,3)})
   self.assertEqual(self.conn.selects,150);self.assertEqual(self.conn.wire_commits,150 if mode=='baseline' else 0);self.assertFalse(self.conn.autocommit);self.assertEqual(self.conn.get_transaction_status(),extensions.TRANSACTION_STATUS_IDLE)
  print('TRANSLATOR_NATIVE_FENCE '+json.dumps(result))
 def test_next_fence_sees_proof_revocation_from_separate_connection(self):
  self.check();self.update("UPDATE kilas_realtime_checks SET status='UNKNOWN'")
  with self.assertRaises(live.audio_store.AudioError) as error:self.check()
  self.assertEqual(error.exception.code,'translator_unavailable');self.assertFalse(self.conn.autocommit)
 def test_next_fence_sees_end_cancel_expiry_and_foreign_owner(self):
  self.check()
  for query,params,owner,key,code in [
   (None,(),self.other,None,'session_unavailable'),(None,(),None,'missing','turn_cancelled'),
   ("UPDATE kilas_live_translator_turns SET status='CANCELLED'",(),None,None,'turn_cancelled'),
   ("UPDATE kilas_live_translator_turns SET status='PROCESSING';UPDATE kilas_live_translator_sessions SET expires_at='2000-01-01T00:00:00+00:00'",(),None,None,'session_ended'),
   ("UPDATE kilas_live_translator_sessions SET expires_at='',status='ENDED'",(),None,None,'session_ended')]:
   if query:self.update(query,params)
   with self.assertRaises(live.audio_store.AudioError) as error:self.check(owner,key)
   self.assertEqual(error.exception.code,code);self.assertFalse(self.conn.autocommit)
 def test_caller_transaction_rollback_stays_owned_and_is_never_committed_by_fence(self):
  self.cache.commerce_transaction=True
  with self.conn.cursor() as cursor:cursor.execute('INSERT INTO rollback_marker VALUES (1)')
  self.check();self.assertFalse(self.conn.autocommit);self.assertEqual(self.conn.get_transaction_status(),extensions.TRANSACTION_STATUS_INTRANS);self.conn.rollback()
  with self.admin.cursor() as cursor:cursor.execute('SELECT count(*) FROM rollback_marker');self.assertEqual(cursor.fetchone()[0],0)
if __name__=='__main__':unittest.main()
