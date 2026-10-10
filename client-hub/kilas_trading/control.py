"""Disabled DEMO intent coordination; never an order or execution authorization."""
from datetime import timedelta
from decimal import Decimal
import json
import os
import secrets
from . import bridge, bridge_store
from .store import query

PICKUP_SECONDS=30
MAX_RUN_SECONDS=300
ACK_SECONDS=6
CHALLENGE_SECONDS=10
SYMBOL={'BTC':'BTCUSD','GOLD':'GOLD'}
SCOPE='DEMO_BOUNDED_RUN_COORDINATION_V2'
WAIT_REASONS=('NONE','MODEL_UNAVAILABLE','STRATEGY_UNAVAILABLE','NEWS_UNVERIFIED','RISK_BLOCKED','DEMO_UNVERIFIED','TRANSPORT_UNAVAILABLE')

def enabled():return os.environ.get('KILAS_TRADING_CONTROL_ENABLED')=='true'
def row_for(conn,user):return query(conn,'SELECT * FROM kilas_trading_controls_v2 WHERE user_id=?',(user,),one=True)
def ensure(conn,user):
    if not row_for(conn,user):query(conn,'INSERT INTO kilas_trading_controls_v2(user_id) VALUES (?)',(user,))
    return row_for(conn,user)
def lot(value):
    amount=bridge.positive(value)
    bridge.require(amount>=Decimal('0.01'),'INVALID_LOT')
    bridge.require(value==format(amount.normalize(),'f'),'NONCANONICAL_LOT')
    return value

def binding(conn,user,current):
    # No issuer exists here. Only a separately approved control scope may be
    # provisioned. Read-only bridge tokens are never accepted for this channel.
    b=query(conn,'SELECT * FROM kilas_trading_control_credentials_v2 WHERE user_id=?',(user,),one=True)
    if not b or b['revoked'] or b['scope']!=SCOPE:return None
    if query(conn,'SELECT 1 AS shared FROM kilas_trading_bridges WHERE token_hash=?',(b['credential_hash'],),one=True):return None
    created,expires=bridge.date(b['created_at']),bridge.date(b['expires_at'])
    return b if created<=current<expires and 0<(expires-created).total_seconds()<=1800 else None

def fresh(row,b,current):
    if not row or not b or row['worker_session_id']!=b['session_id'] or not row['ack_received_at'] or not row['ack_json']:return False
    return 0<=(current-bridge.date(row['ack_received_at'])).total_seconds()<=ACK_SECONDS

def ready(ack):
    return ack['account_mode']=='DEMO' and ack['terminal_connected'] and ack['policy_state']=='READY' and ack['specs_verified'] and ack['risk_allowed'] and ack['wait_reason']=='NONE'

def end_run(conn,row,reason):
    if row and row['run_status'] in ('PENDING','ACTIVE'):
        query(conn,"UPDATE kilas_trading_controls_v2 SET run_status='ENDED',end_reason=?,worker_lease_expires_at=NULL WHERE user_id=?",(reason,row['user_id']))
        return row_for(conn,row['user_id'])
    return row

def fence(conn,row,b,current):
    if not row or row['run_status'] not in ('PENDING','ACTIVE'):return row
    reason=None
    if not b:reason='CREDENTIAL_UNAVAILABLE'
    elif current<bridge.date(row['issued_at']):reason='CLOCK_DISCONTINUITY'
    elif current>=bridge.date(row['run_expires_at']):reason='RUN_DEADLINE'
    elif row['run_status']=='PENDING' and current>=bridge.date(row['command_expires_at']):reason='PICKUP_EXPIRED'
    elif not row['worker_lease_expires_at'] or current>=bridge.date(row['worker_lease_expires_at']):reason='WORKER_LEASE_EXPIRED'
    elif row['ack_received_at'] and current<bridge.date(row['ack_received_at']):reason='CLOCK_DISCONTINUITY'
    return end_run(conn,row,reason) if reason else row

def project(row,b,current):
    live=enabled() and fresh(row,b,current)
    ack=json.loads(row['ack_json']) if live else None
    matches=bool(ack and ack['revision']==row['revision'] and ack['command_id']==row['command_id'])
    active=bool(row and row['run_status'] in ('PENDING','ACTIVE') and row['run_expires_at'] and row['worker_lease_expires_at'] and bridge.date(row['issued_at'])<=current<bridge.date(row['run_expires_at']) and current<bridge.date(row['worker_lease_expires_at']))
    effective='ON' if enabled() and active and row['desired_state']=='ON' and ack and ready(ack) and ack['instrument']==row['instrument'] and ack['lot']==row['lot'] and (row['run_status']=='PENDING' or matches) else 'OFF'
    actual=ack['actual_state'] if matches else 'UNKNOWN'
    if actual=='RUNNING' and effective!='ON':actual='UNKNOWN'
    return dict(schema_version=2,enabled=enabled(),desired_state=row['desired_state'] if row else 'OFF',effective_desired_state=effective,
        actual_state=actual,actual_state_source='WORKER_ACK_NOT_BROKER_ATTESTATION',worker_fresh=bool(live),
        revision=row['revision'] if row else 0,command_id=row['command_id'] if row else None,
        instrument=row['instrument'] if row else 'BTC',lot=row['lot'] if row else '0.01',
        issued_at=row['issued_at'] if row else None,command_expires_at=row['command_expires_at'] if row else None,
        run_seconds=row['run_seconds'] if row else 0,run_expires_at=row['run_expires_at'] if row else None,
        run_started_at=row['run_started_at'] if row else None,worker_lease_expires_at=row['worker_lease_expires_at'] if row else None,
        run_status=row['run_status'] if row else 'NONE',end_reason=row['end_reason'] if row else 'NONE',
        received_at=bridge.stamp(current),ack_received_at=row['ack_received_at'] if row else None,
        execution_authorized=False,off_behavior='STOP_ENTRIES_KEEP_PROTECTION',
        wait_reason=ack['wait_reason'] if ack else 'WORKER_OFFLINE' if enabled() else 'CONTROL_DISABLED',
        account_detail=dict(account_mode='DEMO',broker='XM',platform='MT5',server=b['server'],verification='WORKER_REPORT_ONLY') if ack and ack['account_mode']=='DEMO' and ack['terminal_connected'] else None)

def status(user):
    if not enabled():return project(None,None,bridge.now())
    with bridge_store.transaction() as conn:
        bridge.pilot(conn,user);current=bridge.now()
        b=binding(conn,user,current)
        return project(fence(conn,row_for(conn,user),b,current),b,current)

def desired(user,data):
    bridge.require(enabled(),'DISABLED',404)
    bridge.exact(data,('schema_version','command_id','expected_revision','desired_state','instrument','lot','run_seconds'))
    bridge.require(type(data['schema_version']) is int and data['schema_version']==2)
    bridge.secret(data['command_id'],32)
    bridge.require(type(data['expected_revision']) is int and 0<=data['expected_revision']<2**63-2)
    bridge.require(type(data['desired_state']) is str and type(data['instrument']) is str and data['desired_state'] in ('ON','OFF') and data['instrument'] in SYMBOL)
    bridge.require(type(data['run_seconds']) is int and (1<=data['run_seconds']<=MAX_RUN_SECONDS if data['desired_state']=='ON' else data['run_seconds']==0),'INVALID_RUN_DURATION')
    lot(data['lot']);hashed=bridge.digest(json.dumps(data,sort_keys=True,separators=(',',':')))
    with bridge_store.transaction() as conn:
        bridge.pilot(conn,user);current=bridge.now();row=ensure(conn,user);b=binding(conn,user,current);row=fence(conn,row,b,current)
        prior=query(conn,'SELECT * FROM kilas_trading_control_receipts_v2 WHERE user_id=? AND command_id=?',(user,data['command_id']),one=True)
        if prior:
            bridge.require(prior['payload_hash']==hashed,'COMMAND_ID_CONFLICT')
            bridge.require(prior['revision']==row['revision'],'COMMAND_SUPERSEDED')
            return dict(project(row,b,current),outcome='IDEMPOTENT')
        bridge.require(data['expected_revision']==row['revision'],'REVISION_CONFLICT')
        ack=json.loads(row['ack_json']) if fresh(row,b,current) else None
        changed=(data['instrument'],data['lot'])!=(row['instrument'],row['lot'])
        if changed and row['revision']:
            bridge.require(ack and ack['revision']==row['revision'] and ack['actual_state']=='OFF' and not ack['position_open'],'CONFIGURATION_LOCKED')
        if data['desired_state']=='ON':
            bridge.require(b and b['symbol']==SYMBOL[data['instrument']],'WORKER_SCOPE_UNAVAILABLE')
            bridge.require(ack and ready(ack) and ack['revision']==row['revision'] and ack['command_id']==row['command_id'],'WORKER_NOT_READY')
            bridge.require(not changed,'CONFIGURATION_REQUIRES_OFF_ACK')
            bridge.require(row['run_status'] not in ('PENDING','ACTIVE'),'RUN_ALREADY_ACTIVE')
            bridge.require(ack['actual_state']=='OFF' and not ack['position_open'],'RUN_REQUIRES_FLAT_OFF_ACK')
            bridge.require(type(b['max_run_seconds']) is int and 1<=data['run_seconds']<=b['max_run_seconds']<=MAX_RUN_SECONDS,'RUN_DURATION_UNAPPROVED')
            bridge.require(current+timedelta(seconds=data['run_seconds'])<=bridge.date(b['expires_at']),'INSUFFICIENT_SCOPE_LIFETIME')
        revision=row['revision']+1
        on=data['desired_state']=='ON'
        hard=current+timedelta(seconds=data['run_seconds']) if on else None
        pickup=min(current+timedelta(seconds=PICKUP_SECONDS),hard) if on else None
        soft=min(bridge.date(row['ack_received_at'])+timedelta(seconds=ACK_SECONDS),hard,bridge.date(b['expires_at'])) if on else None
        phase='PENDING' if on else 'ENDED' if row['run_status']!='NONE' else 'NONE'
        query(conn,'UPDATE kilas_trading_controls_v2 SET revision=?,command_id=?,desired_state=?,instrument=?,lot=?,issued_at=?,command_expires_at=?,run_seconds=?,run_expires_at=?,run_started_at=NULL,worker_lease_expires_at=?,run_status=?,end_reason=? WHERE user_id=?',
              (revision,data['command_id'],data['desired_state'],data['instrument'],data['lot'],bridge.stamp(current),bridge.stamp(pickup) if pickup else None,data['run_seconds'],bridge.stamp(hard) if hard else None,bridge.stamp(soft) if soft else None,phase,'NONE' if on or phase=='NONE' else 'OFF_REQUESTED',user))
        intent=dict(data,issued_at=bridge.stamp(current),command_expires_at=bridge.stamp(pickup) if pickup else None,run_expires_at=bridge.stamp(hard) if hard else None)
        query(conn,'INSERT INTO kilas_trading_control_receipts_v2 VALUES (?,?,?,?,?)',(user,data['command_id'],revision,hashed,json.dumps(intent,separators=(',',':'))))
        query(conn,'DELETE FROM kilas_trading_control_receipts_v2 WHERE user_id=? AND revision<=?',(user,revision-64))
        return dict(project(row_for(conn,user),b,current),outcome='DESIRED_ACCEPTED')

def validate_ack(data,row,b,current,conn):
    bridge.exact(data,('revision','command_id','actual_state','instrument','lot','account_mode','terminal_connected','position_open','protection_active','specs_verified','risk_allowed','policy_state','wait_reason'))
    bridge.require(type(data['revision']) is int and 0<=data['revision']<=row['revision'],'ACK_COMMAND_MISMATCH')
    current_ack=data['revision']==row['revision'] and data['command_id']==row['command_id']
    intent=row
    if not current_ack:
        prior=query(conn,'SELECT * FROM kilas_trading_control_receipts_v2 WHERE user_id=? AND command_id=?',(row['user_id'],data['command_id']),one=True) if type(data['command_id']) is str else None
        if prior and prior['revision']==data['revision']:intent=json.loads(prior['intent_json'])
        else:
            bridge.require(data['revision']<row['revision'] and data['command_id'] is None and data['actual_state']=='OFF' and data['position_open'] is False,'ACK_COMMAND_MISMATCH')
            intent=dict(row,desired_state='OFF')
    bridge.require(all(type(data[k]) is str for k in ('actual_state','instrument','lot','account_mode','policy_state','wait_reason')))
    bridge.require(data['instrument']==intent['instrument'] and data['lot']==intent['lot'] and b['symbol']==SYMBOL[data['instrument']],'ACK_SCOPE_MISMATCH')
    bridge.require(data['actual_state'] in ('OFF','PROTECTING','RUNNING','BLOCKED') and data['policy_state'] in ('UNSET','READY','BLOCKED'))
    bridge.require(data['wait_reason'] in WAIT_REASONS)
    bridge.require(data['account_mode'] in ('DEMO','UNKNOWN'),'REAL_ACCOUNT_REJECTED')
    bridge.require(all(type(data[k]) is bool for k in ('terminal_connected','position_open','protection_active','specs_verified','risk_allowed')))
    bridge.require(not data['position_open'] or data['protection_active'] and data['actual_state'] in ('PROTECTING','RUNNING'),'PROTECTION_REQUIRED')
    if data['actual_state']=='RUNNING':
        bridge.require(not current_ack or row['run_status'] in ('PENDING','ACTIVE'),'RUN_ENDED')
        bridge.require(data['account_mode']=='DEMO' and ready(data),'RUNNING_GATES_REJECTED')
        bridge.require(intent['desired_state']=='ON' and intent['issued_at'] and bridge.date(intent['issued_at'])<=current<bridge.date(intent['run_expires_at']),'RUNNING_LEASE_REJECTED')
    return data

def sync(token,data):
    bridge.require(enabled(),'DISABLED',404)
    bridge.secret(token);bridge.exact(data,('schema_version','sequence','challenge','ack'))
    bridge.require(type(data['schema_version']) is int and data['schema_version']==2 and type(data['sequence']) is int and 0<=data['sequence']<2**63)
    rejected=None;result=None
    with bridge_store.transaction() as conn:
        b=query(conn,'SELECT * FROM kilas_trading_control_credentials_v2 WHERE credential_hash=?',(bridge.digest(token),),one=True);current=bridge.now()
        bridge.require(b,'INVALID_CONTROL_CREDENTIAL',401)
        try:
            bridge.require(binding(conn,b['user_id'],current),'INVALID_CONTROL_CREDENTIAL',401)
            bridge.pilot(conn,b['user_id'])
        except bridge.Rejected as exc:
            end_run(conn,row_for(conn,b['user_id']),'CREDENTIAL_UNAVAILABLE');rejected=exc
        if not rejected:
            row=fence(conn,ensure(conn,b['user_id']),b,current)
            try:
                if data['sequence']==0:
                    if row['worker_session_id']==b['session_id']:row=end_run(conn,row,'WORKER_RESTARTED')
                    bridge.require(data['challenge'] is None and data['ack'] is None and row['worker_session_id']!=b['session_id'],'BOOTSTRAP_REPLAY')
                    prior=row['run_status']!='NONE'
                    if not row['revision']:query(conn,'UPDATE kilas_trading_controls_v2 SET instrument=? WHERE user_id=?',('BTC' if b['symbol']=='BTCUSD' else 'GOLD',b['user_id']))
                    query(conn,"UPDATE kilas_trading_controls_v2 SET revision=revision+?,desired_state='OFF',command_id=NULL,issued_at=NULL,command_expires_at=NULL,run_seconds=0,run_expires_at=NULL,run_started_at=NULL,worker_lease_expires_at=NULL,run_status=?,end_reason=?,ack_json=NULL,ack_received_at=NULL WHERE user_id=?",(int(row['revision']>0),'ENDED' if prior else 'NONE','SESSION_REPLACED' if prior else 'NONE',b['user_id']))
                    ack=None
                else:
                    bridge.secret(data['challenge'])
                    bridge.require(row['worker_session_id']==b['session_id'] and data['sequence']==row['worker_sequence']+1 and row['worker_challenge_hash'] and secrets.compare_digest(bridge.digest(data['challenge']),row['worker_challenge_hash']) and bridge.date(row['worker_challenge_expires'])-timedelta(seconds=CHALLENGE_SECONDS)<=current<bridge.date(row['worker_challenge_expires']),'REPLAY_OR_EXPIRED_CHALLENGE')
                    bridge.require(not row['ack_received_at'] or (current-bridge.date(row['ack_received_at'])).total_seconds()>=1,'CONTROL_RATE_LIMIT',429)
                    try:
                        ack=validate_ack(data['ack'],row,b,current,conn)
                        current_ack=ack['revision']==row['revision'] and ack['command_id']==row['command_id']
                        if row['run_status'] in ('PENDING','ACTIVE'):
                            if current_ack:
                                query(conn,"UPDATE kilas_trading_controls_v2 SET run_status='ACTIVE',run_started_at=COALESCE(run_started_at,?) WHERE user_id=?",(bridge.stamp(current),b['user_id']))
                            # A prior OFF/flat report may deliver a pending intent, but
                            # cannot keep pending beyond its fixed pickup deadline.
                            if current_ack or row['run_status']=='PENDING' and ack['actual_state']=='OFF' and not ack['position_open']:
                                deadline=min(current+timedelta(seconds=ACK_SECONDS),bridge.date(row['run_expires_at']),bridge.date(b['expires_at']))
                                query(conn,'UPDATE kilas_trading_controls_v2 SET worker_lease_expires_at=? WHERE user_id=?',(bridge.stamp(deadline),b['user_id']))
                    except bridge.Rejected as exc:
                        rejected=exc;ack=None;end_run(conn,row,'UNSAFE_ACK')
                challenge=secrets.token_hex(32);deadline=current+timedelta(seconds=CHALLENGE_SECONDS)
                query(conn,'UPDATE kilas_trading_controls_v2 SET worker_session_id=?,worker_sequence=?,worker_challenge_hash=?,worker_challenge_expires=?,ack_json=?,ack_received_at=? WHERE user_id=?',
                      (b['session_id'],data['sequence'],bridge.digest(challenge),bridge.stamp(deadline),json.dumps(ack,separators=(',',':')) if ack else None,bridge.stamp(current) if ack else None,b['user_id']))
                result=dict(project(row_for(conn,b['user_id']),b,current),outcome='ACK_ACCEPTED' if ack else 'BOOTSTRAPPED',sequence=data['sequence'],challenge=challenge,challenge_expires_at=bridge.stamp(deadline))
            except bridge.Rejected as exc:
                # Commit a previously computed deadline/revocation fence even
                # when the incoming challenge/sequence cannot be accepted.
                rejected=exc
    if rejected:raise rejected
    return result
