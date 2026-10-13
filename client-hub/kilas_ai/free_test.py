"""Server-owned, fixed-end app sponsorship; never a role or provider-credit grant."""
import json
import os
from datetime import datetime, timezone
import db

# Explicit owner authorization; login, deployment and month changes cannot renew it.
END_AT = datetime(2026, 12, 11, 16, 59, tzinfo=timezone.utc)
STT_END_AT = datetime(2026, 11, 1, tzinfo=timezone.utc)


def active(now=None):
    if os.environ.get('KILAS_APP_FREE_TEST_ENABLED', '').lower() not in ('1', 'true', 'on'):
        return False
    try:
        cutoff = datetime.fromisoformat(os.environ['KILAS_APP_FREE_TEST_END_AT'].replace('Z', '+00:00'))
        now = now or datetime.now(timezone.utc)
        return bool(cutoff.tzinfo and now.tzinfo and cutoff == END_AT and now < END_AT)
    except (KeyError, ValueError, TypeError):
        return False


def eligible(user, conn=None, now=None):
    if type(user) is not int or user <= 0 or not active(now):
        return False
    from . import usage
    row = (usage._query(conn, 'SELECT id FROM users WHERE id=?', (user,), one=True)
           if conn is not None else db.query_one('SELECT id FROM users WHERE id=?', (user,)))
    return bool(row)


def speech_audience(user, config, *, allow_unscoped=True):
    """Audience expansion reuses verified funding, with its separately fixed expiry."""
    if not config:
        return False
    if active():
        if datetime.now(timezone.utc) >= STT_END_AT or not eligible(user):
            return False
        # Persisted proof is key-, account-, model- and campaign-bound; no paid read.
        from . import live_translator_realtime_check
        return live_translator_realtime_check.verified()
    return config['allowed_owner'] == user or (allow_unscoped and config['allowed_owner'] is None)


def mark_audio(conn, user, ident, now):
    if eligible(user, conn, now):
        from . import usage
        usage._query(conn, 'INSERT INTO kilas_free_test_audio(job_id,user_id,end_at) VALUES (?,?,?) ON CONFLICT(job_id) DO NOTHING',
                     (ident, user, END_AT.isoformat()))


def sponsored_audio(conn, user, ident):
    from . import usage
    return bool(usage._query(conn, 'SELECT 1 FROM kilas_free_test_audio WHERE job_id=? AND user_id=? AND end_at=?',
                            (ident, user, END_AT.isoformat()), one=True))


def report():
    # Configuration-only: no users, prompts, secrets or provider calls in logs.
    value={'active':active(), 'end_at':END_AT.isoformat(), 'audience':'authenticated',
           'stt_funding_end_at':STT_END_AT.isoformat()}
    try:
        if active():
            from . import learning, live_translator, audio_transcription_budget as budget
            config=budget.policy()
            row=db.query_one("SELECT id FROM users WHERE role='CLIENT_OWNER' AND id<>? ORDER BY id LIMIT 1", ((config or {}).get('allowed_owner',0),))
            user=row['id'] if row else None
            value.update(nonowner_checked=bool(row), nonowner_app_eligible=eligible(user),
                         nonowner_learning_ready=learning.ready(user), nonowner_translator_ready=live_translator.ready(user),
                         nonowner_stt_ready=budget.ready(user))
    except Exception:
        value["report_available"]=False
    print('KILAS_APP_FREE_TEST '+json.dumps(value,sort_keys=True),flush=True)
