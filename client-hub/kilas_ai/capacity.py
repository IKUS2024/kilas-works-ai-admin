"""Private shared premium ledger, using the existing locked usage transaction."""
import os
from datetime import timedelta
from decimal import Decimal, InvalidOperation


def allowance():
    fx = Decimal(os.environ.get('KILAS_AI_USD_IDR', '17000'))
    if not fx.is_finite() or fx <= 0:
        raise ValueError('invalid_capacity_configuration')
    return Decimal(35000) / fx


def premium(operation, mode, thread_id, key, model=None):
    from . import fair_use
    return (operation != 'CHAT' or mode in ('SMART', 'EXPERT')
            or (model and '-sol' in model)
            or not fair_use.normal_chat(thread_id, key, 'CHAT'))


def forecast(operation, mode, profile=None):
    from . import usage
    if operation == 'CHAT' and profile:
        value = usage.estimate(profile['model'], 12000, profile['output_tokens'], 'CHAT')
        if value is not None:
            return Decimal(value)
    # Bounded search includes synthesis and up to five technical search calls.
    if operation == 'WEB_SEARCH':
        return Decimal('0.12')
    if operation == 'CHAT' and mode in ('SMART', 'EXPERT'):
        return Decimal('0.18')
    if operation == 'CHAT':
        return Decimal('0.025')
    return {'IMAGE_GENERATION': Decimal('0.08'), 'IMAGE_EDIT': Decimal('0.08'),
            'PDF': Decimal('0.04')}.get(operation, Decimal('0.08'))


def level(consumed):
    ratio = max(Decimal(0), consumed) / allowance()
    return 'PROTECTION' if ratio >= 1 else 'HEAVY' if ratio >= Decimal('0.9') else 'WATCH' if ratio >= Decimal('0.7') else 'GREEN'


def spent(conn, user_id, start, now):
    from . import usage
    rows = usage._rows(conn, "SELECT operation_type,mode,thread_id,operation_key,model,"
        "estimated_cost_usd,status FROM kilas_ai_usage WHERE user_id=? AND quota_source='BASE' "
        "AND created_at>=? AND (status IN ('COMPLETE','FAILED') OR "
        "(status='PENDING' AND created_at>=?))",
        (user_id, start.isoformat(), (now-timedelta(minutes=10)).isoformat()))
    total = Decimal(0)
    for operation, mode, thread, key, model, cost, status in rows:
        if not premium(operation, mode, thread, key, model):
            continue
        if status == 'FAILED' and cost is None:
            continue  # No evidence of a billed call; do not invent a failure cost.
        try:
            value = Decimal(str(cost)) if cost is not None else forecast(operation, mode)
            total += value if value.is_finite() and value >= 0 else forecast(operation, mode)
        except InvalidOperation:
            total += forecast(operation, mode)
    return total


def summary(user_id):
    """Only safe public state leaves this module, never raw costs/models/QA grants."""
    from . import usage, topups
    conn = usage._connect()
    try:
        now = usage._now()
        plan, start, end = usage._plan(conn, user_id, now)
        exempt = usage._qa_quota_exempt(conn, user_id, now)
        remaining = Decimal(0)
        if plan != 'FREE':
            cycle = usage._period(plan, start, end, 'CHAT', now)[0]
            remaining = max(Decimal(0), allowance()-spent(conn, user_id, cycle, now))
        extra = sum(max(0, int(total)-int(used)) for _, total, used in topups._lots(conn, user_id, now))
        if exempt:
            label = 'Cukup'
        elif plan == 'FREE':
            label = 'Habis'
        elif extra or remaining > allowance()*Decimal('0.1'):
            label = 'Cukup'
        elif remaining > 0:
            label = 'Menipis'
        else:
            label = 'Habis'
        return {'state': label, 'available': label != 'Habis', 'active': plan != 'FREE',
                'has_topup': bool(extra)}
    finally:
        conn.close()
