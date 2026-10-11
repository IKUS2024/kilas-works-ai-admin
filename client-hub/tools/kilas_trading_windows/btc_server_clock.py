"""Conservative server time from authenticated, bounded HTTP receipt samples.

The caller validates transport authentication and the complete response before
observing it. No PC UTC or broker timezone assumption is used. An inconsistent
sample poisons this clock. A valid overlapping request's older receipt sample
is discarded, retaining the existing fresh clock and its bound.
"""
import math
from datetime import datetime, timedelta, timezone
from threading import RLock
from time import perf_counter


class ServerClockError(ValueError):
    pass


def _utc(value):
    if type(value) is str:
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ServerClockError('SERVER_CLOCK_TIMESTAMP_INVALID')
    return value.astimezone(timezone.utc)


class ServerClock:
    """QPC seconds, at most 1.5s RTT and 3s sample age by default.

    Fifty milliseconds scheduling margin plus 0.1% elapsed drift is charged to
    the server-now upper bound. Sample intervals account for either direction
    of network latency; inconsistent intervals reject instead of moving time.
    """
    def __init__(self, *, clock=perf_counter, max_rtt=1.5, max_age=3.0,
                 margin=0.05, discontinuity_tolerance=0.25, drift=0.001):
        values=(max_rtt,max_age,margin,discontinuity_tolerance,drift)
        if not all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in values):
            raise ServerClockError('SERVER_CLOCK_CONFIGURATION_INVALID')
        if not (0<max_rtt<=2 and 0<max_age<=5 and margin>0 and drift>0):
            raise ServerClockError('SERVER_CLOCK_CONFIGURATION_INVALID')
        self.clock=clock; self.max_rtt=max_rtt; self.max_age=max_age
        self.margin=margin; self.tolerance=discontinuity_tolerance; self.drift=drift
        self._sample=None; self._failed=False; self._last_mono=None; self._last_upper=None
        self._lock=RLock()

    @property
    def ready(self):
        with self._lock: return self._sample is not None and not self._failed

    def _reject(self,code):
        self._failed=True
        raise ServerClockError(code)

    def _mono(self,value):
        if type(value) not in (int,float) or not math.isfinite(value):
            self._reject('SERVER_CLOCK_MONOTONIC_INVALID')
        if self._last_mono is not None and value<self._last_mono:
            self._reject('SERVER_CLOCK_DISCONTINUITY')
        self._last_mono=value
        return value

    def observe(self,send_mono,receive_mono,server_received_at):
        """Record only a fully validated authenticated sync/evidence response."""
        with self._lock:
            if self._failed: raise ServerClockError('SERVER_CLOCK_DISCONTINUITY')
            try: received=_utc(server_received_at)
            except Exception: self._reject('SERVER_CLOCK_TIMESTAMP_INVALID')
            if not all(type(v) in (int,float) and math.isfinite(v) for v in (send_mono,receive_mono)):
                self._reject('SERVER_CLOCK_MONOTONIC_INVALID')
            if not 0<=receive_mono-send_mono<=self.max_rtt:
                self._reject('SERVER_CLOCK_SAMPLE_TOO_SLOW')
            now=self._mono(self.clock())
            if now<receive_mono: self._reject('SERVER_CLOCK_DISCONTINUITY')
            if self._sample is not None:
                old_send,old_receive,old_received=self._sample
                delta=(received-old_received).total_seconds()
                allowance=self.tolerance+self.drift*max(0,receive_mono-old_send)
                if not send_mono-old_receive-allowance<=delta<=receive_mono-old_send+allowance:
                    self._reject('SERVER_CLOCK_DISCONTINUITY')
                if receive_mono<old_receive or received<old_received:
                    # Independent sync/evidence lanes may receive/parse replies
                    # in a different order than the server received requests.
                    # Reject the superseded sample, not the still-valid clock.
                    # Sequential regressions remain a discontinuity.
                    if send_mono<old_receive and receive_mono>=old_send:
                        return self.upper_now()
                    self._reject('SERVER_CLOCK_DISCONTINUITY')
            self._sample=(send_mono,receive_mono,received)
            return self.upper_now()

    def upper_now(self, *, require_fresh=True):
        with self._lock:
            if self._failed: raise ServerClockError('SERVER_CLOCK_DISCONTINUITY')
            if self._sample is None: raise ServerClockError('SERVER_CLOCK_UNAVAILABLE')
            now=self._mono(self.clock())
            sent,received,server=self._sample
            if now<received: self._reject('SERVER_CLOCK_DISCONTINUITY')
            if require_fresh and now-received>=self.max_age:
                raise ServerClockError('SERVER_CLOCK_STALE')
            result=server+timedelta(seconds=(now-sent)*(1+self.drift)+self.margin)
            # Improving latency may narrow uncertainty but may not move a bound
            # already used for an eligibility check backwards.
            if self._last_upper is not None: result=max(result,self._last_upper)
            self._last_upper=result
            return result

    def deadline(self,value):
        """Convert one server expiry to a conservative local monotonic bound."""
        with self._lock:
            now=self.clock()
            upper=self.upper_now()
            remaining=(_utc(value)-upper).total_seconds()
            return now+remaining/(1+self.drift)

    def lower_now(self, *, require_fresh=True):
        """Earliest possible server time, for proving nonce expiry recovery."""
        with self._lock:
            # Share monotonic/freshness/discontinuity validation with entry time.
            self.upper_now(require_fresh=require_fresh)
            now=self._mono(self.clock())
            _,received,server=self._sample
            return server+timedelta(seconds=(now-received)*(1-self.drift)-self.margin)

    def fresh(self):
        try: self.upper_now(); return True
        except (ServerClockError,ValueError,OverflowError): return False
