"""Exact wire profiles reviewed against cloud release db035b5; no authority."""
from dataclasses import dataclass
from types import MappingProxyType
from demo_auto_controller import Blocked


@dataclass(frozen=True)
class WireInstrument:
    instrument: str
    symbol: str
    provider: str
    coverage: str
    evidence_path: str
    analysis_path: str


BASE = '/products/services/trading/control/'
PROFILES = MappingProxyType({
    'BTC': WireInstrument('BTC','BTCUSD','TRUSTED_BTC_V1','BTC_EDITORIAL_ONLY',
                          BASE+'btc-evidence',BASE+'btc-analysis'),
    'GOLD': WireInstrument('GOLD','GOLD','TRUSTED_GOLD_V1','GOLD_MACRO_CALENDAR',
                           BASE+'gold-evidence',BASE+'gold-analysis'),
})


def wire_profile(instrument):
    if type(instrument) is not str or instrument not in PROFILES:
        raise Blocked('WIRE_INSTRUMENT_UNREVIEWED')
    return PROFILES[instrument]
