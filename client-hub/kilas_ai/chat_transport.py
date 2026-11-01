"""Bounded Chat transport; never retry an uncertain provider dispatch.

HTTP callers can time out/cancel even when a provider stalls. A transport slot is
held until its producer actually exits, so stalled sockets cannot spawn an
unbounded number of threads or new billable requests. Native read timeout is 30s.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import queue
import threading
import time

TOTAL_SECONDS = 180
FIRST_TEXT_SECONDS = 60
IDLE_SECONDS = 45
_slots = threading.BoundedSemaphore(2)
_cancelled = ContextVar('chat_cancelled', default=lambda: False)


@contextmanager
def cancellation(check):
    token = _cancelled.set(check)
    try:
        yield
    finally:
        _cancelled.reset(token)


class Control:
    def __init__(self):
        self.started = self.last_text = time.monotonic()
        self.has_text = False
        self.stopped = threading.Event()

    def check(self, force=False):
        from .providers import ProviderError
        now = time.monotonic()
        if self.stopped.is_set():
            raise ProviderError('chat_cancelled')
        if (now-self.started >= TOTAL_SECONDS or
                now-self.last_text >= (IDLE_SECONDS if self.has_text else FIRST_TEXT_SECONDS)):
            raise ProviderError('chat_timeout')

    def timeout(self, connect=5, read=30):
        self.check()
        left = max(.1, TOTAL_SECONDS-(time.monotonic()-self.started))
        return min(connect, left), min(read, left)


def bounded(factory):
    from .providers import ProviderError
    slots = _slots
    if not slots.acquire(blocking=False):
        raise ProviderError('chat_capacity')
    control, updates = Control(), queue.Queue(maxsize=32)
    cancelled = _cancelled.get()
    dispatch_ack = threading.Event()

    def publish(value):
        while not control.stopped.is_set():
            try:
                updates.put(value, timeout=.1)
                return
            except queue.Full:
                control.check()

    def produce():
        source = None
        try:
            source = factory(control)
            for event in source:
                control.check()
                if event.get('type') == 'delta' and event.get('text'):
                    control.has_text = True
                    control.last_text = time.monotonic()
                publish(('event', event))
                if event.get('type') == 'provider':
                    while not dispatch_ack.wait(.1):
                        control.check()
            publish(('end', None))
        except Exception as error:
            publish(('error', error))
        finally:
            try:
                if source is not None and hasattr(source, 'close'):
                    source.close()
            finally:
                # Producer owns its DB connection; never close a request's one.
                import db
                db._discard_cached_connection()
                slots.release()

    try:
        threading.Thread(target=produce, name='chat-provider', daemon=True).start()
        while True:
            if cancelled():
                raise ProviderError('chat_cancelled')
            control.check()
            try:
                kind, value = updates.get(timeout=.1)
            except queue.Empty:
                continue
            if kind == 'end':
                return
            if kind == 'error':
                raise value
            if value.get('type') == 'provider':
                dispatch_ack.set()
            yield value
    finally:
        control.stopped.set()
