"""Non-blocking Core CRM/Jobs maintenance for owner navigation.

Owner GET routes must stay fast. Slow Customer Insight/model work runs on one bounded daemon
executor so a page render never waits on AI. Database connections are thread-local, and all
underlying Customer/Job services remain idempotent and tenant-scoped.
"""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from flask import current_app

import platform_workspace
from kilas_core import customer_action_jobs, customers

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kilas-core-bg")
_guard = threading.Lock()
_inflight = set()
_last_started = {}


def _testing():
    try:
        return bool(current_app.config.get("TESTING"))
    except RuntimeError:
        return False


def _run(key, fn, args):
    try:
        fn(*args)
    except Exception:
        # Background enrichment must never affect navigation or crash the worker.
        pass
    finally:
        with _guard:
            _inflight.discard(key)


def _submit(key, fn, args=(), min_interval=20):
    if _testing():
        return False
    now = time.monotonic()
    with _guard:
        if key in _inflight:
            return False
        last = _last_started.get(key, 0.0)
        if now - last < max(0, min_interval):
            return False
        _last_started[key] = now
        _inflight.add(key)
    try:
        _executor.submit(_run, key, fn, args)
        return True
    except Exception:
        with _guard:
            _inflight.discard(key)
        return False


def _refresh_business(business, actor_id):
    business = dict(business or {})
    bid = business.get("id")
    if not bid:
        return
    if platform_workspace.is_scope_business(bid):
        try:
            scope, _ = platform_workspace.sync_contacts()
            if scope:
                business = dict(scope)
        except Exception:
            pass
        try:
            customer_action_jobs.reconcile_actionable_platform_leads(
                business, actor_id=actor_id, limit=10
            )
        except Exception:
            pass
    else:
        try:
            customers.sync_demo_binding_lead(bid)
        except Exception:
            pass

    try:
        customer_action_jobs.prune_invalid_lead_jobs(bid)
    except Exception:
        pass
    try:
        customer_action_jobs.reconcile_business(business, limit=10)
    except Exception:
        pass


def schedule_business_refresh(business, actor_id=None):
    bid = (business or {}).get("id")
    if not bid:
        return False
    return _submit(
        ("business", int(bid)),
        _refresh_business,
        (dict(business), actor_id),
        min_interval=30,
    )


def _refresh_customer(business, customer_id, actor_id):
    business = dict(business or {})
    bid = business.get("id")
    if not bid or not customer_id:
        return
    try:
        customer = customers.get_customer(bid, customer_id)
        customer_action_jobs.refresh_and_sync(
            business, customer, actor_id=actor_id
        )
    except Exception:
        pass


def schedule_customer_refresh(business, customer_id, actor_id=None):
    bid = (business or {}).get("id")
    if not bid or not customer_id:
        return False
    return _submit(
        ("customer", int(bid), str(customer_id)),
        _refresh_customer,
        (dict(business), str(customer_id), actor_id),
        min_interval=15,
    )
