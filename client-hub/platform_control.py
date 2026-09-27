"""Read models for Kilas Works SaaS operations, separate from tenant CRM and Finance."""
import os
import time
from datetime import datetime, timezone
import db
import repo
import assist_costs
import assist_journey
import assist_connections

SECTIONS = (('overview','Overview'),('businesses','Businesses'),('whatsapp','WhatsApp'),
            ('subscriptions','Subscriptions'),('cost','AI Usage & Cost'),('finance','Platform Finance'),('system','System'))


def businesses():
    rows = db.query_all('''SELECT b.*,s.plan_key,s.status AS subscription_status,s.period_end,
        q.state AS connection_state,q.requested_phone,q.last_error,q.updated_at AS connection_updated_at
        FROM businesses b LEFT JOIN subscriptions s ON s.business_id=b.id
        LEFT JOIN kw_assist_connections q ON q.business_id=b.id ORDER BY b.id DESC''')
    costs = {r['business_id']:r for r in assist_costs.platform_report()['businesses']}
    for row in rows:
        row['journey'] = assist_journey.state(row) if row['package'] in ('AI_ADMIN','AI_ADMIN_BASIC','AI_ADMIN_PRO') else None
        row['cost'] = costs.get(row['id'])
    return rows


def overview(rows):
    today = int(datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
    metrics = {'Businesses':len(rows), 'Demos':sum(bool(b.get('journey') and b['journey']['demo_active']) for b in rows),
               'Pending WhatsApp':sum(bool(b['connection_state'] and b['connection_state'] != 'Connected') for b in rows),
               'Active subscriptions':sum(b['subscription_status']=='ACTIVE' for b in rows)}
    for label, table, clause in (
        ('Conversations today','kw_web_conversations','created_at>=?'),
        ('Replies today','kw_web_messages',"created_at>=? AND role='assistant'"),
        ('Customers today','kw_core_customer_stages',"created_at>=? AND stage='CUSTOMER'"),
        ('Leads today','kw_core_customer_stages',"created_at>=? AND stage='LEAD'"),
        ('Jobs today','kw_core_jobs','created_at>=?')):
        metrics[label]=db.query_one('SELECT COUNT(*) AS n FROM '+table+' WHERE '+clause,(today,))['n']
    return metrics


def economics():
    result = assist_costs.platform_report()
    costs = result['businesses']
    result['ai_cost'] = None if any(r['unknown'] for r in costs) else sum(r['cost'] for r in costs)
    # Platform operating expense estimates are explicit configuration, never tenant ledger totals.
    result['expenses'] = {}
    for label,key in (('WhatsApp reserve / cost','WHATSAPP'),('Hosting / infrastructure','INFRA'),
                      ('Payment fees','PAYMENT_FEES'),('Refunds / credits','REFUNDS')):
        value = os.environ.get('KILAS_PLATFORM_'+key+'_MTD_IDR')
        try:
            amount = float(value) if value else None
            if amount is not None and amount < 0: amount = None
        except ValueError:
            amount = None
        result['expenses'][label] = amount
    known = result['ai_cost'] is not None and all(v is not None for v in result['expenses'].values())
    result['contribution'] = result['revenue'] - result['ai_cost'] - sum(result['expenses'].values()) if known else None
    return result


def system():
    started=time.monotonic();db.query_one('SELECT 1 AS ok')
    result={'Database': 'Reachable ('+str(round((time.monotonic()-started)*1000))+' ms)',
            'Deployed commit': os.environ.get('RENDER_GIT_COMMIT','local / unavailable'),
            'OpenAI configuration': 'Configured' if os.environ.get('OPENAI_API_KEY') else 'Missing on this service',
            'Claude configuration': 'Configured' if os.environ.get('ANTHROPIC_API_KEY') else 'Missing on this service',
            'WhatsApp bridge': 'Configured; see connection tests for delivery' if os.environ.get('INTERNAL_SERVICE_SECRET') else 'Missing',
            'Provider availability':'Requires a successful recent inference; configuration alone is not a health test'}
    result['WhatsApp credentials on Client Hub']='Configured' if os.environ.get('WHATSAPP_ACCESS_TOKEN','').strip() else 'Missing on this service'
    if os.environ.get('INTERNAL_SERVICE_SECRET','').strip():
        try:
            bot=assist_connections.bridge('health',{})
            result['Bot bridge']='Reachable and authenticated'
            for key,label in (('database','Bot database'),('whatsapp','Bot WhatsApp configuration'),
                              ('openai','Bot OpenAI configuration'),('claude','Bot Claude configuration'),
                              ('webhook_signature','Bot webhook signature configuration'),('assist_runtime','Bot Assist runtime')):
                result[label]='Available' if bot.get(key) is True else 'Unavailable'
            import re
            commit=bot.get('commit','')
            result['Bot deployed commit']=commit if isinstance(commit,str) and re.fullmatch(r'[a-f0-9]{40}',commit) else 'Unavailable'
        except Exception:
            result['Bot bridge']='Unreachable or configuration not yet verified'
    pending=db.query_one("SELECT COUNT(*) AS n FROM kw_assist_demo_events WHERE status IN ('processing','sending')")['n']
    result['Demo events awaiting resolution']=pending
    result['Finance bridge']='Tables reachable' if db.query_one('SELECT COUNT(*) AS n FROM kw_core_finance_connections') is not None else 'Unavailable'
    result['Recent connection errors']=db.query_all('SELECT business_id,last_error,updated_at FROM kw_assist_connections WHERE last_error IS NOT NULL ORDER BY updated_at DESC LIMIT 20')
    return result
