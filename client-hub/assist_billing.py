"""Assist offers and entitlement bridge to the existing purchase/subscription lifecycle.

No parallel ledger. Invoice/payment remain payment_service; periods remain subscriptions.
The immutable order snapshot records the pricing rule actually used at purchase time.
"""
import json

import db
import repo
import catalog_service
import projects_repo
import subscription_service
from pricing_config import ASSIST_PLANS, ASSIST_LAUNCH_RULE


def offer(bid, plan):
    if plan not in ASSIST_PLANS:
        raise ValueError('invalid_plan')
    paid = db.query_one("SELECT 1 FROM payments p JOIN invoices i ON i.id=p.invoice_id "
        "JOIN projects pr ON pr.id=i.project_id WHERE p.business_id=? AND i.business_id=? "
        "AND pr.business_id=? AND pr.catalog_key IN ('ai_admin','ai_admin_basic','ai_admin_pro') "
        "AND p.status='VERIFIED' AND i.status='PAID' LIMIT 1", (bid,bid,bid))
    regular = ASSIST_PLANS[plan]['price']
    promo = plan in ASSIST_LAUNCH_RULE['eligible_plans'] and not paid
    return {'plan':plan,'name':ASSIST_PLANS[plan]['name'],'regular':regular,
            'amount':ASSIST_LAUNCH_RULE['amount'] if promo else regular,
            'rule_id':ASSIST_LAUNCH_RULE['id'] if promo else 'assist_standard_202609_v1',
            'discount':regular-ASSIST_LAUNCH_RULE['amount'] if promo else 0,
            'promo':promo,'period_days':subscription_service.DEFAULT_PERIOD_DAYS}


def pending(bid):
    return db.query_one("SELECT * FROM projects WHERE business_id=? "
        "AND catalog_key IN ('ai_admin','ai_admin_basic','ai_admin_pro') "
        "AND status IN ('APPROVED','PAYMENT_PENDING') ORDER BY id DESC LIMIT 1", (bid,))


def purchase(bid, actor, plan):
    with db.app_purchase_transaction(bid,None):
        if not db.query_one('SELECT 1 FROM business_memberships WHERE business_id=? AND user_id=?',(bid,actor)):
            raise ValueError('not_found')
        existing = pending(bid)
        if existing:
            return existing['id']
        facts = offer(bid,plan)
        item = catalog_service.get_catalog_item(plan)
        if not item:
            raise ValueError('plan_unavailable')
        pid = projects_repo.create_fixed_price_project(bid,dict(item,price_amount=facts['amount']),actor)
        snapshot = {'assist_pricing':dict(facts,version=1)}
        db.execute('UPDATE projects SET requirements_json=? WHERE id=? AND business_id=?',
                   (json.dumps(snapshot,sort_keys=True),pid,bid))
        repo.write_audit(actor,bid,'ASSIST_PRICING_APPLIED',json.dumps(facts,sort_keys=True),project_id=pid)
        return pid


def apply_verified(payment, actor):
    """Called inside payment_service's locked verification; one invoice grants one period."""
    bid=payment['business_id']
    if bid is None:
        return False
    invoice=db.query_one('SELECT * FROM invoices WHERE id=? AND business_id=?',(payment['invoice_id'],bid))
    project=projects_repo.get_project(invoice['project_id']) if invoice else None
    snapshot=(project or {}).get('requirements',{}).get('assist_pricing')
    if not snapshot:
        return False  # Historical orders retain their established lifecycle.
    plan=project['catalog_key']
    if (plan not in ASSIST_PLANS or snapshot.get('plan') != plan or invoice['status'] != 'PAID'
            or payment['status'] != 'VERIFIED' or invoice['amount'] != snapshot.get('amount')):
        raise ValueError('invalid_verified_offer')
    key='invoice:'+str(invoice['id'])
    if db.query_one("SELECT 1 FROM audit_log WHERE business_id=? AND action='ASSIST_SUBSCRIPTION_PAYMENT_APPLIED' AND detail=?",(bid,key)):
        return True
    sub=subscription_service.get_subscription(bid)
    if sub:
        subscription_service.renew_subscription(bid,actor,plan_key=plan)
    else:
        if repo.get_business(bid)['package'] != plan.upper():
            repo.set_business_package(bid,plan.upper(),actor)
        subscription_service.establish_paid_subscription(bid,actor)
    repo.write_audit(actor,bid,'ASSIST_SUBSCRIPTION_PAYMENT_APPLIED',key,project_id=project['id'])
    return True
