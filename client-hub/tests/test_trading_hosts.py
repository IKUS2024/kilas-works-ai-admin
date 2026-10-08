"""Separate host routing/auth regressions on disposable SQLite, no broker/order actions."""
import copy,re,unittest
from unittest.mock import patch
import test_kilas_trading as f
APP='https://app.kilasworks.id';TRADING='https://trading.kilasworks.id'
PATH='/products/services/trading'

class TradingHostsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not hasattr(f.TradingTests,'user'):f.TradingTests.setUpClass()
    def setUp(self):
        self.base=f.TradingTests('test_xauusd_contract_and_units');self.base.setUp();self.addCleanup(self.base.doCleanups)
    def client(self,user,host):
        client=self.base.login(user);cookie=client.get_cookie('session').value
        client.set_cookie('session',cookie,domain=host.split('://')[1]);return client
    def test_app_restores_services_and_no_trading_entry(self):
        c=self.client(f.TradingTests.user,APP)
        for path in ('/products/start','/products/services'):
            page=c.get(path,base_url=APP);self.assertEqual(page.status_code,200)
            self.assertIn('Kilas Services',page.text);self.assertNotIn('Kilas Trading',page.text)
        self.assertEqual(c.get(PATH,base_url=APP).location,TRADING+'/')
        self.assertEqual(c.post(PATH+'/analyze',base_url=APP,json={}).status_code,404)
    def test_trading_host_is_dashboard_only_and_keeps_pilot_gate(self):
        c=self.client(f.TradingTests.user,TRADING)
        self.assertEqual(c.get('/',base_url=TRADING,follow_redirects=True).status_code,200)
        page=c.get(PATH,base_url=TRADING);self.assertIn('Kilas Trading',page.text)
        self.assertNotIn('Kilas Services',page.text);self.assertNotIn('Kilas Finance',page.text)
        for path in ('/products/services','/account','/register','/auth/google','/oauth/google','/oauth/google/start','/settings'):
            self.assertEqual(c.get(path,base_url=TRADING).status_code,404,path)
        for user in (f.TradingTests.other,f.TradingTests.admin):self.assertEqual(self.client(user,TRADING).get(PATH,base_url=TRADING).status_code,404)
        anonymous=f.app.app.test_client();self.assertEqual(anonymous.get(PATH,base_url=TRADING).location,'/login')
        self.assertIn('Masuk ke Kilas Trading',anonymous.get('/login',base_url=TRADING).text)
        self.assertNotIn('Masuk dengan Google',anonymous.get('/login',base_url=TRADING).text)
    def test_host_allowlist_and_forwarded_host_spoofing(self):
        c=self.client(f.TradingTests.user,APP)
        self.assertEqual(c.get('/',base_url='https://evil.test').status_code,400)
        page=c.get('/products/start',base_url=APP,headers={'X-Forwarded-Host':'trading.kilasworks.id'})
        self.assertEqual(page.status_code,200);self.assertNotIn('Kilas Trading',page.text)
    def test_password_login_logout_csrf_and_host_only_cookie(self):
        c=f.app.app.test_client()
        page=c.get('/login',base_url=TRADING);token=re.search('name="csrf_token" value="([^"]+)"',page.text)[1]
        with patch.dict(f.app.app.config,{'SESSION_COOKIE_SECURE':True}):
            response=c.post('/login',base_url=TRADING,data={'csrf_token':token,'email':'irvankarnavi@gmail.com','password':'paper-test-only'})
            cookie=response.headers.get('Set-Cookie','')
            self.assertIn('Secure',cookie);self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Lax',cookie)
            self.assertNotIn('Domain=',cookie);self.assertNotIn('Max-Age=',cookie)
            self.assertEqual(c.get(response.location,base_url=TRADING,follow_redirects=True).status_code,200)
            # App host receives no trading-host cookie and remains unauthenticated.
            self.assertEqual(c.get('/products/start',base_url=APP).location,'/login')
            self.assertEqual(c.post(PATH+'/analyze',base_url=TRADING,json={}).status_code,400)
            self.assertEqual(c.get('/logout',base_url=TRADING).location,'/login')
            self.assertEqual(c.get(PATH,base_url=TRADING).location,'/login')
        self.assertEqual(f.db.query_one('SELECT count(*) AS n FROM kilas_trading_positions')['n'],0)
