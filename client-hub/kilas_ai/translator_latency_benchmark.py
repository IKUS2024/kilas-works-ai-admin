"""Owner-approved four-call synthetic text benchmark; no audio/customer billing.

Explicit approval: 2026-10-20, source thread 01a15783-011a-71d6-bd5f-1190497b50e2.
Fixed campaign PK is consumed before dispatch; never resume/re-arm after restart.
"""
import hashlib,json,os,re,secrets
from datetime import datetime,timezone
from decimal import Decimal,ROUND_CEILING
from threading import Thread
from time import monotonic
import requests,db
from . import live_translator as live,providers,usage
from .autonomous_store import transaction

CAMPAIGN='translator-latency-owner-20261020-v1'
FLAG='KILAS_TRANSLATOR_LATENCY_BENCHMARK'
SERVICE='srv-da7ti2psrm7s73dh9i2g'
MODEL='gpt-6-luna'
OWNER=9
START=int(datetime(2026,10,20,8,30,tzinfo=timezone.utc).timestamp()*1000)
END=int(datetime(2026,10,20,10,0,tzinfo=timezone.utc).timestamp()*1000)
MAX_BYTES=8192
INPUT_BOUND=16384  # Entire serialized UTF-8 body + 8192-token framing margin.
OUTPUT_BOUND=3500  # Includes ALL completion/reasoning tokens, n=1, no tools.
CAP=100000
RESERVE=10000  # Four irreversible USD .01 slots, USD .04 reserved <= .10.
PRICE_VERSION='openai-official-20261020-gpt6luna-standard'
SOURCES=(
 ('id','en','Nama saya Rina, bukan Budi. Bukan hari Jumat; jadwalnya Senin, 26 Oktober 2026. Totalnya Rp125.000. Apakah sudah termasuk ongkir?'),
 ('en','id','Could you deliver two boxes, not three, to Rina on Monday, 26 October 2026? The total is 125,000 rupiah, not dollars. Each box weighs 2.5 kilograms. Wait, wait: please confirm the shipping cost first.'))
CASES=((0,'low'),(0,'none'),(1,'none'),(1,'low'))

class Blocked(ValueError):pass

def upper_bound_micro():
    # Cache WRITE premium 1.25x, even though normal input is cheaper. Include
    # an extra 2x tier and 10% regional margin despite explicitly Standard tier.
    per=(Decimal(INPUT_BOUND)*Decimal('.125')+Decimal(OUTPUT_BOUND)*Decimal('.50'))*Decimal('2.2')
    return int(per.to_integral_value(rounding=ROUND_CEILING))*len(CASES)

def payload(index):
    source,effort=CASES[index];a,b,text=SOURCES[source]
    profile=live.translation_profile(text)
    if profile['model']!=MODEL or profile['effort']!='low' or profile['output_tokens']!=OUTPUT_BOUND:raise Blocked('profile_drift')
    body={'model':MODEL,'messages':[{'role':'system','content':live.translation_system(a,b)},{'role':'user','content':json.dumps({'source_text':text},ensure_ascii=False)}],
          'max_completion_tokens':OUTPUT_BOUND,'reasoning_effort':effort,'stream':True,'stream_options':{'include_usage':True},
          'store':False,'response_format':live.translation_format(a,b),'service_tier':'default','n':1}
    if len(json.dumps(body,ensure_ascii=False).encode())>MAX_BYTES:raise Blocked('input_bound')
    return body

def preflight():
    if len(CASES)!=4 or len(set(CASES))!=4 or upper_bound_micro()>RESERVE*4 or RESERVE*4>CAP:raise Blocked('cost_bound')
    return [payload(index) for index in range(4)]

def configured():
    return (os.environ.get(FLAG)==CAMPAIGN and db.BACKEND=='postgres'
        and os.environ.get('RENDER_SERVICE_ID')==SERVICE
        and os.environ.get('KILAS_LIVE_TRANSLATOR_VERIFIED_MODEL')==MODEL
        and bool(os.environ.get('OPENAI_API_KEY','').strip())
        and bool(re.fullmatch(r'proj_[A-Za-z0-9_-]{1,100}',os.environ.get('KILAS_LIVE_TRANSLATOR_VERIFIED_PROJECT',''))))

def _now(conn):
    query="SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint" if db.BACKEND=='postgres' else "SELECT CAST(strftime('%s','now') AS INTEGER)*1000"
    return int(usage._query(conn,query,one=True)[0])

def _window(conn):
    now=_now(conn)
    if not START<=now<END:raise Blocked('expired')
    return now

def _owner(conn):
    row=usage._query(conn,'SELECT email,role FROM users WHERE id=?',(OWNER,),one=True)
    if not row or str(row[0]).strip().casefold()!='irvankarnavi@gmail.com' or row[1]!='CLIENT_OWNER':raise Blocked('owner_mismatch')

def _claim(token,bodies):
    fingerprint=hashlib.sha256(json.dumps(bodies,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    with transaction() as conn:
        now=_window(conn);_owner(conn)
        # Independent benchmark metadata, never a customer allowance/top-up.
        usage._query(conn,"CREATE TABLE IF NOT EXISTS kilas_translator_latency_benchmarks(id TEXT PRIMARY KEY,owner_id BIGINT NOT NULL REFERENCES users(id),token_digest TEXT NOT NULL,fingerprint TEXT NOT NULL,started_ms BIGINT NOT NULL,deadline_ms BIGINT NOT NULL,status TEXT NOT NULL CHECK(status IN ('ACTIVE','COMPLETED','FAILED')),reserved_micro INTEGER NOT NULL CHECK(reserved_micro BETWEEN 0 AND 100000),attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 4),results TEXT NOT NULL DEFAULT '[]')")
        row=usage._query(conn,"INSERT INTO kilas_translator_latency_benchmarks(id,owner_id,token_digest,fingerprint,started_ms,deadline_ms,status,reserved_micro) VALUES (?,?,?,?,?,?,'ACTIVE',?) ON CONFLICT(id) DO NOTHING RETURNING id",(CAMPAIGN,OWNER,hashlib.sha256(token.encode()).hexdigest(),fingerprint,now,min(now+600000,END),RESERVE*4),one=True)
        return bool(row)

def _locked(conn,token):
    suffix=' FOR UPDATE' if db.BACKEND=='postgres' else ''
    row=usage._query(conn,'SELECT token_digest,status,attempts,deadline_ms,results,reserved_micro FROM kilas_translator_latency_benchmarks WHERE id=?'+suffix,(CAMPAIGN,),one=True)
    if not row or row[0]!=hashlib.sha256(token.encode()).hexdigest():raise Blocked('claim_mismatch')
    return row

def _dispatch(token,index):
    with transaction() as conn:
        now=_window(conn);_owner(conn);row=_locked(conn,token)
        if row[1]!='ACTIVE' or row[2]!=index or not 0<=index<4 or now>=row[3] or row[5]!=RESERVE*4:raise Blocked('no_replay')
        # Commit irreversible attempt BEFORE any provider network operation.
        usage._query(conn,'UPDATE kilas_translator_latency_benchmarks SET attempts=attempts+1 WHERE id=?',(CAMPAIGN,))

def _record(token,report,*,terminal=None):
    with transaction() as conn:
        row=_locked(conn,token);results=json.loads(row[4])
        if len(results)>=row[2] or len(results)>=4:raise Blocked('duplicate_result')
        results.append(report)
        usage._query(conn,'UPDATE kilas_translator_latency_benchmarks SET results=?,status=? WHERE id=?',(json.dumps(results,ensure_ascii=False),terminal or 'ACTIVE',CAMPAIGN))

def _request(body):
    began=monotonic();timings={};parts=[];tokens=None;finished=False;actual_model=None;tier=None
    headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY'].strip(),'Content-Type':'application/json','OpenAI-Project':os.environ['KILAS_LIVE_TRANSLATOR_VERIFIED_PROJECT']}
    with requests.Session() as client:
        if client.get_adapter('https://api.openai.com/').max_retries.total!=0:raise Blocked('transport_retry')
        with client.post('https://api.openai.com/v1/chat/completions',headers=headers,json=body,stream=True,allow_redirects=False,timeout=(10,45)) as response:
            timings['translation_http_headers_ms']=(monotonic()-began)*1000
            if response.status_code!=200:raise Blocked('http_'+str(response.status_code))
            response.encoding='utf-8'
            for event in providers._events(response,chunk_size=1,timings=timings,started=began):
                if monotonic()-began>90:raise Blocked('duration_bound')
                if event.get('model'):actual_model=event['model']
                if event.get('service_tier'):tier=event['service_tier']
                if event.get('usage'):tokens=event['usage']
                for choice in event.get('choices') or []:
                    delta=choice.get('delta') or {}
                    if delta.get('refusal'):raise Blocked('refusal')
                    if delta.get('content'):
                        timings.setdefault('ttft_ms',(monotonic()-began)*1000);parts.append(delta['content'])
                        if sum(map(len,parts))>24000:raise Blocked('response_bound')
                    if choice.get('finish_reason'):finished=choice['finish_reason']=='stop'
    if not finished or not tokens:raise Blocked('unknown_completion')
    if actual_model!=MODEL and not re.fullmatch(r'gpt-6-luna-20\d\d-\d\d-\d\d',actual_model or ''):raise Blocked('returned_model')
    if tier not in (None,'default'):raise Blocked('returned_tier')
    prompt,completion=tokens.get('prompt_tokens'),tokens.get('completion_tokens')
    if type(prompt)is not int or not 0<=prompt<=INPUT_BOUND or type(completion)is not int or not 0<=completion<=OUTPUT_BOUND:raise Blocked('usage_bound')
    result=json.loads(''.join(parts));source=body['response_format']['json_schema']['schema']['properties']['source_language']['enum']
    if not isinstance(result,dict) or {result.get('source_language'),result.get('target_language')}!=set(source)-{'unknown'} or not isinstance(result.get('text'),str) or not 1<=len(result['text'])<=4000:raise Blocked('invalid_translation')
    timings['total_ms']=(monotonic()-began)*1000
    details=tokens.get('completion_tokens_details') or {};reasoning=details.get('reasoning_tokens') if isinstance(details,dict) else None
    if reasoning is not None and (type(reasoning)is not int or not 0<=reasoning<=completion):raise Blocked('reasoning_usage')
    return {'timings':{key:round(value,1) for key,value in timings.items()},'model':actual_model,'service_tier':tier,'effort':body['reasoning_effort'],
            'usage':{'input_tokens':prompt,'completion_tokens':completion,'reasoning_tokens':reasoning},
            'standard_cost_micro':float(Decimal(prompt)*Decimal('.10')+Decimal(completion)*Decimal('.50')),
            'conservative_cost_micro':float((Decimal(prompt)*Decimal('.125')+Decimal(completion)*Decimal('.50'))*Decimal('2.2')),
            'translation':result}

def run():
    if not configured():return
    token=secrets.token_hex(32)
    try:
        bodies=preflight()
        if not _claim(token,bodies):return
        print('KILAS_TRANSLATOR_BENCHMARK '+json.dumps({'status':'claimed','upper_bound_micro':upper_bound_micro(),'reserved_micro':RESERVE*4,'max_calls':4,'price_version':PRICE_VERSION}),flush=True)
        for index,body in enumerate(bodies):
            _dispatch(token,index)
            try:report=_request(body)
            except Exception as error:
                code=str(error) if isinstance(error,Blocked) else 'provider_or_parse_failure'
                report={'index':index,'source':SOURCES[CASES[index][0]][0],'effort':CASES[index][1],'status':'UNCERTAIN','code':code}
                _record(token,report,terminal='FAILED')
                print('KILAS_TRANSLATOR_BENCHMARK '+json.dumps(report),flush=True);return
            report.update(index=index,source=SOURCES[CASES[index][0]][0],status='COMPLETED')
            _record(token,report,terminal='COMPLETED' if index==3 else None)
            print('KILAS_TRANSLATOR_BENCHMARK '+json.dumps(report,ensure_ascii=False),flush=True)
    except Exception as error:
        # An uncertain claim/attempt is never resumed; its full budget remains.
        code=str(error) if isinstance(error,Blocked) else type(error).__name__
        print('KILAS_TRANSLATOR_BENCHMARK '+json.dumps({'status':'blocked_no_retry','code':code}),flush=True)

def start():
    if os.environ.get(FLAG)!=CAMPAIGN:return
    if not configured():
        print('KILAS_TRANSLATOR_BENCHMARK status=runtime_scope_denied',flush=True);return
    Thread(target=run,name='translator-approved-benchmark',daemon=True).start()
