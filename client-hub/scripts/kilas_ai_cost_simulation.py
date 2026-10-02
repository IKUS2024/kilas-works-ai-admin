"""Offline estimates from configured prices; no provider requests. Not observed usage."""
import json
import sys
from pathlib import Path
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from kilas_ai import usage, fair_use, model_policy


def simulate():
    report=[]
    for name,turns in (('LIGHT',100),('NORMAL',500),('HEAVY',2000),('EXTREME',10000)):
        # Illustrative bounded mixed turns: not a prediction of customer usage.
        incoming,cached,outgoing=2400,1200,650
        per_turn=Decimal(usage.estimate(model_policy.LUNA,incoming,outgoing,'CHAT',cached_input_tokens=cached))
        cost=per_turn*turns
        revenue=fair_use.revenue_usd(99000)
        ceiling=fair_use.sustainability_ceiling(99000)
        # Sequential bounded requests: stop BEFORE the next call once settled cost reaches the ceiling.
        permitted=turns
        if per_turn > 0:
            from decimal import ROUND_CEILING
            permitted=min(turns,int((ceiling/per_turn).to_integral_value(rounding=ROUND_CEILING)))
        enforced=per_turn*permitted
        report.append(dict(scenario=name,turns=turns,input_tokens=incoming*turns,
            cached_input_tokens=cached*turns,output_tokens=outgoing*turns,
            provider_cost_usd=str(cost),retail_idr=99000,cost_revenue_percent=str((cost/revenue*100).quantize(Decimal('.01'))),
            cost_level=fair_use.cost_level(cost,99000),
            policy_enforced={'provider_calls':permitted,'denied_turns':turns-permitted,
                'provider_cost_usd':str(enforced),'cost_revenue_percent':str((enforced/revenue*100).quantize(Decimal('.01'))),
                'sustainability_ceiling_usd':str(ceiling),'stopped_at_ceiling':permitted<turns}))
    return report


if __name__=='__main__':
    print(json.dumps({'label':'SIMULATION ONLY / NOT OBSERVED CUSTOMER USAGE / NOT AN OFFICIAL PROVIDER INVOICE',
        'assumptions':'Unthrottled baseline and policy-enforced sequential requests: 2400 input / 1200 cached / 650 output per turn; existing configured rate estimates; cached tokens billed at input rate unless configured separately','scenarios':simulate()},indent=2))
