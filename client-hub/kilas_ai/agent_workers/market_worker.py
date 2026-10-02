"""Read-only injectable market adapter. No trading or model-generated observations."""
import math
from datetime import datetime, timezone
from typing import Protocol
from . import Result


class MarketProvider(Protocol):
    def observe(self, symbol: str, timeframe: str) -> dict: ...


provider: MarketProvider | None = None


def run(job, step, data):
    if provider is None:
        return Result('WAITING_CAPABILITY', 'Market data provider is not configured.', {'reason': 'provider_not_configured'})
    observation = provider.observe(data['symbol'], data['timeframe'])
    for key in ('symbol', 'provider', 'provider_timestamp', 'timeframe', 'open', 'high', 'low', 'close'):
        if key not in observation:
            raise ValueError('invalid_market_observation')
    observed_at = datetime.fromisoformat(observation['provider_timestamp'].replace('Z', '+00:00'))
    if observed_at.tzinfo is None or abs((datetime.now(timezone.utc) - observed_at).total_seconds()) > 86400:
        raise ValueError('stale_market_observation')
    if observation['symbol'] != data['symbol'] or observation['timeframe'] != data['timeframe'] or not observation['provider']:
        raise ValueError('market_identity_mismatch')
    values = [observation[k] for k in ('open', 'high', 'low', 'close')]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('invalid_market_price')
    if observation['low'] > min(values) or observation['high'] < max(values) or data['operator'] not in ('lt', 'gt'):
        raise ValueError('invalid_market_condition')
    matched = observation['close'] < data['threshold'] if data['operator'] == 'lt' else observation['close'] > data['threshold']
    condition = {'operator': data['operator'], 'threshold': data['threshold']}
    return Result('SUCCEEDED' if matched else 'WAITING', 'Sinyal terverifikasi dari provider.' if matched else 'Belum ada sinyal.',
                  {'facts': observation, 'computed_indicators': {}, 'strategy_conditions': [condition],
                   'conditions_met': [condition] if matched else [], 'conditions_not_met': [] if matched else [condition], 'signal': matched},
                  verified=True, delay=job['interval_seconds'])
