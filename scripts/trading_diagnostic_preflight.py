#!/usr/bin/env python3
"""Local report preflight. No broker, transport, inference or runtime activation.

Reads raw report bytes in memory only. Reuses the browser's bounded diagnostic
parser, existing market projection and exact pinned offline clock/source policy.
Emits fixed messages plus allowlisted facts; never writes the source report.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'client-hub'))
from kilas_trading.producer import project_collector_market

MAX_BYTES = 131072
PARSER = ROOT / 'client-hub/static/kilas_trading.js'
PINS = {
    'validate_trace.py': '6359d012d244c1098b9a58608228d1ee8c817eb49facc91b5115d8ac64992698',
    'clock_batch_offline.py': '044699f31425412b3c6ee94432d58c398fc6ec9050047178ec9ed8a31f3b049b',
    'source_batch_offline.py': '68b4e85f971bb0169ad888b1058e8f1709c1ce39e3efe0e4ff80c29f542535c4',
}
SPEC_NUMBERS = ('point', 'trade_tick_size', 'trade_tick_value', 'trade_contract_size',
                'volume_min', 'volume_step', 'volume_max')
RISK_SPEC = ('trade_contract_size', 'volume_min', 'volume_step', 'volume_max')


def state(status, action, **facts):
    return dict(status=status, action=action, **facts)


def base_result():
    return {
        'outcome': 'INVALID_REPORT', 'capture_timestamp': None,
        'diagnostic_outcome': None, 'sdk_shutdown': None,
        'schema': state('NOT_EVALUATED', 'Gunakan laporan diagnosis lengkap yang kompatibel.'),
        'integrity': state('NOT_PROVIDED', 'Bandingkan dengan SHA256 capture; kecocokan bukan autentikasi sumber.'),
        'policy_integrity': state('NOT_EVALUATED', 'Sediakan tiga source policy dengan pin yang tepat.'),
        'demo_identity_binding': state('NOT_EVALUATED', 'Periksa konsistensi klaim sesi DEMO; tenant belum terverifikasi.'),
        'clock_replay': state('NOT_EVALUATED', 'Replay batch dengan policy asli; jangan membuat lease runtime.'),
        'contract_specs': state('NOT_EVALUATED', 'Cocokkan specs dan grid; unit broker perlu bukti independen.'),
        'minimum_lot_notional': state('NOT_EVALUATED', 'Periksa formula laporan terhadap cap USD2000 yang tetap.'),
        'runtime': state('HISTORICAL_UNVERIFIED_RUNTIME_BLOCKED', 'Jangan aktifkan AI, paper atau order dari laporan replay.',
                         producer_acceptance='NOT_IMPLEMENTED', source_freshness='NOT_GRANTED',
                         connected=False, runtime_eligible=False, broker_execution_allowed=False,
                         ai_analysis=False, paper_execution=False, policy_replay_only=True),
    }


def browser_projection(data):
    script = """const fs=require('fs'),p=require(process.argv[1]);
try {process.stdout.write(JSON.stringify(p.parseReport(fs.readFileSync(0,'utf8'))));}
catch (_) {process.exitCode=2;}"""
    run = subprocess.run(['node', '-e', script, str(PARSER)], input=data,
                         capture_output=True, timeout=10)
    if run.returncode or len(run.stdout) > MAX_BYTES:
        raise ValueError()
    return json.loads(run.stdout)


@contextmanager
def pinned_policy(directory):
    # Copy only hash-matched reviewed code into a private directory. Imports
    # cannot race against changes to the caller's source files after checking.
    files = {}
    for name, digest in PINS.items():
        with (Path(directory) / name).open('rb') as stream:
            data = stream.read(65537)
        if len(data) > 65536 or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError()
        files[name] = data
    names = ('clock_batch_offline', 'source_batch_offline', '_kilas_pinned_clock')
    old = {name: sys.modules.get(name) for name in names}
    with tempfile.TemporaryDirectory(prefix='kilas-offline-policy-') as tmp:
        for name, data in files.items():
            (Path(tmp) / name).write_bytes(data)
        try:
            modules = []
            for name in names[:2]:
                spec = importlib.util.spec_from_file_location(name, Path(tmp) / (name + '.py'))
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)
                modules.append(module)
            yield modules
        finally:
            for name, previous in old.items():
                if previous is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = previous


def number(value):
    # Reviewed collector numeric shape; exact Decimal arithmetic, no float
    # conversion or claim of economic units. Report parser validates notionals.
    if type(value) is not str or len(value) > 24:
        raise ValueError()
    result = Decimal(value)
    if not result.is_finite() or not 0 < result <= 100000000:
        raise ValueError()
    return result


def binding(report):
    markets = report['markets']; cycles = report['collection']['cycles']
    if len(markets) != 2 or len(cycles) != 2:
        raise ValueError()
    session = cycles[0]['batch']['session_id']
    if type(session) is not str or not re.fullmatch(r'[A-Za-z0-9]{16,64}', session):
        raise ValueError()
    for market, cycle in zip(markets, cycles):
        project_collector_market(market)
        if market['session_id'] != session or cycle['batch']['session_id'] != session or market['server'] != 'XMGlobal-MT5 10':
            raise ValueError()
        sample = market['sample']
        for key in ('acquired_start_utc', 'acquired_end_utc', 'acquired_start_mono_ns', 'acquired_end_mono_ns'):
            if sample[key] != cycle['batch'][key]:
                raise ValueError()
        calls = market['calls']
        if type(calls) is not dict or set(calls) != {'tick', 'candles', 'specs'}:
            raise ValueError()
        previous = sample['acquired_start_mono_ns']
        for name in ('tick', 'candles', 'specs'):
            call = calls[name]
            start, end = call['started_mono_ns'], call['ended_mono_ns']
            if (call['session_id'] != session or call['symbol'] != 'GOLD'
                    or type(start) is not int or type(end) is not int
                    or not previous <= start < end <= sample['acquired_end_mono_ns']):
                raise ValueError()
            previous = end
    for risk in report['risk_evidence']:
        if (risk['session']['status'] != 'READ_ONLY_DEMO_SESSION'
                or risk['session']['session_id'] != session):
            raise ValueError()


def replay(report, clock, source_module):
    # Candidate profile comes from the recorded normalized result, never a
    # guessed +3h rule. approved=True is confined to this OFFLINE fixture replay.
    tick = report['clock_results'][-1]['tick']
    policy = clock.policy
    profile = policy.BrokerTimeProfile(
        'offline-recorded-candidate', 'XMGlobal-MT5 10', policy.APIS,
        (policy.OffsetWindow(tick['validity_start_utc'], tick['validity_end_utc'], tick['applied_offset_seconds']),),
        'UNTRUSTED_RECORDED_PROFILE', 'OFFLINE_REPLAY_ONLY', True,
    )
    source = source_module.BatchFixtureSource(profile=profile, server=profile.server)
    source.connect(); replies = 0; statuses = []; uncertainties = []
    for market, cycle, claimed_clock in zip(report['markets'], report['collection']['cycles'], report['clock_results']):
        calculated = clock.qualify_batch(cycle['batch'])
        claimed = cycle['qualification']
        if any(claimed.get(key) != value for key, value in calculated.items()):
            raise ValueError()
        sample = dict(market['sample']); sample['kind'] = 'TEST_FIXTURE'
        result = source.observe_batch(sample, [bar['time'] for bar in market['candles']], cycle['batch'])
        if result['status'] != claimed_clock['status'] or result['status'] == 'UNAVAILABLE':
            raise ValueError()
        # Match reviewed clock outputs, not just the favorable status label.
        for key in ('clock_offset_seconds', 'clock_uncertainty_ms', 'tick', 'closed_candles'):
            if key in result and key in claimed_clock and result[key] != claimed_clock[key]:
                # Provenance refs differ because replay config is explicitly
                # synthetic; compare normalized tick's numerical/time facts.
                if key != 'tick' or any(result[key][k] != claimed_clock[key].get(k) for k in
                                        ('raw_time', 'raw_time_msc', 'normalized_time_utc', 'applied_offset_seconds')):
                    raise ValueError()
        replies += calculated['reply_count']; statuses.append(result['status'])
        uncertainties.append(calculated['uncertainty_seconds'])
    if statuses != ['WAIT', 'READ_ONLY_VALIDATED_FIXTURE']:
        raise ValueError()
    return state('OFFLINE_REPLAY_CONSISTENT_ONLY', 'Clock replay konsisten; profil broker dan lease runtime belum terverifikasi.',
                 observations=2, replies=replies, uncertainty_seconds=uncertainties,
                 assurance='UNAUTHENTICATED_OPERATIONAL_PAPER_ONLY', live_lease_granted=False)


def spec_consistency(report):
    markets = report['markets']; specs = []
    for market in markets:
        s = market['specs']
        n = {key: number(s[key]) for key in SPEC_NUMBERS}
        if (s['currency_profit'] != 'USD' or s['currency_margin'] != 'USD'
                or n['volume_min'] > n['volume_max']
                or any(n[k] % n['volume_step'] for k in ('volume_min', 'volume_max'))
                or any(number(market['tick'][k]) % n['trade_tick_size'] for k in ('bid', 'ask'))):
            raise ValueError()
        specs.append(n)
    if specs[0] != specs[1]:
        raise ValueError()
    s = specs[-1]
    return s, state('NUMERIC_SPECS_CONSISTENT_ONLY', 'Unit harga/kontrak dan mapping perlu bukti broker independen.',
                    minimum_lots=format(s['volume_min'], 'f'), step_lots=format(s['volume_step'], 'f'),
                    maximum_lots=format(s['volume_max'], 'f'), contract_size=format(s['trade_contract_size'], 'f'),
                    economic_units='NOT_INDEPENDENTLY_VERIFIED')


def minimum_risk(report, s):
    quote = report['markets'][-1]['tick']; outputs = []
    for risk in report['risk_evidence']:
        if any(number(risk['specs'][k]) != s[k] for k in RISK_SPEC):
            raise ValueError()
        if risk['specs']['currency_profit'] != 'USD' or risk['specs']['currency_margin'] != 'USD':
            raise ValueError()
        if (risk['quote']['raw_time'] != quote['time'] or risk['quote']['raw_time_msc'] != quote['time_msc']
                or any(number(risk['quote'][k]) != number(quote[k]) for k in ('bid', 'ask'))):
            raise ValueError()
        for scenario in risk['scenarios']:
            lots = number(scenario['volume_lots'])
            if lots != s['volume_min']:
                raise ValueError()
            with localcontext() as ctx:
                ctx.prec = 80
                notional = lots * s['trade_contract_size'] * number(quote['ask' if scenario['direction'] == 'BUY' else 'bid'])
            if notional != number(scenario['notional_usd']):
                raise ValueError()
            outputs.append({'direction': scenario['direction'], 'minimum_lots': format(lots, 'f'),
                            'reported_formula_notional': format(notional, 'f'),
                            'cap_status': 'BLOCKED' if notional > 2000 else 'WITHIN_CAP_ARITHMETIC_ONLY'})
    return state('BLOCKED_MINIMUM_LOT_CAP' if any(x['cap_status'] == 'BLOCKED' for x in outputs) else
                 'WITHIN_CAP_ARITHMETIC_ONLY' if outputs else 'NOT_REPORTED',
                 'Cap USD2000 tetap; formula laporan bukan bukti unit broker atau izin trading.',
                 cap_usd='2000', formula_basis='REPORTED_CONTRACT_SIZE_TIMES_LOTS_TIMES_QUOTE', scenarios=outputs)


def preflight(data, policy_dir, expected_sha256=None, now=None):
    out = base_result()
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        out['schema'] = state('REJECTED_SIZE', 'File harus UTF-8 JSON 1–131072 byte.')
        return out
    if expected_sha256 is not None:
        if not isinstance(expected_sha256, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256):
            out['integrity'] = state('INVALID_DIGEST', 'Gunakan tepat64 digit hex SHA256.')
            return out
        if hashlib.sha256(data).hexdigest() != expected_sha256.lower():
            out['integrity'] = state('DIGEST_MISMATCH', 'File berbeda dari digest yang diberikan; hentikan pemeriksaan.')
            return out
        out['integrity'] = state('SUPPLIED_DIGEST_MATCH', 'Integritas bytes cocok; asal/sesi broker belum diautentikasi.')
    try:
        projection = browser_projection(data)
        report = json.loads(data.decode('utf-8'))
    except (ValueError, UnicodeError, subprocess.SubprocessError):
        out['schema'] = state('REJECTED_SCHEMA', 'Laporan tidak kompatibel, malformed atau mengklaim eksekusi.')
        return out
    except OSError:
        out['schema'] = state('PARSER_UNAVAILABLE', 'Sediakan Node untuk validator diagnosis yang sudah ada.')
        out['outcome'] = 'PREFLIGHT_UNAVAILABLE'
        return out
    out['schema'] = state('COMPATIBLE_DIAGNOSTIC', 'Schema lolos validator diagnosis; bukan autentikasi laporan.')
    out['capture_timestamp'] = report['finished_utc']
    out['diagnostic_outcome'] = projection['outcome']
    out['sdk_shutdown'] = 'COMPLETED'
    age = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(report['finished_utc'].replace('Z', '+00:00'))).total_seconds()
    out['runtime']['capture_recency'] = 'STALE_HISTORICAL' if age > 120 else 'FUTURE_CAPTURE_UNVERIFIED' if age < 0 else 'RECENT_CAPTURE_UNVERIFIED'
    try:
        binding(report)
        out['demo_identity_binding'] = state('RECORDED_DEMO_SESSION_CONSISTENT_ONLY', 'Klaim sesi/call konsisten; sumber dan tenant perlu verifikasi independen.',
                                            provenance='REPORT_CLAIMS_ONLY_NOT_SDK_AUTHENTICATION',
                                            static_ui_evidence_grants_sdk_binding=False)
    except (ValueError, TypeError, KeyError, ArithmeticError):
        out['demo_identity_binding'] = state('REJECTED_BINDING', 'Sesi DEMO, call marks atau sample/batch berbeda; capture ulang tanpa repin.')
        return out
    try:
        with pinned_policy(policy_dir) as (clock, source):
            out['policy_integrity'] = state('PINNED_POLICY_MATCH', 'Tiga source policy cocok dengan pin; hanya replay offline.')
            try:
                out['clock_replay'] = replay(report, clock, source)
            except (ValueError, TypeError, KeyError, ArithmeticError):
                out['clock_replay'] = state('REJECTED_CLOCK_REPLAY', 'Packet, lease, profile candidate, urutan atau hasil replay tidak konsisten.')
                return out
    except (OSError, ValueError, ImportError):
        out['policy_integrity'] = state('POLICY_UNAVAILABLE_OR_PIN_MISMATCH', 'Sediakan source asli dengan pin yang tepat; jangan ganti policy.')
        out['outcome'] = 'PREFLIGHT_UNAVAILABLE'
        return out
    try:
        specs, out['contract_specs'] = spec_consistency(report)
    except (ValueError, TypeError, KeyError, ArithmeticError):
        out['contract_specs'] = state('REJECTED_MARKET_SPECS', 'Specs market atau grid antar-observasi berbeda; tinjau capture.')
        return out
    try:
        out['minimum_lot_notional'] = minimum_risk(report, specs)
    except (ValueError, TypeError, KeyError, ArithmeticError):
        out['minimum_lot_notional'] = state('REJECTED_RISK_BINDING_OR_FORMULA', 'Specs/quote risk, minimum lot atau formula laporan berbeda; tinjau capture.')
        return out
    out['outcome'] = 'OFFLINE_CHECKS_PASSED_RUNTIME_BLOCKED'
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--policy-dir', required=True, type=Path)
    digest = parser.add_mutually_exclusive_group()
    digest.add_argument('--sha256')
    digest.add_argument('--sha256-file', type=Path)
    args = parser.parse_args(argv)
    try:
        with args.report.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        expected = args.sha256
        if args.sha256_file:
            with args.sha256_file.open('rb') as stream:
                expected = stream.read(256).decode('ascii').strip()
        out = preflight(data, args.policy_dir, expected)
    except (OSError, UnicodeError):
        out = base_result(); out['outcome'] = 'PREFLIGHT_UNAVAILABLE'
        out['schema'] = state('LOCAL_INPUT_UNREADABLE', 'Gunakan report/digest lokal yang dapat dibaca; tidak ada URL fetch.')
    print(json.dumps(out, indent=2, allow_nan=False))
    return 0 if out['outcome'] == 'OFFLINE_CHECKS_PASSED_RUNTIME_BLOCKED' else 3 if out['outcome'] == 'PREFLIGHT_UNAVAILABLE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
