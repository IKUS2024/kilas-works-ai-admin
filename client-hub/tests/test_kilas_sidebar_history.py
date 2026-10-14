"""Owned metadata pagination beyond legacy caps; no providers or history mutation."""
import os
import unittest
from unittest.mock import patch
import test_kilas_home as fixture
from kilas_ai import agent_store, store


class SidebarHistoryTests(unittest.TestCase):
    setUp=fixture.HomeTests.setUp
    client=fixture.HomeTests.client

    def seed(self,conversations=35,threads=125):
        self.database=fixture.fixture.base.f.fixture.db
        agents=[agent_store.new_conversation(self.owner) for _ in range(conversations)]
        legacy=[store.create_thread(self.owner) for _ in range(threads)]
        for table,ids in (('kilas_ai_conversations',agents),('kilas_ai_threads',legacy)):
            for ident in ids:self.database.execute(f'UPDATE {table} SET title=?,updated_at=? WHERE id=?',('Saved <script> '+str(ident),'2026-10-14T04:00:00+00:00',ident))
        # Keep fixture conversations outside the expected walk without deleting them.
        if agents:
            self.database.execute('UPDATE kilas_ai_conversations SET archived_at=? WHERE user_id=? AND id NOT IN ('+','.join('?' for _ in agents)+')',('2026-10-14T04:00:00+00:00',self.owner,*agents))
        else:self.database.execute('UPDATE kilas_ai_conversations SET archived_at=? WHERE user_id=?',('2026-10-14T04:00:00+00:00',self.owner))
        return agents,legacy

    def walk(self,client=None):
        client=client or self.client();result=[];cursor=None;seen=set()
        while True:
            response=client.get('/kilas-ai/sidebar/history',query_string={'cursor':cursor} if cursor else {})
            self.assertEqual(response.status_code,200);self.assertEqual(response.headers['Cache-Control'],'private, no-store')
            body=response.json;self.assertLessEqual(len(body['items']),20)
            result.extend(body['items']);cursor=body['next_cursor']
            if not cursor:break
            self.assertNotIn(cursor,seen);seen.add(cursor);self.assertLess(len(seen),100)
        return result

    def test_all_owned_history_reachable_in_existing_group_order_with_ties_and_exclusions(self):
        agents,legacy=self.seed()
        foreign_agent=agent_store.new_conversation(self.other);foreign_thread=store.create_thread(self.other)
        hidden=store.create_thread(self.owner);store.append_user_once(self.owner,hidden,'Synthetic attachment.','SMART','agent-attachments:history-hidden')
        archived=agent_store.new_conversation(self.owner);self.database.execute('UPDATE kilas_ai_conversations SET archived_at=? WHERE id=?',('2026-10-14T04:00:00+00:00',archived))
        items=self.walk()
        self.assertEqual([(item['kind'],item['id']) for item in items],[('conversation',ident) for ident in reversed(agents)]+[('thread',ident) for ident in reversed(legacy)])
        self.assertEqual(len(items),160)
        for item in items:
            self.assertEqual(set(item),{'kind','id','title','href'})
            self.assertIn('<script>',item['title'])
        self.assertNotIn(('conversation',foreign_agent),[(item['kind'],item['id']) for item in items])
        self.assertNotIn(('thread',foreign_thread),[(item['kind'],item['id']) for item in items])

    def test_get_keeps_current_conversation_session_and_database_unchanged(self):
        agents,_=self.seed(1,1);client=self.client()
        with client.session_transaction() as state:state['agent_conversation_id']=agents[0]
        before={table:[dict(row) for row in self.database.query_all('SELECT * FROM '+table)] for table in ('kilas_ai_conversations','kilas_ai_threads','kilas_ai_messages','kilas_ai_usage')}
        self.walk(client)
        with client.session_transaction() as state:self.assertEqual(state['agent_conversation_id'],agents[0])
        for table,rows in before.items():self.assertEqual([dict(row) for row in self.database.query_all('SELECT * FROM '+table)],rows)

    def test_cursor_cannot_be_tampered_or_used_by_another_owner(self):
        self.seed(25,1);client=self.client();token=client.get('/kilas-ai/sidebar/history').json['next_cursor']
        for bad in ('',token+'x','x'*2049):self.assertEqual(client.get('/kilas-ai/sidebar/history',query_string={'cursor':bad}).status_code,400)
        foreign=self.client(self.other)
        self.assertEqual(foreign.get('/kilas-ai/sidebar/history',query_string={'cursor':token}).status_code,400)

    def test_existing_access_and_feature_gates_apply(self):
        self.seed(25,1)
        anonymous=fixture.fixture.base.f.fixture.app.app.test_client()
        self.assertEqual(anonymous.get('/kilas-ai/sidebar/history').status_code,302)
        forged=self.client()
        with forged.session_transaction() as state:state['role']='KILAS_ADMIN'
        self.assertEqual(forged.get('/kilas-ai/sidebar/history').status_code,303)
        from auth_test_helpers import authenticate
        authenticate(forged,fixture.fixture.base.f.fixture.repo.get_user_by_id(self.owner),_csrf_token='work-csrf')
        with patch.dict(os.environ,{'KILAS_AI_ENABLED':'false'}):self.assertEqual(self.client().get('/kilas-ai/sidebar/history').status_code,404)
        token=self.client().get('/kilas-ai/sidebar/history').json['next_cursor']
        with patch.dict(os.environ,{'KILAS_AI_AUTOMATION_ENABLED':'false'}):
            self.assertTrue(all(item['kind']=='thread' for item in self.walk()))
            self.assertEqual(self.client().get('/kilas-ai/sidebar/history',query_string={'cursor':token}).status_code,400)

    def test_new_head_record_does_not_shift_or_duplicate_remaining_pages(self):
        _,legacy=self.seed(0,45);client=self.client();first=client.get('/kilas-ai/sidebar/history').json
        newest=store.create_thread(self.owner)
        self.database.execute('UPDATE kilas_ai_threads SET updated_at=? WHERE id=?',('2026-10-14T05:00:00+00:00',newest))
        items=first['items'];cursor=first['next_cursor']
        while cursor:
            body=client.get('/kilas-ai/sidebar/history',query_string={'cursor':cursor}).json;items.extend(body['items']);cursor=body['next_cursor']
        self.assertEqual([item['id'] for item in items],list(reversed(legacy)))
        self.assertEqual(client.get('/kilas-ai/sidebar/history').json['items'][0]['id'],newest)

    def test_empty_and_exact_page_boundary_can_reach_legacy_group(self):
        self.seed(20,1);items=self.walk();self.assertEqual(len(items),21);self.assertEqual(items[-1]['kind'],'thread')
        self.database.execute('UPDATE kilas_ai_conversations SET archived_at=? WHERE user_id=?',('2026-10-14T04:00:00+00:00',self.owner))
        self.assertEqual([item['kind'] for item in self.walk()],['thread'])
        self.database.execute('DELETE FROM kilas_ai_threads WHERE user_id=?',(self.owner,))
        self.assertEqual(self.walk(),[])


if __name__=='__main__':unittest.main()
