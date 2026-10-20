"""Opt-in disposable loopback PostgreSQL; synthetic calls, never external IO."""
import io,json,os,unittest,uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack,redirect_stdout
from threading import Lock
from urllib.parse import urlsplit
from unittest.mock import patch
import psycopg2
from psycopg2 import sql
from kilas_ai import translator_latency_benchmark as b

DSN=os.environ.get('KILAS_TRANSLATOR_FENCE_PG_DSN','')
@unittest.skipUnless(DSN,'Requires explicit disposable loopback PostgreSQL DSN')
class NativeBenchmarkTests(unittest.TestCase):
 def setUp(self):
  if urlsplit(DSN).hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('Refusing non-loopback PostgreSQL')
  self.stack=ExitStack();self.addCleanup(self.stack.close)
  self.admin=psycopg2.connect(DSN);self.admin.autocommit=True;self.schema='benchmark_'+uuid.uuid4().hex
  with self.admin.cursor() as cursor:
   cursor.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)));cursor.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
   cursor.execute("CREATE TABLE users(id BIGINT PRIMARY KEY,email TEXT,role TEXT);INSERT INTO users VALUES (9,'irvankarnavi@gmail.com','CLIENT_OWNER')")
  self.addCleanup(self.cleanup_pg)
  self.stack.enter_context(patch.object(b.db,'BACKEND','postgres'))
  self.stack.enter_context(patch.object(b.usage,'_connect',side_effect=lambda:psycopg2.connect(DSN,options='-c search_path='+self.schema)))
  self.stack.enter_context(patch.object(b,'_now',return_value=b.START+1000));self.stack.enter_context(patch.object(b,'configured',return_value=True))
 def cleanup_pg(self):
  with self.admin.cursor() as cursor:cursor.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
  self.admin.close()
 def row(self):
  with self.admin.cursor() as cursor:cursor.execute('SELECT attempts,reserved_micro,status,results FROM kilas_translator_latency_benchmarks');return cursor.fetchone()
 def test_eight_concurrent_workers_and_later_restarts_dispatch_only_four_calls_total(self):
  # Install the isolated table first; then race only the actual durable claim.
  b._claim('schema-only',b.preflight())
  with self.admin.cursor() as cursor:cursor.execute('DELETE FROM kilas_translator_latency_benchmarks')
  lock=Lock();calls=[]
  def synthetic(body):
   with lock:
    self.assertEqual(self.row()[0],len(calls)+1);self.assertEqual(self.row()[1],40000)
    calls.append(body['reasoning_effort'])
   return {'usage':{'input_tokens':400,'completion_tokens':120,'reasoning_tokens':0},'translation':{'text':'Synthetic complete translation'}}
  with patch.object(b,'_request',side_effect=synthetic),redirect_stdout(io.StringIO()):
   with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:b.run(),range(8)))
   b.run();b.run()
  row=self.row();self.assertEqual(calls,['low','none','none','low']);self.assertEqual(row[:3],(4,40000,'COMPLETED'));self.assertEqual(len(json.loads(row[3])),4)

if __name__=='__main__':unittest.main()
