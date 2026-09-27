"""Business-facing capacity and platform economics over existing authoritative ledgers."""
import calendar
import os
from datetime import datetime, timezone

import ai_usage
import db
from pricing_config import ASSIST_PLANS


def _month():
    now=datetime.now(timezone.utc)
    return now,now.replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat()


def customer_usage(bid):
    _,start=_month()
    plan=db.query_one('SELECT plan_key FROM subscriptions WHERE business_id=?',(bid,)) or {}
    facts=ASSIST_PLANS.get(plan.get('plan_key'),ASSIST_PLANS['ai_admin'])
    name='PRO' if plan.get('plan_key')=='ai_admin_pro' else 'STARTER'
    capacity=int(ai_usage.number('KILAS_AI_'+name+'_CAPACITY',facts['capacity']))
    media_capacity=int(ai_usage.number('KILAS_AI_'+name+'_MEDIA_CAPACITY',facts['media_capacity']))
    row=db.query_one("SELECT SUM(CASE WHEN is_reply THEN 1 ELSE 0 END) AS replies, "
        "SUM(CASE WHEN classification='vision' THEN 1 ELSE 0 END) AS media, "
        "SUM(CASE WHEN context_type='follow_up' THEN 1 ELSE 0 END) AS followups "
        "FROM ai_usage_ledger WHERE tenant_id=? AND created_at>=? AND context_type NOT LIKE ?",(bid,start,'finance_%'))
    replies,media,followups=(int(row.get(key) or 0) for key in ('replies','media','followups'))
    ratio=max(replies/capacity,media/media_capacity)
    return dict(replies=replies,media=media,followups=followups,
                status='HIGH' if ratio>=.9 else 'WARNING' if ratio>=.7 else 'NORMAL')


def platform_report():
    now,start=_month()
    rows=db.query_all('SELECT tenant_id,context_type,provider,model,COUNT(*) AS calls,'
        'SUM(estimated_cost_idr) AS cost_idr,SUM(estimated_cost_usd) AS cost_usd,'
        'SUM(CASE WHEN estimated_cost_idr IS NULL THEN 1 ELSE 0 END) AS unknown '
        'FROM ai_usage_ledger WHERE created_at>=? GROUP BY tenant_id,context_type,provider,model',(start,))
    revenues=db.query_all("SELECT i.business_id,SUM(i.amount) AS revenue FROM invoices i JOIN projects pr ON pr.id=i.project_id "
        "WHERE i.status='PAID' AND pr.catalog_key IN ('ai_admin','ai_admin_basic','ai_admin_pro') "
        "AND EXISTS (SELECT 1 FROM payments p WHERE p.invoice_id=i.id AND p.status='VERIFIED' AND p.verified_at>=?) "
        "GROUP BY i.business_id",(start,))
    revenue={r['business_id']:float(r['revenue']) for r in revenues}
    businesses={}
    for row in rows:
        bid=row['tenant_id']
        item=businesses.setdefault(bid,dict(business_id=bid,cost=0,unknown=0,features={},calls=0))
        cost=float(row['cost_idr'] or 0)
        item['cost']+=cost;item['unknown']+=row['unknown'];item['calls']+=row['calls']
        feature=row['context_type'];item['features'][feature]=item['features'].get(feature,0)+cost
    green=ai_usage.number('KILAS_AI_GREEN_RATIO',.15)
    red=max(green,ai_usage.number('KILAS_AI_RED_RATIO',.25))
    for bid,item in businesses.items():
        item['revenue']=revenue.get(bid,0)
        item['projected']=item['cost']/now.day*calendar.monthrange(now.year,now.month)[1]
        item['ratio']=item['cost']/item['revenue'] if item['revenue'] else None
        item['guardrail']=('UNKNOWN' if item['unknown'] else 'NO_REVENUE' if item['ratio'] is None else
            'RED' if item['ratio']>red else 'YELLOW' if item['ratio']>green else 'GREEN')
        item['largest_feature']=max(item['features'],key=item['features'].get,default=None)
        if item['unknown']:
            item['cost']=item['projected']=item['ratio']=None
    return dict(businesses=list(businesses.values()),breakdown=rows,revenue=sum(revenue.values()),
                green=green,red=red)
