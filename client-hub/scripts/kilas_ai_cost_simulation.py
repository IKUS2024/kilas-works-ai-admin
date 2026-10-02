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
        cost=Decimal(usage.estimate(model_policy.LUNA,incoming,outgoing,'CHAT',cached_input_tokens=cached))*turns
        revenue=Decimal(99000)/fair_use.setting('KILAS_AI_USD_IDR','17000')
        report.append(dict(scenario=name,turns=turns,input_tokens=incoming*turns,
            cached_input_tokens=cached*turns,output_tokens=outgoing*turns,
            provider_cost_usd=str(cost),retail_idr=99000,cost_revenue_percent=str((cost/revenue*100).quantize(Decimal('.01'))),
            cost_level=fair_use.cost_level(cost,99000)))
    return report


if __name__=='__main__':
    print(json.dumps({'assumptions':'2400 input / 1200 cached / 650 output per turn; existing configured rate estimates, not actual usage; cached tokens billed at input rate unless configured separately','scenarios':simulate()},indent=2))
