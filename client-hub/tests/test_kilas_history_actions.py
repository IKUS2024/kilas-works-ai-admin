"""Synthetic history lifecycle, meaningful recency and owner/CSRF action gates."""
import io,unittest,json
from unittest.mock import patch
import test_kilas_chat_models as f
from kilas_ai import agent_store,store,sidebar_history,providers
import db


class HistoryActionTests(unittest.TestCase):
    client=f.RouteTests.client
    def setUp(self):
        f.RouteTests.setUp(self)

    def post(self,path,**data):
        return self.client().post(path,data={'csrf_token':'work-csrf',**data},headers={'Accept':'application/json','X-Agent-Chat':'1'})

    def items(self,client=None):return (client or self.client()).get('/kilas-ai/sidebar/history').json['items']

    def test_empty_creation_draft_and_model_selection_never_enter_history(self):
        self.assertEqual(self.items(),[])
        client=self.client();client.get('/products/start');client.get('/kilas-ai/agent?conversation='+str(self.conversation))
        for _ in range(3):self.assertEqual(client.post('/kilas-ai/agent/conversations',data={'csrf_token':'work-csrf'}).status_code,303)
        client.post('/kilas-ai/chat/model',json={'model':'gpt-6-luna','surface':'thread','conversation_id':self.thread},headers={'X-CSRF-Token':'work-csrf'})
        self.post(f'/kilas-ai/threads/{self.thread}/rename',title='Unsent renamed draft')
        self.assertEqual(self.items(),[])
        self.assertIsNotNone(store.thread(self.owner,self.thread));self.assertIsNotNone(agent_store.conversation(self.owner,self.conversation))

    def test_first_submitted_text_appears_with_no_provider_followup_required(self):
        with patch.object(providers,'stream',side_effect=f.answer):
            result=self.post('/kilas-ai/agent/chat',message='Hello synthetic',conversation_id=self.conversation,operation_key='history_first_send_synthetic',selected_model='gpt-6-luna')
            result.get_data();self.assertEqual(result.status_code,200)
        self.assertEqual([(x['kind'],x['id']) for x in self.items()],[('conversation',self.conversation)])
        self.assertNotIn('agent-section-head',self.client().get('/kilas-ai/agent?conversation='+str(self.conversation)).text)

    def test_submitted_attachment_is_meaningful_but_unsent_attachment_is_not(self):
        db.execute('INSERT INTO kilas_ai_attachments(user_id,thread_id,filename,mime_type,byte_size,content) VALUES (?,?,?,?,?,?)',(self.owner,self.thread,'synthetic.txt','text/plain',1,b'x'))
        self.assertEqual(self.items(),[])
        msg=db.insert_returning_id("INSERT INTO kilas_ai_messages(thread_id,role) VALUES (?,'user')",(self.thread,))
        db.execute('UPDATE kilas_ai_attachments SET message_id=? WHERE thread_id=?',(msg,self.thread))
        self.assertEqual(self.items()[0]['id'],self.thread)

    def seed_job(self,ident=None,owner=None):
        return db.insert_returning_id("INSERT INTO kilas_agent_jobs(user_id,title,instruction,mode,status,origin_conversation_id) VALUES (?,?,?,'ONE_SHOT','COMPLETED',?)",(owner or self.owner,'Synthetic work','Synthetic local fixture',ident or self.conversation))

    def test_work_only_conversation_retained_and_heartbeat_not_activity(self):
        job=self.seed_job()
        db.execute('UPDATE kilas_agent_jobs SET created_at=?,updated_at=? WHERE id=?',('2026-10-16T10:00:00+00:00','2026-10-17T22:00:00+00:00',job))
        self.assertEqual(self.items()[0]['kind'],'conversation')
        store.append_user_once(self.owner,self.thread,'Existing synthetic message.','FAST','history_existing_text')
        db.execute('UPDATE kilas_ai_messages SET created_at=? WHERE thread_id=?',('2026-10-17 09:00:00',self.thread))
        self.assertEqual(self.items()[0]['kind'],'thread')
        db.execute("INSERT INTO kilas_agent_events(job_id,kind,summary,created_at) VALUES (?,'COMPLETED','Synthetic finished',?)",(job,'2026-10-17T12:00:00+00:00'))
        self.assertEqual(self.items()[0]['kind'],'conversation')

    def test_recency_uses_messages_across_both_kinds_not_open_rename_or_model(self):
        agent_store.append(self.owner,'user','Older synthetic discussion',self.conversation)
        store.append_user_once(self.owner,self.thread,'Newer synthetic discussion','FAST','history_recency_text')
        db.execute('UPDATE kilas_ai_agent_messages SET created_at=? WHERE conversation_id=?',('2026-10-17T08:00:00+00:00',self.conversation))
        db.execute('UPDATE kilas_ai_messages SET created_at=? WHERE thread_id=?',('2026-10-17 09:00:00',self.thread))
        before=self.items();self.assertEqual([x['kind'] for x in before],['thread','conversation'])
        self.client().get('/kilas-ai/agent?conversation='+str(self.conversation))
        self.post(f'/kilas-ai/agent/conversations/{self.conversation}/rename',title='Renamed older chat')
        self.client().post('/kilas-ai/chat/model',json={'model':'gpt-6-luna','surface':'conversation','conversation_id':self.conversation},headers={'X-CSRF-Token':'work-csrf'})
        self.assertEqual([x['kind'] for x in self.items()],['thread','conversation'])
        agent_store.append(self.owner,'user','Latest synthetic correction',self.conversation)
        self.assertEqual(self.items()[0]['kind'],'conversation')

    def test_mixed_pagination_and_isolation_exclude_empty_archived_and_backing(self):
        expected=set()
        for i in range(26):
            ident=agent_store.new_conversation(self.owner) if i%2 else store.create_thread(self.owner)
            if i%2:agent_store.append(self.owner,'user','Synthetic page '+str(i),ident);table='kilas_ai_agent_messages';field='conversation_id';kind='conversation'
            else:store.append_user_once(self.owner,ident,'Synthetic page '+str(i),'FAST','history_page_'+str(i));table='kilas_ai_messages';field='thread_id';kind='thread'
            db.execute('UPDATE '+table+' SET created_at=? WHERE '+field+'=?',('2026-10-17T10:'+str(i).zfill(2)+':00+00:00',ident));expected.add((kind,ident))
        foreign=store.create_thread(self.other);store.append_user_once(self.other,foreign,'Foreign synthetic','FAST','foreign_history')
        client=self.client();first=client.get('/kilas-ai/sidebar/history').json;self.assertEqual(len(first['items']),20)
        self.assertEqual(self.client(self.other).get('/kilas-ai/sidebar/history',query_string={'cursor':first['next_cursor']}).status_code,400)
        second=client.get('/kilas-ai/sidebar/history',query_string={'cursor':first['next_cursor']}).json
        all_items=first['items']+second['items'];self.assertEqual(len(all_items),26);self.assertEqual({(x['kind'],x['id']) for x in all_items},expected)
        self.assertEqual(all_items[0]['title'],'Synthetic page 25')
        self.assertIsNone(second['next_cursor'])

    def test_rename_delete_owner_csrf_and_recovery_boundaries(self):
        agent_store.append(self.owner,'user','Retained synthetic archive',self.conversation);job=self.seed_job()
        store.append_user_once(self.owner,self.thread,'Synthetic permanent thread','FAST','delete_owned_fixture')
        for path in (f'/kilas-ai/threads/{self.thread}/delete',f'/kilas-ai/agent/conversations/{self.conversation}/delete'):
            self.assertNotEqual(self.client().post(path).status_code,200)
            response=self.client(self.other).post(path,data={'csrf_token':'work-csrf'},headers={'Accept':'application/json'});self.assertEqual(response.status_code,404)
        for path in (f'/kilas-ai/threads/{self.thread}/rename',f'/kilas-ai/agent/conversations/{self.conversation}/rename'):
            self.assertEqual(self.post(path,title='').status_code,400)
            self.assertEqual(self.client(self.other).post(path,data={'csrf_token':'work-csrf','title':'Wrong owner'},headers={'Accept':'application/json'}).status_code,404)
            self.assertEqual(self.post(path,title='Owned renamed').json['title'],'Owned renamed')
        result=self.post(f'/kilas-ai/agent/conversations/{self.conversation}/delete');self.assertEqual(result.status_code,200)
        self.assertIsNone(agent_store.conversation(self.owner,self.conversation));self.assertIsNotNone(db.query_one('SELECT archived_at FROM kilas_ai_conversations WHERE id=?',(self.conversation,))['archived_at'])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_ai_agent_messages WHERE conversation_id=?',(self.conversation,))['n'],1)
        self.assertIsNotNone(db.query_one('SELECT id FROM kilas_agent_jobs WHERE id=?',(job,)))
        self.assertEqual(self.post(f'/kilas-ai/threads/{self.thread}/delete').status_code,200);self.assertIsNone(store.thread(self.owner,self.thread));self.assertEqual(self.items(),[])

    def test_normal_pages_have_no_redundant_headings_or_cost_widget(self):
        for path in ('/products/start','/kilas-ai/threads/'+str(self.thread),'/kilas-ai/agent?conversation='+str(self.conversation)):
            html=self.client().get(path).text
            for marker in ('home-workspace-brand','home-chat-heading','agent-rename','data-image-cost-template','data-image-cost-disclosure'):self.assertNotIn(marker,html)
            self.assertIn('data-chat-context-menu',html);self.assertIn('class="ai-new"',html);self.assertIn('data-chat-model-selector',html)

if __name__=='__main__':unittest.main()
