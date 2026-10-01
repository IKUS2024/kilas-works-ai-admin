"""Read-only, admin-only operating views for Kilas AI and Kilas Finance.

All queries are platform scoped and must only be called behind admin_required.
Finance ledger tables are never written or joined to customer-visible routes.
"""
from datetime import timedelta
from decimal import Decimal
import os

import db
from kilas_ai import usage, topups

SECTIONS = (("overview", "Overview"), ("customers", "Customers"),
            ("kilas-ai", "Kilas AI"), ("finance", "Kilas Finance"),
            ("payments", "Payments"), ("usage-cost", "Usage & Cost"),
            ("settings", "Settings"))


def _number(sql, params=()):
    return int(db.query_one(sql, params)["n"] or 0)


def overview():
    now = usage._now().isoformat()
    active_plans = db.query_all("SELECT plan,COUNT(*) AS n FROM kilas_ai_subscriptions WHERE status='ACTIVE' AND period_end>? GROUP BY plan", (now,))
    subscriptions = sum(int(row["n"]) for row in active_plans)
    return {
        "customers": _number("SELECT COUNT(*) AS n FROM users WHERE role='CLIENT_OWNER'"),
        "subscriptions": subscriptions,
        "finance": _number("SELECT COUNT(*) AS n FROM businesses b WHERE EXISTS (SELECT 1 FROM finance_entitlements e WHERE e.business_id=b.id) OR EXISTS (SELECT 1 FROM finance_accounts a WHERE a.business_id=b.id)"),
        "pending": _number("SELECT COUNT(*) AS n FROM kilas_ai_invoices WHERE status='UNDER_REVIEW'") + _number("SELECT COUNT(*) AS n FROM kilas_ai_topup_orders WHERE status='UNDER_REVIEW'") + _number("SELECT COUNT(*) AS n FROM finance_subscription_bills WHERE status='REVIEW'"),
        "capacity_orders": _number("SELECT COUNT(*) AS n FROM kilas_ai_topup_orders WHERE invoice_number LIKE 'KAI-C-%%' AND status='VERIFIED'"),
        "revenue_idr": sum(int(row["n"]) * usage.PLANS[row["plan"]]["price"] for row in active_plans),
    }


def customers(query="", product="", status="", page=1):
    where = ["u.role='CLIENT_OWNER'"]
    params = []
    if query:
        where.append("LOWER(COALESCE(u.full_name,'') || ' ' || u.email) LIKE ?")
        params.append("%" + query.lower() + "%")
    finance = "EXISTS (SELECT 1 FROM business_memberships m JOIN businesses b ON b.id=m.business_id WHERE m.user_id=u.id AND (EXISTS (SELECT 1 FROM finance_entitlements e WHERE e.business_id=b.id) OR EXISTS (SELECT 1 FROM finance_accounts a WHERE a.business_id=b.id)))"
    if product == "finance":
        where.append(finance)
    elif product == "ai":
        where.append("EXISTS (SELECT 1 FROM kilas_ai_threads t WHERE t.user_id=u.id) OR EXISTS (SELECT 1 FROM kilas_ai_subscriptions s WHERE s.user_id=u.id) OR EXISTS (SELECT 1 FROM kilas_ai_invoices i WHERE i.user_id=u.id)")
    if status == "active":
        where.append("EXISTS (SELECT 1 FROM kilas_ai_subscriptions s WHERE s.user_id=u.id AND s.status='ACTIVE' AND s.period_end>?)")
        params.append(usage._now().isoformat())
    elif status == "pending":
        where.append("EXISTS (SELECT 1 FROM kilas_ai_invoices i WHERE i.user_id=u.id AND i.status='UNDER_REVIEW') OR EXISTS (SELECT 1 FROM kilas_ai_topup_orders o WHERE o.user_id=u.id AND o.status='UNDER_REVIEW')")
    sql = "SELECT u.id,u.full_name,u.email,u.created_at,s.plan,s.status AS subscription_status,s.period_end," \
          "(SELECT MAX(created_at) FROM kilas_ai_usage k WHERE k.user_id=u.id) AS last_ai_activity," \
          "(SELECT status FROM kilas_ai_invoices i WHERE i.user_id=u.id ORDER BY id DESC LIMIT 1) AS billing_status," \
          "(SELECT COUNT(*) FROM business_memberships m JOIN businesses b ON b.id=m.business_id WHERE m.user_id=u.id AND (EXISTS (SELECT 1 FROM finance_entitlements e WHERE e.business_id=b.id) OR EXISTS (SELECT 1 FROM finance_accounts a WHERE a.business_id=b.id))) AS finance_count," \
          "(SELECT COUNT(*) FROM kilas_ai_threads t WHERE t.user_id=u.id) AS ai_threads," \
          "(SELECT COUNT(*) FROM kilas_ai_invoices i WHERE i.user_id=u.id) AS ai_invoices " \
          "FROM users u LEFT JOIN kilas_ai_subscriptions s ON s.user_id=u.id WHERE " + " AND ".join("(" + item + ")" for item in where)
    total = _number("SELECT COUNT(*) AS n FROM users u WHERE " + " AND ".join("(" + item + ")" for item in where), tuple(params))
    rows = db.query_all(sql + " ORDER BY u.id DESC LIMIT 50 OFFSET ?", tuple(params + [(page - 1) * 50]))
    return {"rows": rows, "total": total, "page": page, "has_next": total > page * 50}


def ai_customer(user_id):
    user = db.query_one("SELECT id,full_name,email,created_at FROM users WHERE id=? AND role='CLIENT_OWNER'", (user_id,))
    if not user:
        return None
    since = (usage._now() - timedelta(days=30)).isoformat()
    subscription = db.query_one("SELECT plan,status,period_start,period_end FROM kilas_ai_subscriptions WHERE user_id=?", (user_id,))
    operations = db.query_all("SELECT operation_type,mode,quota_source,COUNT(*) AS n,COALESCE(SUM(CAST(estimated_cost_usd AS NUMERIC)),0) AS cost, SUM(CASE WHEN estimated_cost_usd IS NULL THEN 1 ELSE 0 END) AS unknown FROM kilas_ai_usage WHERE user_id=? AND status='COMPLETE' AND created_at>=? GROUP BY operation_type,mode,quota_source ORDER BY n DESC", (user_id, since))
    models = db.query_all("SELECT provider,model,COUNT(*) AS n,COALESCE(SUM(CAST(estimated_cost_usd AS NUMERIC)),0) AS cost FROM kilas_ai_usage WHERE user_id=? AND status='COMPLETE' AND created_at>=? GROUP BY provider,model ORDER BY cost DESC", (user_id, since))
    recent = db.query_all("SELECT operation_type,mode,quota_source,status,created_at FROM kilas_ai_usage WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,))
    cost = sum(Decimal(str(row["cost"] or 0)) for row in operations)
    price = usage.PLANS[subscription["plan"]]["price"] if subscription and subscription["status"] == "ACTIVE" else 0
    fx = Decimal(os.environ.get("KILAS_AI_USD_IDR", "17000"))
    ratio = (cost * fx / Decimal(price)) if price else None
    return {"user": user, "subscription": subscription, "operations": operations, "models": models,
            "recent": recent, "cost_usd": cost, "cost_ratio": ratio, "capacity": topups.balance(user_id),
            "finance_businesses": db.query_all("SELECT b.id,b.business_name,e.trial_until,e.paid_until FROM businesses b JOIN business_memberships m ON m.business_id=b.id LEFT JOIN finance_entitlements e ON e.business_id=b.id WHERE m.user_id=? AND (e.business_id IS NOT NULL OR EXISTS (SELECT 1 FROM finance_accounts a WHERE a.business_id=b.id)) ORDER BY b.id DESC", (user_id,)),
            "invoices": db.query_all("SELECT id,invoice_number,amount_idr,status,created_at FROM kilas_ai_invoices WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,)),
            "topups": db.query_all("SELECT id,invoice_number,amount_idr,status,created_at FROM kilas_ai_topup_orders WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,))}


def finance_businesses(query="", page=1):
    where = "(EXISTS (SELECT 1 FROM finance_entitlements e WHERE e.business_id=b.id) OR EXISTS (SELECT 1 FROM finance_accounts a WHERE a.business_id=b.id))"
    params = []
    if query:
        where += " AND LOWER(b.business_name) LIKE ?"
        params.append("%" + query.lower() + "%")
    total = _number("SELECT COUNT(*) AS n FROM businesses b WHERE " + where, tuple(params))
    rows = db.query_all("SELECT b.id,b.business_name,b.created_at,b.status, e.trial_until,e.paid_until, "
        "(SELECT COUNT(*) FROM finance_branches r WHERE r.business_id=b.id) AS branches,"
        "(SELECT u.full_name FROM users u JOIN business_memberships m ON m.user_id=u.id WHERE m.business_id=b.id AND m.role_in_business='OWNER' ORDER BY m.id LIMIT 1) AS owner_name,"
        "(SELECT u.email FROM users u JOIN business_memberships m ON m.user_id=u.id WHERE m.business_id=b.id AND m.role_in_business='OWNER' ORDER BY m.id LIMIT 1) AS owner_email,"
        "(SELECT u.id FROM users u JOIN business_memberships m ON m.user_id=u.id WHERE m.business_id=b.id AND m.role_in_business='OWNER' ORDER BY m.id LIMIT 1) AS owner_id "
        "FROM businesses b LEFT JOIN finance_entitlements e ON e.business_id=b.id WHERE " + where +
        " ORDER BY b.id DESC LIMIT 50 OFFSET ?", tuple(params + [(page - 1) * 50]))
    return {"rows": rows, "total": total, "page": page, "has_next": total > page * 50}


def payments():
    return {
        "subscriptions": db.query_all("SELECT i.id,i.invoice_number,i.amount_idr,i.status,i.created_at,u.full_name,u.email,p.id AS proof_id,p.proof_filename FROM kilas_ai_invoices i JOIN users u ON u.id=i.user_id LEFT JOIN kilas_ai_payments p ON p.invoice_id=i.id ORDER BY CASE WHEN i.status='UNDER_REVIEW' THEN 0 ELSE 1 END,i.id DESC LIMIT 100"),
        "capacity": db.query_all("SELECT o.id,o.invoice_number,o.amount_idr,o.status,o.created_at,o.proof_filename,u.full_name,u.email FROM kilas_ai_topup_orders o JOIN users u ON u.id=o.user_id ORDER BY CASE WHEN o.status='UNDER_REVIEW' THEN 0 ELSE 1 END,o.id DESC LIMIT 100"),
        "finance_pending": _number("SELECT COUNT(*) AS n FROM finance_subscription_bills WHERE status='REVIEW'"),
    }


def usage_cost():
    from kilas_ai import economics
    summary = economics.admin_snapshot()
    since = (usage._now() - timedelta(days=30)).isoformat()
    summary["operations_by_type"] = db.query_all("SELECT operation_type,mode,COUNT(*) AS n,COALESCE(SUM(CAST(estimated_cost_usd AS NUMERIC)),0) AS cost FROM kilas_ai_usage WHERE status='COMPLETE' AND created_at>=? GROUP BY operation_type,mode ORDER BY n DESC", (since,))
    summary["capacity_revenue"] = db.query_one("SELECT COALESCE(SUM(amount_idr),0) AS total FROM kilas_ai_topup_orders WHERE status='VERIFIED' AND verified_at>=?", (since,))["total"]
    summary["capacity_allocation"] = db.query_one("SELECT COALESCE(SUM(c.total_micro),0) AS total FROM kilas_ai_topup_credits c JOIN kilas_ai_topup_orders o ON o.id=c.order_id WHERE o.verified_at>=?", (since,))["total"]
    summary["capacity_consumed"] = db.query_one("SELECT COALESCE(SUM(d.charged_micro),0) AS total FROM kilas_ai_topup_debits d WHERE d.status='COMPLETE' AND d.created_at>=?", (since,))["total"]
    fx = Decimal(os.environ.get("KILAS_AI_USD_IDR", "17000"))
    summary["cost_ratio"] = (summary["cost_usd"] * fx / Decimal(summary["revenue_idr"])) if summary["revenue_idr"] else None
    active_count = sum(int(item["n"]) for item in summary["active"])
    summary["cost_per_active_usd"] = summary["cost_usd"] / Decimal(active_count) if active_count else None
    summary["near_guard"] = []
    for row in db.query_all("SELECT u.id,u.email,s.plan,COALESCE(SUM(CAST(k.estimated_cost_usd AS NUMERIC)),0) AS cost "
            "FROM users u JOIN kilas_ai_subscriptions s ON s.user_id=u.id "
            "JOIN kilas_ai_usage k ON k.user_id=u.id AND k.status='COMPLETE' AND k.created_at>=s.period_start "
            "WHERE s.status='ACTIVE' AND s.period_end>? GROUP BY u.id,u.email,s.plan", (usage._now().isoformat(),)):
        ratio = Decimal(str(row["cost"] or 0)) * fx / Decimal(usage.PLANS[row["plan"]]["price"])
        if ratio >= Decimal("0.25"):
            summary["near_guard"].append({"id": row["id"], "email": row["email"], "ratio": ratio})
    summary["near_guard"].sort(key=lambda item: item["ratio"], reverse=True)
    return summary


def settings():
    return {"ai_enabled": os.environ.get("KILAS_AI_ENABLED", "").lower() in ("1", "true", "yes", "on"),
            "payment_review": "Manual, admin-only", "assist_visibility": "Disembunyikan dari navigasi utama"}