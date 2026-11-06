"""Disabled-by-default product admission. No proposed tariff is a default.

Provider funding/safety gates remain independent. Callers must supply a digest of
server-resolved immutable inputs and an explicit authorized spending ceiling.
Only operations admitted here are settled here, even if activation is later off.
"""
import hashlib
import json
import os
import db
from . import usage, credit_wallet as wallet

OWNER_ID = 9
OWNER_EMAIL = 'irvankarnavi@gmail.com'
FREE = {'CHAT':(70,500),'IMAGE':(None,1),'VOICE':(60000,300000),'TRANSLATOR':(180000,900000)}


def enabled():
    return os.environ.get('KILAS_CREDIT_ENFORCEMENT_ENABLED') == 'yes'


def owner(conn,user):
    if type(user) is not int or user != OWNER_ID:return False
    row=usage._query(conn,'SELECT email,role FROM users WHERE id=?',(user,),one=True)
    return bool(row and str(row[0]).strip().casefold()==OWNER_EMAIL and row[1]=='CLIENT_OWNER')


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _rate(feature):
    # Runtime configuration is only installed after the separate tariff approval.
    try:
        config=json.loads(os.environ.get('KILAS_CREDIT_TARIFFS_JSON','{}'))
        if config.get('version') != 'customer-credit-v1':raise ValueError()
        item=config['rates'][feature]
        milli=wallet._amount(item['milli']);unit=wallet._amount(item['units'])
        return milli,unit
    except (KeyError,TypeError,ValueError,json.JSONDecodeError):
        raise wallet.WalletError('tariff_not_approved') from None


def _ceil(n,d):return (n+d-1)//d


def remaining_in(conn,user,feature,now):
    if feature not in FREE:return 0
    daily,monthly=FREE[feature]
    def used(start):
        rows=usage._rows(conn,"SELECT maximum_units,actual_units,status FROM kilas_credit_admissions WHERE user_id=? AND feature=? AND source='FREE'"+(' AND created_at>=?' if start else ''),(user,feature,start.isoformat()) if start else (user,feature))
        return sum(r[0] if r[2]=='RESERVED' else (r[1] or 0) if r[2]=='CAPTURED' else 0 for r in rows)
    if feature=='IMAGE':return max(0,monthly-used(None)-historical_in(conn,user,feature,None))
    day=now.replace(hour=0,minute=0,second=0,microsecond=0)
    month=day.replace(day=1)
    return max(0,min(daily-used(day)-historical_in(conn,user,feature,day),monthly-used(month)-historical_in(conn,user,feature,month)))


def admit_in(conn,user,key,feature,maximum_units,digest,*,spending_ceiling=0):
    if feature not in ('CHAT','IMAGE','VOICE','TRANSLATOR','RECEIPT'):raise wallet.WalletError('feature_unpriced')
    key=wallet._key(key);maximum_units=wallet._amount(maximum_units)
    wallet._amount(spending_ceiling,zero=True)
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise wallet.WalletError('invalid_fingerprint')
    old=usage._query(conn,'SELECT feature,maximum_units,fingerprint,status FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(user,key),one=True)
    if old:
        if tuple(old[:3])!=(feature,maximum_units,digest):raise wallet.WalletError('idempotency_conflict')
        # Caller MUST return/reload the existing result, never redispatch.
        return {'dispatch':False,'status':old[3]}
    if not enabled():raise wallet.WalletError('credit_policy_disabled')
    source='OWNER' if owner(conn,user) else 'FREE'
    rate=0;unit=1;maximum_charge=0
    available=remaining_in(conn,user,feature,usage._now())
    if source!='OWNER' and maximum_units>available:
        if available and feature in ('VOICE','TRANSLATOR'):
            raise wallet.WalletError('free_partial_quote_required')
        if feature=='VOICE':raise wallet.WalletError('voice_character_quote_required')
        rate,unit=_rate(feature)
        maximum_charge=_ceil(maximum_units*rate,unit)
        if maximum_charge>spending_ceiling:raise wallet.WalletError('credit_consent_required')
        source='PAID'
        wallet.reserve_in(conn,user,key,maximum_charge,fingerprint=digest)
    usage._query(conn,"INSERT INTO kilas_credit_admissions(user_id,operation_key,feature,maximum_units,fingerprint,source,rate_milli,rate_units,maximum_charge,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,'RESERVED',?)",
                 (user,key,feature,maximum_units,digest,source,rate,unit,maximum_charge,usage._now().isoformat()))
    return {'dispatch':True,'status':'RESERVED','source':source,'maximum_charge':maximum_charge}


def finish_in(conn,user,key,actual_units,*,success,definitive_failure=False):
    row=usage._query(conn,'SELECT maximum_units,source,rate_milli,rate_units,status,actual_units FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(user,key),one=True)
    if not row:return False
    if not success and not definitive_failure:
        # Ambiguous provider result remains held for explicit reconciliation.
        return True
    actual_units=wallet._amount(actual_units,zero=True)
    if actual_units>row[0]:raise wallet.WalletError('meter_exceeds_reservation')
    target='CAPTURED' if success else 'RELEASED'
    if row[4]!='RESERVED':
        if row[4]!=target or (success and row[5]!=actual_units):raise wallet.WalletError('settlement_conflict')
        return True
    if row[1]=='PAID':
        if success:wallet.settle_in(conn,user,key,_ceil(actual_units*row[2],row[3]))
        else:wallet.release_in(conn,user,key)
    usage._query(conn,'UPDATE kilas_credit_admissions SET status=?,actual_units=?,finished_at=? WHERE user_id=? AND operation_key=?',(target,actual_units if success else 0,usage._now().isoformat(),user,key))
    return True


def admit(user,key,feature,maximum_units,digest,*,spending_ceiling=0):
    with wallet._locked(user) as conn:
        return admit_in(conn,user,key,feature,maximum_units,digest,spending_ceiling=spending_ceiling)


def finish(user,key,actual_units,*,success,definitive_failure=False):
    with wallet._locked(user) as conn:
        return finish_in(conn,user,key,actual_units,success=success,definitive_failure=definitive_failure)


def installed(conn):
    if db.BACKEND=='postgres':
        return bool(usage._query(conn,"SELECT to_regclass('kilas_credit_admissions')",one=True)[0])
    return bool(usage._query(conn,"SELECT name FROM sqlite_master WHERE type='table' AND name='kilas_credit_admissions'",one=True))


def historical_in(conn,user,feature,start):
    # Read successful pre-wallet usage; never create retroactive debits or reset
    # lifetime trials. Newly admitted operations are excluded to avoid double count.
    if feature not in ('CHAT','IMAGE') or not table_exists(conn,'kilas_ai_usage'):return 0
    clause="u.operation_type='CHAT'" if feature=='CHAT' else "u.operation_type IN ('IMAGE_GENERATION','IMAGE_EDIT')"
    sql="SELECT COUNT(*) FROM kilas_ai_usage u WHERE u.user_id=? AND u.status='COMPLETE' AND "+clause+" AND NOT EXISTS (SELECT 1 FROM kilas_credit_admissions a WHERE a.user_id=u.user_id AND a.operation_key=u.operation_key)"
    args=(user,)
    if start:sql+=' AND u.created_at>=?';args+=(start.isoformat(),)
    if feature=='CHAT':sql+=usage._chat_only_sql()
    return usage._query(conn,sql,args,one=True)[0]


def table_exists(conn,name):
    if name not in ('kilas_credit_admissions','kilas_ai_usage'):raise ValueError('invalid_table')
    if db.BACKEND=='postgres':return bool(usage._query(conn,'SELECT to_regclass(?)',(name,),one=True)[0])
    return bool(usage._query(conn,"SELECT name FROM sqlite_master WHERE type='table' AND name=?",(name,),one=True))


def validate_request(conn,user,feature,profile):
    if owner(conn,user):return
    try:
        config=json.loads(os.environ.get('KILAS_CREDIT_TARIFFS_JSON','{}'))
        limits=config['limits'][feature]
        if config['version']!='customer-credit-v1':raise ValueError()
        if feature=='IMAGE':
            from . import image_options
            model=profile.get('image_model')
            options=image_options.resolve(model,profile.get('image_prompt',''))
            if (model not in limits['models'] or options['quality'] not in limits['qualities']
                    or options['size'] not in limits['sizes'] or len(profile.get('image_prompt',''))>limits['prompt_chars']):raise ValueError()
        elif feature=='CHAT':
            if (profile.get('model') not in limits['models'] or profile.get('output_tokens',0)>limits['output_tokens']
                    or profile.get('input_token_bound',0)>limits['input_tokens']):raise ValueError()
    except (ValueError,KeyError,TypeError):raise wallet.WalletError('credit_request_outside_approved_bounds') from None
