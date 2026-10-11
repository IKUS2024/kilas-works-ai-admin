"""Offline checks of the real HTTPS transport; factories never open sockets."""
import json
import time
import unittest
from io import BytesIO
from threading import Event,Thread
from unittest.mock import patch

from demo_worker_runtime import (BoundedControlHTTP,TransportFailure,PATH,
                                 EVIDENCE_PATH,ANALYSIS_PATH)


SYNC={'schema_version':2,'sequence':0,'challenge':None,'ack':None}
BOOT={'schema_version':2,'session_id':'1'*32,'revision':1,'command_id':'2'*32,
      'instrument':'BTC','lot':'0.01','sequence':0,'challenge':None,
      'account_mode':'DEMO','terminal_connected':True,'market':None,'spec':None,'risk':None}
ANALYSIS={'schema_version':2,'operation_key':'offline-operation-123','session_id':'1'*32,
          'revision':1,'command_id':'2'*32,'instrument':'BTC','lot':'0.01',
          'evidence':{'market_id':'3'*32,'news_id':'4'*32,'spec_id':'5'*32}}


class HTTPFixture:
    """Synthetic replies and metadata only: never stores Authorization values."""
    def __init__(self):
        self.connections=[]; self.requests=[]; self.entered=Event()
        self.stalls={}; self.statuses={}; self.payloads={}; self.headers={}

    def factory(self,*args,**kwargs):
        connection=FixtureConnection(self)
        self.connections.append(connection)
        return connection


class FixtureConnection:
    def __init__(self,fixture):
        self.fixture=fixture; self.sock=self; self.timeout=0; self.closed=False
        self.path=None; self.release=Event()

    def settimeout(self,value): self.timeout=value
    def connect(self): pass

    def request(self,method,path,body,headers):
        if self.closed: raise RuntimeError('closed')
        self.path=path
        self.fixture.requests.append({'method':method,'path':path,'body':json.loads(body),
            'header_names':set(headers),'has_bearer':headers.get('Authorization','').startswith('Bearer ')})

    def getresponse(self):
        self.fixture.entered.set()
        if self.fixture.stalls.get(self.path): self.release.wait(3)
        if self.closed: raise RuntimeError('closed')
        payload=self.fixture.payloads.get(self.path,b'{"outcome":"SYNTHETIC_ONLY"}')
        return FixtureResponse(self.fixture.statuses.get(self.path,200),payload,
                               self.fixture.headers.get(self.path,{}))

    def close(self): self.closed=True; self.release.set()


class FixtureResponse:
    def __init__(self,status,payload,headers):
        self.status=status; self.stream=BytesIO(payload)
        self.headers={'Content-Type':'application/json',**headers}
    def getheader(self,name,default=None): return self.headers.get(name,default)
    def read(self,n): return self.stream.read(n)


class DiagnosticTransport(BoundedControlHTTP):
    inspect_sync_error_outcomes=True

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.safe_responses={}; self.diagnostic_calls=[]

    def _response_diagnostic(self,path,status,outcome=None):
        self.safe_responses[path]={'http_status':status,'outcome':outcome}
        self.diagnostic_calls.append((path,status,outcome))


class BTCTransportTests(unittest.TestCase):
    def setUp(self): self.fixture=HTTPFixture()

    def transport(self,**overrides):
        options=dict(endpoint='https://fixture.invalid',credential_provider=lambda:'a'*64,
            endpoint_authorized=True,connection_factory=self.fixture.factory,
            total_timeout=.5,analysis_timeout=.8)
        options.update(overrides)
        return BoundedControlHTTP(**options)

    def test_all_three_exact_paths_and_no_sensitive_header_retention(self):
        transport=self.transport()
        for path,body in ((PATH,SYNC),(EVIDENCE_PATH,BOOT),(ANALYSIS_PATH,ANALYSIS)):
            self.assertEqual(transport.post(path,body),b'{"outcome":"SYNTHETIC_ONLY"}')
            request=self.fixture.requests[-1]
            self.assertEqual((request['method'],request['path'],request['body']),('POST',path,body))
            self.assertTrue(request['has_bearer'])
            self.assertEqual(request['header_names'],{'Authorization','Content-Type','Accept','Accept-Encoding','Connection'})
        self.assertTrue(all(c.closed for c in self.fixture.connections))

    def test_default_authority_does_not_connect_any_lane(self):
        for path,body in ((PATH,SYNC),(EVIDENCE_PATH,BOOT),(ANALYSIS_PATH,ANALYSIS)):
            with self.assertRaisesRegex(TransportFailure,'TRANSPORT_NOT_AUTHORIZED'):
                self.transport(endpoint_authorized=False).post(path,body)
        self.assertEqual(self.fixture.connections,[])

    def test_btc_requires_exact_lowercase_hex_credential(self):
        for credential in ('fixture-token','A'*64,'a'*63,'a'*65,'a'*63+'\n'):
            for path,body in ((EVIDENCE_PATH,BOOT),(ANALYSIS_PATH,ANALYSIS)):
                with self.subTest(path=path,length=len(credential)):
                    with self.assertRaisesRegex(TransportFailure,'^CREDENTIAL_UNAVAILABLE$'):
                        self.transport(credential_provider=lambda:credential).post(path,body)
        self.assertEqual(self.fixture.connections,[])

    def test_native_sync_also_requires_exact_credential_before_connection(self):
        with patch('demo_worker_runtime.http.client.HTTPSConnection') as native:
            with self.assertRaisesRegex(TransportFailure,'^CREDENTIAL_UNAVAILABLE$'):
                self.transport(connection_factory=None,credential_provider=lambda:'fixture-token').post(PATH,SYNC)
            native.assert_not_called()

    def test_real_btc_request_validators_reject_wrong_context_shape(self):
        cases=[(EVIDENCE_PATH,dict(BOOT,account_balance='private')),
               (EVIDENCE_PATH,dict(BOOT,terminal_connected=1)),
               (EVIDENCE_PATH,dict(BOOT,instrument='GOLD')),
               (EVIDENCE_PATH,dict(BOOT,session_id='not-a-session')),
               (ANALYSIS_PATH,dict(ANALYSIS,model='gpt-6-astra')),
               (ANALYSIS_PATH,dict(ANALYSIS,revision=True)),
               (ANALYSIS_PATH,dict(ANALYSIS,operation_key='short')),
               (ANALYSIS_PATH,dict(ANALYSIS,lot='0.010'))]
        for path,body in cases:
            with self.subTest(path=path,keys=sorted(body)):
                with self.assertRaisesRegex(TransportFailure,'TRANSPORT_CONFIGURATION_INVALID'):
                    self.transport().post(path,body)
        self.assertEqual(self.fixture.connections,[])

    def test_unknown_path_never_connects(self):
        for path in (ANALYSIS_PATH+'?key=x',ANALYSIS_PATH+'/', '/btc-analysis'):
            with self.assertRaisesRegex(TransportFailure,'PATH_INVALID'):
                self.transport().post(path,ANALYSIS)
        self.assertEqual(self.fixture.connections,[])

    def test_analysis_inflight_does_not_block_fast_lanes(self):
        self.fixture.stalls[ANALYSIS_PATH]=True
        transport=self.transport(); results=[]
        def analyze():
            try: results.append(transport.post(ANALYSIS_PATH,ANALYSIS))
            except TransportFailure as exc: results.append(str(exc))
        thread=Thread(target=analyze,daemon=True); thread.start()
        try:
            self.assertTrue(self.fixture.entered.wait(.5))
            started=time.perf_counter()
            transport.post(PATH,SYNC); transport.post(EVIDENCE_PATH,BOOT)
            self.assertLess(time.perf_counter()-started,.5)
            with self.assertRaisesRegex(TransportFailure,'TRANSPORT_BUSY_OR_PATH_INVALID'):
                transport.post(ANALYSIS_PATH,ANALYSIS)
            self.assertEqual(len(self.fixture.requests),3)
        finally:
            for connection in self.fixture.connections: connection.release.set()
            thread.join(1)
        self.assertEqual(results,[b'{"outcome":"SYNTHETIC_ONLY"}'])

    def test_analysis_deadline_separate_and_uncertainty_isolated(self):
        self.fixture.stalls[ANALYSIS_PATH]=True
        transport=self.transport(total_timeout=.05,analysis_timeout=.16)
        started=time.perf_counter()
        with self.assertRaisesRegex(TransportFailure,'TRANSPORT_TIMEOUT'):
            transport.post(ANALYSIS_PATH,ANALYSIS)
        elapsed=time.perf_counter()-started
        self.assertGreaterEqual(elapsed,.13); self.assertLess(elapsed,.6)
        self.assertTrue(transport.path_unresolved(ANALYSIS_PATH)); self.assertFalse(transport.unresolved)
        transport.post(PATH,SYNC); transport.post(EVIDENCE_PATH,BOOT)
        with self.assertRaisesRegex(TransportFailure,'TRANSPORT_UNRESOLVED'):
            transport.post(ANALYSIS_PATH,ANALYSIS)
        self.assertEqual(sum(r['path']==ANALYSIS_PATH for r in self.fixture.requests),1)

    def test_explicit_expiry_recovery_resets_only_evidence_and_never_replays(self):
        self.fixture.stalls.update({EVIDENCE_PATH:True,ANALYSIS_PATH:True})
        transport=self.transport(total_timeout=.05,analysis_timeout=.05)
        for path,body in ((EVIDENCE_PATH,BOOT),(ANALYSIS_PATH,ANALYSIS)):
            with self.assertRaisesRegex(TransportFailure,'TRANSPORT_TIMEOUT'): transport.post(path,body)
        before=len(self.fixture.requests)
        # The protocol client, not transport, proves nonce expiry before this call.
        self.assertTrue(transport.reset_evidence_after_expiry())
        self.assertEqual(len(self.fixture.requests),before)
        self.assertTrue(transport.path_unresolved(ANALYSIS_PATH))
        self.fixture.stalls[EVIDENCE_PATH]=False
        transport.post(EVIDENCE_PATH,BOOT)
        self.assertEqual(len(self.fixture.requests),before+1)

    def test_abandoned_slow_provider_cannot_send_after_evidence_reset(self):
        release=Event(); entered=Event()
        def slow_provider(): entered.set(); release.wait(1); return 'a'*64
        transport=self.transport(total_timeout=.05,credential_provider=slow_provider)
        with self.assertRaisesRegex(TransportFailure,'TRANSPORT_TIMEOUT'): transport.post(EVIDENCE_PATH,BOOT)
        self.assertTrue(entered.is_set())
        transport.reset_evidence_after_expiry(); release.set()
        time.sleep(.04)
        self.assertEqual(self.fixture.connections,[])
        transport.provider=lambda:'a'*64
        transport.post(EVIDENCE_PATH,BOOT)
        self.assertEqual(len(self.fixture.requests),1)

    def test_non200_fixed_error_validated_redacted_and_not_retried(self):
        self.fixture.statuses[EVIDENCE_PATH]=409
        self.fixture.payloads[EVIDENCE_PATH]=b'{"outcome":"PRIVATE_FIXED_SENTINEL"}'
        transport=self.transport()
        with self.assertRaisesRegex(TransportFailure,'^HTTP_STATUS_REJECTED$'):
            transport.post(EVIDENCE_PATH,BOOT)
        with self.assertRaisesRegex(TransportFailure,'^TRANSPORT_UNRESOLVED$'):
            transport.post(EVIDENCE_PATH,BOOT)
        self.assertEqual(len(self.fixture.requests),1)
        self.assertFalse(transport.unresolved)

    def test_malformed_non200_body_cannot_escape_as_public_error_text(self):
        self.fixture.statuses[ANALYSIS_PATH]=503
        for raw in (b'{"outcome":"SECRET","detail":"private"}',b'{"outcome":"private secret"}',
                    b'{"outcome":"A","outcome":"B"}',b'{"outcome":null}',b'{"__proto__":{}}'):
            self.fixture.payloads[ANALYSIS_PATH]=raw
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(TransportFailure,'^HTTP_FORMAT_REJECTED$'):
                    self.transport().post(ANALYSIS_PATH,ANALYSIS)

    def test_bad_json_and_oversize_success_are_never_returned(self):
        for raw,reason in ((b'{"a":NaN}','HTTP_FORMAT_REJECTED'),
                           (b'{"constructor":1}','HTTP_FORMAT_REJECTED'),
                           (b'{"a":1,"a":2}','HTTP_FORMAT_REJECTED'),
                           (b'{"a":"'+b'x'*8200+b'"}','HTTP_SIZE_REJECTED')):
            self.fixture.payloads[EVIDENCE_PATH]=raw
            with self.assertRaisesRegex(TransportFailure,reason): self.transport().post(EVIDENCE_PATH,BOOT)

    def test_configured_timeout_bounds(self):
        for value in (None,True,0,.049,61,float('inf'),float('nan')):
            with self.assertRaisesRegex(TransportFailure,'TRANSPORT_CONFIGURATION_INVALID'):
                self.transport(analysis_timeout=value)


class TransportDiagnosticTests(unittest.TestCase):
    def setUp(self): self.fixture=HTTPFixture()

    def transport(self,kind=DiagnosticTransport):
        return kind('https://fixture.invalid',lambda:'a'*64,endpoint_authorized=True,
                    connection_factory=self.fixture.factory,total_timeout=.5)

    def test_safe_error_status_and_known_outcome_on_each_requested_status(self):
        for path,body in ((PATH,SYNC),(EVIDENCE_PATH,BOOT)):
            for status in (401,403,409,503):
                self.fixture.statuses[path]=status
                self.fixture.payloads[path]=b'{"outcome":"POLICY_BLOCKED"}'
                transport=self.transport()
                with self.subTest(path=path,status=status):
                    with self.assertRaisesRegex(TransportFailure,'^HTTP_STATUS_REJECTED$'):
                        transport.post(path,body)
                    self.assertEqual(transport.safe_responses[path],
                                     {'http_status':status,'outcome':'POLICY_BLOCKED'})
                    self.assertEqual(transport.diagnostic_calls,
                                     [(path,status,None),(path,status,'POLICY_BLOCKED')])

    def test_unknown_uppercase_and_undocumented_auth_codes_are_omitted(self):
        for code in ('SECRET_SENTINEL','UNAUTHORIZED','FORBIDDEN'):
            for path,body in ((PATH,SYNC),(EVIDENCE_PATH,BOOT)):
                self.fixture.statuses[path]=401
                self.fixture.payloads[path]=json.dumps({'outcome':code}).encode()
                transport=self.transport()
                with self.assertRaisesRegex(TransportFailure,'^HTTP_STATUS_REJECTED$'):
                    transport.post(path,body)
                self.assertEqual(transport.diagnostic_calls,[(path,401,None)])
                self.assertNotIn(code,repr(transport.safe_responses))

    def test_malformed_secret_bodies_keep_status_only(self):
        self.fixture.statuses[EVIDENCE_PATH]=403
        for raw in (b'private-secret-sentinel',b'{"outcome":"POLICY_BLOCKED","secret":"private"}',
                    b'{"outcome":"POLICY_BLOCKED","outcome":"SECRET"}',
                    b'{"outcome":"POLICY_BLOCKED","__proto__":{}}',
                    b'{"outcome":"private secret"}'):
            self.fixture.payloads[EVIDENCE_PATH]=raw
            transport=self.transport()
            with self.assertRaisesRegex(TransportFailure,'^HTTP_FORMAT_REJECTED$'):
                transport.post(EVIDENCE_PATH,BOOT)
            self.assertEqual(transport.diagnostic_calls,[(EVIDENCE_PATH,403,None)])
            self.assertEqual(transport.safe_responses[EVIDENCE_PATH],{'http_status':403,'outcome':None})

    def test_opted_in_sync_errors_keep_existing_byte_limit(self):
        self.fixture.statuses[PATH]=503
        self.fixture.payloads[PATH]=b'{"outcome":"'+b'X'*8200+b'"}'
        transport=self.transport()
        with self.assertRaisesRegex(TransportFailure,'^HTTP_SIZE_REJECTED$'):
            transport.post(PATH,SYNC)
        self.assertEqual(transport.diagnostic_calls,[(PATH,503,None)])

    def test_standard_sync_error_behavior_unchanged_without_opt_in(self):
        class StatusOnlyTransport(DiagnosticTransport): inspect_sync_error_outcomes=False
        self.fixture.statuses[PATH]=409
        self.fixture.payloads[PATH]=b'not-json-private-sentinel'
        self.fixture.headers[PATH]={'Content-Type':'text/plain'}
        transport=self.transport(StatusOnlyTransport)
        with self.assertRaisesRegex(TransportFailure,'^HTTP_STATUS_REJECTED$'):
            transport.post(PATH,SYNC)
        self.assertEqual(transport.diagnostic_calls,[(PATH,409,None)])

    def test_known_successes_and_blocked_results_are_metadata_only(self):
        for outcome in ('BOOTSTRAPPED','ACK_ACCEPTED','CAPTURE_CHALLENGE_ISSUED',
                        'EVIDENCE_ACCEPTED','PROPOSAL_READY','COSTS_UNKNOWN'):
            raw=json.dumps({'outcome':outcome}).encode()
            self.fixture.payloads[EVIDENCE_PATH]=raw
            transport=self.transport()
            self.assertEqual(transport.post(EVIDENCE_PATH,BOOT),raw)
            self.assertEqual(transport.safe_responses[EVIDENCE_PATH],{'http_status':200,'outcome':outcome})

    def test_invalid_http_status_never_reaches_diagnostic_sink(self):
        transport=self.transport()
        for status in (True,None,'200',99,600):
            transport._report_response_diagnostic(EVIDENCE_PATH,status,'EVIDENCE_ACCEPTED')
        self.assertEqual(transport.diagnostic_calls,[])

    def test_optional_hook_errors_cannot_replace_transport_result(self):
        class BrokenDiagnosticTransport(DiagnosticTransport):
            def _response_diagnostic(self,path,status,outcome=None):
                raise RuntimeError('private-hook-sentinel')
        self.fixture.payloads[EVIDENCE_PATH]=b'{"outcome":"EVIDENCE_ACCEPTED"}'
        transport=self.transport(BrokenDiagnosticTransport)
        self.assertEqual(transport.post(EVIDENCE_PATH,BOOT),self.fixture.payloads[EVIDENCE_PATH])
        self.fixture.statuses[EVIDENCE_PATH]=503
        self.fixture.payloads[EVIDENCE_PATH]=b'{"outcome":"COSTS_UNKNOWN"}'
        with self.assertRaisesRegex(TransportFailure,'^HTTP_STATUS_REJECTED$'):
            self.transport(BrokenDiagnosticTransport).post(EVIDENCE_PATH,BOOT)


if __name__=='__main__': unittest.main()
