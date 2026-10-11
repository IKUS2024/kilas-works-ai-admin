"""Pinned local DEMO identity and receipt liveness; no SDK attachment or orders."""
import ntpath
import time
from decimal import Decimal

EXE = r'C:\Program Files\MetaTrader 5\terminal64.exe'
DATA = 'REVIEW_REQUIRED_LOCAL_DEMO_DATA_PATH'
SERVER = 'XMGlobal-MT5 10'
RECEIPT_POLICY = 'DEMO_SMOKE_RECEIPT_LIVENESS_V1'
RECEIPT_WINDOW, RECEIPT_MAX_AGE = 15., 1.5

class Stop(Exception):
    pass

def need(condition, reason):
    if not condition:
        raise Stop(reason)

def decimal(value):
    need(type(value) in (int, float, str, Decimal) and not isinstance(value, bool), 'INVALID_NUMBER')
    result = Decimal(str(value))
    need(result.is_finite(), 'INVALID_NUMBER')
    return result

def path(value):
    return ntpath.normcase(ntpath.normpath(value))

class DemoReceiptLiveness:
    """DEMO smoke transport evidence only: no offset or absolute age assertion."""
    def __init__(self, now=None):
        self.now = now or time.perf_counter
        self.last_raw = None
        self.advances = []
        self.established = False
    def __call__(self, tick):
        now = self.now()
        need(type(tick.time_msc) is int and tick.time_msc > 0 and tick.time_msc // 1000 == tick.time, 'TICK_TIME_INVALID')
        need(self.last_raw is None or tick.time_msc >= self.last_raw, 'TICK_TIMESTAMP_REGRESSED')
        if self.last_raw is None or tick.time_msc > self.last_raw:
            self.advances.append((tick.time_msc, now))
            self.last_raw = tick.time_msc
        self.advances = [(raw, receipt) for raw, receipt in self.advances if 0 <= now-receipt <= RECEIPT_WINDOW]
        age = now-self.advances[-1][1] if self.advances else float('inf')
        verified = len(self.advances) >= 3 and 0 <= age < RECEIPT_MAX_AGE
        warmup = not self.established and not verified
        self.established = self.established or verified
        return dict(verified=verified, warmup_required=warmup, receipt_age_seconds=age if age != float('inf') else RECEIPT_WINDOW+1,
                    distinct_observations=len(self.advances), policy=RECEIPT_POLICY, raw_time_msc=tick.time_msc,
                    absolute_source_age_verified=False, timezone_correction_applied=False,
                    reason='QUOTE_LIVENESS_NOT_ESTABLISHED' if warmup else 'QUOTE_RECEIPT_STALE_OR_FROZEN')

def one_terminal_running():
    from terminal_process_guard import inspect_terminal
    return inspect_terminal(EXE)['verified']

