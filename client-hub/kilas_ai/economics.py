"""Read-only, admin-only Kilas AI usage summary for release economics."""
from datetime import timedelta
from decimal import Decimal

import db
from . import usage


def admin_snapshot():
    now = usage._now()
    since = (now - timedelta(days=30)).isoformat()
    active = db.query_all("SELECT plan,COUNT(*) AS n FROM kilas_ai_subscriptions "
                          "WHERE status='ACTIVE' AND period_end>? GROUP BY plan ORDER BY plan", (now.isoformat(),))
    estimated_revenue = sum(usage.PLANS[row["plan"]]["price"] * int(row["n"]) for row in active)
    totals = db.query_one("SELECT COUNT(*) AS operations,"
        "SUM(CASE WHEN estimated_cost_usd IS NULL THEN 1 ELSE 0 END) AS unknown,"
        "COALESCE(SUM(CAST(estimated_cost_usd AS NUMERIC)),0) AS cost,"
        "SUM(CASE WHEN operation_type='WEB_SEARCH' THEN 1 ELSE 0 END) AS web,"
        "SUM(CASE WHEN operation_type IN ('IMAGE_GENERATION','IMAGE_EDIT') THEN 1 ELSE 0 END) AS images "
        "FROM kilas_ai_usage WHERE status='COMPLETE' AND created_at>=?", (since,))
    models = db.query_all("SELECT provider,model,COUNT(*) AS operations,"
        "COALESCE(SUM(CAST(estimated_cost_usd AS NUMERIC)),0) AS cost "
        "FROM kilas_ai_usage WHERE status='COMPLETE' AND created_at>=? "
        "AND provider IS NOT NULL GROUP BY provider,model ORDER BY cost DESC LIMIT 8", (since,))
    users = db.query_all("SELECT u.email,COUNT(*) AS operations,"
        "COALESCE(SUM(CAST(k.estimated_cost_usd AS NUMERIC)),0) AS cost "
        "FROM kilas_ai_usage k JOIN users u ON u.id=k.user_id "
        "WHERE k.status='COMPLETE' AND k.created_at>=? "
        "GROUP BY u.id,u.email ORDER BY cost DESC LIMIT 5", (since,))
    return {"active": active, "revenue_idr": estimated_revenue,
            "cost_usd": Decimal(str(totals["cost"] or 0)), "unknown": totals["unknown"] or 0,
            "operations": totals["operations"] or 0, "web": totals["web"] or 0,
            "images": totals["images"] or 0, "models": models, "users": users}
