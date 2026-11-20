import os
import time
import unittest
from unittest.mock import patch
import test_kilas_trading as f
from kilas_trading import hfm_sol as sol

PATH='/products/services/trading/robot-hfm/signal'
HOST='https://trading.kilasworks.id'


class RobotProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not hasattr(f.TradingTests,'user'):
            f.TradingTests.setUpClass()

    def setUp(self):
        self.base=f.TradingTests('test_xauusd_contract_and_units')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.user=self.base.user
        self.owner=self.login(self.user)
        self.device=f.app.app.test_client()
        f.db.execute('DELETE FROM hfm_sol_devices WHERE user_id=?',(self.user,))
        self.token=sol.issue(self.user,'12345')
        self.data={'login':'12345','server':sol.SERVER,'symbol':'XAUUSDc','at':int(time.time()),
                   'bar':1782000000,'side':'BUY','bid':3000,'ask':3000.3,'sl':2990,'tp':3020,
                   'frames':{k:[[3000,3005,2995,3002]]*6 for k in sol.FRAMES}}

    def login(self,user):
        import customer_auth
        c=self.base.login(user)
        row=f.db.query_one('SELECT * FROM users WHERE id=?',(user,))
        with f.app.app.app_context(), c.session_transaction() as session:
            session[customer_auth.SID]=customer_auth.create(row)
        return c

    def call(self):
        return self.device.post(PATH,base_url=HOST,json=self.data,
                                headers={'Authorization':'Bearer '+self.token})

    def test_product_visibility_download_and_revoke(self):
        self.assertIn('Robot Trading',self.owner.get('/products/catalog').text)
        self.assertNotIn('Robot Trading',self.login(self.base.other).get('/products/catalog').text)
        self.assertEqual(self.login(self.base.other).get('/products/robot-trading/download').status_code,404)
        self.assertEqual(self.owner.get('/products/robot-trading').status_code,200)
        with self.owner.get('/products/robot-trading/download') as download:
            self.assertGreater(len(download.data),20000)
        self.assertEqual(self.owner.post('/products/robot-trading/pair',data={'login':'12345'}).status_code,400)
        result=self.owner.post('/products/robot-trading/pair',data={'csrf_token':'paper-csrf','login':'12345'})
        self.assertEqual(result.status_code,200)
        login,secret=result.data.decode().splitlines()
        self.assertEqual(login,'12345')
        self.assertFalse(sol.device(sol.digest(self.token)))
        self.token=secret
        self.assertIsNotNone(sol.device(sol.digest(secret)))
        self.owner.post('/products/robot-trading/revoke',data={'csrf_token':'paper-csrf'})
        self.assertEqual(self.call().status_code,403)

    def test_approval_market_only_once(self):
        response={'status':'completed','model':sol.MODEL,'output':[{'type':'message','content':[
            {'type':'output_text','text':'{"decision":"BUY"}'}]}]}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'mock-local'}),patch.object(sol,'_http',return_value=response) as model:
            self.assertEqual(self.call().text,'K1|1782000000|BUY')
            body=model.call_args.args[3]
            self.assertEqual(body['model'],sol.MODEL)
            self.assertNotIn('12345',body['input'])
            self.assertEqual(self.call().status_code,429)
            self.assertEqual(model.call_count,1)
            response['output'][0]['content'][0]['text']='{"decision":"SELL"}'
            self.assertEqual(sol.analyze(self.data,'mock-local'),'WAIT')

    def test_fail_closed(self):
        self.data['at']-=80
        self.assertEqual(self.call().status_code,400)
        self.data['at']=int(time.time())
        self.data['login']='54321'
        self.assertEqual(self.call().status_code,400)
        self.data['login']='12345'
        with patch.dict(os.environ,{'OPENAI_API_KEY':'mock-local'}),patch.object(sol,'_http',side_effect=TimeoutError()):
            self.assertEqual(self.call().status_code,503)
            self.assertEqual(self.call().status_code,429)
        self.assertEqual(self.device.post(PATH,base_url='https://app.kilasworks.id',json=self.data).status_code,404)


    def test_daily_budget_survives_rotation_and_disabled_owner(self):
        day=int(time.time())//86400
        f.db.execute('UPDATE hfm_sol_devices SET calls=?,quota_day=? WHERE user_id=?',(sol.MAX_CALLS,day,self.user))
        self.token=sol.issue(self.user,'12345')
        with patch.dict(os.environ,{'OPENAI_API_KEY':'mock-local'}),patch.object(sol,'_http') as model:
            self.assertEqual(self.call().status_code,429)
            model.assert_not_called()
        f.db.execute('UPDATE customer_auth_account_state SET disabled=1 WHERE user_id=?',(self.user,))
        try:
            self.assertEqual(self.call().status_code,403)
        finally:
            f.db.execute('UPDATE customer_auth_account_state SET disabled=0 WHERE user_id=?',(self.user,))
