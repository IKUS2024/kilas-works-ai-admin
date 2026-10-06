"""Pilot authorization uses current stored identity, never role/session email."""
import os
import db
import security
from flask import session

PILOT_EMAIL = 'irvankarnavi@gmail.com'


def enabled():
    return os.environ.get('KILAS_TRADING_ENABLED', 'true').lower() in ('true', '1', 'yes', 'on')


def is_pilot(user=None):
    user = user or security.current_user()
    if not enabled() or not user or session.get('support_business_id'):
        return False
    if str(user.get('email', '')).casefold() != PILOT_EMAIL:
        return False
    return bool(db.query_one("SELECT 1 FROM oauth_identities WHERE user_id=? AND provider='google' AND lower(email_at_link)=?", (user['id'], PILOT_EMAIL)))
