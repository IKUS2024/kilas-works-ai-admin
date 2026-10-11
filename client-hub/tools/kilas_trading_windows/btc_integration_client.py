"""BTC v2 worker integration. No configured endpoint, credentials or activation.

Uses the actual control/evidence/analysis protocols. Providers are explicit local
integration dependencies, not grants; only a validated server result can confer
bounded eligibility, and the existing DEMO controller/adapter retain final gates.
"""
import hashlib
import json
import sqlite3
import uuid
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, localcontext, Inexact
from threading import Event, Lock, Thread, current_thread
from time import perf_counter

from ai_market_news_contract import utc
from btc_integration_protocol import (EVIDENCE_PATH, ANALYSIS_PATH, canonical_json,
    contract_hash, validate_evidence_request, parse_evidence_response,
    validate_analysis_request, parse_analysis_response)
from demo_auto_controller import Blocked, Signal
from demo_integration_instruments import wire_profile


def require(value, code='BTC_INTEGRATION_BLOCKED'):
    if not value:
        raise Blocked(code)


class DecisionJournal:
    """Durable one-time consumption before any local entry attempt; no secrets."""
    def __init__(self, filename):
        self.filename = str(filename)
        db = self.connect()
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS btc_decisions '
                           '(session TEXT,decision TEXT,request_hash TEXT,PRIMARY KEY(session,decision))')
                db.execute('CREATE TABLE IF NOT EXISTS btc_operations '
                           '(session TEXT,operation TEXT,request_hash TEXT,PRIMARY KEY(session,operation))')
        finally:
            db.close()

    def connect(self):
        db = sqlite3.connect(self.filename, timeout=2)
        db.execute('PRAGMA synchronous=FULL')
        return db

    def consume(self, session, decision, request):
        digest = hashlib.sha256(canonical_json(request)).hexdigest()
        db = self.connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                require(db.execute('SELECT 1 FROM btc_decisions WHERE session=? AND decision=?',
                                   (session, decision)).fetchone() is None, 'DECISION_ALREADY_CONSUMED')
                db.execute('INSERT INTO btc_decisions VALUES(?,?,?)', (session, decision, digest))
        finally:
            db.close()

    def bind_operation(self, request):
        """Preserve exact retry identity without inventing a local budget grant."""
        digest = hashlib.sha256(canonical_json(request)).hexdigest()
        db = self.connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                prior = db.execute('SELECT request_hash FROM btc_operations WHERE session=? AND operation=?',
                                   (request['session_id'], request['operation_key'])).fetchone()
                require(prior is None or prior[0] == digest, 'OPERATION_INTENT_CHANGED')
                db.execute('INSERT OR IGNORE INTO btc_operations VALUES(?,?,?)',
                           (request['session_id'], request['operation_key'], digest))
        finally:
            db.close()


class BTCIntegrationClient:
    def __init__(self, control, transport, collector, decisions, *,
                 readiness_provider=None, activation_enabled=False, clock=perf_counter,instrument='BTC'):
        self.wire=wire_profile(instrument)
        require(getattr(control,'instrument','BTC')==instrument,'CONTROL_INSTRUMENT_MISMATCH')
        require(instrument=='BTC' or activation_enabled is False,'GOLD_RUNTIME_UNREVIEWED')
        self.control, self.transport, self.collector = control, transport, collector
        self.controller = control.controller
        self.clock, self.decisions = clock, decisions
        self.server_clock = control.server_clock
        require(self.server_clock is not None, 'SERVER_CLOCK_REQUIRED')
        self.readiness_provider = readiness_provider
        self.activation_enabled = activation_enabled is True
        self.capture_lock, self.analysis_lock = Lock(), Lock()
        self.challenge = None
        self.challenge_expires = None
        self.nonce_received_at = None
        self.recovery_after = None
        self.sequence = 0
        self.latest = None
        self.grant = None
        self.pending_signal = None
        self.failure = None
        self.last_outcome = None
        self.previous_strategy = self.controller.strategy
        self.controller.strategy = self
        self.controller.bind_authority_guard(self.authority_valid)
        self.control.readiness = self.readiness
        binder = getattr(self.controller.broker, 'bind_market_guard', None)
        if callable(binder):
            binder(self.check_market_contract)
        risk_binder = getattr(self.controller.broker, 'bind_risk_guard', None)
        if callable(risk_binder):
            risk_binder(self.check_current_risk)
        self.controller.stop()

    def context(self):
        p, scope = self.control.projection, self.control.scope
        require(scope is not None and p is not None and not self.control.ended)
        require(p['enabled'] is True and p['instrument'] == self.wire.instrument
                and scope.instrument == self.wire.instrument)
        return (scope.session_id, p['revision'], p['command_id'], p['instrument'], p['lot'])

    def active(self):
        try:
            self.context()
            p = self.control.projection
            return (p['desired_state'] == p['effective_desired_state'] == 'ON'
                    and p['run_status'] == 'ACTIVE' and p['worker_fresh'] is True
                    and self.control.hard is not None and self.clock() < self.control.hard
                    and self.control.soft is not None and self.clock() < self.control.soft)
        except Exception:
            return False

    def readiness(self):
        try:
            ready = (self.failure is None and callable(self.readiness_provider)
                     and self.readiness_provider() is True
                     and self.controller.policy is not None)
        except Exception:
            ready = False
        return dict(ready=ready, entry_authorized=ready and self.authority_valid(),
                    wait_reason='NONE' if ready else 'RISK_BLOCKED')

    def revoke(self, code):
        self.grant = None
        self.pending_signal = None
        self.failure = code  # Only local fixed codes are supplied here.
        self.controller.stop()

    def authority_valid(self):
        if self.wire.instrument!='BTC': return False
        try:
            grant = self.grant
            return bool(self.activation_enabled and self.failure is None and grant is not None
                        and callable(self.readiness_provider) and self.readiness_provider() is True
                        and self.active() and self.context() == grant['context']
                        and self.control.last_ack_context == grant['context']
                        and self.server_clock.upper_now() < utc(grant['response']['authorization_expires_at'])
                        and self.latest is not None
                        and self.latest['context'] == grant['context']
                        and self.latest['response']['tick_liveness'] == 'VERIFIED'
                        and self.latest['risk']['strategy_verified'] is True
                        and self.latest['risk']['cooldown_clear'] is True
                        and self.latest['risk']['loss_streak_clear'] is True
                        and self.latest['risk']['position_open'] is False
                        and self.latest['risk']['daily_loss_remaining_cents'] > 0
                        and self.latest['risk']['policy_version'] == grant['policy_version']
                        and self.policy_fingerprint() == grant['policy_fingerprint']
                        and self.latest['response']['evidence']['spec_id'] == grant['request']['evidence']['spec_id']
                        and self.latest['response']['evidence']['news_id'] == grant['request']['evidence']['news_id']
                        and self.latest['candles_hash'] == grant['candles_hash'])
        except Exception:
            return False

    def policy_fingerprint(self):
        return hashlib.sha256(repr((self.controller.policy,
                       getattr(self.controller.broker, 'policy', None))).encode()).hexdigest()

    def check_current_risk(self, risk):
        if self.grant is None:
            return
        require(self.authority_valid(), 'ENTRY_AUTHORITY_UNAVAILABLE')
        require(risk.stop_loss_usd*100 <= self.latest['risk']['daily_loss_remaining_cents'],
                'CURRENT_LOSS_BUDGET_EXCEEDED')
        cost = self.grant['spec']['cost_bound_cents']
        policy = getattr(self.controller.broker, 'policy', None)
        require(cost is not None and policy is not None
                and policy.fee_reserve_usd*100 >= cost, 'COST_BOUND_UNCOVERED')

    def check_market_contract(self, info):
        grant = self.grant
        if grant is None:
            return
        from btc_evidence_capture import spec_from_info
        spec = spec_from_info(info, cost_bound_cents=grant['spec']['cost_bound_cents'],
                              verified_at=grant['spec']['verified_at'],instrument=self.wire.instrument)
        require(contract_hash(spec,instrument=self.wire.instrument) == grant['contract_hash'], 'BROKER_CONTRACT_CHANGED')

    def _request_context(self):
        session, revision, command, instrument, lot = self.context()
        return dict(schema_version=2, session_id=session, revision=revision,
                    command_id=command, instrument=instrument, lot=lot)

    def capture_once(self):
        """Bootstrap/recover nonce or collect one NEW capture after receipt."""
        if not self.capture_lock.acquire(False):
            return None
        posted = False
        try:
            context = self.context()
            if self.controller.lot != Decimal(context[4]):
                self.controller.stop()
                self.controller.set_lot(context[4])
                return None  # The next independent sync must acknowledge this lot.
            require(self.control.last_ack_context == context
                    and self.control.projection['worker_fresh'] is True, 'MATCHING_ACK_REQUIRED')
            self.server_clock.upper_now()  # Requires a recent fast authenticated sample.
            if self.challenge is not None and self.server_clock.upper_now() >= self.challenge_expires:
                self.challenge = None
                self.recovery_after = self.challenge_expires
                self.latest = None
            if self.challenge is None and self.recovery_after is not None:
                require(self.server_clock.lower_now() >= self.recovery_after, 'CAPTURE_RECOVERY_WAIT')
                reset = getattr(self.transport, 'reset_evidence_after_expiry', None)
                if callable(reset):
                    if self.wire.instrument=='BTC': reset()
                    else: reset(instrument=self.wire.instrument)
            bootstrap = self.challenge is None
            request = dict(self._request_context(), sequence=0 if bootstrap else self.sequence+1,
                           challenge=self.challenge, account_mode='DEMO', terminal_connected=True,
                           market=None, spec=None, risk=None)
            if not bootstrap:
                require(self.server_clock.upper_now() < self.challenge_expires, 'CAPTURE_NONCE_EXPIRED')
                require(self.clock() >= self.nonce_received_at, 'CAPTURE_CLOCK_INVALID')
                payload = self.collector.collect()
                require(type(payload) is dict and set(payload) == {'market', 'spec', 'risk'})
                request.update(payload)
                require(self.context() == context, 'INTENT_CHANGED')
            validate_evidence_request(request,instrument=self.wire.instrument)
            used = self.challenge
            self.challenge = None  # Ambiguous delivery never reuses captured data/nonce.
            sent = self.clock()
            posted = True
            raw = self.transport.post(self.wire.evidence_path, request)
            received = self.clock()
            response = parse_evidence_response(raw, request,instrument=self.wire.instrument)
            require(self.context() == context, 'INTENT_CHANGED')
            self.server_clock.observe(sent, received, response['received_at'])
            expiry = utc(response['challenge_expires_at'])
            require(self.server_clock.upper_now() < expiry and response['challenge'] != used)
            self.sequence = response['sequence']
            self.challenge, self.challenge_expires = response['challenge'], expiry
            self.nonce_received_at = received
            self.recovery_after = None
            if not bootstrap:
                self.latest = dict(context=context, response=deepcopy(response), spec=deepcopy(request['spec']),
                    risk=deepcopy(request['risk']), policy_fingerprint=self.policy_fingerprint(),
                    contract_hash=contract_hash(request['spec'],instrument=self.wire.instrument),
                    quote=deepcopy(request['market']['tick']),
                    candles_hash=hashlib.sha256(canonical_json(request['market']['candles'])).hexdigest())
            if self.failure == 'EVIDENCE_UNAVAILABLE':
                self.failure = None
            return response
        except Blocked as exc:
            if str(exc) == 'CAPTURE_RECOVERY_WAIT':
                self.controller.stop()
                return None
            self.revoke('EVIDENCE_UNAVAILABLE')
            if posted:
                self._ambiguous_capture()
            return None
        except Exception:
            self.revoke('EVIDENCE_UNAVAILABLE')
            if posted:
                self._ambiguous_capture()
            return None
        finally:
            self.capture_lock.release()

    def _ambiguous_capture(self):
        self.challenge = None
        self.latest = None
        try:
            # A lost normal response may already have rotated the nonce. Wait
            # through that possible next nonce; never replay the old capture.
            bound = self.server_clock.upper_now(require_fresh=False)+timedelta(seconds=5)
            if self.challenge_expires is not None:
                bound = max(bound, self.challenge_expires+timedelta(seconds=5))
            self.recovery_after = bound
        except Exception:
            self.control.stop('CLOCK_DISCONTINUITY')

    def analyze_once(self, operation_key=None):
        """Server inference request; caller must schedule sync/captures independently."""
        if not self.analysis_lock.acquire(False):
            return None
        try:
            if not self.active() or not self.readiness()['ready']:
                return None
            context = self.context()
            latest = deepcopy(self.latest)
            if latest is None or latest['context'] != context:
                return None
            evidence = latest['response']['evidence']
            if evidence['news_id'] is None or latest['response']['tick_liveness'] != 'VERIFIED':
                self.last_outcome = 'EVIDENCE_PENDING'
                return None
            gate=self.analysis_gate(latest)
            if gate!='READY':
                self.last_outcome=gate
                return None
            operation = operation_key or self.wire.instrument.lower()+'-'+uuid.uuid4().hex
            request = dict(self._request_context(), operation_key=operation, evidence=deepcopy(evidence))
            validate_analysis_request(request,instrument=self.wire.instrument)
            self.decisions.bind_operation(request)
            raw = self.transport.post(self.wire.analysis_path, request)
            response = parse_analysis_response(raw, request,instrument=self.wire.instrument)
            # Slow analysis timestamps never update the fast authenticated clock.
            require(self.active() and self.context() == context, 'INTENT_CHANGED')
            server_now = self.server_clock.upper_now()
            require(utc(response['checked_at']) <= server_now, 'ANALYSIS_CLOCK_INVALID')
            require(self.wire.instrument=='BTC' or response['execution_authorized'] is False,
                    'GOLD_RUNTIME_UNREVIEWED')
            if response['execution_authorized']:
                expires = utc(response['authorization_expires_at'])
                p = self.control.projection
                require(expires <= min(self.control.scope.expires_at,
                    utc(p['run_expires_at']), utc(p['worker_lease_expires_at']),
                    utc(self.latest['response']['challenge_expires_at'])), 'AUTHORIZATION_BOUND_INVALID')
            if not self.activation_enabled:
                self.last_outcome = 'LOCAL_ACTIVATION_DISABLED'
                return response
            if not response['execution_authorized']:
                self.grant = None
                self.pending_signal = None
                self.last_outcome = response['outcome']
                self.controller.stop()
                return response
            grant = dict(context=context, request=request, response=response, spec=latest['spec'],
                         policy_version=latest['risk']['policy_version'],
                         policy_fingerprint=latest['policy_fingerprint'],
                         contract_hash=latest['contract_hash'], candles_hash=latest['candles_hash'])
            self.grant = grant
            require(self.authority_valid(), 'ENTRY_AUTHORITY_UNAVAILABLE')
            decision = response['decision']
            self.pending_signal = Signal(response['decision_id'], decision['decision'],
                Decimal(decision['stop_cents'])/100, Decimal(decision['target_cents'])/100,
                symbol='BTCUSD')
            if self.controller.lot != Decimal(context[4]):
                self.controller.stop()
                self.controller.set_lot(context[4])
            if not self.controller.on:
                self.controller.start()
            require(self.controller.entry_allowed(), 'LOCAL_ENTRY_BLOCKED')
            self.controller.poll()  # Existing broker, exact SL/TP, exposure and risk gates.
            return response
        except Exception:
            self.revoke('ANALYSIS_UNAVAILABLE')
            return None
        finally:
            self.grant = None
            self.pending_signal = None
            self.controller.stop()
            self.analysis_lock.release()

    def analysis_gate(self, latest):
        """Local pre-request veto; never substitutes for server cost/news gates."""
        try:
            spec,risk=latest['spec'],latest['risk']
            if spec['cost_bound_cents'] is None:return 'COSTS_UNKNOWN'
            policy=getattr(self.controller.broker,'policy',None)
            if policy is None or policy.fee_reserve_usd is None:return 'COSTS_UNKNOWN'
            if policy.fee_reserve_usd*100<spec['cost_bound_cents']:return 'COST_BOUND_UNCOVERED'
            volume=Decimal(latest['context'][4])
            if not Decimal(spec['volume_min'])<=volume<=Decimal(spec['volume_max']) or volume%Decimal(spec['volume_step']):
                return 'VOLUME_BLOCKED'
            with localcontext() as context:
                context.prec=max(28,len(str(volume))+len(spec['contract_size'])+len(latest['quote']['ask'])+3)
                context.traps[Inexact]=True
                exposure=volume*Decimal(spec['contract_size'])*Decimal(latest['quote']['ask'])
            if exposure>min(Decimal('2000'),self.controller.policy.max_notional_usd):return 'NOTIONAL_CAP_BLOCKED'
            if risk['position_open']:return 'POSITION_OPEN'
            if not all(risk[k] is True for k in ('strategy_verified','cooldown_clear','loss_streak_clear')):
                return 'POLICY_BLOCKED'
            if risk['daily_loss_remaining_cents']<=0:return 'LOSS_CAP_BLOCKED'
            if self.wire.instrument=='GOLD' and latest['response']['risk_review']!='SERVER_REVIEWED':
                return 'GOLD_NEWS_UNREVIEWED'
            return 'READY'
        except Exception:return 'POLICY_BLOCKED'

    def decision(self, snapshot):
        require(self.authority_valid() and self.pending_signal is not None, 'ENTRY_AUTHORITY_UNAVAILABLE')
        signal = self.pending_signal
        self.decisions.consume(self.context()[0], signal.key, self.grant['request'])
        self.pending_signal = None
        return signal

    def protective_stop(self, snapshot, position):
        provider = getattr(self.previous_strategy, 'protective_stop', None)
        return provider(snapshot, position) if callable(provider) else None

    def status(self):
        return dict(activation_enabled=self.activation_enabled, execution_authorized=self.authority_valid(),
                    evidence_sequence=self.sequence, evidence_available=self.latest is not None,
                    failure=self.failure, last_outcome=self.last_outcome, credentials_provisioned_by_client=False,
                    runtime_model='gpt-6.1-sol', reasoning='medium', service_tier='default')


class BTCWorker:
    """Independent control heartbeat/sync, capture and analysis; opt-in start only."""
    def __init__(self, integration, snapshot_provider, *, capture_interval=1., analysis_interval=2.):
        from demo_worker_runtime import CoordinationWorker
        require(0.1 <= capture_interval <= 2 and analysis_interval >= 1)
        self.integration = integration
        self.coordination = CoordinationWorker(integration.control, snapshot_provider)
        self.capture_interval, self.analysis_interval = capture_interval, analysis_interval
        self.finished = Event()
        self.threads = []

    def start(self):
        require(not self.threads)
        self.coordination.start()
        self.threads = [Thread(target=self._captures, daemon=True, name='btc-captures'),
                        Thread(target=self._analysis, daemon=True, name='btc-analysis')]
        for thread in self.threads:
            thread.start()
        return self

    def _captures(self):
        while not self.finished.is_set() and not self.integration.control.ended:
            if self.integration.control.last_ack_context is not None:
                self.integration.capture_once()
            self.finished.wait(self.capture_interval)

    def _analysis(self):
        while not self.finished.is_set() and not self.integration.control.ended:
            if (self.integration.active() and self.integration.latest is not None
                    and self.integration.latest['response']['tick_liveness'] == 'VERIFIED'
                    and self.integration.latest['response']['evidence']['news_id'] is not None):
                self.integration.analyze_once()
            self.finished.wait(self.analysis_interval)

    def stop(self):
        self.integration.revoke('OFF_REQUESTED')
        self.finished.set()
        self.coordination.stop()
        for thread in self.threads:
            if thread is not current_thread():
                thread.join(.1)


def build_btc_worker(adapter, *, control_ledger, decision_ledger, scope=None,
                     risk_provider=None, readiness_provider=None,
                     cost_bound_cents=None, policy_version=None, endpoint=None,
                     credential_provider=None, endpoint_authorized=False,
                     activation_enabled=False,instrument='BTC'):
    """Assemble the real client path without connecting, starting or provisioning.

    The adapter must be supplied explicitly; this function never attaches MT5.
    Scope, reviewed risk/cost/policy facts, secure credential handoff and any
    future activation are caller responsibilities. All shipped defaults block.
    """
    from btc_evidence_capture import BTCMarketCapture
    from btc_server_clock import ServerClock
    from demo_auto_controller import Controller
    from demo_control_v2 import V2Client, V2Journal
    from demo_worker_runtime import BoundedControlHTTP
    from demo_instrument_profiles import mapping

    require(adapter.profile==mapping(instrument),'BROKER_INSTRUMENT_MISMATCH')
    require(instrument=='BTC' or adapter.execute is False and activation_enabled is False,
            'GOLD_RUNTIME_UNREVIEWED')

    transport = BoundedControlHTTP(endpoint, credential_provider,
                                    endpoint_authorized=endpoint_authorized)
    controller = Controller(adapter, policy=adapter.policy.controller if adapter.policy else None)
    control = V2Client(transport, V2Journal(control_ledger), controller, scope=scope,
                       server_clock=ServerClock(),instrument=instrument)
    collector = BTCMarketCapture(adapter, risk_provider, cost_bound_cents=cost_bound_cents,
                                 policy_version=policy_version,instrument=instrument)
    integration = BTCIntegrationClient(control, transport, collector, DecisionJournal(decision_ledger),
        readiness_provider=readiness_provider, activation_enabled=activation_enabled,instrument=instrument)
    return BTCWorker(integration, adapter.snapshot)


def build_gold_proposal_worker(adapter, **kwargs):
    """Gold evidence/proposals only; no attachment, startup or entry capability."""
    require('instrument' not in kwargs,'INSTRUMENT_OVERRIDE_REJECTED')
    return build_btc_worker(adapter,instrument='GOLD',**kwargs)
