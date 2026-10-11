"""Explicit logical/cloud/broker symbol mapping, with broker-supplied units.

Profiles are metadata, not strategy, risk policy or execution authorization.
GOLD execution remains unreviewed. Never infer aliases or contract multipliers.
"""
from dataclasses import dataclass
from decimal import Decimal, DecimalException, Inexact, localcontext
from types import MappingProxyType
from demo_auto_controller import Blocked,number

@dataclass(frozen=True)
class InstrumentMapping:
    logical: str
    model_symbol: str
    broker_symbol: str
    order_transport_supported: bool=False

MAPPINGS=MappingProxyType({'BTC':InstrumentMapping('BTC','BTCUSD','BTCUSD',True),
          'GOLD':InstrumentMapping('GOLD','XAUUSD','GOLD',False)})

def mapping(logical):
    if type(logical) is not str or logical not in MAPPINGS: raise Blocked('INSTRUMENT_MAPPING_UNREVIEWED')
    return MAPPINGS[logical]

def _broker_number(value):
    # Reject bools and objects with invented string conversions as broker data.
    if type(value) not in (int, float, str, Decimal):
        raise Blocked('BROKER_NUMBER_INVALID')
    try:
        return number(value)
    except (Blocked, DecimalException):
        raise Blocked('BROKER_NUMBER_INVALID') from None


def _on_grid(value, step, code):
    try:
        valid = value % step == 0
    except DecimalException:
        valid = False
    if not valid:
        raise Blocked(code)


def broker_specs(info):
    """Validate broker units without substituting instrument or UI defaults.

    Volume maximum is an inclusive bound, so it need not be a step multiple.
    Stops/freeze values are integer counts of broker points, not price units.
    These facts do not establish quote freshness, an open session or readiness.
    """
    fields = dict(volume_min='volume_min', volume_max='volume_max',
                  volume_step='volume_step', contract_size='trade_contract_size',
                  point='point', tick_size='trade_tick_size')
    values = {key: _broker_number(getattr(info, source, None))
              for key, source in fields.items()}
    if values['volume_min'] > values['volume_max']:
        raise Blocked('BROKER_VOLUME_SPEC_INVALID')
    _on_grid(values['volume_min'], values['volume_step'],
             'BROKER_VOLUME_SPEC_INVALID')
    _on_grid(values['tick_size'], values['point'], 'BROKER_PRICE_SPEC_INVALID')
    for source, code in (('trade_stops_level', 'STOPS_INVALID'),
                         ('trade_freeze_level', 'FREEZE_INVALID')):
        value = getattr(info, source, None)
        if type(value) is not int or value < 0:
            raise Blocked(code)
        values[source + '_points'] = value
    return values


def broker_facts(profile, info):
    if (type(profile) is not InstrumentMapping
            or any(type(value) is not str for value in
                   (profile.logical, profile.model_symbol, profile.broker_symbol))
            or type(profile.order_transport_supported) is not bool
            or profile != mapping(profile.logical)):
        raise Blocked('INSTRUMENT_MAPPING_UNREVIEWED')
    if (type(getattr(info, 'name', None)) is not str
            or info.name != profile.broker_symbol
            or getattr(info, 'custom', None) is not False
            or type(getattr(info, 'currency_profit', None)) is not str
            or info.currency_profit != 'USD'
            or type(getattr(info, 'currency_margin', None)) is not str
            or info.currency_margin != 'USD'):
        raise Blocked('BROKER_SYMBOL_OR_UNITS_UNVERIFIED')
    specs = broker_specs(info)
    return dict(logical=profile.logical, model_symbol=profile.model_symbol,
        broker_symbol=info.name,
        **{key: str(value) if isinstance(value, Decimal) else value
           for key, value in specs.items()},
        currency_profit=info.currency_profit, currency_margin=info.currency_margin,
        order_transport_supported=profile.order_transport_supported)

def minimum_notional(info,ask):
    """Exact minimum broker exposure, with no execution or cap approval."""
    name = getattr(info, 'name', None)
    if type(name) is not str:
        raise Blocked('BROKER_SYMBOL_OR_UNITS_UNVERIFIED')
    profile = next((value for value in MAPPINGS.values()
                    if value.broker_symbol == name), None)
    if profile is None:
        raise Blocked('BROKER_SYMBOL_OR_UNITS_UNVERIFIED')
    facts = broker_facts(profile, info)
    ask = _broker_number(ask)
    _on_grid(ask, Decimal(facts['tick_size']), 'BROKER_QUOTE_GRID_INVALID')
    try:
        # A rounded-down notional must never pass a strict exposure ceiling.
        with localcontext() as context:
            context.traps[Inexact] = True
            return Decimal(facts['volume_min']) * Decimal(facts['contract_size']) * ask
    except DecimalException:
        raise Blocked('BROKER_NUMBER_INVALID') from None

def price_distance_for_usd(display_usd,profit_for_one_price_unit):
    # Display only. Executable SL/TP must use broker calculation, ticks, fees,
    # deviation, stops/freeze levels and recheck the exact proposal afterwards.
    return number(display_usd)/number(abs(Decimal(str(profit_for_one_price_unit))))
