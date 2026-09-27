"""Assist presentation and demo lifecycle, using existing onboarding events.

Reading a workspace never starts a trial, calls a model, or provisions Finance.
Subscription, WhatsApp mapping and knowledge keep their existing authorities.
"""
import json
from datetime import datetime, timedelta, timezone

import db
import repo
import subscription_service

DEMO_STEP = 'assist_demo_started'
SETUP_EVENT = 'assist_setup_complete'
ONBOARDING_PARTS = ('basics', 'services', 'operations', 'faq', 'style', 'upload')


def _event(bid, step):
    row = db.query_one('SELECT raw_payload_json FROM onboarding_sessions '
                       'WHERE business_id=? AND step=? ORDER BY id DESC LIMIT 1', (bid, step))
    if not row:
        return None
    return repo._coerce_json_column(row['raw_payload_json'], dict)


def onboarding_complete(bid):
    status = repo.get_onboarding_status(bid) or {}
    return bool(_event(bid, SETUP_EVENT)) or all(status.get(part + '_done') for part in ONBOARDING_PARTS)


def start_demo(bid, actor):
    """One seven-day demo per business; retry or further onboarding edits cannot renew it."""
    with db.app_purchase_transaction(bid, None):
        if not onboarding_complete(bid):
            raise ValueError('onboarding_incomplete')
        if not _event(bid, DEMO_STEP):
            now = datetime.now(timezone.utc)
            repo.save_onboarding_session(bid, DEMO_STEP, {
                'started_at': now.isoformat(),
                'expires_at': (now + timedelta(days=7)).isoformat(),
            }, actor)
            repo.write_audit(actor, bid, 'ASSIST_DEMO_STARTED', 'Seven-day demo; no paid entitlement')
    return state(repo.get_business(bid))


def state(business):
    bid = business['id']
    settings = repo.get_ai_settings(bid) or {}
    onboarding = repo.get_onboarding_status(bid) or {}
    trained = settings.get('ai_status') == 'DONE'
    ready_event = _event(bid, 'assist_ready')
    import assist_demo
    bound = assist_demo.active_binding(bid)
    ready = bool(ready_event or bound)
    training_started = bool(_event(bid, 'assist_teach') or _event(bid, 'assist_test'))
    wa = repo.get_whatsapp_config(bid) or {}
    connected = (business.get('status') == 'ACTIVE' and wa.get('connection_status') == 'CONNECTED'
                 and bool(wa.get('phone_number_id')) and bool(wa.get('validated_at')))
    readiness = ('Siap melayani' if ready or connected else
                 'Sedang dilatih' if training_started or trained or settings.get('ai_status') == 'STALE'
                 else 'Belum dilatih')
    subscription = subscription_service.get_subscription(bid) or {}
    entitlement_end = subscription_service._parse(subscription.get('period_end'))
    if subscription.get('status') == 'GRACE':
        grace_start = subscription_service._parse(subscription.get('grace_started_at')) or entitlement_end
        entitlement_end = (grace_start + timedelta(days=subscription.get('grace_days') or 0)) if grace_start else None
    paid = (subscription.get('status') in ('ACTIVE', 'GRACE') and entitlement_end
            and entitlement_end > datetime.now(timezone.utc))
    event = _event(bid, DEMO_STEP)
    expires = subscription_service._parse(event.get('expires_at')) if event else None
    active = bool(expires and expires > datetime.now(timezone.utc))
    return dict(readiness=readiness, ready=readiness == 'Siap melayani',
                onboarding_complete=onboarding_complete(bid), connected=bool(connected),
                whatsapp='Terhubung' if connected else 'Menunggu dihubungkan' if paid else 'Belum terhubung',
                demo_started=bool(event), demo_active=active, demo_expires_at=expires,
                demo_visible=not connected, demo_bound=bool(bound), paid=bool(paid), subscription=subscription)
