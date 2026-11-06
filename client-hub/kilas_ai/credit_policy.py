"""Disabled-by-default product admission. No proposed tariff is a default.

Provider funding/safety gates remain independent. Callers must supply a digest of
server-resolved immutable inputs and an explicit authorized spending ceiling.
Only operations admitted here are settled here, even if activation is later off.
"""
import hashlib
import json
import os
import secrets
from datetime import timedelta
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


def lock_account_in(conn,user):
    # Serialize admission and settlement across every feature and session.
    suffix=' FOR UPDATE' if db.BACKEND=='postgres' else ''
    if not usage._query(conn,'SELECT id FROM users WHERE id=?'+suffix,(user,),one=True):raise wallet.WalletError('account_not_found')


def _ceil(n,d):return (n+d-1)//d


def remaining_in(conn,user,feature,now):
    if feature not in FREE:return 0
    daily,monthly=FREE[feature]
    def used(start):
        rows=usage._rows(conn,"SELECT free_reserved,free_actual,status FROM kilas_credit_admissions WHERE user_id=? AND feature=? AND source IN ('FREE','SPLIT')"+(' AND created_at>=?' if start else ''),(user,feature,start.isoformat()) if start else (user,feature))
        return sum(r[0] if r[2]=='RESERVED' else (r[1] or 0) if r[2]=='CAPTURED' else 0 for r in rows)
    if feature=='IMAGE':return max(0,monthly-used(None)-historical_in(conn,user,feature,None))
    day=now.replace(hour=0,minute=0,second=0,microsecond=0)
    month=day.replace(day=1)
    return max(0,min(daily-used(day)-historical_in(conn,user,feature,day),monthly-used(month)-historical_in(conn,user,feature,month)))


class ConsentRequired(wallet.WalletError):
    def __init__(self,token):
        super().__init__('credit_consent_required')
        self.token=token


def _quote(conn,user,key,feature,maximum_units,digest,priced_units,pricing_feature=None):
    source='OWNER' if owner(conn,user) else 'FREE'
    available=remaining_in(conn,user,feature,usage._now())
    free=min(maximum_units,available) if source!='OWNER' else maximum_units
    priced=0;rate=0;unit=1;allocation='units'
    if source!='OWNER' and free<maximum_units:
        rate,unit=_rate(pricing_feature or feature)
        if feature=='VOICE':
            config=json.loads(os.environ.get('KILAS_CREDIT_TARIFFS_JSON','{}'))
            if config.get('voice_allocation')!='proportional_actual_duration':raise wallet.WalletError('voice_allocation_unapproved')
            priced=wallet._amount(priced_units)
            allocation='voice_characters'
        else:priced=maximum_units-free
        source='SPLIT' if free else 'PAID'
    maximum_charge=_ceil(priced*rate,unit)
    if feature=='WORK':
        from .credit_work_steps import terms
        terms(pricing_feature)
    return {'source':source,'free':free,'priced':priced,'rate':rate,'unit':unit,'charge':maximum_charge,'allocation':allocation,'pricing_feature':pricing_feature or feature,'output_ratio_milli':json.loads(os.environ.get('KILAS_CREDIT_TARIFFS_JSON','{}')).get('limits',{}).get(pricing_feature or 'TRANSLATOR',{}).get('output_ratio_milli') if feature=='TRANSLATOR' else None}


def _consent(conn,user,key,feature,maximum_units,digest,q,*,consume=True):
    quote_hash=fingerprint({'feature':feature,'maximum_units':maximum_units,'fingerprint':digest,**q})
    now=usage._now()
    old=usage._query(conn,'SELECT token,status,expires_at,fingerprint FROM kilas_credit_consents WHERE user_id=? AND operation_key=? AND quote_hash=?',(user,key,quote_hash),one=True)
    if old:
        if old[3]!=digest:raise wallet.WalletError('idempotency_conflict')
        if usage._as_utc(old[2])<=now:raise wallet.WalletError('credit_quote_expired')
        if old[1]=='APPROVED':
            if not consume:return old[0]
            usage._query(conn,"UPDATE kilas_credit_consents SET status='CONSUMED' WHERE token=?",(old[0],))
            return
        if old[1] in ('DECLINED','CONSUMED'):raise wallet.WalletError('credit_consent_declined')
        error=ConsentRequired(old[0]);error.request=(user,key,feature,maximum_units,digest,q);raise error
    token=secrets.token_hex(32)
    usage._query(conn,"INSERT INTO kilas_credit_consents(token,user_id,operation_key,fingerprint,quote_hash,feature,maximum_units,free_units,maximum_charge,terms_json,status,expires_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,'PENDING',?,?)",
                 (token,user,key,digest,quote_hash,feature,maximum_units,q['free'],q['charge'],json.dumps(q,sort_keys=True),(now+timedelta(minutes=20)).isoformat(),now.isoformat()))
    error=ConsentRequired(token);error.request=(user,key,feature,maximum_units,digest,q);raise error


def admit_in(conn,user,key,feature,maximum_units,digest,*,spending_ceiling=0,priced_units=None,require_consent=True,pricing_feature=None):
    if feature not in ('CHAT','IMAGE','VOICE','TRANSLATOR','RECEIPT','WORK'):raise wallet.WalletError('feature_unpriced')
    lock_account_in(conn,user)
    key=wallet._key(key);maximum_units=wallet._amount(maximum_units)
    wallet._amount(spending_ceiling,zero=True)
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise wallet.WalletError('invalid_fingerprint')
    old=usage._query(conn,'SELECT feature,maximum_units,fingerprint,status,priced_max FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(user,key),one=True)
    if old:
        if tuple(old[:3])!=(feature,maximum_units,digest) or (feature=='VOICE' and priced_units is not None and old[4] not in (0,priced_units)):raise wallet.WalletError('idempotency_conflict')
        return {'dispatch':False,'status':old[3]}
    if not enabled():raise wallet.WalletError('credit_policy_disabled')
    from . import credit_activation
    credit_activation.gate_in(conn,user)
    if pricing_feature not in (None,'INTERPRETER','WORK_TEXT','WORK_WEB','WORK_WATCH','WORK_DOCUMENT','WORK_CODE','WORK_PROJECT'):raise wallet.WalletError('invalid_pricing_feature')
    if pricing_feature and feature!=('WORK' if pricing_feature.startswith('WORK_') else 'TRANSLATOR'):raise wallet.WalletError('invalid_pricing_feature')
    q=_quote(conn,user,key,feature,maximum_units,digest,priced_units,pricing_feature)
    if q['charge']:
        if wallet._totals(conn,user)['available_milli']<q['charge']:raise wallet.WalletError('insufficient_credit')
        if require_consent:_consent(conn,user,key,feature,maximum_units,digest,q)
        elif q['charge']>spending_ceiling:raise wallet.WalletError('credit_consent_required')
        wallet.reserve_in(conn,user,key,q['charge'],fingerprint=digest)
    usage._query(conn,"INSERT INTO kilas_credit_admissions(user_id,operation_key,feature,maximum_units,fingerprint,source,rate_milli,rate_units,maximum_charge,free_reserved,priced_max,allocation,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'RESERVED',?)",
                 (user,key,feature,maximum_units,digest,q['source'],q['rate'],q['unit'],q['charge'],q['free'],q['priced'],q['allocation'],usage._now().isoformat()))
    return {'dispatch':True,'status':'RESERVED','source':q['source'],'maximum_charge':q['charge']}


def finish_in(conn,user,key,actual_units,*,success,definitive_failure=False):
    lock_account_in(conn,user)
    row=usage._query(conn,'SELECT maximum_units,source,rate_milli,rate_units,status,actual_units,free_reserved,priced_max,allocation FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(user,key),one=True)
    if not row:return False
    if not success and not definitive_failure:return True
    actual_units=wallet._amount(actual_units,zero=True)
    if actual_units>row[0]:raise wallet.WalletError('meter_exceeds_reservation')
    target='CAPTURED' if success else 'RELEASED'
    if row[4]!='RESERVED':
        if row[4]!=target or (success and row[5]!=actual_units):raise wallet.WalletError('settlement_conflict')
        return True
    free=min(actual_units,row[6]) if success else 0
    paid=max(0,actual_units-free) if success and row[1]!='OWNER' else 0
    priced=(_ceil(row[7]*paid,actual_units) if actual_units else 0) if row[8]=='voice_characters' else paid
    if row[1] in ('PAID','SPLIT'):
        if success:wallet.settle_in(conn,user,key,_ceil(priced*row[2],row[3]))
        else:wallet.release_in(conn,user,key)
    usage._query(conn,'UPDATE kilas_credit_admissions SET status=?,actual_units=?,free_actual=?,priced_actual=?,finished_at=? WHERE user_id=? AND operation_key=?',(target,actual_units if success else 0,free,priced,usage._now().isoformat(),user,key))
    return True


def admit(user,key,feature,maximum_units,digest,*,spending_ceiling=0,priced_units=None,require_consent=True,pricing_feature=None):
    # Persist only the quote on a consent response; no usage/provider dispatch.
    with wallet._locked(user) as conn:
        try:return admit_in(conn,user,key,feature,maximum_units,digest,spending_ceiling=spending_ceiling,priced_units=priced_units,require_consent=require_consent,pricing_feature=pricing_feature)
        except ConsentRequired as error:
            pending=error
    raise pending


def finish(user,key,actual_units,*,success,definitive_failure=False):
    with wallet._locked(user) as conn:
        return finish_in(conn,user,key,actual_units,success=success,definitive_failure=definitive_failure)


def installed(conn):
    if db.BACKEND=='postgres':
        return bool(usage._query(conn,"SELECT to_regclass('kilas_credit_admissions')",one=True)[0])
    return bool(usage._query(conn,"SELECT name FROM sqlite_master WHERE type='table' AND name='kilas_credit_admissions'",one=True))


def historical_in(conn,user,feature,start):
    from . import credit_activation
    baseline=credit_activation.baseline_in(conn,user,feature,start)
    if baseline:
        units,cutoff=baseline
        return units+historical_raw_in(conn,user,feature,max(start,cutoff) if start else cutoff)
    return historical_raw_in(conn,user,feature,start)


def historical_raw_in(conn,user,feature,start,end=None):
    # Read successful pre-wallet usage; never create retroactive debits or reset
    # lifetime trials. Newly admitted operations are excluded to avoid double count.
    if feature in ('VOICE','TRANSLATOR') and table_exists(conn,'kilas_audio_jobs'):
        field='actual_ms' if feature=='VOICE' else 'source_ms'
        mode='voiceover' if feature=='VOICE' else 'translate'
        sql=f"SELECT COALESCE(SUM(j.{field}),0) FROM kilas_audio_jobs j WHERE j.user_id=? AND j.mode=? AND j.status='COMPLETED'"
        args=(user,mode)
        if feature=='VOICE':
            sql+=" AND j.content_origin!='live_session'"
            if table_exists(conn,'kilas_live_translator_turns') and table_exists(conn,'kilas_live_translator_sessions'):
                sql+=" AND NOT EXISTS (SELECT 1 FROM kilas_live_translator_turns t JOIN kilas_live_translator_sessions s ON s.id=t.session_id WHERE s.user_id=j.user_id AND t.audio_job_id=j.id)"
        if table_exists(conn,'kilas_credit_audio_links'):
            sql+=" AND NOT EXISTS (SELECT 1 FROM kilas_credit_audio_links l WHERE l.user_id=j.user_id AND l.job_id=j.id)"
        if start:sql+=' AND j.created_at>=?';args+=(start.isoformat(),)
        if end:sql+=' AND j.created_at<?';args+=(end.isoformat(),)
        return usage._query(conn,sql,args,one=True)[0]
    if feature not in ('CHAT','IMAGE') or not table_exists(conn,'kilas_ai_usage'):return 0
    clause="u.operation_type='CHAT'" if feature=='CHAT' else "u.operation_type IN ('IMAGE_GENERATION','IMAGE_EDIT')"
    sql="SELECT COUNT(*) FROM kilas_ai_usage u WHERE u.user_id=? AND u.status='COMPLETE' AND "+clause+" AND NOT EXISTS (SELECT 1 FROM kilas_credit_admissions a WHERE a.user_id=u.user_id AND a.operation_key=u.operation_key)"
    args=(user,)
    if feature=='CHAT' and table_exists(conn,'kilas_credit_translation_links'):sql+=' AND NOT EXISTS (SELECT 1 FROM kilas_credit_translation_links l WHERE l.user_id=u.user_id AND l.operation_key=u.operation_key)'
    if table_exists(conn,'kilas_credit_work_usage'):sql+=' AND NOT EXISTS (SELECT 1 FROM kilas_credit_work_usage w WHERE w.user_id=u.user_id AND w.operation_key=u.operation_key)'
    if start:sql+=' AND u.created_at>=?';args+=(start.isoformat(),)
    if end:sql+=' AND u.created_at<?';args+=(end.isoformat(),)
    if feature=='CHAT':sql+=usage._chat_only_sql()
    return usage._query(conn,sql,args,one=True)[0]


def table_exists(conn,name):
    if name not in ('kilas_credit_admissions','kilas_agent_jobs','kilas_vo_stt_operations','kilas_ai_subscriptions','kilas_ai_usage','kilas_credit_audio_links','kilas_credit_translation_links','kilas_audio_jobs','kilas_live_translator_turns','kilas_live_translator_sessions','kilas_credit_interpreter_sessions','kilas_credit_interpreter_turns','kilas_credit_work_waits','kilas_credit_work_usage','kilas_credit_work_operations','kilas_credit_activation','kilas_credit_activation_payload','kilas_credit_quota_baselines'):raise ValueError('invalid_table')
    if db.BACKEND=='postgres':
        row=usage._query(conn,'SELECT to_regclass(?)',(name,),one=True)
        return bool(row and row[0])
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
        elif feature in ('CHAT','RECEIPT'):
            if (profile.get('model') not in limits['models'] or profile.get('output_tokens',0)>limits['output_tokens']
                    or profile.get('input_token_bound',0)>limits['input_tokens']):raise ValueError()
            if feature=='RECEIPT':
                from .credit_receipts import CONTRACT
                if (profile.get('receipt_bytes',0)>limits['bytes'] or profile.get('input_accounting')!=CONTRACT
                        or limits.get('input_accounting_verified')!=CONTRACT):raise ValueError()
        elif feature=='VOICE':
            if (profile['model'] not in limits['models'] or profile['characters']>limits['characters']
                    or profile['output_ms']>limits['output_ms']):raise ValueError()
        elif feature=='TRANSLATOR':
            if profile['model'] not in limits['models'] or profile['source_ms']>limits['source_ms']:raise ValueError()
    except (ValueError,KeyError,TypeError):raise wallet.WalletError('credit_request_outside_approved_bounds') from None


def consent_in(conn,user,token,approve):
    row=usage._query(conn,'SELECT status,expires_at FROM kilas_credit_consents WHERE token=? AND user_id=?',(token,user),one=True)
    if not row:raise wallet.WalletError('consent_not_found')
    if usage._as_utc(row[1])<=usage._now():raise wallet.WalletError('credit_quote_expired')
    target='APPROVED' if approve else 'DECLINED'
    if row[0]==target:return target
    if row[0]!='PENDING':raise wallet.WalletError('consent_closed')
    usage._query(conn,'UPDATE kilas_credit_consents SET status=?,decided_at=? WHERE token=? AND user_id=?',(target,usage._now().isoformat(),token,user))
    return target


def consent(user,token,approve):
    with wallet._locked(user) as conn:return consent_in(conn,user,token,approve)

def reconcile(user,key,reviewer,outcome,actual_units,evidence):
    if outcome not in ('DELIVERED','NOT_DELIVERED') or not isinstance(evidence,str) or not 10<=len(evidence)<=1000:raise wallet.WalletError('reconciliation_evidence_required')
    actual_units=wallet._amount(actual_units,zero=True)
    if outcome=='NOT_DELIVERED' and actual_units:raise wallet.WalletError('reconciliation_units_conflict')
    with wallet._locked(user) as conn:
        role=usage._query(conn,'SELECT role FROM users WHERE id=?',(reviewer,),one=True)
        if not role or role[0]!='KILAS_ADMIN' or user==reviewer:raise wallet.WalletError('reconciliation_forbidden')
        old=usage._query(conn,'SELECT outcome,actual_units,evidence FROM kilas_credit_reconciliations WHERE user_id=? AND operation_key=?',(user,key),one=True)
        if old:
            if tuple(old)!=(outcome,actual_units,evidence):raise wallet.WalletError('reconciliation_conflict')
            return
        admission=usage._query(conn,'SELECT status FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(user,key),one=True)
        if not admission or admission[0]!='RESERVED':raise wallet.WalletError('not_reconcilable')
        if table_exists(conn,'kilas_audio_jobs') and table_exists(conn,'kilas_credit_audio_links'):
            active=usage._query(conn,"SELECT 1 FROM kilas_audio_jobs j JOIN kilas_credit_audio_links l ON l.job_id=j.id AND l.user_id=j.user_id WHERE l.user_id=? AND l.operation_key=? AND j.status IN ('QUEUED','PROCESSING')",(user,key),one=True)
            if active:raise wallet.WalletError('reconciliation_operation_still_active')
        if table_exists(conn,'kilas_live_translator_turns') and table_exists(conn,'kilas_live_translator_sessions'):
            active=usage._query(conn,"SELECT 1 FROM kilas_live_translator_turns t JOIN kilas_live_translator_sessions s ON s.id=t.session_id WHERE s.user_id=? AND t.operation_key=? AND t.status='PROCESSING'",(user,key),one=True)
            if active:raise wallet.WalletError('reconciliation_operation_still_active')
        if table_exists(conn,'kilas_credit_interpreter_turns') and usage._query(conn,"SELECT 1 FROM kilas_credit_interpreter_turns WHERE user_id=? AND operation_key=? AND status='ACTIVE'",(user,key),one=True):raise wallet.WalletError('reconciliation_operation_still_active')
        if table_exists(conn,'kilas_agent_jobs') and table_exists(conn,'kilas_credit_work_operations') and usage._query(conn,"SELECT 1 FROM kilas_credit_work_operations w JOIN kilas_agent_jobs j ON j.id=w.job_id AND j.user_id=w.user_id WHERE w.user_id=? AND w.operation_key=? AND j.status IN ('PLANNING','RUNNING','WAITING','NEEDS_APPROVAL','PAUSED')",(user,key),one=True):raise wallet.WalletError('reconciliation_operation_still_active')
        if table_exists(conn,'kilas_ai_usage') and usage._query(conn,"SELECT 1 FROM kilas_ai_usage WHERE user_id=? AND operation_key=? AND status='PENDING'",(user,key),one=True):raise wallet.WalletError('reconciliation_operation_still_active')
        finish_in(conn,user,key,actual_units,success=outcome=='DELIVERED',definitive_failure=True)
        priced=usage._query(conn,'SELECT priced_actual FROM kilas_credit_admissions WHERE user_id=? AND operation_key=?',(user,key),one=True)[0]
        usage._query(conn,'INSERT INTO kilas_credit_reconciliations(user_id,operation_key,reviewer,outcome,actual_units,priced_actual,evidence,created_at) VALUES (?,?,?,?,?,?,?,?)',(user,key,reviewer,outcome,actual_units,priced,evidence,usage._now().isoformat()))


def persist_consent(error):
    request=error.request
    with wallet._locked(request[0]) as conn:
        try:token=_consent(conn,*request,consume=False)
        except ConsentRequired as pending:token=pending.token
    return token
