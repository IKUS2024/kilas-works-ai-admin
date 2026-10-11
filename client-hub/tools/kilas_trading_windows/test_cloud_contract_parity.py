"""Offline comparisons to pinned db035b5 source; never import the cloud app."""
import ast
import copy
import hashlib
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import btc_integration_protocol as local
from demo_integration_instruments import PROFILES, BASE
from demo_worker_runtime import HTTP_PATHS

ROOT = Path(__file__).parent / 'cloud-contract-db035'


def selected(name, names, namespace=None):
    """Evaluate only reviewed definitions, excluding imports/app initialization."""
    tree = ast.parse((ROOT / 'kilas_trading' / name).read_text(encoding='utf-8'))
    nodes = []
    for node in tree.body:
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)] if isinstance(node, ast.Assign) else []
        if set(targets) & set(names) or isinstance(node, ast.FunctionDef) and node.name in names:
            nodes.append(node)
    scope = dict(namespace or {})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), name, 'exec'), scope)
    return scope


class Rejected(ValueError):
    pass


def require(ok, code='INVALID'):
    if not ok:
        raise Rejected(code)


def exact(value, fields):
    require(type(value) is dict and set(value) == set(fields))
    return value


BRIDGE = SimpleNamespace(require=require, exact=exact,
    secret=lambda value, size: require(type(value) is str and re.fullmatch('[0-9a-f]{'+str(size)+'}', value)),
    date=lambda value: datetime.fromisoformat(value.replace('Z', '+00:00')))


class CloudParityTests(unittest.TestCase):
    def setUp(self):
        self.config = selected('demo_instruments.py', ('INSTRUMENTS','NEWS_FIELDS','CALENDAR_FIELDS',
            'BLACKOUT_SECONDS','contract','validate_news','news_gate'), {'bridge':BRIDGE,'timedelta':timedelta})
        self.now = datetime(2026,10,12,12,tzinfo=timezone.utc)

    def news(self):
        stamp=lambda offset: (self.now+timedelta(seconds=offset)).isoformat()
        return dict(id='a'*32,provider='TRUSTED_GOLD_NEWS_V1',as_of=stamp(-1),valid_until=stamp(299),
            verified=True,event_risk='LOW',sentiment=0,coverage='GOLD_MACRO_CALENDAR',risk_review='SERVER_REVIEWED',
            articles=[dict(id='b'*32,published_at=stamp(-60),title='Synthetic macro fixture')],
            calendar=dict(provider='TRUSTED_GOLD_CALENDAR_V1',as_of=stamp(-1),valid_until=stamp(299),
                coverage_start_at=stamp(-1800),coverage_end_at=stamp(1800),verified=True,event_risk='LOW',events=[]))

    def test_pinned_sources_match_github_blobs(self):
        manifest=json.loads((ROOT/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['commit'],'db035b5da415bed61bed08e2b1cac50d8d31f73c')
        for item in manifest['files']:
            content=(ROOT/'kilas_trading'/item['name']).read_text(encoding='utf-8').encode()
            self.assertEqual(hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest(),item['sha'])

    def test_exact_symbols_providers_coverage_routes(self):
        for instrument, profile in PROFILES.items():
            remote=self.config['INSTRUMENTS'][instrument]
            self.assertEqual((profile.symbol,profile.provider,profile.coverage),
                (remote['symbol'],remote['provider'],remote['coverage']))
            self.assertEqual(profile.evidence_path,BASE+instrument.lower()+'-evidence')
            self.assertEqual(profile.analysis_path,BASE+instrument.lower()+'-analysis')
        tree=ast.parse((ROOT/'kilas_trading'/'control_routes.py').read_text(encoding='utf-8'))
        routes={BASE.removesuffix('control/')+dec.args[0].value.lstrip('/') for node in tree.body
            if isinstance(node,ast.FunctionDef) for dec in node.decorator_list
            if isinstance(dec,ast.Call) and isinstance(dec.func,ast.Attribute) and dec.func.attr=='post'}
        self.assertTrue(set(HTTP_PATHS)<=routes)

    def test_wire_fields_match_server(self):
        source=selected('btc_sources.py',('SPEC_FIELDS','INGEST_FIELDS','RISK_FIELDS'))
        analyst=selected('btc_analysis.py',('REQUEST_FIELDS','EVIDENCE_FIELDS'))
        self.assertEqual(set(source['SPEC_FIELDS']),local.SPEC_FIELDS)
        self.assertEqual(set(source['INGEST_FIELDS']),local.EVIDENCE_FIELDS)
        self.assertEqual(set(analyst['REQUEST_FIELDS']),local.ANALYSIS_FIELDS)
        self.assertEqual(set(analyst['EVIDENCE_FIELDS']),{'market_id','news_id','spec_id'})
        # Compare the strict local risk shape to the source literal in its AST.
        tree=ast.parse(Path(local.__file__).read_text(encoding='utf-8'))
        shapes=[ast.literal_eval(n.args[1]) for n in ast.walk(tree) if isinstance(n,ast.Call)
            and isinstance(n.func,ast.Name) and n.func.id=='_shape' and len(n.args)==2
            and isinstance(n.args[0],ast.Name) and n.args[0].id=='risk']
        self.assertEqual(shapes,[set(source['RISK_FIELDS'])])

    def test_runtime_model_and_cap_unchanged(self):
        budget=selected('analysis_budget.py',('MODEL','EFFORT'))
        engine=selected('engine.py',('RISK',))
        self.assertEqual((local.MODEL,local.REASONING),(budget['MODEL'],budget['EFFORT']))
        self.assertEqual(engine['RISK']['max_exposure_cents'],200000)

    def test_contract_hash_matches_server(self):
        remote=selected('btc_analysis.py',('digest',),{'hashlib':hashlib,'json':json})['digest']
        for instrument,profile in PROFILES.items():
            spec=dict(symbol=profile.symbol,contract_size='100' if instrument=='GOLD' else '1',volume_min='0.01',
                volume_max='50',volume_step='0.01',tick_cents=1,stops_distance_cents=0,cost_bound_cents=None,
                verified_at=self.now.isoformat())
            self.assertEqual(local.contract_hash(spec,instrument=instrument),remote({k:v for k,v in spec.items() if k!='verified_at'}))

    def test_gold_calendar_and_macro_ready_are_explicit(self):
        news=self.news()
        self.config['validate_news'](news,'GOLD',news['id'],self.now)
        self.assertEqual(self.config['news_gate'](news,'GOLD',self.now),'READY')
        news['risk_review']='UNREVIEWED'
        self.assertEqual(self.config['news_gate'](news,'GOLD',self.now),'GOLD_NEWS_UNREVIEWED')

    def test_gold_blackout_edges_and_insufficient_coverage(self):
        for seconds in (-900,900):
            news=self.news();news['calendar']['events']=[dict(id='c'*32,at=(self.now+timedelta(seconds=seconds)).isoformat(),
                currency='USD',impact='HIGH',title='Synthetic event')]
            self.config['validate_news'](news,'GOLD',news['id'],self.now)
            self.assertEqual(self.config['news_gate'](news,'GOLD',self.now),'CALENDAR_EVENT_BLOCKED')
        news=self.news();news['calendar']['coverage_end_at']=(self.now+timedelta(seconds=899)).isoformat()
        self.assertEqual(self.config['news_gate'](news,'GOLD',self.now),'CALENDAR_COVERAGE_INSUFFICIENT')

    def test_gold_stale_calendar_and_wrong_coverage_rejected(self):
        news=self.news();news['calendar']['valid_until']=self.now.isoformat()
        with self.assertRaisesRegex(Rejected,'CALENDAR_STALE'):
            self.config['validate_news'](news,'GOLD',news['id'],self.now)
        news=self.news();news['coverage']='BTC_EDITORIAL_ONLY'
        with self.assertRaisesRegex(Rejected,'NEWS_COVERAGE_INVALID'):
            self.config['validate_news'](news,'GOLD',news['id'],self.now)


if __name__=='__main__':
    unittest.main()
