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


class DiagnosticTests(unittest.TestCase):
    def parse(self, data):
        source = data if isinstance(data, str) else json.dumps(data)
        script = '''const fs=require('fs');const {parseReport}=require(process.argv[1]);
try {console.log(JSON.stringify(parseReport(fs.readFileSync(0,'utf8'))));}
catch (_) {console.log('REJECTED');}'''
        return subprocess.run(['node', '-e', script, str(PARSER)], input=source, text=True, capture_output=True, check=True).stdout.strip()

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

    def test_client_has_no_upload_or_persistence_surface(self):
        source=PARSER.read_text().split('// Recorded reports are local data,')[1]
        for forbidden in ('fetch(', 'XMLHttpRequest', 'localStorage', 'sessionStorage', 'indexedDB', 'innerHTML', 'console.', 'window.location', 'config.'):
            self.assertNotIn(forbidden, source)
        template=(PARSER.parents[1]/'templates/kilas_trading.html').read_text().split('id="diagnostic-details"')[1].split('id="observation-details"')[0]
        self.assertNotIn('<form', template)
        self.assertNotIn('name=', template)


if __name__ == '__main__': unittest.main()
