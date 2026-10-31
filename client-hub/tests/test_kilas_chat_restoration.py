"""Reversible Chat default, retained history and owner fences; no provider calls."""
import os
import unittest
from unittest.mock import patch
import test_kilas_home as fixture
from kilas_ai import copilot, store, sidebar_history
import db


class RestorationTests(unittest.TestCase):
    setUp=fixture.HomeTests.setUp
    client=fixture.HomeTests.client

    def test_default_and_explicit_reactivation(self):
        with patch.dict(os.environ):
            os.environ.pop('KILAS_COPILOT_VISIBLE',None)
            self.assertFalse(copilot.visible())
            for path in ('/kilas-ai','/products/start'):
                page=self.client().get(path,follow_redirects=True)
                self.assertEqual(page.status_code,200)
                self.assertTrue('id="ai-composer"' in page.text or 'id="agent-chat-form"' in page.text)
                self.assertNotIn('id="copilot"',page.text)
                self.assertNotIn('href="/kilas-ai/copilot"',page.text)
        with patch.dict(os.environ,{'KILAS_COPILOT_VISIBLE':'true'}):
            self.assertTrue(copilot.visible())
            self.assertIn('id="copilot"',self.client().get('/kilas-ai').text)

    def test_history_projection_preserves_both_products_and_preferences(self):
        ordinary=store.create_thread(self.owner)
        store.append_user_once(self.owner,ordinary,'Discuss Copilot without hiding this Chat','FAST','ordinary_history_1234')
        ident=copilot.create(self.owner)
        store.append_user_once(self.owner,ident,'Owned voice history','SMART','copilot_history_1234')
        copilot.preferences(self.owner,ident,{'style':'profesional','target':'es','translate':True})
        foreign=store.create_thread(self.other)
        store.append_user_once(self.other,foreign,'Foreign history','FAST','foreign_history_1234')
        tables=('kilas_ai_threads','kilas_ai_messages','kilas_ai_attachments','kilas_ai_usage')
        before={table:[dict(row) for row in db.query_all('SELECT * FROM '+table)] for table in tables}
        client=self.client()
        rows=client.get('/kilas-ai/sidebar/history').json['items']
        self.assertIn(ordinary,[row['id'] for row in rows if row['kind']=='thread'])
        self.assertNotIn(ident,[row['id'] for row in rows if row['kind']=='thread'])
        self.assertNotIn(foreign,[row['id'] for row in rows if row['kind']=='thread'])
        self.assertIn('Discuss Copilot without hiding this Chat',client.get(f'/kilas-ai/threads/{ordinary}').text)
        for path in ('/kilas-ai/copilot',f'/kilas-ai/copilot/sessions/{ident}',f'/kilas-ai/threads/{ident}'):
            response=client.get(path)
            self.assertEqual(response.status_code,303)
            self.assertEqual(response.location,'/kilas-ai')
        self.assertEqual(self.client(self.other).get(f'/kilas-ai/copilot/sessions/{ident}').status_code,404)
        self.assertEqual(self.client(self.other).get(f'/kilas-ai/threads/{ident}').status_code,404)
        with patch.dict(os.environ,{'KILAS_COPILOT_VISIBLE':'true'}):
            self.assertIn('id="copilot"',client.get(f'/kilas-ai/copilot/sessions/{ident}').text)
            ids=[r['id'] for r in client.get('/kilas-ai/sidebar/history').json['items'] if r['kind']=='thread']
            self.assertIn(ident,ids);self.assertNotIn(ordinary,ids)
        for table,rows in before.items():
            self.assertEqual([dict(row) for row in db.query_all('SELECT * FROM '+table)],rows,table)
        self.assertEqual(copilot.preferences(self.owner,ident),{'style':'profesional','target':'es','translate':True})

    def test_hidden_sessions_do_not_disrupt_pagination_or_owner_cursor(self):
        client=self.client();owned=[]
        for i in range(25):
            ident=copilot.create(self.owner)
            store.append_user_once(self.owner,ident,'Voice','SMART','voice_history_'+str(i))
            ident=store.create_thread(self.owner);owned.append(ident)
            store.append_user_once(self.owner,ident,'Chat','FAST','chat_history_'+str(i))
        result=[];token=None;first=None
        while True:
            response=client.get('/kilas-ai/sidebar/history',query_string={'cursor':token} if token else {})
            self.assertEqual(response.status_code,200)
            result.extend(r['id'] for r in response.json['items'] if r['kind']=='thread')
            token=response.json['next_cursor'];first=first or token
            if not token:break
        self.assertTrue(set(owned)<=set(result));self.assertEqual(len(result),len(set(result)))
        self.assertEqual(self.client(self.other).get('/kilas-ai/sidebar/history',query_string={'cursor':first}).status_code,400)
        # Unscoped internal callers retain their existing all-history contract.
        all_ids=[row['id'] for row in sidebar_history.recent(self.owner,include_conversations=False,limit=200)]
        self.assertGreater(len(all_ids),len(result))

    def test_legacy_view_files_are_retained(self):
        from pathlib import Path
        root=Path(__file__).parents[1]
        for name in ('kilas_ai.js','kilas_home.js','kilas_chat.css','kilas_copilot.mjs','kilas_copilot_capture.mjs'):
            self.assertTrue((root/'static'/name).is_file())

if __name__=='__main__':unittest.main()
