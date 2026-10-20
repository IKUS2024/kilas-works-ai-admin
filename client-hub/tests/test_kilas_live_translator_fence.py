"""Translator-only read-mode lifecycle; no DB/provider sockets."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import ExitStack
from kilas_ai import live_translator as live,audio_store

class Connection:
 def __init__(self,mode=False,status=0):self.mode=mode;self.status=status;self.closed=0;self.changes=[];self.fail_enable=False;self.fail_restore=False
 @property
 def autocommit(self):return self.mode
 @autocommit.setter
 def autocommit(self,value):
  if (value and self.fail_enable) or (not value and self.fail_restore):raise RuntimeError('synthetic driver detail')
  self.mode=value;self.changes.append(value)
 def get_transaction_status(self):return self.status
 def close(self):self.closed=1

class ReadFenceTests(unittest.TestCase):
 def context(self,conn,backend='postgres',**flags):
  stack=ExitStack();cache=SimpleNamespace(conn=conn,**flags)
  stack.enter_context(patch.object(live.db,'BACKEND',backend));stack.enter_context(patch.object(live.db,'_local',cache));getter=stack.enter_context(patch.object(live.db,'get_connection',return_value=conn));return stack,cache,getter
 def test_every_owned_session_and_funding_check_still_runs_and_mode_is_restored(self):
  conn=Connection();stack,cache,_=self.context(conn);calls=[]
  def session(owner,ident,key):self.assertTrue(conn.autocommit);calls.append((owner,ident,key));return {'voice_alias':'kilas-male'}
  def ready(owner,**kwargs):self.assertTrue(conn.autocommit);self.assertEqual(kwargs,{'session_table_checked':True})
  with stack,patch.object(live.sessions,'check',side_effect=session),patch.object(live,'require_ready',side_effect=ready) as require:
   for _ in range(25):self.assertEqual(live.check_session(17,'owned-session','owned-turn'),{'voice_alias':'kilas-male'})
  self.assertEqual(len(calls),25);self.assertEqual(require.call_count,25);self.assertEqual(conn.changes,[True,False]*25);self.assertFalse(conn.autocommit)
 def test_end_and_revoked_funding_preserve_exact_error_and_restore_mode(self):
  for stage in ['session','funding']:
   conn=Connection();stack,_,_=self.context(conn);error=audio_store.AudioError('Synthetic denial','session_ended' if stage=='session' else 'translator_unavailable',409)
   with stack,patch.object(live.sessions,'check',side_effect=error if stage=='session' else None),patch.object(live,'require_ready',side_effect=error if stage=='funding' else None):
    with self.assertRaises(audio_store.AudioError) as failed:live.check_session(17,'owned','turn')
    self.assertIs(failed.exception,error)
   self.assertFalse(conn.autocommit);self.assertEqual(conn.changes,[True,False])
 def test_sqlite_and_caller_owned_transaction_never_change_connection_mode(self):
  for backend,flags in [('sqlite',{}),('postgres',{'commerce_transaction':True}),('postgres',{'knowledge_business':123})]:
   conn=Connection();stack,_,getter=self.context(conn,backend,**flags)
   with stack,live._read_fence():pass
   getter.assert_not_called();self.assertEqual(conn.changes,[])
 def test_preexisting_mode_or_active_transaction_is_unchanged(self):
  for conn in [Connection(True),Connection(False,2)]:
   stack,_,_=self.context(conn)
   with stack,live._read_fence():pass
   self.assertEqual(conn.changes,[])
 def test_nested_read_scope_only_outer_owner_restores(self):
  conn=Connection();stack,_,_=self.context(conn)
  with stack:
   with live._read_fence():
    with live._read_fence():self.assertTrue(conn.autocommit)
    self.assertTrue(conn.autocommit)
  self.assertEqual(conn.changes,[True,False]);self.assertFalse(conn.autocommit)
 def test_enable_failure_discards_connection_and_uses_original_read_path(self):
  conn=Connection();conn.fail_enable=True;stack,cache,_=self.context(conn)
  with stack,patch.object(live.sessions,'check',return_value={'ok':True}) as check,patch.object(live,'require_ready'):
   self.assertEqual(live.check_session(17,'owned','turn'),{'ok':True})
   self.assertIsNone(cache.conn);self.assertTrue(conn.closed);check.assert_called_once()
 def test_restore_failure_discards_connection_instead_of_leaking_mode_to_writes(self):
  conn=Connection();conn.fail_restore=True;stack,cache,_=self.context(conn)
  with stack,live._read_fence():pass
  self.assertIsNone(cache.conn);self.assertTrue(conn.closed)
 def test_connection_replaced_by_existing_read_recovery_is_not_reconfigured(self):
  conn=Connection();new=Connection();stack,cache,_=self.context(conn)
  with stack:
   with live._read_fence():conn.close();cache.conn=new
  self.assertIs(cache.conn,new);self.assertEqual(new.changes,[]);self.assertFalse(new.autocommit)
if __name__=='__main__':unittest.main()
