"""Explicit one-attempt qualification. No flag-only activation or automatic retry."""
import hashlib,json,os,secrets,subprocess,sys,time
import db
from urllib.parse import parse_qs,urlsplit
from datetime import datetime,timezone
from threading import Thread,Timer
from . import audio_transcription_budget as budget,live_translator_realtime_account as account,usage
from .autonomous_store import transaction

APPROVAL='approved-realtime-20261013-044844-v1'
PRICE='elevenlabs-realtime-public-039usd-hour-10s-check-v1'
OPERATION='live-realtime-check-20261013-v1'
RESERVE=1084
SOURCE=hashlib.sha256(b'kilas-tone-440hz-1200-int16le-16000hz-80000-v1').hexdigest()

def stamp():return datetime.now(timezone.utc).isoformat()
def digest():return hashlib.sha256(os.environ.get('ELEVENLABS_API_KEY','').strip().encode()).hexdigest()

def subscription():
    value=account._get('user/subscription')
    used,limit=value.get('character_count'),value.get('character_limit')
    if not(value.get('tier')=='creator' and value.get('status')=='active' and type(value.get('max_credit_limit_extension')) is int and value['max_credit_limit_extension']==0 and value.get('allowed_to_extend_character_limit') is False and value.get('can_extend_character_limit') is False and type(used) is int and type(limit) is int and 0<=used<limit<=1000000000000):raise ValueError('billing_unsafe')
    if 'current_overage' in value and not account.zero_overage(value['current_overage']):raise ValueError('billing_unsafe')
    return {'used':used,'limit':limit,'overage_zero':account.zero_overage(value.get('current_overage')),'overage_currency':'usd' if isinstance(value.get('current_overage'),dict) else 'legacy_numeric' if 'current_overage' in value else 'not_supplied'}

def quiet(conn,exclude=''):
    # Observe only; never cancel another user's work. External activity is checked
    # separately against authenticated workspace request analytics.
    if usage._query(conn,"SELECT COUNT(*) FROM kilas_vo_stt_operations WHERE status IN ('RESERVED','DISPATCHED') AND operation_key<>?",(exclude,),one=True)[0]:return False
    if usage._query(conn,"SELECT COUNT(*) FROM kilas_audio_jobs WHERE status IN ('QUEUED','PROCESSING')",one=True)[0]:return False
    if usage._query(conn,"SELECT COUNT(*) FROM kilas_live_translator_turns WHERE status='PROCESSING'",one=True)[0]:return False
    return True

def claim(before,window_start_ms=None):
    window_start_ms=window_start_ms if type(window_start_ms) is int else int(datetime.now(timezone.utc).timestamp()*1000)
    base=budget.policy()
    if not base or not budget.configured() or base['allowed_owner'] is None or len(base['id'])>71:raise ValueError('policy_unavailable')
    policy={**base,'base_id':base['id'],'id':base['id']+'-rt-check','price_version':PRICE}
    owner=base['allowed_owner']
    with transaction() as conn:
        budget._global_lock(conn)
        if usage._query(conn,'SELECT approval FROM kilas_realtime_checks WHERE approval=?',(APPROVAL,),one=True):return None
        budget._campaign(conn,policy);budget._owner(conn,owner);budget._expire(conn,campaign=base['id'])
        if not quiet(conn):raise ValueError('service_busy')
        budget._admit(conn,owner,policy,RESERVE,OPERATION)
        lease=secrets.token_hex(32);now=stamp()
        # Atomic approval + allowance commit BEFORE the possible paid child launch.
        usage._query(conn,"INSERT INTO kilas_vo_stt_operations(user_id,operation_key,campaign,fingerprint,status,charge_micro,duration_ms,lease_digest,created_at,dispatched_at) VALUES (?,?,?,?,'DISPATCHED',?,10000,?,?,?)",(owner,OPERATION,policy['id'],SOURCE,RESERVE,budget._hash(lease),now,now))
        usage._query(conn,"INSERT INTO kilas_realtime_checks(approval,user_id,key_digest,campaign,source_digest,model,status,expected_pcm_ms,before_used,before_limit,before_overage_kind,window_start_ms,result,created_at) VALUES (?,?,?,?,?,?,'DISPATCHED',5000,?,?,?,?,'pending',?)",(APPROVAL,owner,digest(),policy['id'],SOURCE,account.MODEL,before['used'],before['limit'],before.get('overage_currency','not_supplied'),window_start_ms,now))
    return owner

def wire():
    started=time.monotonic();child=None;expired=False
    def kill():
        nonlocal expired
        expired=True
        if child is not None:
            try:child.kill()
            except OSError:pass
    timer=Timer(9.8,kill);timer.daemon=True;timer.start()
    try:
        # Server secret stays in this server-only child environment, never argv/
        # client/logs. Child SIGALRM also survives parent worker death.
        env={'ELEVENLABS_API_KEY':os.environ['ELEVENLABS_API_KEY'],'PYTHONPATH':os.path.dirname(os.path.dirname(__file__)),'PATH':os.environ.get('PATH',''),'PYTHONDONTWRITEBYTECODE':'1'}
        child=subprocess.Popen([sys.executable,'-B','-m','kilas_ai.live_translator_realtime_check_wire'],env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        if expired:kill()
        try:raw,_=child.communicate(timeout=max(.01,9.8-(time.monotonic()-started)))
        except subprocess.TimeoutExpired:kill();raw,_=child.communicate(timeout=1)
        if len(raw)>4096:raise ValueError('wire_output_invalid')
        result={'accepted':False,'result':'deadline_unknown','stable_characters':0,'sent_pcm_ms':0}
        for line in raw.splitlines():
            value=json.loads(line)
            if type(value.get('accepted')) is bool:result['accepted']=value['accepted']
            if value.get('result') in ('committed','config_invalid','provider_rejected','connection_unknown','response_invalid','provider_http_400','provider_http_401','provider_http_402','provider_http_403','provider_http_404','provider_http_429'):result['result']=value['result']
            if type(value.get('sent_pcm_ms')) is int and 0<=value['sent_pcm_ms']<=5000:result['sent_pcm_ms']=value['sent_pcm_ms']
            if type(value.get('stable_characters')) is int and 0<=value['stable_characters']<=4000:result['stable_characters']=value['stable_characters']
        result['wire_process_ms']=round((time.monotonic()-started)*1000)
        return result
    finally:
        kill();timer.cancel()

def attributed(start_ms,end_ms,committed=False):
    # Sanitized shape evidence only; raw values/rows/IDs never leave the server.
    flags={'row_count':0,'readonly_row_count':0,'candidate_count':0}
    def outcome(reason,accepted=False):
        print('KILAS_REALTIME_ATTRIBUTION '+json.dumps({**flags,'reason':reason,'attributed':accepted},sort_keys=True),flush=True)
        return accepted
    from . import live_translator_transport as transport
    with transport.post('https://api.elevenlabs.io/v1/workspace/analytics/requests',headers={'xi-api-key':os.environ['ELEVENLABS_API_KEY'].strip()},json={'start_time':start_ms,'end_time':end_ms,'limit':100},timeout=(2,3),stream=True,allow_redirects=False) as response:
        flags['http_status']=response.status_code if type(response.status_code) is int and 100<=response.status_code<=599 else 0
        if response.status_code!=200:return outcome('analytics_http')
        raw=bytearray();deadline=time.monotonic()+6
        for part in response.iter_content(8192):
            raw.extend(part)
            if len(raw)>262144 or time.monotonic()>deadline:return outcome('analytics_bounds')
        value=json.loads(raw)
    cols,rows=value.get('columns'),value.get('rows')
    if not isinstance(cols,list) or not isinstance(rows,list) or len(rows)>=100 or len(cols)>64 or any(not isinstance(c,str) for c in cols) or len(set(cols))!=len(cols):return outcome('analytics_schema')
    flags['row_count']=len(rows)
    if any(not isinstance(r,list) or len(r)!=len(cols) for r in rows):return outcome('analytics_schema')
    if not all(c in cols for c in ('path','query','timestamp','response_code')):return outcome('required_columns_missing')
    records=[dict(zip(cols,r)) for r in rows]
    readonly={'/v1/user/subscription','/v1/models','/v1/workspace/analytics/requests'}
    flags['readonly_row_count']=sum(isinstance(r['path'],str) and r['path'] in readonly for r in records)
    flags['exact_realtime_count']=sum(r['path']=='/v1/speech-to-text/realtime' for r in records)
    flags['fixed_origin_realtime_count']=0;flags['parsed_readonly_path_count']=0
    for record in records:
        if not isinstance(record['path'],str):continue
        try:
            parsed=urlsplit(record['path'])
            fixed=parsed.scheme in ('https','wss') and parsed.netloc=='api.elevenlabs.io'
            flags['fixed_origin_realtime_count']+=int(fixed and parsed.path=='/v1/speech-to-text/realtime')
            flags['parsed_readonly_path_count']+=int((fixed or not parsed.scheme and not parsed.netloc) and parsed.path in readonly)
        except ValueError:pass
    records=[r for r in records if not isinstance(r['path'],str) or r['path'] not in readonly];flags['candidate_count']=len(records)
    if len(records)!=1:return outcome('candidate_count')
    row=records[0];when=row['timestamp'];query=row['query'];path=row['path']
    kind=lambda x:'string' if isinstance(x,str) else 'integer' if type(x) is int else 'float' if type(x) is float else 'object' if isinstance(x,dict) else 'array' if isinstance(x,list) else 'null' if x is None else 'other'
    flags.update(timestamp_type=kind(when),query_type=kind(query),response_code_type=kind(row['response_code']),exact_path=path=='/v1/speech-to-text/realtime',response_http=row['response_code'] if type(row['response_code']) is int and 100<=row['response_code']<=599 else 0,response_code=row['response_code'] if type(row['response_code']) is int and -999<=row['response_code']<=4999 else None,committed_wire=committed is True)
    if isinstance(path,str):
        parsed=urlsplit(path);flags['fixed_origin_realtime_path']=parsed.scheme in ('https','wss') and parsed.netloc=='api.elevenlabs.io' and parsed.path=='/v1/speech-to-text/realtime'
    flags['query_model_key']=isinstance(query,str) and 'model_id' in parse_qs(query.lstrip('?'))
    flags['query_model_match']=isinstance(query,str) and parse_qs(query.lstrip('?')).get('model_id')==[account.MODEL]
    flags['query_json_object']=False;flags['query_json_model_match']=False
    if isinstance(query,str):
        try:
            q=json.loads(query);flags['query_json_object']=isinstance(q,dict);flags['query_json_model_match']=isinstance(q,dict) and q.get('model_id')==account.MODEL
        except (ValueError,TypeError):pass
    units=value.get('column_units');unit=units[cols.index('timestamp')] if isinstance(units,list) and len(units)==len(cols) else None
    flags['timestamp_unit']=unit if unit in ('ms','s','us',None) else 'other'
    types=value.get('column_types');typ=types[cols.index('timestamp')] if isinstance(types,list) and len(types)==len(cols) else None
    flags['timestamp_column_type']=typ if typ in ('String','DateTime','DateTime64','Int64','Float64',None) else 'other'
    flags['timestamp_iso_timezone']=False;flags['timestamp_window_match']=False
    try:
        if isinstance(when,str):
            parsed=datetime.fromisoformat(when.replace('Z','+00:00'));flags['timestamp_iso_timezone']=parsed.tzinfo is not None
            if parsed.tzinfo is None:return outcome('timestamp_timezone_missing')
            ms=int(parsed.timestamp()*1000)
        elif type(when) is int and unit=='ms':ms=when
        else:return outcome('timestamp_format')
    except (ValueError,TypeError,OverflowError):return outcome('timestamp_format')
    flags['timestamp_window_match']=start_ms<=ms<=end_ms
    if not flags['timestamp_window_match']:return outcome('timestamp_outside_window')
    if not flags['exact_path']:return outcome('path_mismatch')
    if not flags['query_model_match']:return outcome('model_query_mismatch')
    code=row['response_code']
    if type(code) is not int or not -999<=code<=4999:return outcome('response_status')
    if code not in (101,200):
        # REST status conventions do not define WSS analytics sentinels. They
        # prove no success alone; only private accepted+committed wire evidence
        # permits a non-HTTP sentinel. HTTPdenials remain authoritative.
        if 100<=code<=599 or committed is not True:return outcome('response_status')
        return outcome('verified_committed_wire_sentinel',True)
    return outcome('verified',True)

def finish(owner,result,after,attribution):
    with transaction() as conn:
        budget._global_lock(conn);budget._owner(conn,owner)
        old=usage._query(conn,'SELECT before_used,key_digest,before_limit FROM kilas_realtime_checks WHERE approval=?',(APPROVAL,),one=True)
        verified=bool(type(result.get('wire_process_ms')) is int and 0<=result['wire_process_ms']<=10000 and type(result.get('sent_pcm_ms')) is int and 0<=result['sent_pcm_ms']<=5000 and result['accepted'] and result['result'] in ('committed','deadline_unknown') and after and after['used']>old[0] and after['limit']==old[2] and digest()==old[1] and attribution and quiet(conn,OPERATION))
        status='VERIFIED' if verified else 'UNKNOWN'
        usage._query(conn,'UPDATE kilas_realtime_checks SET status=?,actual_wire_ms=?,sent_pcm_ms=?,after_overage_kind=?,after_used=?,after_limit=?,accepted=?,attributed=?,result=?,finished_at=? WHERE approval=?',(status,result.get('wire_process_ms'),result.get('sent_pcm_ms'),after.get('overage_currency','not_supplied') if after else None,after['used'] if after else None,after['limit'] if after else None,int(result['accepted']),int(attribution),result['result'],stamp(),APPROVAL))
        usage._query(conn,"UPDATE kilas_vo_stt_operations SET status=?,finished_at=? WHERE user_id=? AND operation_key=?",('COMPLETED' if verified else 'UNKNOWN',stamp(),owner,OPERATION))
        return verified,old[0]

def verified():
    try:
        base=budget.policy()
        if not base or base['allowed_owner'] is None:return False
        # This proof is a single read, including on every streamed translation
        # fence. Reuse the thread's read connection rather than opening a fresh
        # write transaction per event. Never cache the proof or its revocation.
        row=db.query_one("SELECT user_id,key_digest,source_digest,model,campaign FROM kilas_realtime_checks WHERE approval=? AND status='VERIFIED' AND accepted=1 AND attributed=1 AND after_used>before_used AND after_limit=before_limit AND prepaid_guard=1 AND actual_wire_ms BETWEEN 0 AND 10000 AND sent_pcm_ms BETWEEN 0 AND 5000 AND result IN ('committed','deadline_unknown')",(APPROVAL,))
        return bool(row and row['user_id']==base['allowed_owner'] and row['key_digest']==digest() and row['source_digest']==SOURCE and row['model']==account.MODEL and row['campaign']==base['id']+'-rt-check')
    except Exception:return False

def readiness():
    value={'persisted_realtime_proof':False,'owner_realtime_ready':False}
    try:
        value['persisted_realtime_proof']=verified()
        from . import live_translator_realtime as realtime
        policy=budget.policy()
        value['owner_realtime_ready']=bool(policy and policy['allowed_owner'] is not None and realtime.ready(policy['allowed_owner']))
    except Exception:pass
    return value

def save_wire(owner,result,end_ms):
    # Preserve received proof before slow/deferred subscription reconciliation.
    # Child has already exited; this DB work cannot extend its socket lifetime.
    with transaction() as conn:
        budget._global_lock(conn)
        usage._query(conn,"UPDATE kilas_realtime_checks SET status='UNKNOWN',accepted=?,result=?,actual_wire_ms=?,sent_pcm_ms=?,wire_end_ms=?,finished_at=? WHERE approval=? AND user_id=?",(int(result['accepted']),result['result'],result['wire_process_ms'],result['sent_pcm_ms'],end_ms,stamp(),APPROVAL,owner))

def reconcile(owner,result,before,start):
    after=None;attribution=False
    for wait in (0,2,4):
        if wait:time.sleep(wait)
        try:
            after=subscription();comparison_end=int(datetime.now(timezone.utc).timestamp()*1000)
            # Entire interval between before/after snapshots, not just WSS time.
            attribution=attributed(start,comparison_end,committed=result['accepted'] is True and result['result']=='committed')
            with transaction() as conn:usage._query(conn,'UPDATE kilas_realtime_checks SET comparison_end_ms=? WHERE approval=?',(comparison_end,APPROVAL))
        except Exception:continue
        if after['used']>before['used'] and attribution:break
    active,used=finish(owner,result,after,attribution)
    print('KILAS_REALTIME_CHECK '+json.dumps({'approval':APPROVAL,'source':'synthetic_pcm','pcm_ms':5000,'maximum_connection_ms':10000,'accepted':result['accepted'],'result':result['result'],'stable_characters':result.get('stable_characters',0),'before_used':used,'after_used':after['used'] if after else None,'credit_delta':after['used']-used if after else None,'positive_credit_delta':bool(after and after['used']>used),'wire_process_ms':result['wire_process_ms'],'sent_pcm_ms':result['sent_pcm_ms'],'overage_zero_before':before.get('overage_zero',False),'overage_zero_after':after['overage_zero'] if after else False,'overage_currency_before':before.get('overage_currency','not_supplied'),'overage_currency_after':after['overage_currency'] if after else 'unverified','zero_extension_before':True,'extensions_disabled_before':True,'zero_extension_after':after is not None,'extensions_disabled_after':after is not None,'attributed':attribution,'activation_ready':active,**readiness()},sort_keys=True),flush=True)

def reconcile_existing():
    with transaction() as conn:
        row=usage._query(conn,'SELECT user_id,key_digest,status,accepted,result,actual_wire_ms,sent_pcm_ms,before_used,before_limit,window_start_ms,before_overage_kind,wire_end_ms FROM kilas_realtime_checks WHERE approval=?',(APPROVAL,),one=True)
    # A live/ambiguous child can never be relaunched or treated as settled.
    if not row or row[1]!=digest() or row[2]!='UNKNOWN' or not row[3] or row[11] is None or row[4] not in ('committed','deadline_unknown'):
        print('KILAS_REALTIME_CHECK '+json.dumps({'approval':APPROVAL,'result':'already_claimed','activation_ready':verified()}),flush=True);return
    result={'accepted':True,'result':row[4],'wire_process_ms':row[5],'sent_pcm_ms':row[6]}
    before={'used':row[7],'limit':row[8],'overage_currency':row[10],'overage_zero':row[10]!='not_supplied'}
    reconcile(row[0],result,before,row[9])

def run():
    owner=None;result=None
    try:
        start=int(datetime.now(timezone.utc).timestamp()*1000)
        before=subscription();fresh=time.monotonic();owner=claim(before,start)
        if owner is None:reconcile_existing();return
        if time.monotonic()-fresh>2:raise ValueError('credit_check_stale')
        print('KILAS_REALTIME_CHECK '+json.dumps({'approval':APPROVAL,'result':'dispatch_claim_committed','maximum_connection_ms':10000,'pcm_ms':5000}),flush=True)
        result=wire();end=int(datetime.now(timezone.utc).timestamp()*1000)
        save_wire(owner,result,end)
        reconcile(owner,result,before,start)
    except Exception as error:
        if owner is not None and result is None:
            try:finish(owner,{'accepted':False,'result':'connection_unknown'},None,False)
            except Exception:pass
        print('KILAS_REALTIME_CHECK '+json.dumps({'approval':APPROVAL,'result':str(error) if str(error) in ('billing_unsafe','policy_unavailable','service_busy','credit_check_stale') else 'check_unknown','possible_dispatch':owner is not None,'activation_ready':False}),flush=True)

def startup():
    if os.environ.get('KILAS_REALTIME_CHECK_ONCE','')==APPROVAL:
        Thread(target=run,name='kilas-realtime-one-check',daemon=True).start()
