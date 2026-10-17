"""Offline Group Chat integration with current revocable customer sessions."""
import os,sys,tempfile,threading,unittest,uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(CLIENT_HUB_DB_PATH=tempfile.mktemp(prefix='kilas-group-',suffix='.sqlite'),SECRET_KEY='group-synthetic-only',KILAS_AI_ENABLED='true')
os.environ.pop('DATABASE_URL',None)
import app,customer_auth,db,repo,security
from kilas_ai import group_chat as groups,providers,store,usage

def key(): return uuid.uuid4().hex

def events(text='Keputusan: gunakan opsi A. Tugas: belum ditetapkan.'):
    return iter([{'type':'provider','provider':'openai','model':'gpt-6-luna'},{'type':'delta','text':text},{'type':'usage','input_tokens':100,'output_tokens':20},{'type':'finish','reason':'stop'}])

class GroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=app.app;cls.app.config.update(TESTING=True,CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
    def setUp(self):
        self.owner,self.member,self.other=[repo.create_user(key()+'@example.test',security.hash_password('test-password'),full_name=name) for name in ('Group Owner','Group Member','Other Person')]
        self.ident=groups.create(self.owner,'Tim A');self.path=f'/kilas-ai/groups/{self.ident}';self.token=groups.invitation(self.owner,self.ident)
        self.a,self.b,self.c=[self.client(u) for u in (self.owner,self.member,self.other)]
        patch('requests.sessions.Session.request',side_effect=AssertionError('NO LIVE NETWORK IN QA')).start();self.addCleanup(patch.stopall)
    def client(self,user):
        client=self.app.test_client()
        with self.app.test_request_context(): token=customer_auth.create(repo.get_user_by_id(user))
        with client.session_transaction() as state:state.update(user_id=user,role='CLIENT_OWNER',_customer_session=token,_csrf_token='group-csrf')
        return client
    def post(self,client,path,payload):return client.post(path,json=payload,headers={'X-CSRF-Token':'group-csrf'})
    def join(self):groups.join(self.member,self.token)

    def test_create_plain_discussion_idempotency_no_ai(self):
        with patch.object(providers,'stream') as provider:
            created=self.post(self.a,'/kilas-ai/groups',{'name':'<script>Team</script>'});self.assertEqual(created.status_code,201)
            self.assertIn('&lt;script&gt;Team&lt;/script&gt;',self.a.get(created.json['url']).text)
            self.assertFalse(groups.state(self.owner,self.ident)['messages'])
            payload={'content':'Teks biasa','operation_key':key()}
            self.assertEqual(self.post(self.a,self.path+'/messages',payload).json['status'],'COMPLETE')
            self.assertTrue(self.post(self.a,self.path+'/messages',payload).json['cached'])
            self.assertEqual(self.post(self.a,self.path+'/messages',{**payload,'content':'changed'}).status_code,409)
            self.assertEqual(len(groups.state(self.owner,self.ident)['messages']),1)
            self.assertFalse(db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=?',(self.owner,)));provider.assert_not_called()

    def test_every_private_route_membership_and_csrf(self):
        for suffix in ('','/messages','/messages?after=0','/messages?before=999'):self.assertEqual(self.c.get(self.path+suffix).status_code,404)
        for suffix,payload in [('/messages',{'content':'spy','operation_key':key()}),('/messages',{'kind':'SUMMARY','operation_key':key()}),('/settings',{'action':'ai','enabled':False}),('/invitation',{})]:self.assertEqual(self.post(self.c,self.path+suffix,payload).status_code,404)
        self.assertEqual(self.a.post(self.path+'/messages',json={'content':'hi','operation_key':key()}).status_code,400)
        self.assertIn(self.app.test_client().get(self.path+'/messages').status_code,(302,303,401))

    def test_invitation_login_explicit_consent_no_preview_history(self):
        groups.send(self.owner,self.ident,'Secret group history',key());link='/kilas-ai/group-invitation/'+self.token
        anon=self.app.test_client();preview=anon.get(link)
        self.assertNotIn('Secret group history',preview.text);self.assertNotIn('Tim A',preview.text)
        self.assertIn('no-store',preview.headers['Cache-Control']);self.assertEqual(preview.headers['Referrer-Policy'],'no-referrer')
        anon.get('/login')
        with anon.session_transaction() as state:csrf=state['_csrf_token']
        login=anon.post('/login',data={'email':repo.get_user_by_id(self.member)['email'],'password':'test-password','csrf_token':csrf})
        self.assertTrue(login.location.endswith(link));self.assertEqual(anon.get(self.path+'/messages').status_code,404)
        self.assertNotIn('Secret group history',anon.get(link).text)
        with anon.session_transaction() as state:csrf=state['_csrf_token']
        self.assertEqual(anon.post(link,data={'csrf_token':csrf}).status_code,303)
        self.assertIn('Secret group history',anon.get(self.path+'/messages').text)

    def test_registration_returns_without_auto_join(self):
        anon=self.app.test_client();link='/kilas-ai/group-invitation/'+self.token;anon.get(link);anon.get('/register')
        with anon.session_transaction() as state:csrf=state['_csrf_token']
        response=anon.post('/register',data={'email':key()+'@example.test','full_name':'New Member','password':'synthetic-password','csrf_token':csrf})
        self.assertTrue(response.location.endswith(link));self.assertEqual(anon.get(self.path+'/messages').status_code,404);anon.get(link)
        with anon.session_transaction() as state:csrf=state['_csrf_token']
        self.assertEqual(anon.post(link,data={'csrf_token':csrf}).status_code,303);self.assertEqual(anon.get(self.path+'/messages').status_code,200)

    def test_rotate_revoke_remove_immediate_and_no_self_readmission(self):
        self.join();new=groups.invitation(self.owner,self.ident)
        self.assertFalse(groups.preview(self.token));self.assertTrue(groups.preview(new))
        self.assertEqual(self.post(self.b,self.path+'/invitation',{}).status_code,404)
        groups.invitation(self.owner,self.ident,revoke=True);self.assertFalse(groups.preview(new));new=groups.invitation(self.owner,self.ident)
        self.assertEqual(self.post(self.a,self.path+'/settings',{'action':'remove','user_id':self.member}).status_code,200)
        for suffix in ('','/messages'):self.assertEqual(self.b.get(self.path+suffix).status_code,404)
        with self.assertRaises(groups.GroupError):groups.join(self.member,new)
        for payload in ({'content':'no','kind':'ASK','operation_key':key()},{'kind':'SUMMARY','operation_key':key()}):self.assertEqual(self.post(self.b,self.path+'/messages',payload).status_code,404)
        self.assertEqual(self.post(self.a,self.path+'/settings',{'action':'remove','user_id':self.owner}).status_code,400)

    def test_personal_and_other_group_secrets_excluded_from_ai(self):
        second=groups.create(self.other,'Other group');groups.send(self.other,second,'OTHER GROUP SECRET',key())
        thread=store.create_thread(self.owner);store.append_user_once(self.owner,thread,'PERSONAL SECRET','FAST',key());self.join()
        with patch.object(providers,'stream',side_effect=lambda *a,**kw:events()) as provider:
            result=self.post(self.b,self.path+'/messages',{'content':'@Kilas bantu keputusan ini','operation_key':key()})
            self.assertEqual(result.json['status'],'COMPLETE');self.assertNotIn('SECRET',str(provider.call_args.args[1]));self.assertIn('ONLY',provider.call_args.kwargs['system'])
        self.assertEqual(self.a.get(f'/kilas-ai/groups/{second}/messages').status_code,404)
        self.assertEqual(self.b.get(f'/kilas-ai/threads/{thread}').status_code,404);self.assertEqual(len(store.messages(self.owner,thread)),1)

    def test_summary_bills_owner_only_and_retry_cached(self):
        self.join();groups.send(self.owner,self.ident,'Kita setuju opsi A.',key());payload={'kind':'SUMMARY','operation_key':key()}
        with patch.object(providers,'stream',side_effect=lambda *a,**kw:events()) as provider:
            self.assertEqual(self.post(self.b,self.path+'/messages',payload).json['status'],'COMPLETE');self.assertTrue(self.post(self.b,self.path+'/messages',payload).json['cached'])
            self.assertEqual(provider.call_count,1);self.assertIn('Kita setuju opsi A.',str(provider.call_args.args[1]))
        rows=db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=?',(self.owner,));self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'COMPLETE');self.assertIsNone(rows[0]['thread_id'])
        self.assertEqual(db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=?',(self.member,)),[])
        self.assertEqual(groups.state(self.owner,self.ident)['ai_requests'],1);self.assertNotIn('ai_requests',groups.state(self.member,self.ident));self.assertIn('@Kilas /summary',[m['content'] for m in groups.state(self.member,self.ident)['messages']])

    def test_pause_and_owner_quota_prevent_provider(self):
        self.join();groups.manage(self.owner,self.ident,'ai',enabled=False)
        with patch.object(providers,'stream') as provider:
            self.assertEqual(self.post(self.b,self.path+'/messages',{'content':'@Kilas hi','operation_key':key()}).status_code,403)
            self.assertEqual(self.post(self.b,self.path+'/settings',{'action':'ai','enabled':True}).status_code,404)
            groups.manage(self.owner,self.ident,'ai',enabled=True)
            with patch.object(usage,'reserve',side_effect=usage.UsageLimit('limit')):
                result=self.post(self.b,self.path+'/messages',{'content':'ask','kind':'ASK','operation_key':key()});self.assertEqual(result.json['status'],'FAILED');self.assertIn('capacity',result.json['error'])
            provider.assert_not_called()
        self.assertEqual(len(groups.state(self.member,self.ident)['messages']),1)

    def test_concurrent_duplicates_and_ai_mutex_allow_human_messages(self):
        self.join();started=threading.Event();release=threading.Event();operation=key()
        def provider(*a,**kw):
            started.set();assert release.wait(5);yield from events()
        with patch.object(providers,'stream',side_effect=provider) as mock,ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(groups.send,self.member,self.ident,'ask',operation,'ASK');self.assertTrue(started.wait(5))
            duplicate=pool.submit(groups.send,self.member,self.ident,'ask',operation,'ASK').result(5);self.assertTrue(duplicate['cached']);self.assertEqual(duplicate['status'],'DISPATCHED')
            with self.assertRaises(groups.GroupError) as error:groups.send(self.owner,self.ident,'another',key(),'ASK')
            self.assertEqual(error.exception.code,'ai_busy');groups.send(self.owner,self.ident,'Human discussion still works',key());release.set();self.assertEqual(first.result(5)['status'],'COMPLETE');self.assertEqual(mock.call_count,1)
        self.assertEqual(len(db.query_all('SELECT * FROM kilas_ai_usage WHERE user_id=?',(self.owner,))),1);self.assertEqual(len(groups.state(self.owner,self.ident)['messages']),3)

    def test_remove_during_generation_no_answer_publication_or_leak(self):
        self.join()
        def provider(*a,**kw):
            yield {'type':'provider','provider':'openai','model':'gpt-6-luna'};groups.manage(self.owner,self.ident,'remove',target=self.member);yield from list(events())[1:]
        with patch.object(providers,'stream',side_effect=provider):self.assertEqual(self.post(self.b,self.path+'/messages',{'content':'ask','kind':'ASK','operation_key':key()}).status_code,404)
        self.assertEqual([r['role'] for r in groups.state(self.owner,self.ident)['messages']],['user']);self.assertEqual(db.query_one('SELECT status FROM kilas_ai_usage WHERE user_id=?',(self.owner,))['status'],'FAILED')

    def test_remove_between_reserve_and_dispatch(self):
        self.join();reserve=usage.reserve
        def removal(*a,**kw):
            value=reserve(*a,**kw);groups.manage(self.owner,self.ident,'remove',target=self.member);return value
        with patch.object(usage,'reserve',side_effect=removal),patch.object(providers,'stream') as provider:
            self.assertEqual(self.post(self.b,self.path+'/messages',{'content':'ask','kind':'ASK','operation_key':key()}).status_code,404);provider.assert_not_called()

    def test_failure_and_unknown_retry_never_redispatch(self):
        payload={'content':'@Kilas answer','operation_key':key()}
        with patch.object(providers,'stream',side_effect=providers.ProviderError('synthetic')) as provider:
            self.assertEqual(self.post(self.a,self.path+'/messages',payload).json['status'],'FAILED');self.assertTrue(self.post(self.a,self.path+'/messages',payload).json['cached']);self.assertEqual(provider.call_count,1)
        self.assertEqual(len(groups.state(self.owner,self.ident)['messages']),1)

    def test_pagination_order_and_durability(self):
        with groups.transaction() as conn:
            for n in range(105):
                op='fixture-'+key();usage._query(conn,"INSERT INTO kilas_chat_group_operations VALUES (?,?,?,?,'TEXT','COMPLETE',NULL,?)",(op,self.ident,self.owner,op,groups.stamp()))
                usage._query(conn,"INSERT INTO kilas_chat_group_messages(group_id,user_id,role,content,operation_key,created_at) VALUES (?,?,'user',?,?,?)",(self.ident,self.owner,str(n),op,groups.stamp()))
        latest=self.a.get(self.path+'/messages').json;self.assertEqual(len(latest['messages']),100);self.assertTrue(latest['has_older']);before=latest['messages'][0]['id']
        older=self.a.get(self.path+f'/messages?before={before}').json;self.assertEqual(len(older['messages']),5);self.assertFalse(older['has_older'])
        ids=[r['id'] for r in older['messages']+latest['messages']];self.assertEqual(ids,sorted(set(ids)));self.assertEqual(self.a.get(self.path+f'/messages?after={ids[-1]}').json['messages'],[])

    def test_limits_empty_summary_languages_and_revoked_login(self):
        for payload in ({'content':'x'*6001,'operation_key':key()},{'content':'x','operation_key':'bad'},{'kind':'SUMMARY','operation_key':key()}):self.assertEqual(self.post(self.a,self.path+'/messages',payload).status_code,400)
        self.assertEqual(self.post(self.a,'/kilas-ai/groups',{'name':'x'*101}).status_code,400);self.assertEqual(self.a.get(self.path+'/messages?after=bad').status_code,400)
        self.join();groups.send(self.member,self.ident,'<img src=x onerror=alert(1)>',key())
        for language,label in [('id','Chat grup'),('en','Group chat'),('es','Chat de grupo'),('zh','群聊')]:
            self.a.set_cookie('kilas_language',language);page=self.a.get(self.path);self.assertEqual(page.status_code,200);self.assertIn(label,page.text);self.assertNotIn('<img src=x onerror',page.text)
        customer_auth.revoke_all(self.owner);self.assertIn(self.a.get(self.path+'/messages').status_code,(401,302,303))

    def test_existing_owner_credits_and_hard_budget_are_authoritative(self):
        from datetime import timedelta
        from decimal import Decimal
        from kilas_ai import capacity
        self.join();now=usage._now()
        db.execute("INSERT INTO kilas_ai_subscriptions(user_id,plan,status,period_start,period_end) VALUES (?,'PRO','ACTIVE',?,?)",(self.owner,now.isoformat(),(now+timedelta(days=30)).isoformat()))
        with patch.object(capacity,'allowance',return_value=Decimal(0)),patch.object(providers,'stream',side_effect=lambda *a,**kw:events()) as provider:
            result=groups.send(self.member,self.ident,'ask without credit',key(),'ASK');self.assertEqual(result['error'],'owner_quota');provider.assert_not_called()
            order=db.insert_returning_id("INSERT INTO kilas_ai_topup_orders(user_id,invoice_number,pack,amount_idr,status) VALUES (?,?,'MINI',39000,'VERIFIED')",(self.owner,'SYNTHETIC-'+key()))
            db.execute('INSERT INTO kilas_ai_topup_credits(order_id,user_id,total_micro,expires_at) VALUES (?,?,1000000,?)',(order,self.owner,(now+timedelta(days=30)).isoformat()))
            self.assertEqual(groups.send(self.member,self.ident,'ask with owner credit',key(),'ASK')['status'],'COMPLETE')
        debit=db.query_one('SELECT * FROM kilas_ai_topup_debits WHERE user_id=?',(self.owner,))
        self.assertEqual(debit['status'],'COMPLETE');self.assertGreater(debit['charged_micro'],0)
        self.assertEqual(db.query_all('SELECT * FROM kilas_ai_topup_debits WHERE user_id=?',(self.member,)),[])

    def test_personal_chat_stream_and_privacy_regression(self):
        thread=store.create_thread(self.owner)
        with patch.object(providers,'stream',return_value=events('Halo.')):
            response=self.post(self.a,f'/kilas-ai/threads/{thread}/send',{'content':'Halo','operation_key':key()});self.assertEqual(response.status_code,200);self.assertIn('Halo.',response.get_data(as_text=True))
        self.assertEqual([r['role'] for r in store.messages(self.owner,thread)],['user','assistant']);self.assertEqual(groups.state(self.owner,self.ident)['messages'],[])
        self.assertEqual(self.b.get(f'/kilas-ai/threads/{thread}').status_code,404)
        for language in ('id','en','es','zh'):
            self.a.set_cookie('kilas_language',language)
            for path in ('/kilas-ai',f'/kilas-ai/threads/{thread}'):
                page=self.a.get(path);self.assertEqual(page.status_code,200)
                self.assertNotIn('group-chat-tabs',page.text);self.assertNotIn('href="/kilas-ai/groups',page.text)
                for control in ('ai-composer','ai-input','ai-send','ai-files'):
                    self.assertIn(f'id="{control}"',page.text)

if __name__=='__main__':unittest.main()
