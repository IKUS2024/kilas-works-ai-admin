"""Bounded accepted source state in the existing tenant Trading ledger."""
import copy
import json
import os
import secrets
import threading
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from . import bridge, bridge_store, btc_news
from .store import query

SPEC_FIELDS=('symbol','contract_size','volume_min','volume_max','volume_step','tick_cents','stops_distance_cents','cost_bound_cents','verified_at')
RISK_FIELDS=('captured_at','position_open','protection_active','daily_loss_remaining_cents','strategy_verified','cooldown_clear','loss_streak_clear','broker_contract_sha256','policy_version')
ACCEPTANCE_FIELDS=('producer_acceptance','clock_verified','profile_verified','profile_id','evidence_ref','candidate_offset_seconds','broker_contract_sha256','policy_version')
INGEST_FIELDS=('schema_version','session_id','revision','command_id','instrument','lot','sequence','challenge','account_mode','terminal_connected','market','spec','risk')
STATE_ACTION='BTC_SOURCE_STATE_V2'
STATE_KEY='btc-source-state-v2'
CAPTURE_WINDOW_SECONDS=5

def contract_hash(spec):
    from .btc_analysis import digest
    return digest({k:v for k,v in spec.items() if k not in ('verified_at','id','verified')})

def cents(raw):
    value=bridge.positive(raw)*100
    bridge.require(value==value.to_integral_value() and value<=100000000,'PRICE_PRECISION_REJECTED')
    return int(value)

class AcceptedSources:
    def __init__(self):
        self.lock=threading.RLock();self.sessions={};self.news=None;self._connection=None
    @contextmanager
    def transaction(self):
        # The database lock, not this process lock, serializes different workers.
        # Reentrant calls share the same transaction; no DDL or new infrastructure.
        with self.lock:
            if self._connection is not None:
                yield self._connection;return
            rejected=None
            with bridge_store.transaction() as conn:
                self._connection=conn
                try:
                    rows=query(conn,'SELECT user_id,inputs_json FROM kilas_trading_events WHERE action=?',(STATE_ACTION,))
                    bridge.require(len(rows)<=1,'SOURCE_STATE_CONFLICT')
                    self.sessions={};self.news=None
                    if rows:
                        raw=rows[0]['inputs_json'];bridge.require(len(raw.encode())<=262144,'SOURCE_STATE_BOUND')
                        saved=json.loads(raw);bridge.require(saved['version']==2,'SOURCE_STATE_VERSION')
                        self.news=saved['news']
                        for entry in saved['sessions']:
                            state=entry['state'];state['records']=OrderedDict(state['records']);state['expires']=bridge.date(state['expires'])
                            bridge.require(entry['user_id']==rows[0]['user_id'],'SOURCE_TENANT_MISMATCH')
                            self.sessions[(entry['user_id'],entry['session_id'])]=state
                    self._purge()
                    try:yield conn
                    except bridge.Rejected as exc:rejected=exc
                    entries=[]
                    for (user,ident),state in self.sessions.items():
                        encoded=copy.deepcopy(state);encoded['expires']=bridge.stamp(state['expires']);encoded['records']=list(state['records'].items())
                        entries.append(dict(user_id=user,session_id=ident,state=encoded))
                    payload=json.dumps(dict(version=2,sessions=entries,news=self.news),separators=(',',':'),allow_nan=False)
                    bridge.require(len(payload.encode())<=262144,'SOURCE_STATE_BOUND')
                    query(conn,'DELETE FROM kilas_trading_events WHERE action=?',(STATE_ACTION,))
                    if entries:
                        user=entries[0]['user_id']
                        query(conn,'INSERT INTO kilas_trading_events(user_id,operation_key,fingerprint,action,outcome,message,inputs_json,created_at) VALUES (?,?,?,?,?,?,?,?)',(user,STATE_KEY,bridge.digest(payload.encode().hex()),STATE_ACTION,'INERT','Bounded sanitized BTC session state.',payload,bridge.stamp(bridge.now())))
                finally:self._connection=None
            if rejected:raise rejected
    def reset(self):
        with self.transaction():self.sessions.clear();self.news=None
    def install_reviewed(self,manifest,acceptance):
        # Server-only handoff: never registered as HTTP, never automatically called.
        # This accepts an already reviewed nonsecret record, not a new credential.
        from . import btc_analysis as btc
        bridge.exact(manifest,('user_id','session_id','instrument','server','created_at','expires_at','model_analysis_allowed','policy_version','max_loss_cents','max_requests'))
        bridge.exact(acceptance,ACCEPTANCE_FIELDS)
        bridge.require(type(manifest['user_id']) is int and manifest['user_id']>0 and manifest['instrument']=='BTC' and manifest['server']==bridge.SERVER and manifest['model_analysis_allowed'] is True,'APPROVAL_REJECTED')
        bridge.secret(manifest['session_id'],32);bridge.secret(manifest['policy_version'])
        start,end=bridge.date(manifest['created_at']),bridge.date(manifest['expires_at'])
        bridge.require(start<=bridge.now()<end and 0<(end-start).total_seconds()<=300 and btc.integer(manifest['max_loss_cents'],1,2000) and btc.integer(manifest['max_requests'],1,10),'APPROVAL_REJECTED')
        bridge.require(acceptance['producer_acceptance']=='ACCEPTED' and type(acceptance['clock_verified']) is bool and type(acceptance['profile_verified']) is bool and acceptance['policy_version']==manifest['policy_version'],'PRODUCER_UNACCEPTED')
        bridge.secret(acceptance['broker_contract_sha256'])
        bridge.require(type(acceptance['candidate_offset_seconds']) is int and abs(acceptance['candidate_offset_seconds'])<=50400 and all(type(acceptance[k]) is str and 1<=len(acceptance[k])<=80 for k in ('profile_id','evidence_ref')),'PROFILE_REJECTED')
        # Existing ledger has an account FK; use its existing owner-only initializer.
        from . import store
        with store.locked(manifest['user_id']):pass
        with self.transaction() as conn:
            bridge.pilot(conn,manifest['user_id'])
            self._purge()
            bridge.require(not self.sessions,'ONE_REVIEWED_SESSION_ONLY')
            key=(manifest['user_id'],manifest['session_id'])
            self.sessions[key]=dict(manifest=copy.deepcopy(manifest),acceptance=copy.deepcopy(acceptance),records=OrderedDict(),sequence=0,latest=None,expires=end,news_review=None,capture_challenge_hash=None,capture_issued_at=None,runtime=None)
    def _purge(self):
        current=bridge.now()
        for key in list(self.sessions):
            if current>=self.sessions[key]['expires'] or current<bridge.date(self.sessions[key]['manifest']['created_at']):del self.sessions[key]
        if self.news and current>=bridge.date(self.news['valid_until']):self.news=None
    def _session(self,user,ident):
        self._purge();record=self.sessions.get((user,ident))
        bridge.require(record,'ACCEPTED_SESSION_UNAVAILABLE')
        return record
    def session(self,user,ident):
        with self.transaction():return copy.deepcopy(self._session(user,ident)['manifest'])
    def revoke(self,user,ident):
        with self.transaction():self.sessions.pop((user,ident),None)
    def collect_news(self):
        record=btc_news.collect()
        with self.transaction():
            bridge.require(self.sessions,'ACCEPTED_SESSION_UNAVAILABLE')
            record['id']=secrets.token_hex(16);self.news=record
            return copy.deepcopy(record)
    def review_news(self,user,ident,record):
        # Separate server-side risk-review evidence; public RSS cannot self-promote.
        bridge.exact(record,('news_id','policy_version','coverage','event_risk','sentiment','expires_at'))
        bridge.require(record['coverage']==btc_news.COVERAGE and record['event_risk'] in ('LOW','HIGH','UNKNOWN') and type(record['sentiment']) is int and -1<=record['sentiment']<=1,'NEWS_REVIEW_REJECTED')
        with self.transaction():
            state=self._session(user,ident)
            bridge.require(self.news and record['news_id']==self.news['id'] and record['policy_version']==state['manifest']['policy_version'] and bridge.now()<bridge.date(record['expires_at'])<=min(state['expires'],bridge.date(self.news['valid_until'])),'NEWS_REVIEW_REJECTED')
            state['news_review']=copy.deepcopy(record)
    def _news(self,state):
        bridge.require(self.news,'NEWS_UNAVAILABLE')
        news=copy.deepcopy(self.news);review=state['news_review']
        if review and review['news_id']==news['id'] and bridge.now()<bridge.date(review['expires_at']):
            news.update(event_risk=review['event_risk'],sentiment=review['sentiment'],risk_review='SERVER_REVIEWED')
        return news
    def _save(self,state,kind,value):
        for ident,(oldkind,old) in state['records'].items():
            if oldkind==kind and old==value:return ident
        ident=secrets.token_hex(16);state['records'][ident]=(kind,copy.deepcopy(value))
        while len(state['records'])>64:state['records'].popitem(last=False)
        return ident
    def _rotate_capture(self,state,current):
        challenge=secrets.token_hex(32)
        state['capture_challenge_hash']=bridge.digest(challenge)
        state['capture_issued_at']=bridge.stamp(current)
        return challenge,bridge.stamp(min(current+timedelta(seconds=CAPTURE_WINDOW_SECONDS),state['expires']))
    def ensure_news(self):
        # Shared lease/backoff prevents each web worker from fetching independently.
        with self.transaction():
            if self.news and self.news['articles']:return
            bridge.require(self.sessions,'ACCEPTED_SESSION_UNAVAILABLE')
            state=next(iter(self.sessions.values()));now=bridge.now()
            if state.get('news_retry_at') and now<bridge.date(state['news_retry_at']):return
            state['news_retry_at']=bridge.stamp(now+timedelta(seconds=30))
        try:self.collect_news()
        except bridge.Rejected:pass  # Missing news stays explicit and blocks analysis.
    def install_runtime_authority(self,user,ident,authority):
        # Server-only, once per approved session. Does not create or elevate a token.
        bridge.exact(authority,('user_id','session_id','policy_version','expires_at','runtime_eligible','broker_execution_allowed','policy_replay_only','server','instrument'))
        with self.transaction() as conn:
            bridge.pilot(conn,user);state=self._session(user,ident)
            bridge.require(state['runtime'] is None and authority['user_id']==user and authority['session_id']==ident and authority['policy_version']==state['manifest']['policy_version'] and authority['server']==bridge.SERVER and authority['instrument']=='BTC','RUNTIME_APPROVAL_REJECTED')
            bridge.require(authority['runtime_eligible'] is True and authority['broker_execution_allowed'] is True and authority['policy_replay_only'] is False and bridge.now()<bridge.date(authority['expires_at'])<=state['expires'],'RUNTIME_APPROVAL_REJECTED')
            state['runtime']=copy.deepcopy(authority)
    def authorization(self,user,ident):
        from . import control
        with self.transaction() as conn:
            state=self._session(user,ident);grant=state['runtime']
            bridge.require(grant and bridge.now()<bridge.date(grant['expires_at']),'RUNTIME_UNAPPROVED')
            row=control.row_for(conn,user)
            bridge.require(row and row['worker_session_id']==ident and row['desired_state']=='ON' and row['run_status']=='ACTIVE','RUNTIME_INTENT_UNAVAILABLE')
            return dict(copy.deepcopy(grant),command_id=row['command_id'],revision=row['revision'])
    def ingest(self,token,data):
        from . import btc_analysis as btc
        bridge.require(os.environ.get('KILAS_TRADING_BTC_EVIDENCE_ENABLED')=='true','EVIDENCE_DISABLED',404)
        bridge.exact(data,INGEST_FIELDS)
        bridge.require(type(data['schema_version']) is int and data['schema_version']==2 and data['instrument']=='BTC' and data['account_mode']=='DEMO' and data['terminal_connected'] is True,'DEMO_EVIDENCE_ONLY')
        bridge.require(type(data['sequence']) is int and 0<=data['sequence']<2**63,'EVIDENCE_SEQUENCE_REJECTED')
        bridge.require(type(data['revision']) is int and 0<=data['revision']<2**63-1,'EVIDENCE_REVISION_REJECTED');bridge.secret(data['session_id'],32)
        if data['command_id'] is not None:bridge.secret(data['command_id'],32)
        btc.control.lot(data['lot']);scope,manifest=btc.authorize(token,data)
        if data['sequence']==0:
            bridge.require(data['challenge'] is None and data['market'] is None and data['spec'] is None and data['risk'] is None,'CAPTURE_BOOTSTRAP_INVALID')
            # Public collection precedes the capture challenge; no network operation
            # consumes the five-second capture window or holds a database lock.
            self.ensure_news()
            with self.transaction():
                state=self._session(scope['user_id'],scope['session_id'])
                bridge.require(state['capture_challenge_hash'] is None or bridge.now()>=bridge.date(state['capture_issued_at'])+timedelta(seconds=CAPTURE_WINDOW_SECONDS),'CAPTURE_BOOTSTRAP_REPLAY')
                current=bridge.now();challenge,expires=self._rotate_capture(state,current)
                return dict(schema_version=2,outcome='CAPTURE_CHALLENGE_ISSUED',sequence=state['sequence'],challenge=challenge,challenge_expires_at=expires,received_at=bridge.stamp(current),execution_authorized=False)
        bridge.secret(data['challenge'])
        bridge.validate_market(data['market'],'BTCUSD');bridge.exact(data['spec'],SPEC_FIELDS);bridge.exact(data['risk'],RISK_FIELDS)
        # Missing/empty feeds can recover during the normal capture loop. A slow
        # retry may expire this nonce; reject it below and let bootstrap recover
        # with the cached news. Collection never holds the source/control DB lock.
        self.ensure_news()
        with self.transaction():
            state=self._session(scope['user_id'],scope['session_id']);accept=state['acceptance'];current=bridge.now()
            bridge.require(data['sequence']==state['sequence']+1,'EVIDENCE_REPLAY_REJECTED')
            bridge.require(state['capture_challenge_hash'] and secrets.compare_digest(bridge.digest(data['challenge']),state['capture_challenge_hash']),'CAPTURE_CHALLENGE_REJECTED')
            issued=bridge.date(state['capture_issued_at']);age=(current-issued).total_seconds()
            bridge.require(0<=age<CAPTURE_WINDOW_SECONDS,'CAPTURE_WINDOW_EXPIRED')
            raw=data['market'];duration=(raw['capture']['end_mono_ns']-raw['capture']['start_mono_ns'])/1e9
            bridge.require(duration<=age+.05,'CAPTURE_PRECEDES_CHALLENGE')
            # Receipt-window liveness is not absolute UTC/profile attestation.
            # Epochs remain broker labels; only relative closed-bar ages are used.
            market=dict(kind='DEMO',provider='TRUSTED_BTC_V1',symbol='BTCUSD',timeframe='M1',captured_at=raw['capture']['end_utc'],quote_time=raw['tick']['time'],broker_tick_msc=raw['tick']['time_msc'],tick_advanced_at=None,bid_cents=cents(raw['tick']['bid']),ask_cents=cents(raw['tick']['ask']),clock_verified=False,profile_verified=False,time_basis='RECEIPT_BOUNDED',received_at=bridge.stamp(current),freshness_started_at=bridge.stamp(issued),candles=[dict(time=bar['time']+60,**{k:cents(bar[k]) for k in ('open','high','low','close')}) for bar in raw['candles']])
            if state['latest']:
                previous=state['records'][state['latest']['market_id']][1]
                bridge.require(market['broker_tick_msc']>=previous['broker_tick_msc'],'BROKER_CLOCK_REWOUND')
                market['tick_advanced_at']=bridge.stamp(current) if market['broker_tick_msc']>previous['broker_tick_msc'] else previous['tick_advanced_at']
            spec=copy.deepcopy(data['spec']);risk=copy.deepcopy(data['risk'])
            bridge.require(spec['symbol']=='BTCUSD' and contract_hash(spec)==accept['broker_contract_sha256'] and risk['broker_contract_sha256']==accept['broker_contract_sha256'] and risk['policy_version']==accept['policy_version'],'BROKER_CONTRACT_MISMATCH')
            bridge.require(risk['captured_at']==raw['capture']['end_utc'] and (not risk['position_open'] or risk['protection_active'] is True),'RISK_CAPTURE_MISMATCH')
            for field in ('broker_contract_sha256','policy_version'):risk.pop(field)
            risk['captured_at']=bridge.stamp(issued)  # conservative earliest capture bound
            bridge.date(spec['verified_at'])  # validate producer claim shape only
            spec['verified']=True;spec['verified_at']=state['manifest']['created_at']
            placeholder=dict(id='0'*32,provider='TRUSTED_NEWS_V1',as_of=bridge.stamp(current),valid_until=bridge.stamp(current+timedelta(seconds=1)),verified=True,event_risk='UNKNOWN',sentiment=0,coverage=btc_news.COVERAGE,risk_review='UNREVIEWED',articles=[dict(id='0'*32,published_at=bridge.stamp(current),title='Validation placeholder; never retained or sent')])
            btc.validate(dict(market=dict(market,id='0'*32),spec=dict(spec,id='0'*32),risk=risk,news=placeholder),dict(evidence=dict(market_id='0'*32,news_id='0'*32,spec_id='0'*32)))
            market_id=self._save(state,'market',market);spec_id=self._save(state,'spec',spec)
            state['sequence']=data['sequence'];state['latest']=dict(market_id=market_id,spec_id=spec_id,risk=copy.deepcopy(risk))
            news_id=self._save(state,'news',self._news(state)) if self.news else None
            challenge,expires=self._rotate_capture(state,current)
            return dict(schema_version=2,outcome='EVIDENCE_ACCEPTED',session_id=scope['session_id'],sequence=data['sequence'],challenge=challenge,challenge_expires_at=expires,evidence=dict(market_id=market_id,spec_id=spec_id,news_id=news_id),coverage=btc_news.COVERAGE,risk_review=self._news(state)['risk_review'] if self.news else 'UNREVIEWED',tick_liveness='VERIFIED' if market['tick_advanced_at'] and (current-bridge.date(market['tick_advanced_at'])).total_seconds()<=5 else 'UNCONFIRMED',execution_authorized=False,received_at=bridge.stamp(current))
    def resolve(self,user,ident,ids):
        with self.transaction():
            state=self._session(user,ident);out={}
            for field,kind in (('market_id','market'),('news_id','news'),('spec_id','spec')):
                saved=state['records'].get(ids[field]);bridge.require(saved and saved[0]==kind,'EVIDENCE_ID_UNAVAILABLE')
                out[kind]=dict(copy.deepcopy(saved[1]),id=ids[field])
            review=state['news_review']
            if out['news']['risk_review']=='SERVER_REVIEWED':
                stored=state['records'][ids['news_id']][1]
                bridge.require(review and self.news and review['news_id']==stored['id']==self.news['id'] and review['event_risk']==stored['event_risk'] and review['sentiment']==stored['sentiment'] and bridge.now()<bridge.date(review['expires_at']),'NEWS_REVIEW_EXPIRED')
            bridge.require(state['latest'],'LATEST_RISK_UNAVAILABLE');out['risk']=copy.deepcopy(state['latest']['risk'])
            return out
    def latest(self,user,ident):
        with self.transaction():
            state=self._session(user,ident);bridge.require(state['latest'],'LATEST_EVIDENCE_UNAVAILABLE')
            ids={k:state['latest'][k] for k in ('market_id','spec_id')};ids['news_id']=self._save(state,'news',self._news(state))
            return self.resolve(user,ident,ids)

accepted_sources=AcceptedSources()
