"""Offline local diagnostic parser/security contracts; synthetic data only."""
import json
import subprocess
import unittest
from pathlib import Path

PARSER = Path(__file__).resolve().parents[1] / 'static/kilas_trading.js'


def diagnostic_fixture():
    flags = dict(runtime_eligible=False, broker_execution_allowed=False, paper_execution=False, ai_analysis=False)
    return dict(flags, status='READ_ONLY_DEMO_DIAGNOSTIC_CAPTURED', input_kind='DEMO_OBSERVATION',
                finished_utc='2026-10-09T15:47:08.104107Z', producer_acceptance='NOT_IMPLEMENTED',
                sdk_shutdown='COMPLETED', source_semantics='CANDIDATE_PROFILE_NOT_BROKER_VERIFIED',
                history_complete=False, profit_after_costs='NOT_EVALUATED', drawdown='NOT_EVALUATED', ntp_datagrams_sent=8,
                collection=dict(flags, schema='kilas-collector-diagnostic-v1', status='DIAGNOSTIC_COLLECTION_VALIDATED',
                                synthetic=True, producer_acceptance='NOT_IMPLEMENTED', request_count=8,
                                cycles=[dict(qualification=dict(flags, status='OFFLINE_CLOCK_BATCH_VALIDATED',
                                        assurance='UNAUTHENTICATED_OPERATIONAL_PAPER_ONLY', producer_acceptance='NOT_IMPLEMENTED',
                                        attempt_count=4, reply_count=4)) for _ in range(2)]),
                clock_results=[dict(flags, input_kind='DEMO_OBSERVATION', policy_replay_only=True,
                                    producer_acceptance='NOT_IMPLEMENTED', clock_assurance='UNAUTHENTICATED_OPERATIONAL_PAPER_ONLY',
                                    status='WAIT'), dict(flags, input_kind='DEMO_OBSERVATION', policy_replay_only=True,
                                    producer_acceptance='NOT_IMPLEMENTED', clock_assurance='UNAUTHENTICATED_OPERATIONAL_PAPER_ONLY',
                                    status='READ_ONLY_VALIDATED_FIXTURE', clock_uncertainty_ms=82)],
                markets=[dict(flags, input_kind='DEMO_OBSERVATION', account_mode='DEMO') for _ in range(2)],
                risk_evidence=[dict(flags, status='READ_ONLY_DEMO_RISK_EVIDENCE', notional_cap_usd='2000',
                                    account={'login': 'SYNTHETIC_PRIVATE_MARKER', 'balance': 'SYNTHETIC_PRIVATE_MARKER'},
                                    costs=dict(commission='UNKNOWN', slippage='UNKNOWN', swap_execution_cost='UNKNOWN'),
                                    scenarios=[dict(direction=d, volume_lots='0.01', notional_usd='4188.55',
                                    cap_status='BLOCKED', hypothetical=True, account_sizing_applied=False) for d in ('BUY', 'SELL')])],
                history={'private': 'SYNTHETIC_PRIVATE_MARKER'}, raw_attempts=['SYNTHETIC_PRIVATE_MARKER'],
                arbitrary='<img src=x onerror=alert(1)>')


def notional_facts_fixture():
    """Declared synthetic units, never a broker verification fixture."""
    return dict(schema='kilas-offline-notional-facts-v1', input_kind='SYNTHETIC_TEST_FACTS',
                units=dict(quote_currency='USD', price_unit='USD_PER_TROY_OUNCE',
                           contract_unit='TROY_OUNCES_PER_LOT', volume_step_origin='ZERO_MULTIPLES'),
                specs=dict(currency_profit='USD', trade_contract_size='100.0', volume_min='0.01',
                           volume_step='0.01', volume_max='50.0'), quote=dict(bid='4188.02', ask='4188.55'),
                notional_cap_usd='2000', scenarios=[dict(direction=d, volume_lots='0.01', notional_usd=n,
                cap_status='BLOCKED', hypothetical=True, account_sizing_applied=False)
                for d,n in [('BUY','4188.55000'),('SELL','4188.02000')]])


def diagnostic_with_notional_facts():
    r=diagnostic_fixture();f=notional_facts_fixture();e=r['risk_evidence'][0]
    e.update(notional_units=f['units'],specs=f['specs'],quote=f['quote'],scenarios=f['scenarios'])
    e['specs']['ignored_private']='SYNTHETIC_PRIVATE_MARKER'
    e['quote']['ignored_private']='SYNTHETIC_PRIVATE_MARKER'
    return r


def parse_in_node(data, name='parseReport'):
    source=data if isinstance(data,str) else json.dumps(data)
    script="""const fs=require('fs');const parser=require(process.argv[1])[process.argv[2]];
try {console.log(JSON.stringify(parser(fs.readFileSync(0,'utf8'))));}
catch (_) {console.log('REJECTED');}"""
    return subprocess.run(['node','-e',script,str(PARSER),name],input=source,text=True,
                          capture_output=True,check=True).stdout.strip()


class DiagnosticTests(unittest.TestCase):
    def parse(self, data):
        return parse_in_node(data)

    def test_allowlisted_projection_and_blocked_status(self):
        output = self.parse(diagnostic_fixture())
        self.assertNotIn('SYNTHETIC_PRIVATE_MARKER', output)
        self.assertNotIn('onerror', output)
        report = json.loads(output)
        self.assertEqual(set(report), {'timestamp', 'outcome', 'synthetic', 'observations', 'requests', 'replies', 'clocks', 'risks'})
        self.assertEqual(report['replies'], 8)
        self.assertEqual(report['clocks'][1]['uncertaintyMs'], 82)
        self.assertEqual([s['capStatus'] for s in report['risks'][0]['scenarios']], ['BLOCKED', 'BLOCKED'])

    def test_incompatible_or_executable_reports(self):
        for key, value in dict(input_kind='REAL', status='CONNECTED', runtime_eligible=True,
                               broker_execution_allowed=True, paper_execution=True, ai_analysis=True,
                               producer_acceptance='ACCEPTED', sdk_shutdown='RUNNING', history_complete=True,
                               finished_utc='2026-02-30T15:47:08Z', profit_after_costs='PROFITABLE').items():
            with self.subTest(key=key):
                report = diagnostic_fixture(); report[key] = value
                self.assertEqual(self.parse(report), 'REJECTED')

    def test_nested_flags_and_cap_cannot_grant_permission(self):
        for path, key, value in [('collection', 'runtime_eligible', True), ('clock', 'policy_replay_only', False),
                                  ('clock', 'ai_analysis', True), ('market', 'account_mode', 'REAL'),
                                  ('risk', 'notional_cap_usd', 5000), ('scenario', 'cap_status', 'WITHIN_CAP'),
                                  ('scenario', 'hypothetical', False), ('scenario', 'account_sizing_applied', True),
                                  ('scenario', 'volume_lots', '-1'), ('scenario', 'notional_usd', 'Infinity')]:
            with self.subTest(path=path, key=key):
                r=diagnostic_fixture()
                node={'collection':r['collection'], 'clock':r['clock_results'][1], 'market':r['markets'][0],
                      'risk':r['risk_evidence'][0], 'scenario':r['risk_evidence'][0]['scenarios'][0]}[path]
                node[key]=value
                self.assertEqual(self.parse(r), 'REJECTED')

    def test_malformed_duplicate_nonfinite_depth_and_size(self):
        valid=json.dumps(diagnostic_fixture())
        for text in ('', '{', 'null', '[]', valid+'x', valid[:-1]+',"status":"CONNECTED"}',
                     valid.replace('"ntp_datagrams_sent": 8', '"ntp_datagrams_sent": NaN'),
                     valid[:-1]+',"__proto__":{"polluted":true}}',
                     valid[:-1]+',"deep":'+ '['*34+'0'+']'*34+'}',
                     valid[:-1]+',"padding":"'+'x'*131072+'"}'):
            with self.subTest(prefix=text[:20]): self.assertEqual(self.parse(text), 'REJECTED')

    def test_bounded_counts_types_and_missing_fields(self):
        for mutate in (lambda r:r.update(markets=[]), lambda r:r.update(markets=r['markets']*3),
                       lambda r:r['collection'].update(request_count=True), lambda r:r['collection'].update(request_count=100), lambda r:r.update(ntp_datagrams_sent=7),
                       lambda r:r.update(clock_results=r['clock_results'][:1]),
                       lambda r:r['collection']['cycles'][0]['qualification'].update(reply_count=9),
                       lambda r:r['clock_results'][1].update(clock_uncertainty_ms='82'),
                       lambda r:r.pop('runtime_eligible')):
            r=diagnostic_fixture();mutate(r);self.assertEqual(self.parse(r),'REJECTED')

    def test_absent_risk_is_explicitly_not_execution_readiness(self):
        r=diagnostic_fixture();r['risk_evidence']=[]
        self.assertEqual(json.loads(self.parse(r))['risks'],[])

    def test_exact_cap_boundary_and_decimal_projection(self):
        for amount, status in [('1999.99999999', 'WITHIN_CAP'), ('2000.00000000', 'WITHIN_CAP'),
                               ('2000.00000001', 'BLOCKED'), ('4188.55000', 'BLOCKED')]:
            with self.subTest(amount=amount):
                r=diagnostic_fixture();r['risk_evidence'][0]['notional_cap_usd']='2000.00000000'
                for s in r['risk_evidence'][0]['scenarios']:
                    s.update(notional_usd=amount, cap_status=status, volume_lots='0.01000000')
                result=json.loads(self.parse(r))['risks'][0]
                self.assertEqual(result['cap'],'2000')
                self.assertEqual(result['scenarios'][0]['lots'],'0.01')
                self.assertEqual(result['scenarios'][0]['notional'],amount.rstrip('0').rstrip('.') if '.' in amount else amount)
                self.assertEqual(result['scenarios'][0]['capStatus'],status)
                for s in r['risk_evidence'][0]['scenarios']:
                    s['cap_status']='WITHIN_CAP' if status=='BLOCKED' else 'BLOCKED'
                self.assertEqual(self.parse(r),'REJECTED')

    def test_risk_facts_require_bounded_positive_decimal_strings(self):
        for key in ('notional_cap_usd','volume_lots','notional_usd'):
            for bad in (None, True, 2000, 2000.0000000000001, '', '0', '0.00000000', '-1',
                        '+1', '1e3', 'NaN', 'Infinity', '2000.000000001', '1000000000',
                        '1 USD', '<script>1</script>'):
                with self.subTest(key=key,bad=bad):
                    r=diagnostic_fixture()
                    target=r['risk_evidence'][0] if key=='notional_cap_usd' else r['risk_evidence'][0]['scenarios'][0]
                    target[key]=bad
                    self.assertEqual(self.parse(r),'REJECTED')
            r=diagnostic_fixture()
            target=r['risk_evidence'][0] if key=='notional_cap_usd' else r['risk_evidence'][0]['scenarios'][0]
            del target[key]
            self.assertEqual(self.parse(r),'REJECTED')

    def test_json_float_rounding_cannot_hide_cap_excess(self):
        r=diagnostic_fixture()
        for s in r['risk_evidence'][0]['scenarios']:
            s.update(notional_usd='2000.0000000000000001',cap_status='WITHIN_CAP')
        text=json.dumps(r).replace('"2000.0000000000000001"','2000.0000000000000001')
        self.assertEqual(self.parse(text),'REJECTED')

    def test_client_has_no_upload_or_persistence_surface(self):
        source=PARSER.read_text().split('// Recorded reports are local data,')[1]
        for forbidden in ('fetch(', 'XMLHttpRequest', 'localStorage', 'sessionStorage', 'indexedDB', 'innerHTML', 'console.', 'window.location', 'config.'):
            self.assertNotIn(forbidden, source)
        template=(PARSER.parents[1]/'templates/kilas_trading.html').read_text()
        self.assertNotIn('<form', template)
        self.assertNotIn('id="diagnostic-details"', template)
        self.assertNotIn('type="file"', template)
        self.assertNotIn('filename=\'kilas_trading.js\'', template)


class NotionalFactsTests(unittest.TestCase):
    def parse(self,data):
        return parse_in_node(data,'parseNotionalFacts')

    def test_correct_bid_ask_derivation_minimum_and_disabled_gates(self):
        for kind in ('SYNTHETIC_TEST_FACTS','HISTORICAL_DECLARED_FACTS'):
            r=notional_facts_fixture();r['input_kind']=kind
            out=json.loads(self.parse(r))
            self.assertEqual(out['outcome'],'ARITHMETIC_CONSISTENT_ONLY')
            self.assertEqual(out['source_verification'],'NOT_INDEPENDENTLY_VERIFIED')
            self.assertEqual([s['derived_notional_usd'] for s in out['scenarios']],['4188.55','4188.02'])
            self.assertEqual([s['cap_status'] for s in out['minimum_notional']],['BLOCKED','BLOCKED'])
            self.assertEqual(out['producer_acceptance'],'NOT_IMPLEMENTED')
            self.assertTrue(out['policy_replay_only'])
            for key in ('runtime_eligible','broker_execution_allowed','ai_analysis','paper_execution'):
                self.assertIs(out[key],False)

    def test_missing_unknown_and_ambiguous_units_rejected(self):
        for key in ('quote_currency','price_unit','contract_unit','volume_step_origin'):
            for value in (None,'','unknown','USD_PER_LOT','TROY_OUNCE','MINIMUM_ANCHORED','REAL',True):
                with self.subTest(key=key,value=value):
                    r=notional_facts_fixture();r['units'][key]=value
                    self.assertEqual(self.parse(r),'REJECTED')
            r=notional_facts_fixture();del r['units'][key]
            self.assertEqual(self.parse(r),'REJECTED')
        r=notional_facts_fixture();del r['units'];self.assertEqual(self.parse(r),'REJECTED')
        r=notional_facts_fixture();r['units']['verified']=True;self.assertEqual(self.parse(r),'REJECTED')

    def test_missing_malformed_or_long_numeric_facts_rejected(self):
        fields=[('specs',k) for k in ('trade_contract_size','volume_min','volume_step','volume_max')]+[('quote',k) for k in ('bid','ask')]
        for section,key in fields:
            for bad in (None,True,100,0.01,'','0','-0.01','1e2','NaN','Infinity','0.010000000',
                        '9999999999','9'*200,'0.'+'1'*200,'100 ounces','<b>100</b>'):
                with self.subTest(section=section,key=key,bad=bad):
                    r=notional_facts_fixture();r[section][key]=bad
                    self.assertEqual(self.parse(r),'REJECTED')
            r=notional_facts_fixture();del r[section][key]
            self.assertEqual(self.parse(r),'REJECTED')

    def test_invalid_range_currency_quote_and_lot_grid_rejected(self):
        for section,key,value in [('specs','currency_profit','EUR'),('specs','volume_min','51'),
                                  ('specs','volume_step','0.03'),('specs','volume_max','50.005'),
                                  ('quote','bid','4200')]:
            r=notional_facts_fixture();r[section][key]=value
            self.assertEqual(self.parse(r),'REJECTED')
        for volume in ('0.001','0.015','50.01','0.01000001'):
            r=notional_facts_fixture();r['scenarios'][0]['volume_lots']=volume
            self.assertEqual(self.parse(r),'REJECTED')
        r=notional_facts_fixture();r['specs'].update(volume_min='0.03',volume_step='0.02')
        self.assertEqual(self.parse(r),'REJECTED')

    def test_derived_reported_notional_and_status_must_match_exactly(self):
        for key,value in [('notional_usd','4188.55000001'),('notional_usd','4188.02'),
                          ('notional_usd','4188.54'),('cap_status','WITHIN_CAP'),
                          ('direction','WAIT'),('hypothetical',False),('account_sizing_applied',True)]:
            r=notional_facts_fixture();r['scenarios'][0][key]=value
            self.assertEqual(self.parse(r),'REJECTED')
        for key in ('direction','volume_lots','notional_usd','cap_status','hypothetical','account_sizing_applied'):
            r=notional_facts_fixture();del r['scenarios'][0][key];self.assertEqual(self.parse(r),'REJECTED')
        r=notional_facts_fixture();r['scenarios'][1]=r['scenarios'][0].copy()
        self.assertEqual(self.parse(r),'REJECTED')

    def test_product_precision_and_size_never_round_or_overflow(self):
        r=notional_facts_fixture();r['specs'].update(volume_min='0.00000001',volume_step='0.00000001',
                                                  trade_contract_size='1.00000001')
        r['quote'].update(bid='1.00000001',ask='1.00000001')
        for s in r['scenarios']:s.update(volume_lots='0.00000001',notional_usd='0.00000001',cap_status='WITHIN_CAP')
        self.assertEqual(self.parse(r),'REJECTED')
        r=notional_facts_fixture();r['specs'].update(trade_contract_size='999999999',volume_min='1',volume_step='1')
        r['quote'].update(bid='999999999',ask='999999999')
        for s in r['scenarios']:s.update(volume_lots='1',notional_usd='999999999')
        self.assertEqual(self.parse(r),'REJECTED')

    def test_exact_cap_and_lot_step_arithmetic_against_decimal_oracle(self):
        from decimal import Decimal,localcontext
        for price in ('1999.99999999','2000','2000.00000001','4188.55'):
            for volume in ('0.01','0.02','0.03'):
                with self.subTest(price=price,volume=volume),localcontext() as context:
                    context.prec=60
                    r=notional_facts_fixture();r['quote'].update(bid=price,ask=price)
                    amount=Decimal(volume)*Decimal(r['specs']['trade_contract_size'])*Decimal(price)
                    status='BLOCKED' if amount>Decimal('2000') else 'WITHIN_CAP'
                    for s in r['scenarios']:s.update(volume_lots=volume,notional_usd=format(amount.normalize(),'f'),cap_status=status)
                    out=json.loads(self.parse(r))
                    self.assertEqual(Decimal(out['scenarios'][0]['derived_notional_usd']),amount)
                    self.assertEqual(out['scenarios'][0]['cap_status'],status)
                    self.assertIs(out['broker_execution_allowed'],False)

    def test_strict_root_duplicate_keys_and_private_data_rejected(self):
        for key,value in [('account',{'balance':'PRIVATE_MARKER'}),('runtime_eligible',True),
                          ('producer_acceptance','ACCEPTED'),('credentials','PRIVATE_MARKER')]:
            r=notional_facts_fixture();r[key]=value;self.assertEqual(self.parse(r),'REJECTED')
        r=notional_facts_fixture();r['specs']['account']='PRIVATE_MARKER';self.assertEqual(self.parse(r),'REJECTED')
        raw=json.dumps(notional_facts_fixture())
        self.assertEqual(self.parse(raw[:-1]+',"notional_cap_usd":"5000"}'),'REJECTED')
        self.assertEqual(self.parse(raw.replace('"volume_min": "0.01"','"volume_min": "0.01", "volume_min": "0.02"')),'REJECTED')

    def test_legacy_report_view_remains_unverified_and_not_evaluated(self):
        r=diagnostic_fixture()
        # Existing diagnostic quote/spec names do not declare economic units.
        f=notional_facts_fixture();r['risk_evidence'][0].update(specs=f['specs'],quote=f['quote'])
        out=json.loads(parse_in_node(r))
        c=out['risks'][0]['consistency']
        self.assertEqual(c['outcome'],'NOT_EVALUATED_MISSING_UNITS')
        self.assertIs(c['runtime_eligible'],False)
        self.assertEqual([s['capStatus'] for s in out['risks'][0]['scenarios']],['BLOCKED','BLOCKED'])

    def test_optional_report_metadata_checked_without_private_projection(self):
        r=diagnostic_with_notional_facts();raw=parse_in_node(r)
        self.assertNotIn('SYNTHETIC_PRIVATE_MARKER',raw)
        c=json.loads(raw)['risks'][0]['consistency']
        self.assertEqual(c['outcome'],'ARITHMETIC_CONSISTENT_ONLY')
        self.assertIs(c['broker_execution_allowed'],False)
        r['risk_evidence'][0]['scenarios'][0]['notional_usd']='4000'
        self.assertEqual(parse_in_node(r),'REJECTED')
        for bad in (None,{},dict(notional_facts_fixture()['units'],contract_unit='UNKNOWN')):
            r=diagnostic_with_notional_facts();r['risk_evidence'][0]['notional_units']=bad
            self.assertEqual(parse_in_node(r),'REJECTED')


if __name__ == '__main__': unittest.main()
