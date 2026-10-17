"""Execution costs use existing premium capacity/top-up units, not new prices."""
from datetime import timedelta
from decimal import Decimal
from . import usage,capacity,topups

OPERATION='CODE_EXECUTION'


def reserve(conn,user_id,key,micro):
    now=usage._now()
    if usage.db.BACKEND=='postgres':usage._query(conn,'SELECT id FROM users WHERE id=? FOR UPDATE',(user_id,),one=True)
    if usage._query(conn,'SELECT id FROM kilas_ai_usage WHERE user_id=? AND operation_key=?',(user_id,key),one=True):
        raise ValueError('execution_already_dispatched')
    plan,start,end=usage._plan(conn,user_id,now)
    if plan=='FREE':raise usage.UsageLimit('Aktifkan Kilas Pro untuk melanjutkan fitur premium. Finance tetap gratis.')
    # Retain the same burst/hourly/concurrent guards as existing customer work.
    import os
    burst=max(1,int(os.environ.get('KILAS_AI_BURST_PER_MINUTE','30')))
    hourly=max(burst,int(os.environ.get('KILAS_AI_MAX_PER_HOUR','300')))
    for seconds,ceiling in ((60,burst),(3600,hourly)):
        count=usage._query(conn,"SELECT COUNT(DISTINCT operation_key) FROM kilas_ai_usage WHERE user_id=? AND created_at>=?",(user_id,(now-timedelta(seconds=seconds)).isoformat()),one=True)[0]
        if count>=ceiling:raise usage.UsageLimit('Terlalu banyak permintaan dalam waktu singkat. Coba lagi sebentar.')
    concurrent=usage._query(conn,"SELECT COUNT(DISTINCT operation_key) FROM kilas_ai_usage WHERE user_id=? AND status='PENDING' AND created_at>=?",(user_id,(now-timedelta(minutes=10)).isoformat()),one=True)[0]
    if concurrent>=3:raise usage.UsageLimit('Masih ada permintaan yang diproses. Tunggu jawabannya lalu coba lagi.')
    cycle=usage._period(plan,start,end,'CHAT',now)[0]
    predicted=Decimal(micro)/Decimal(1000000)
    source='BASE'
    if capacity.spent(conn,user_id,cycle,now)+predicted>capacity.allowance():
        try:topups.reserve(conn,user_id,key,OPERATION,'SMART',now,forecast_micro=micro)
        except topups.TopupError:raise usage.UsageLimit('Kapasitas Premium belum cukup untuk permintaan ini. Tambah kapasitas atau lanjutkan Chat biasa.') from None
        source='TOPUP'
    usage._query(conn,"INSERT INTO kilas_ai_usage(user_id,operation_key,operation_type,mode,status,quota_source,estimated_cost_usd,created_at) VALUES (?,?,?,'SMART','PENDING',?,?,?)",(user_id,key,OPERATION,source,str(predicted),now.isoformat()))


def settle(conn,user_id,key,micro,success):
    if user_id is None:return
    if usage.db.BACKEND=='postgres':usage._query(conn,'SELECT id FROM users WHERE id=? FOR UPDATE',(user_id,),one=True)
    row=usage._query(conn,"SELECT id FROM kilas_ai_usage WHERE user_id=? AND operation_key=? AND operation_type=? AND status='PENDING'",(user_id,key,OPERATION),one=True)
    if not row:return  # Proof has no customer debit; retries cannot charge twice.
    usage._query(conn,"UPDATE kilas_ai_usage SET status=?,provider='e2b',estimated_cost_usd=? WHERE id=? AND status='PENDING'",('COMPLETE' if success else 'FAILED',str(Decimal(micro)/Decimal(1000000)),row[0]))
    topups.settle(conn,user_id,key,success,micro)


def expired(conn,now):
    rows=usage._rows(conn,"SELECT e.user_id,e.operation_key,e.reserved_micro_usd FROM kilas_workspace_executions e JOIN kilas_ai_usage u ON u.user_id=e.user_id AND u.operation_key=e.operation_key AND u.operation_type=? WHERE e.expires_at<=? AND u.status='PENDING' ORDER BY e.user_id,e.id LIMIT 100",(OPERATION,now.isoformat()))
    for owner,key,micro in rows:settle(conn,owner,key,micro,False)
