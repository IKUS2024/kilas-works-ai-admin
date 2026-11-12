"""Thirty-day paid access, separate from free trials, owner QA and provider guards.

Existing subscription records are authoritative. No request parameter, proof
upload or pending invoice is an access grant. Supplier cost records remain real.
"""
from . import usage


def active(user, conn=None, now=None):
    now = now or usage._now()
    if conn is not None:
        return usage._plan(conn, user, now)[0] in ('PLUS', 'PRO', 'MAX')
    row = usage.effective_plan(user)
    return row['status'] == 'ACTIVE' and row['plan'] in ('PLUS', 'PRO', 'MAX')


def mark_audio(conn, user, job, now):
    if active(user, conn, now):
        usage._query(conn, 'INSERT INTO kilas_paid_audio_grants(job_id,user_id,admitted_at) '
                     'VALUES (?,?,?) ON CONFLICT(job_id) DO NOTHING', (job, user, now.isoformat()))


def audio_granted(conn, user, job):
    # Settlement of already-admitted finite output is valid after expiry. New
    # turns still recheck active(); a grant is never inferred from zero reserve.
    return bool(usage._query(conn, 'SELECT 1 FROM kilas_paid_audio_grants WHERE job_id=? AND user_id=?',
                             (job, user), one=True))
