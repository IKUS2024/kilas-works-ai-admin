"""Internal paid Chat cost tiers. No billing allowance or permanent ban."""
import os
from decimal import Decimal, InvalidOperation


def setting(name, default, minimum='0.01', maximum='1000000'):
    try:
        value = Decimal(os.environ.get(name, default))
        if value.is_finite() and Decimal(minimum) <= value <= Decimal(maximum):
            return value
    except InvalidOperation:
        pass
    return Decimal(default)


def thresholds():
    soft = setting('KILAS_AI_CHAT_SOFT_COST_RATIO','0.16','0.01','1')
    heavy = max(soft,setting('KILAS_AI_CHAT_HEAVY_COST_RATIO','0.24','0.01','1'))
    protection = max(heavy,setting('KILAS_AI_CHAT_PROTECTION_COST_RATIO','0.30','0.01','1'))
    return soft,heavy,protection


def revenue_usd(retail):
    return Decimal(str(retail))/setting('KILAS_AI_USD_IDR','17000','1000','100000')


def sustainability_ceiling(retail):
    ratio = setting('KILAS_AI_CHAT_SUSTAINABILITY_COST_RATIO','0.35','0.20','0.60')
    protection = thresholds()[2]
    if protection > Decimal('0.60'):
        raise ValueError('incompatible_fair_use_thresholds')
    return revenue_usd(retail)*max(ratio,protection)


def cost_level(cost, retail):
    revenue = revenue_usd(retail)
    ratio = Decimal(str(cost))/revenue if revenue else Decimal(0)
    soft,heavy,protection = thresholds()
    return 'PROTECTION' if ratio >= protection else 'VERY_HEAVY' if ratio >= heavy else 'HEAVY' if ratio >= soft else 'NORMAL'


def budgets(level):
    # Commercial capacity never weakens conversation grounding or response depth.
    return (16,32000,3)


def normal_chat(thread_id, key, tool):
    return tool == 'CHAT' and (thread_id is not None or (key.startswith('agent-chat-') and not key.startswith('agent-chat-video-')))
