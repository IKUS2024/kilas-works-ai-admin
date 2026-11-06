"""Synthetic Interpreter wallet boundaries; no provider calls or paid tariffs."""
import json
import os
import struct
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4
import db
from kilas_ai import credit_interpreter as interpreter, credit_policy as policy, credit_wallet as wallet, usage
from test_kilas_credit_adapters import AdapterTests


class InterpreterTests(unittest.TestCase):
    setUp=AdapterTests.setUp
    tearDown=AdapterTests.tearDown
    fund=AdapterTests.fund
    proof=AdapterTests.proof
    approve=AdapterTests.approve
    state=AdapterTests.state

    def terms(self,maximum=1000):
        value=json.loads(os.environ['KILAS_CREDIT_TARIFFS_JSON'])
        value['rates']['INTERPRETER']={'milli':2000,'units':1000}
        value['limits']['INTERPRETER']={'models':['gemini-3.8-live'],'source_ms':maximum,'output_ratio_milli':2000}
        return patch.dict(os.environ,{'KILAS_CREDIT_TARIFFS_JSON':json.dumps(value)})

    def test_both_directions_share_free_and_idle_is_zero(self):
        with self.terms():
            for language in ('id','en'):
                ident=uuid4().hex
                context=interpreter.start(1,ident,{'source':language})
                meter=interpreter.Meter(context)
                meter.input(b'\0\0'*16000)
                interpreter.dispatched(1,ident,0)
                meter.finish(1,ident,0)
                self.assertEqual(self.state(interpreter.operation(ident,0))['actual_units'],0)
            with wallet._locked(1) as conn:self.assertEqual(policy.remaining_in(conn,1,'TRANSLATOR',usage._now()),180000)
            ident=uuid4().hex;meter=interpreter.Meter(interpreter.start(1,ident,{'source':'id'}))
            meter.input(struct.pack('<h',1000)*16000)
            meter.audio(struct.pack('<h',1000)*24000)
            meter.finish(1,ident,0,confirmed=True)
            with self.assertRaisesRegex(wallet.WalletError,'closed'):meter.input(b'\0\0')
            meter.finish(1,ident,0,confirmed=True)
            self.assertEqual(self.state(interpreter.operation(ident,0))['free_actual'],1000)
            with self.assertRaisesRegex(wallet.WalletError,'closed'):interpreter.begin(1,ident,0,{'source':'id'})

    def test_paid_engine_specific_quote_split_and_binding(self):
        self.fund()
        policy.admit(1,'free-used','TRANSLATOR',179500,'a'*64)
        policy.finish(1,'free-used',179500,success=True)
        ident=uuid4().hex
        with self.terms():
            with self.assertRaises(policy.ConsentRequired) as caught:interpreter.start(1,ident,{'source':'id'})
            token=policy.persist_consent(caught.exception)
            row=db.query_one('SELECT * FROM kilas_credit_consents WHERE token=?',(token,))
            self.assertEqual(row['maximum_charge'],1000)
            self.assertEqual(json.loads(row['terms_json'])['pricing_feature'],'INTERPRETER')
            with self.assertRaises(wallet.WalletError):policy.consent(2,token,True)
            policy.consent(1,token,True)
            context=interpreter.start(1,ident,{'source':'id'})
            meter=interpreter.Meter(context);meter.input(struct.pack('<h',1000)*16000)
            interpreter.dispatched(1,ident,0);meter.finish(1,ident,0,confirmed=True)
            self.assertEqual(wallet.balance(1)['balance_milli'],1999000)
            with self.assertRaisesRegex(wallet.WalletError,'changed'):interpreter.begin(1,ident,1,{'source':'en'})
            with self.assertRaises(wallet.WalletError):interpreter.begin(1,ident,1,{'source':'id','model':'other'})
            interpreter.close(1,ident)
            with self.assertRaises(wallet.WalletError):interpreter.begin(1,ident,1,{'source':'id'})

    def test_source_and_output_envelope_reject_before_meter_mutation(self):
        with self.terms():
            meter=interpreter.Meter(interpreter.start(1,uuid4().hex,{}))
            with self.assertRaisesRegex(wallet.WalletError,'output_limit'):meter.audio(struct.pack('<h',1000)*24000)
            self.assertEqual(meter.output.milliseconds,0)
            meter.input(struct.pack('<h',1000)*16000)
            with self.assertRaisesRegex(wallet.WalletError,'source_limit'):meter.input(struct.pack('<h',1000)*320)
            self.assertEqual(meter.source.milliseconds,1000)
            meter.audio(struct.pack('<h',1000)*48000)
            with self.assertRaisesRegex(wallet.WalletError,'output_limit'):meter.audio(struct.pack('<h',1000)*480)
            self.assertEqual(meter.output.milliseconds,2000)

    def test_ambiguous_holds_known_failure_releases_and_no_terminal_readmission(self):
        with self.terms():
            for dispatched in (False,True):
                ident=uuid4().hex;meter=interpreter.Meter(interpreter.start(1,ident,{}))
                meter.input(struct.pack('<h',1000)*16000)
                if dispatched:interpreter.dispatched(1,ident,0)
                meter.finish(1,ident,0)
                self.assertEqual(self.state(interpreter.operation(ident,0))['status'],'RESERVED' if dispatched else 'RELEASED')
                with self.assertRaises(wallet.WalletError):interpreter.begin(1,ident,0,{})
                if dispatched:
                    policy.reconcile(1,interpreter.operation(ident,0),3,'NOT_DELIVERED',0,'synthetic delivery review')
                    self.assertEqual(self.state(interpreter.operation(ident,0))['status'],'RELEASED')

    def test_process_loss_end_holds_missing_meter_for_authorized_review(self):
        with self.terms():
            ident=uuid4().hex;interpreter.start(1,ident,{})
            interpreter.dispatched(1,ident,0)
            key=interpreter.operation(ident,0)
            with self.assertRaisesRegex(wallet.WalletError,'still_active'):
                policy.reconcile(1,key,3,'NOT_DELIVERED',0,'synthetic reviewed evidence')
            interpreter.abandon(1,ident)
            self.assertEqual(self.state(key)['status'],'RESERVED')
            with self.assertRaises(wallet.WalletError):interpreter.start(1,ident,{})
            policy.reconcile(1,key,3,'NOT_DELIVERED',0,'synthetic reviewed evidence')
            self.assertEqual(self.state(key)['status'],'RELEASED')

    def test_parallel_admission_single_dispatch_and_foreign_session_rejected(self):
        ident=uuid4().hex
        with self.terms():
            def start(_):
                try:return interpreter.start(1,ident,{})
                except wallet.WalletError:return None
            with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(start,range(8)))
            self.assertEqual(sum(bool(item) for item in results),1)
            # The global session identity cannot be reassigned to another account.
            with self.assertRaisesRegex(wallet.WalletError,'identity_conflict'):interpreter.start(2,ident,{})
            self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_admissions WHERE user_id=2')['n'],0)

    def test_existing_paid_plan_and_accepted_off_policy_session_keep_legacy_access(self):
        from datetime import timedelta
        db.execute('CREATE TABLE kilas_ai_subscriptions(user_id INTEGER,plan TEXT,status TEXT,period_start TEXT,period_end TEXT)')
        now=usage._now()
        db.execute("INSERT INTO kilas_ai_subscriptions VALUES (1,'PLUS','ACTIVE',?,?)",((now-timedelta(days=1)).isoformat(),(now+timedelta(days=1)).isoformat()))
        with self.terms():
            ident=uuid4().hex
            self.assertEqual(interpreter.start(1,ident,{})['mode'],'LEGACY')
            db.execute("UPDATE kilas_ai_subscriptions SET status='CANCELLED'")
            self.assertEqual(interpreter.begin(1,ident,1,{})['mode'],'LEGACY')
            self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_credit_admissions')['n'],0)

    def test_disabled_legacy_and_exact_owner_do_not_acquire_customer_hold(self):
        with patch.dict(os.environ,{'KILAS_CREDIT_ENFORCEMENT_ENABLED':'no'}):self.assertIsNone(interpreter.start(1,uuid4().hex,{}))
        db.execute("INSERT INTO users(id,email,role) VALUES (9,?,'CLIENT_OWNER')",(policy.OWNER_EMAIL,))
        with self.terms():
            self.assertEqual(interpreter.start(9,uuid4().hex,{})['mode'],'OWNER')
            db.execute("UPDATE users SET email='different@example.invalid' WHERE id=9")
            self.assertEqual(interpreter.start(9,uuid4().hex,{})['mode'],'CUSTOMER')


if __name__=='__main__':unittest.main()
