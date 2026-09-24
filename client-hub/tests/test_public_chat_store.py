"""Durable WEB store: disposable SQLite, no legacy migration execution."""
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.pop('DATABASE_URL', None)
import db
from public_chat import schema, store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = patch.object(db, 'SQLITE_PATH', str(Path(self.temp.name) / 'test.db'))
        self.path.start(); self.addCleanup(self.path.stop)
        with store.transaction() as tx:
            tx.execute('CREATE TABLE businesses(id INTEGER PRIMARY KEY)')
            tx.execute('INSERT INTO businesses VALUES (7),(8)')
        schema.apply_schema(); schema.apply_schema()
        self.ch = store.ensure_channel(7)
        store.ensure_channel(8)
        self.conv, self.token = store.visitor(7, None, 'ip')
        self.cid = self.conv['id']

    def test_slug_and_hash_continuity(self):
        self.assertEqual(store.channel(slug=self.ch['slug'])['business_id'], 7)
        self.assertEqual(store.ensure_channel(7), self.ch)
        self.assertNotEqual(self.conv['visitor_hash'], self.token)
        self.assertEqual(store.visitor(7, self.token, 'ip')[0]['id'], self.cid)
        self.assertNotEqual(store.visitor(8, self.token, 'ip')[0]['id'], self.cid)
        self.assertIsNone(store.channel(slug='missing'))

    def test_forged_or_expired_identity(self):
        for bid, cid, token in ((8,self.cid,self.token),(7,'forged',self.token),(7,self.cid,'x'*40)):
            with self.assertRaises(store.ChatError): store.authorized(bid,cid,token)
        with store.transaction() as tx:
            tx.execute('UPDATE kw_web_conversations SET expires_at=0 WHERE id=?',(self.cid,))
        with self.assertRaises(store.ChatError): store.authorized(7,self.cid,self.token)

    def test_duplicate_and_payload_conflict(self):
        event, history = store.claim(7,self.cid,'one','hello','ip')
        self.assertEqual(history, [])
        store.finish(event, reply='Hi')
        duplicate, history = store.claim(7,self.cid,'one','hello','ip')
        self.assertEqual(duplicate['status'],'done'); self.assertIsNone(history)
        self.assertEqual(len(store.thread(7,self.cid)),2)
        with self.assertRaises(store.ChatError): store.claim(7,self.cid,'one','different','ip')

    def test_concurrent_claim_single_winner(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:store.claim(7,self.cid,'one','hello','ip'),range(2)))
        self.assertEqual(sum(history is not None for event,history in results),1)
        self.assertEqual(len(store.thread(7,self.cid)),1)

    def test_crashed_claim_recovery_and_old_worker_fence(self):
        first,_=store.claim(7,self.cid,'one','hello','ip')
        with store.transaction() as tx:
            tx.execute('UPDATE kw_web_events SET lease_until=0 WHERE conversation_id=?',(self.cid,))
        retry,_=store.claim(7,self.cid,'one','hello','ip')
        store.finish(first,reply='Stale')
        store.finish(retry,reply='Current')
        self.assertEqual([r['content'] for r in store.thread(7,self.cid)],['hello','Current'])

    def test_new_message_fences_abandoned_older_event(self):
        first,_=store.claim(7,self.cid,'old','first','ip')
        with store.transaction() as tx:
            tx.execute('UPDATE kw_web_events SET lease_until=0 WHERE conversation_id=?',(self.cid,))
        new,_=store.claim(7,self.cid,'new','second','ip')
        store.finish(new,reply='Current');store.finish(first,reply='Stale')
        old,history=store.claim(7,self.cid,'old','first','ip')
        self.assertEqual(old['status'],'failed');self.assertIsNone(history)
        self.assertEqual([r['content'] for r in store.thread(7,self.cid)],['first','second','Current'])

    def test_provider_failure_is_terminal_and_durable(self):
        event,_=store.claim(7,self.cid,'one','hello','ip')
        store.finish(event,error='provider_error')
        duplicate,history=store.claim(7,self.cid,'one','hello','ip')
        self.assertEqual(duplicate['status'],'failed');self.assertIsNone(history)
        self.assertEqual(len(store.thread(7,self.cid)),1)

    def test_takeover_fences_inflight_and_accepts_customer_without_ai(self):
        event,_=store.claim(7,self.cid,'one','hello','ip')
        with store.transaction() as tx:
            tx.execute("UPDATE kw_web_conversations SET mode='HUMAN_TAKEOVER',version=version+1 WHERE id=?",(self.cid,))
        store.finish(event,reply='Suppressed')
        next_event,history=store.claim(7,self.cid,'two','next','ip')
        self.assertEqual(next_event['status'],'done');self.assertIsNone(history)
        self.assertEqual([r['role'] for r in store.thread(7,self.cid)],['user','user'])

    def test_rate_limit_and_composite_fk(self):
        with store.transaction() as tx:
            for _ in range(2): store.limit(tx,'test',60,2,now=60)
        with self.assertRaises(store.ChatError):
            with store.transaction() as tx: store.limit(tx,'test',60,2,now=60)
        with self.assertRaises(Exception):
            with store.transaction() as tx:
                tx.execute("INSERT INTO kw_web_messages(business_id,conversation_id,event_id,role,content,created_at) VALUES (8,?,'bad','user','bad',1)",(self.cid,))


if __name__=='__main__': unittest.main()
