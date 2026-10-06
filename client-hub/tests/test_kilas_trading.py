"""Real app/SQLite paper simulation acceptance; no production/provider IO."""
import os
import sys
import tempfile
import uuid
import unittest
from pathlib import Path
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['SECRET_KEY'] = 'trading-disposable-tests-only'
os.environ['KILAS_TRADING_ENABLED'] = 'true'
os.environ['KILAS_TRADING_SCHEMA_APPLY'] = 'true'
if os.environ.get('TRADING_POSTGRES_QA') != '1':
    os.environ.pop('DATABASE_URL', None)
    os.environ['CLIENT_HUB_DB_PATH'] = tempfile.mktemp(suffix='.sqlite')
import app
import db
import repo
import security
from kilas_trading import store, engine, schema


class TradingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.user = repo.create_user('irvankarnavi@gmail.com', security.hash_password('paper-test-only'))
        cls.other = repo.create_user('other-owner@example.test', 'hash')
        cls.admin = repo.create_user('other-admin@example.test', 'hash', role='KILAS_ADMIN')
        db.execute("INSERT INTO oauth_identities(provider,provider_subject,user_id,email_at_link) VALUES ('google','synthetic-paper-pilot',?,?)", (cls.user, 'irvankarnavi@gmail.com'))

    def setUp(self):
        for table in ('kilas_trading_events', 'kilas_trading_positions', 'kilas_trading_accounts'):
            db.execute('DELETE FROM ' + table)
        self.client = self.login(self.user)
        self.transport = patch('requests.sessions.Session.request', side_effect=AssertionError('Trading must never call a provider'))
        self.transport.start(); self.addCleanup(self.transport.stop)

    def login(self, user):
        c = app.app.test_client()
        with c.session_transaction() as s:
            s.update(user_id=user, role=db.query_one('SELECT role FROM users WHERE id=?',(user,))['role'], _csrf_token='paper-csrf')
        return c

    def act(self, action, **data):
        body = dict(operation_key=uuid.uuid4().hex, tick=str(store.snapshot(self.user)['account']['tick']), **data)
        return store.act(self.user, action, body)

    def order(self, side='BUY', **data):
        price = store.snapshot(self.user)['price_cents']/100
        sign = 1 if side=='BUY' else -1
        return self.act('order', **dict(side=side, quantity='0.01', stop=str(price-sign*300), target=str(price+sign*600), **data))

    def test_exact_pilot_server_gate(self):
        self.assertEqual(app.app.test_client().get('/products/services/trading').status_code,302)
        self.assertEqual(self.client.get('/products/services/trading').status_code,200)
        for user in (self.other,self.admin):
            c=self.login(user)
            self.assertEqual(c.get('/products/services/trading').status_code,404)
            self.assertEqual(c.post('/products/services/trading/order',json={'operation_key':uuid.uuid4().hex},headers={'X-CSRF-Token':'paper-csrf'}).status_code,404)
            with self.assertRaises(PermissionError):store.snapshot(user)
        self.assertEqual(db.query_one('SELECT count(*) AS n FROM kilas_trading_accounts')['n'],1)

    def test_verification_revocation_and_support(self):
        db.execute('DELETE FROM oauth_identities WHERE user_id=?',(self.user,))
        try:self.assertEqual(self.client.get('/products/services/trading').status_code,404)
        finally:db.execute("INSERT INTO oauth_identities(provider,provider_subject,user_id,email_at_link) VALUES ('google','synthetic-paper-pilot',?,?)",(self.user,'irvankarnavi@gmail.com'))
        with self.client.session_transaction() as s:s['support_business_id']=999
        self.assertEqual(self.client.get('/products/services/trading').status_code,404)

    def test_csrf_and_disabled_flag(self):
        self.assertEqual(self.client.post('/products/services/trading/pause',json={'operation_key':uuid.uuid4().hex}).status_code,400)
        with patch.dict(os.environ,{'KILAS_TRADING_ENABLED':'false'}):
            self.assertEqual(self.client.get('/products/services/trading').status_code,404)
            with self.assertRaises(PermissionError):store.snapshot(self.user)

    def test_services_catalog_and_pilot_card(self):
        page=self.client.get('/products/services')
        for item in ('Form &amp; Online Assistance','Content Studio','Talent Management','Kilas Trading'):
            self.assertIn(item,page.text)
        self.assertNotIn('Buka Kilas Trading',self.login(self.other).get('/products/services').text)
        self.assertIn('/products/services',self.client.get('/products/start').text)

    def test_finance_session_not_changed(self):
        with self.client.session_transaction() as s:s['active_product']='finance'
        self.assertEqual(self.client.get('/products/services/trading').status_code,200)
        self.order()
        with self.client.session_transaction() as s:self.assertEqual(s['active_product'],'finance')

    def test_other_product_rows_unchanged(self):
        tables=['users','businesses','finance_accounts','finance_transactions','service_catalog','kilas_ai_usage']
        existing={r['name'] for r in db.query_all("SELECT name FROM sqlite_master WHERE type='table'")} if db.BACKEND=='sqlite' else {r['table_name'] for r in db.query_all('SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()')}
        before={t:db.query_all('SELECT * FROM '+t+' ORDER BY 1') for t in tables if t in existing}
        self.order(); self.act('step'); self.act('pause')
        for t,rows in before.items():self.assertEqual(rows,db.query_all('SELECT * FROM '+t+' ORDER BY 1'),t)

    def test_order_close_pnl_persistence(self):
        self.assertEqual(self.order()['outcome'],'OK')
        state=store.snapshot(self.user);p=state['positions'][0]
        self.act('step');self.act('close',position_id=str(p['id']))
        self.assertEqual(store.snapshot(self.user)['positions'],[])
        saved=db.query_one('SELECT * FROM kilas_trading_positions WHERE id=?',(p['id'],))
        self.assertEqual(saved['status'],'CLOSED')
        self.assertEqual(saved['pnl_cents'],engine.pnl(p,saved['exit_cents']))
        import importlib
        importlib.reload(store)
        self.assertEqual(store.snapshot(self.user)['account']['realized_cents'],saved['pnl_cents'])

    def test_sell_and_protect_tighten_only(self):
        self.order('SELL');s=store.snapshot(self.user);p=s['positions'][0];price=s['price_cents']/100
        self.assertEqual(self.act('protect',position_id=str(p['id']),stop=str(price+400),target=str(price-700))['outcome'],'REJECTED')
        self.assertEqual(self.act('protect',position_id=str(p['id']),stop=str(price+200),target=str(price-700))['outcome'],'OK')

    def test_invalid_sizing_and_wrong_sides(self):
        for value in ('NaN','Infinity','-1','0.0000001','2'):
            with self.assertRaises(engine.TradingError):engine.scaled(value,engine.UNITS,engine.UNITS)
        price=store.snapshot(self.user)['price_cents']/100
        for size,stop,target in [('0',price-300,price+600),('0.01',price+300,price+600),('0.01',0,price+600)]:
            self.assertEqual(self.act('order',side='BUY',quantity=size,stop=str(stop),target=str(target))['outcome'],'REJECTED')
        self.assertEqual(store.snapshot(self.user)['positions'],[])

    def test_risk_and_exposure_limits(self):
        p=store.snapshot(self.user)['price_cents']/100
        self.assertEqual(self.act('order',side='BUY',quantity='0.03',stop=str(p-5000),target=str(p+600))['outcome'],'REJECTED')
        self.assertEqual(self.act('order',side='BUY',quantity='0.04',stop=str(p-300),target=str(p+600))['outcome'],'REJECTED')
        for _ in range(3):self.assertEqual(self.order()['outcome'],'OK')
        self.assertEqual(self.order()['outcome'],'REJECTED')

    def test_daily_loss_blocks_new_orders(self):
        self.order();p=store.snapshot(self.user)['positions'][0]
        db.execute("UPDATE kilas_trading_positions SET status='CLOSED',closed_at=?,pnl_cents=-50001 WHERE id=?",(store.stamp(),p['id']))
        self.assertEqual(self.order()['outcome'],'REJECTED')

    def test_stale_missing_and_changed_snapshot(self):
        store.snapshot(self.user)
        db.execute('UPDATE kilas_trading_accounts SET generated_at=? WHERE user_id=?',((store.now()-timedelta(minutes=3)).isoformat(),self.user))
        self.assertEqual(self.order()['outcome'],'REJECTED')
        self.assertEqual(self.act('refresh')['outcome'],'OK');self.assertEqual(self.order()['outcome'],'OK')
        self.assertEqual(store.act(self.user,'step',{'tick':'59','operation_key':uuid.uuid4().hex})['outcome'],'REJECTED')

    def test_pause_resume_kill_and_close(self):
        self.order();p=store.snapshot(self.user)['positions'][0]
        self.act('pause');self.assertEqual(self.order()['outcome'],'REJECTED')
        self.act('resume');self.assertEqual(self.order()['outcome'],'OK')
        self.act('kill');self.assertEqual(self.act('resume')['outcome'],'REJECTED');self.assertEqual(self.order()['outcome'],'REJECTED')
        self.assertEqual(self.act('close',position_id=str(p['id']))['outcome'],'OK')
        self.assertEqual(self.act('step')['outcome'],'OK')

    def test_order_dedup_and_fingerprint(self):
        p=store.snapshot(self.user)['price_cents']/100
        data={'operation_key':uuid.uuid4().hex,'tick':'60','side':'BUY','quantity':'0.01','stop':str(p-300),'target':str(p+600)}
        store.act(self.user,'order',data);store.act(self.user,'order',data)
        self.assertEqual(len(store.snapshot(self.user)['positions']),1)
        with self.assertRaises(engine.TradingError):store.act(self.user,'order',dict(data,quantity='0.02'))

    def test_concurrent_dedup(self):
        p=store.snapshot(self.user)['price_cents']/100
        data={'operation_key':uuid.uuid4().hex,'tick':'60','side':'BUY','quantity':'0.01','stop':str(p-300),'target':str(p+600)}
        with ThreadPoolExecutor(4) as pool:results=list(pool.map(lambda _:store.act(self.user,'order',data),range(4)))
        self.assertEqual(sum(not r['duplicate'] for r in results),1)
        self.assertEqual(len(store.snapshot(self.user)['positions']),1)

    def test_concurrent_exposure_serialized(self):
        p=store.snapshot(self.user)['price_cents']/100
        def create(_):return store.act(self.user,'order',{'operation_key':uuid.uuid4().hex,'tick':'60','side':'BUY','quantity':'0.02','stop':str(p-300),'target':str(p+600)})
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(create,range(2)))
        self.assertEqual(sum(r['outcome']=='OK' for r in results),1)

    def test_position_owner_scope(self):
        self.order()
        self.assertEqual(self.act('close',position_id='99999')['outcome'],'REJECTED')
        self.assertEqual(len(store.snapshot(self.user)['positions']),1)

    def test_stop_priority_gap_and_trailing(self):
        p={'side':'BUY','entry_cents':10000,'stop_cents':9500,'target_cents':11000,'trailing_cents':100,'activation_cents':200}
        self.assertEqual(engine.protect(p,{'open':9000,'low':8900,'high':12000,'close':11500})[:2],(9000,'SL'))
        self.assertEqual(engine.protect(p,{'open':10000,'low':9900,'high':10500,'close':10400})[2],10300)
        p.update(side='SELL',stop_cents=10500,target_cents=9000)
        self.assertEqual(engine.protect(p,{'open':11000,'low':8000,'high':11100,'close':9000})[:2],(11000,'SL'))
        self.assertEqual(engine.protect(p,{'open':10000,'low':9500,'high':10100,'close':9600})[2],9700)

    def test_agent_no_signal_evidence_and_dedup(self):
        r=self.act('agent');self.assertEqual(r['outcome'],'NO_SIGNAL')
        e=store.snapshot(self.user)['events'][0]
        self.assertIn('closes_cents',e['inputs']['decision']);self.assertIn('previous_fast_cents',e['inputs']['decision'])
        self.assertTrue(self.act('agent')['duplicate'])

    def test_agent_real_crossing_orders_and_risk(self):
        crossing=next(t for t in range(61,150) if engine.decision(engine.STRATEGY,engine.candles(t))[0])
        store.snapshot(self.user);db.execute('UPDATE kilas_trading_accounts SET tick=? WHERE user_id=?',(crossing,self.user))
        self.assertEqual(self.act('agent')['outcome'],'OK');self.assertEqual(len(store.snapshot(self.user)['positions']),1)

    def test_atomic_replay_duplicate_and_stop_settlement(self):
        self.order();p=store.snapshot(self.user)['positions'][0];bar=engine.candle(61)
        db.execute('UPDATE kilas_trading_positions SET stop_cents=? WHERE id=?',(bar['low']+1,p['id']))
        data={'operation_key':uuid.uuid4().hex,'tick':'60'}
        store.act(self.user,'step',data);store.act(self.user,'step',data)
        s=store.snapshot(self.user);self.assertEqual(s['account']['tick'],61);self.assertEqual(s['positions'],[])
        self.assertEqual(len(s['events']),2);self.assertEqual(s['events'][0]['inputs']['closed_positions'][0]['reason'],'SL')

    def test_config_bounds_and_no_side_effect_order(self):
        data=dict(engine.STRATEGY,risk_percent='0.5',max_positions='2',max_exposure='1000',daily_loss='100')
        self.assertEqual(self.act('configure',**data)['outcome'],'OK')
        self.assertEqual(store.snapshot(self.user)['risk']['risk_bps'],50);self.assertEqual(store.snapshot(self.user)['positions'],[])
        self.assertEqual(self.act('configure',**dict(data,risk_percent='2'))['outcome'],'REJECTED')

    def test_schema_idempotence(self):
        self.assertEqual(schema.apply_release(),[])


if __name__=='__main__':unittest.main(verbosity=2)
