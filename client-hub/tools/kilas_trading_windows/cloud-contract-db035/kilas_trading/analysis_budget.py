"""Trader-only persistent cost reservations; no AI quota exemption or Finance writes."""
import json
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from . import store, engine

MODEL = 'gpt-6.1-sol'
EFFORT = 'medium'
INPUT_BOUND = 20000
OUTPUT_BOUND = 2000 # Includes reasoning tokens, not just visible JSON.
BODY_BYTE_LIMIT = 16000 # Entire serialized request/schema + 2048 framing tokens < INPUT_BOUND.
MONTH_CAP = 5000000
DAY_CAP = 250000
DAY_REQUESTS = 10
ACTION = 'AI_ANALYSIS'
POLICY_PATH = Path(__file__).with_name('analysis_policy.json')
EXPECTED = {'model': MODEL, 'reasoning': EFFORT, 'service_tier':'default',
            'input_usd_per_million':'2.00','cached_input_usd_per_million':'0.10',
            'cache_write_usd_per_million':'2.50','output_usd_per_million':'10.00',
            'regional_multiplier':'1.10',
            'source':'https://developers.openai.com/api/docs/models/gpt-6.1-sol'}


class GuardError(engine.TradingError):
    pass


def policy():
    try:
        card=json.loads(POLICY_PATH.read_text())
        if set(card)!=set(EXPECTED)|{'verified_at','valid_until'} or any(card[k]!=v for k,v in EXPECTED.items()):
            raise ValueError()
        start=datetime.fromisoformat(card['verified_at']);end=datetime.fromisoformat(card['valid_until'])
        if start.tzinfo is None or end.tzinfo is None or not start<=store.now()<end or (end-start).total_seconds()>7*86400:
            raise ValueError()
        return card
    except (OSError,ValueError,KeyError,TypeError):
        raise GuardError('Tarif/model belum terverifikasi atau bukti tarif kedaluwarsa. Analisis diblokir.') from None


def cost_micros(card, inputs, outputs):
    # No cache discount assumed; cover the highest documented input/cache-write price and regional premium.
    price=max(Decimal(card['input_usd_per_million']),Decimal(card['cache_write_usd_per_million']))
    return int(((inputs*price+outputs*Decimal(card['output_usd_per_million']))*
                Decimal(card['regional_multiplier'])).to_integral_value(rounding=ROUND_CEILING))


def result(row, duplicate=False):
    data=json.loads(row['inputs_json'])
    stale=False
    if duplicate and data.get('quote_time'):
        try:
            at=datetime.fromisoformat(data['quote_time'])
            stale=at.tzinfo is None or not 0<=(store.now()-at).total_seconds()<=120
        except (ValueError,TypeError):stale=True
    return {'outcome':'WAIT' if stale and row['outcome']!='PENDING' else row['outcome'],'message':'Hasil tersimpan stale; tidak dipakai untuk order.' if stale else row['message'],'duplicate':duplicate,'cached_stale':stale,
            'analysis':None if stale else data.get('decision'),'source_kind':data.get('source_kind'),
            'source_time':data.get('quote_time'),'model':MODEL,'reasoning':EFFORT,
            'cost_upper_micros':data['cost_upper_micros'],'reserved_micros':data['reserved_micros'],
            'proposal_only':True}


def request_key(raw):
    import re
    if not isinstance(raw,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}',raw):
        raise GuardError('Kunci analisis tidak valid. Muat ulang halaman.')
    return 'analysis-'+raw


def previous(user, key):
    with store.locked(user) as conn:
        row=store.query(conn,'SELECT * FROM kilas_trading_events WHERE user_id=? AND operation_key=?',(user,key),one=True)
        return result(row,True) if row and row['action']==ACTION else None


def reserve(user, key, fingerprint, meta, *, admission=None):
    card=policy();amount=cost_micros(card,INPUT_BOUND,OUTPUT_BOUND)
    if amount<=0 or amount>DAY_CAP or amount>MONTH_CAP:
        raise GuardError('Reservasi biaya tidak tersedia; analisis diblokir.')
    with store.locked(user) as conn:
        now=store.now();month=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat()
        day=now.replace(hour=0,minute=0,second=0,microsecond=0).isoformat()
        a=store.account(conn,user)
        if a['killed'] or a['paused']:
            raise GuardError('Analisis dijeda oleh kontrol paper/kill switch.')
        same=store.query(conn,'SELECT * FROM kilas_trading_events WHERE user_id=? AND action=? AND (operation_key=? OR fingerprint=?) ORDER BY id LIMIT 1',(user,ACTION,key,fingerprint),one=True)
        if same:return result(same,True),None
        if admission is not None:admission(conn)
        rows=store.query(conn,'SELECT outcome,inputs_json,created_at FROM kilas_trading_events WHERE user_id=? AND action=? ORDER BY id DESC LIMIT 5001',(user,ACTION))
        if len(rows)>5000:raise GuardError('Ledger terlalu besar untuk pilot; perlu peninjauan sebelum analisis.')
        spent=spent_today=count_today=0
        for row in rows:
            try:
                evidence=json.loads(row['inputs_json']);held=evidence['cost_upper_micros']
                if type(held)!=int or held<0 or type(evidence['reserved_micros'])!=int or not evidence.get('accounting_ok',False):
                    raise ValueError()
            except (ValueError,KeyError,TypeError):
                raise GuardError('Ledger biaya memerlukan peninjauan; analisis diblokir.') from None
            if row['outcome']=='PENDING':
                raise GuardError('Ada analisis belum selesai. Reservasi tetap ditahan; jangan ulangi dengan kunci baru.')
            if row['created_at']>=month:spent+=held
            if row['created_at']>=day:spent_today+=held;count_today+=1
        if count_today>=DAY_REQUESTS or spent+amount>MONTH_CAP or spent_today+amount>DAY_CAP:
            raise GuardError('Batas Trading tercapai: USD5/bulan, USD0.25/hari, maksimal 10 permintaan manual/hari. Tidak ada top-up otomatis.')
        evidence=dict(meta,model=MODEL,reasoning=EFFORT,rate_policy=card,
                      reserved_micros=amount,cost_upper_micros=amount,accounting_ok=True,
                      input_bound=INPUT_BOUND,output_bound=OUTPUT_BOUND,proposal_only=True)
        store.query(conn,'INSERT INTO kilas_trading_events(user_id,operation_key,fingerprint,action,outcome,message,inputs_json,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (user,key,fingerprint,ACTION,'PENDING','Analisis manual menunggu hasil; biaya maksimum sudah direservasi.',json.dumps(evidence),now.isoformat()))
    return None,card


def finish(user,key,*,outcome,message,decision=None,usage=None,not_sent=False,invariant_ok=True):
    with store.locked(user) as conn:
        row=store.query(conn,'SELECT * FROM kilas_trading_events WHERE user_id=? AND operation_key=? AND action=?',(user,key,ACTION),one=True)
        if not row or row['outcome']!='PENDING':
            raise GuardError('Reservasi hasil tidak ditemukan. Jangan mengulang panggilan.')
        evidence=json.loads(row['inputs_json']);amount=evidence['reserved_micros']
        if not_sent:amount=0
        elif usage is not None:
            if (not isinstance(usage,dict) or type(usage.get('input_tokens'))!=int or type(usage.get('output_tokens'))!=int
                or not 0<usage['input_tokens']<=INPUT_BOUND or not 0<=usage['output_tokens']<=OUTPUT_BOUND):
                invariant_ok=False
            else:
                counted=cost_micros(evidence['rate_policy'],usage['input_tokens'],usage['output_tokens'])
                if counted>amount:invariant_ok=False
                else:amount=counted;evidence['usage']={k:usage[k] for k in ('input_tokens','output_tokens')}
        if not invariant_ok:
            outcome='ERROR';message='Protocol biaya/model tidak sesuai. Reservasi ditahan; analisis berikutnya diblokir untuk peninjauan.'
            amount=evidence['reserved_micros'];decision=None
        evidence.update(cost_upper_micros=amount,accounting_ok=invariant_ok,decision=decision,finished_at=store.stamp())
        store.query(conn,'UPDATE kilas_trading_events SET outcome=?,message=?,inputs_json=? WHERE id=? AND user_id=?',
                    (outcome,message,json.dumps(evidence),row['id'],user))
        row.update(outcome=outcome,message=message,inputs_json=json.dumps(evidence))
        return result(row)
