"""Nonconsuming account probe. No public price is a credit-only entitlement proof."""
import json
import os
import re
from time import monotonic
from datetime import datetime,timezone
from threading import Lock, Thread
from . import live_translator_transport as transport

MODEL='scribe_v2_realtime'
_lock=Lock()
_started=False
_snapshot=None


class ReadFailure(ValueError):
    def __init__(self,status):
        super().__init__('account_read_failed');self.status=status if type(status) is int and 100<=status<=599 else 0


def _get(path):
    deadline=monotonic()+6
    with transport.get('https://api.elevenlabs.io/v1/'+path,
                       headers={'xi-api-key':os.environ['ELEVENLABS_API_KEY'].strip()},
                       stream=True,timeout=(2,3),allow_redirects=False) as response:
        if response.status_code!=200:raise ReadFailure(response.status_code)
        data=bytearray()
        for chunk in response.iter_content(8192):
            data.extend(chunk)
            if len(data)>262144 or monotonic()>deadline:raise ValueError('account_read_too_large')
        return json.loads(data)


def _analytics():
    # Documented POST is a READ-ONLY analytics query, not speech generation,
    # payment, permission change or a billable WebSocket handshake.
    deadline=monotonic()+6
    with transport.post('https://api.elevenlabs.io/v1/workspace/analytics/requests',
        headers={'xi-api-key':os.environ['ELEVENLABS_API_KEY'].strip()},
        json={'end_time':int(datetime.now(timezone.utc).timestamp()*1000),'limit':100,'search':MODEL},
        stream=True,timeout=(2,3),allow_redirects=False) as response:
        if response.status_code!=200:raise ReadFailure(response.status_code)
        data=bytearray()
        for part in response.iter_content(8192):
            data.extend(part)
            if len(data)>262144 or monotonic()>deadline:raise ValueError('account_read_too_large')
        value=json.loads(data)
    columns,units,rows=value.get('columns'),value.get('column_units'),value.get('rows')
    if not isinstance(columns,list) or not 1<=len(columns)<=64 or not isinstance(units,list) or len(units)!=len(columns) or not isinstance(rows,list) or len(rows)>100:raise ValueError('analytics_schema_invalid')
    if any(not isinstance(c,str) or not re.fullmatch(r'[A-Za-z0-9_ ]{1,64}',c) for c in columns) or any(not isinstance(row,list) or len(row)!=len(columns) for row in rows):raise ValueError('analytics_schema_invalid')
    normalized=[c.strip().lower().replace(' ','_') for c in columns]
    model=next((i for i,c in enumerate(normalized) if c in ('model','model_id','model_name')),None)
    matched=[row for row in rows if model is not None and row[model]==MODEL]
    credit_columns=[i for i,(column,unit) in enumerate(zip(normalized,units)) if column in ('cost','credit_cost','credits','billed_credits','cost_credits') and unit in ('credits','credit')]
    usd_columns=[i for i,(column,unit) in enumerate(zip(normalized,units)) if column in ('cost','usd_cost','cost_usd') and unit in ('USD','usd')]
    # Static schema labels + counts/booleans only. Never raw rows, request/key/
    # workspace IDs, transcript, voice name, account names or error bodies.
    return {'analytics_rows':len(rows),'analytics_columns':normalized,
            'analytics_realtime_rows':len(matched),'analytics_model_column':model is not None,
            'analytics_credit_units':bool(credit_columns),'analytics_usd_units':bool(usd_columns)}


def probe():
    result={'key_present':bool(os.environ.get('ELEVENLABS_API_KEY','').strip()),
            'subscription_read':False,'models_read':False,'prepaid_only':False,
            'subscription_http_status':0,'models_http_status':0,
            'used_credit_count':None,'credit_limit':None,'remaining_credit_count':None,
            'analytics_http_status':0,'analytics_read':False,'analytics_rows':0,
            'analytics_realtime_rows':0,'analytics_model_column':False,
            'analytics_credit_units':False,'analytics_usd_units':False,
            'remaining_credit':False,'model_listed':False,
            'realtime_entitlement_verified':False,'credit_rate_verified':False,
            'billing_bounds_verified':False,'activation_ready':False}
    if result['key_present']:
        with transport.turn_connection():
            try:
                value=_get('user/subscription');result['subscription_read']=True;result['subscription_http_status']=200
                result['prepaid_only']=(value.get('tier')=='creator' and value.get('status')=='active'
                    and type(value.get('max_credit_limit_extension')) is int
                    and value['max_credit_limit_extension']==0
                    and value.get('allowed_to_extend_character_limit') is False
                    and value.get('can_extend_character_limit') is False)
                used,limit=value.get('character_count'),value.get('character_limit')
                result['remaining_credit']=type(used) is int and type(limit) is int and 0<=used<limit
                if type(used) is int and type(limit) is int and 0<=used<=limit<=1000000000000:
                    result.update(used_credit_count=used,credit_limit=limit,remaining_credit_count=limit-used)
            except Exception as error:
                result['subscription_http_status']=getattr(error,'status',0)
            try:
                value=_get('models');result['models_read']=True;result['models_http_status']=200
                result['model_listed']=isinstance(value,list) and any(isinstance(v,dict) and v.get('model_id')==MODEL for v in value)
            except Exception as error:result['models_http_status']=getattr(error,'status',0)
            try:
                result.update(_analytics());result['analytics_read']=True;result['analytics_http_status']=200
            except Exception as error:result['analytics_http_status']=getattr(error,'status',0)
    # These documented GET schemas cannot establish STT key scope, credit rate,
    # silence/minimum/rounding/session bounds. Flags and model presence do NOT
    # substitute for authenticated proof; this release cannot activate paid IO.
    global _snapshot
    with _lock:_snapshot=dict(result)
    try:print('KILAS_REALTIME_ACCOUNT '+json.dumps(result,sort_keys=True),flush=True)
    except OSError:pass
    return result


def startup_probe():
    global _started
    with _lock:
        if _started:return
        _started=True
    Thread(target=probe,name='kilas-realtime-account-read',daemon=True).start()


def verified():
    with _lock:return bool(_snapshot and _snapshot['activation_ready'])
