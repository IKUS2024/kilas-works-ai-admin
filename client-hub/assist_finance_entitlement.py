"""Included Finance access derived from an explicit existing Assist→Finance connection.

No subscription/invoice/payment rows are duplicated. Standalone Finance paid periods remain
independent, and membership, branch and emergency-write checks still belong to Finance.
"""
import os
import db
import subscription_service


def until(finance_business_id):
    if os.environ.get('KILAS_FINANCE_BRIDGE_ENABLED','').lower() != 'true':
        return None
    # Optional bridge installers are intentionally not part of the old Finance migration chain.
    if db.BACKEND=='postgres':
        exists=db.query_one("SELECT to_regclass('kw_core_finance_connections') AS name")
        exists=bool(exists and exists['name'])
    else:
        exists=bool(db.query_one("SELECT name FROM sqlite_master WHERE type='table' AND name='kw_core_finance_connections'"))
    if not exists:return None
    rows=db.query_all('''SELECT s.period_end,s.status,s.grace_started_at,s.grace_days FROM kw_core_finance_connections c
        JOIN businesses b ON b.id=c.source_business_id JOIN subscriptions s ON s.business_id=b.id
        WHERE c.finance_business_id=? AND c.enabled=TRUE
        AND c.version=(SELECT MAX(v.version) FROM kw_core_finance_connections v WHERE v.source_business_id=c.source_business_id)
        AND b.package IN ('AI_ADMIN','AI_ADMIN_PRO','AI_ADMIN_BASIC')
        AND b.status NOT IN ('ARCHIVED','SUSPENDED','CANCELLED') AND s.status IN ('ACTIVE','GRACE')
        AND EXISTS(SELECT 1 FROM business_memberships src JOIN business_memberships dst ON dst.user_id=src.user_id
            WHERE src.business_id=b.id AND dst.business_id=c.finance_business_id
            AND src.role_in_business='OWNER' AND dst.role_in_business='OWNER')
        AND EXISTS(SELECT 1 FROM invoices i JOIN payments p ON p.invoice_id=i.id JOIN projects pr ON pr.id=i.project_id
            WHERE i.business_id=b.id AND i.status='PAID' AND p.status='VERIFIED'
            AND pr.catalog_key IN ('ai_admin','ai_admin_pro','ai_admin_basic'))''',(finance_business_id,))
    from datetime import timedelta
    dates=[]
    for row in rows:
        end=subscription_service._parse(row['period_end'])
        if row['status']=='GRACE':
            start=subscription_service._parse(row['grace_started_at']) or end
            end=start+timedelta(days=row['grace_days'] or 0) if start else None
        if end:dates.append(end)
    return max(dates,default=None)
