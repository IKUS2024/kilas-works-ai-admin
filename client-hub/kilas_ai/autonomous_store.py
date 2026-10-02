"""Durable owner-scoped jobs. Lease tokens fence stale writers after recovery/control."""
import hashlib
import json
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import db
from . import usage

TERMINAL = ('COMPLETED', 'FAILED', 'STOPPED')
ELIGIBLE = ('PLANNING', 'RUNNING', 'WAITING')


def now():
    return datetime.now(timezone.utc)


def stamp(value=None):
    return (value or now()).isoformat()


def encode(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(text.encode()) > 48000:
        raise ValueError('output_too_large')
    return text


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


@contextmanager
def transaction():
    conn = usage._connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def event(conn, job_id, kind, summary, key=None, unread=True):
    usage._query(conn, 'INSERT INTO kilas_agent_events(job_id,kind,summary,event_key,unread,created_at) VALUES (?,?,?,?,?,?) ON CONFLICT(event_key) DO NOTHING',
                 (job_id, kind, str(summary)[:2000], key, int(unread), stamp()))


def get(user_id, job_id):
    row = db.query_one('SELECT * FROM kilas_agent_jobs WHERE id=? AND user_id=?', (job_id, user_id))
    return dict(row) if row else None


def list_jobs(user_id, conversation_id=None, active_only=False):
    where, params = 'user_id=?', [user_id]
    if conversation_id is not None:
        where += ' AND origin_conversation_id=?'
        params.append(conversation_id)
    if active_only:
        where += " AND status NOT IN ('COMPLETED','FAILED','STOPPED')"
    else:
        where += " AND (status NOT IN ('COMPLETED','FAILED','STOPPED') OR id IN (SELECT id FROM kilas_agent_jobs WHERE user_id=? AND status IN ('COMPLETED','FAILED','STOPPED') ORDER BY id DESC LIMIT 8))"
        params.append(user_id)
    order = "CASE WHEN status IN ('COMPLETED','FAILED','STOPPED') THEN 1 ELSE 0 END,id DESC"
    return [dict(row) for row in db.query_all('SELECT j.*,(SELECT COUNT(*) FROM kilas_agent_steps s WHERE s.job_id=j.id AND s.status=\'SUCCEEDED\') AS done,(SELECT COUNT(*) FROM kilas_agent_steps s WHERE s.job_id=j.id) AS total,(SELECT instruction FROM kilas_agent_steps s WHERE s.job_id=j.id AND s.status NOT IN (\'SUCCEEDED\',\'SKIPPED\',\'STOPPED\') ORDER BY sequence LIMIT 1) AS current_step FROM kilas_agent_jobs j WHERE ' + where + ' ORDER BY ' + order + ' LIMIT 30', tuple(params))]


def steps(job_id):
    return [dict(row) for row in db.query_all('SELECT * FROM kilas_agent_steps WHERE job_id=? ORDER BY sequence', (job_id,))]


def create(user_id, instruction, *, mode='ONE_SHOT', constraints=None, wake_at=None, interval=3600, expires_at=None, conversation_id=None, schedule=None):
    from .autonomous_planner import MODES
    if mode not in MODES or not isinstance(instruction, str) or not 1 <= len(instruction.strip()) <= 1200:
        raise ValueError('invalid_job')
    if not 300 <= int(interval) <= 2592000:
        raise ValueError('invalid_interval')
    with transaction() as conn:
        if conversation_id is not None and not usage._query(conn, 'SELECT id FROM kilas_ai_conversations WHERE id=? AND user_id=?', (conversation_id, user_id), one=True):
            raise ValueError('conversation_not_owned')
        if db.BACKEND == 'postgres':
            usage._query(conn, 'SELECT id FROM users WHERE id=? FOR UPDATE', (user_id,), one=True)
        count = usage._query(conn, "SELECT COUNT(*) FROM kilas_agent_jobs WHERE user_id=? AND status NOT IN ('COMPLETED','FAILED','STOPPED')", (user_id,), one=True)[0]
        if count >= 20:
            raise ValueError('active_job_limit')
        job_id = usage._query(conn, 'INSERT INTO kilas_agent_jobs(user_id,title,instruction,mode,status,constraints_json,next_wake_at,interval_seconds,expires_at) VALUES (?,?,?,?,?,?,?,?,?) RETURNING id',
                              (user_id, instruction[:90], instruction.strip(), mode, 'PLANNING', encode(constraints or []), stamp(wake_at), int(interval), stamp(expires_at) if expires_at else None), one=True)[0]
        event(conn, job_id, 'CREATED', 'Pekerjaan tersimpan. Kilas akan menyiapkan langkahnya.')
        if conversation_id is not None or schedule:
            usage._query(conn, 'UPDATE kilas_agent_jobs SET origin_conversation_id=?,schedule_json=? WHERE id=?',
                         (conversation_id, encode(schedule or {}), job_id))
    return job_id


def control(user_id, job_id, action):
    if action not in ('pause', 'resume', 'stop'):
        raise ValueError('invalid_control')
    with transaction() as conn:
        suffix = ' FOR UPDATE' if db.BACKEND == 'postgres' else ''
        row = usage._query(conn, 'SELECT status,plan_json FROM kilas_agent_jobs WHERE id=? AND user_id=?' + suffix, (job_id, user_id), one=True)
        if not row or row[0] in TERMINAL:
            raise ValueError('job_unavailable')
        # Keep the current lease until it expires: pause/resume cannot overlap an in-flight worker.
        state = 'STOPPED' if action == 'stop' else 'PAUSED' if action == 'pause' else 'PLANNING' if row[1] == '{}' else 'RUNNING'
        usage._query(conn, 'UPDATE kilas_agent_jobs SET status=?,next_wake_at=?,revision=revision+1,updated_at=?,stopped_at=? WHERE id=?',
                     (state, stamp() if action == 'resume' else None, stamp(), stamp() if action == 'stop' else None, job_id))
        if action == 'pause' and row[0] == 'PLANNING':
            usage._query(conn, "UPDATE kilas_agent_jobs SET plan_json='{}' WHERE id=?", (job_id,))
        if action == 'stop':
            usage._query(conn, "UPDATE kilas_agent_steps SET status='STOPPED' WHERE job_id=? AND status NOT IN ('SUCCEEDED','SKIPPED')", (job_id,))
        event(conn, job_id, action.upper(), {'pause': 'Pekerjaan dijeda.', 'resume': 'Pekerjaan dilanjutkan.', 'stop': 'Pekerjaan dihentikan.'}[action])


def feedback(user_id, job_id, text):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1200:
        raise ValueError('invalid_feedback')
    with transaction() as conn:
        suffix = ' FOR UPDATE' if db.BACKEND == 'postgres' else ''
        row = usage._query(conn, 'SELECT status,constraints_json,replans FROM kilas_agent_jobs WHERE id=? AND user_id=?' + suffix, (job_id, user_id), one=True)
        if not row or row[0] in TERMINAL or row[2] >= 3:
            raise ValueError('replan_limit')
        constraints = json.loads(row[1]) + [text.strip()]
        if len(constraints) > 12:
            raise ValueError('constraint_limit')
        usage._query(conn, "UPDATE kilas_agent_jobs SET plan_json='{}',constraints_json=?,status=?,next_wake_at=?,revision=revision+1,replans=replans+1,updated_at=? WHERE id=?",
                     (encode(constraints), 'PAUSED' if row[0] == 'PAUSED' else 'PLANNING', None if row[0] == 'PAUSED' else stamp(), stamp(), job_id))
        event(conn, job_id, 'FEEDBACK', text)


def claim_due(limit=2, lease_seconds=180):
    claimed = []
    with transaction() as conn:
        suffix = ' FOR UPDATE SKIP LOCKED' if db.BACKEND == 'postgres' else ''
        ids = usage._rows(conn, "SELECT id FROM kilas_agent_jobs WHERE status IN ('PLANNING','RUNNING','WAITING') AND next_wake_at<=? AND (lease_until IS NULL OR lease_until<=?) ORDER BY next_wake_at,id LIMIT ?" + suffix,
                          (stamp(), stamp(), min(3, max(1, int(limit)))))
        for (job_id,) in ids:
            token = secrets.token_hex(24)
            usage._query(conn, 'UPDATE kilas_agent_jobs SET lease_token=?,lease_until=?,updated_at=? WHERE id=?', (token, stamp(now() + timedelta(seconds=lease_seconds)), stamp(), job_id))
            claimed.append((job_id, token))
    return claimed


def locked(conn, job_id, token, revision=None):
    suffix = ' FOR UPDATE' if db.BACKEND == 'postgres' else ''
    row = usage._query(conn, 'SELECT status,revision FROM kilas_agent_jobs WHERE id=? AND lease_token=? AND lease_until>?' + suffix, (job_id, token, stamp()), one=True)
    return bool(row and row[0] in ELIGIBLE and (revision is None or row[1] == revision))


def install_plan(job, token, plan):
    with transaction() as conn:
        if not locked(conn, job['id'], token, job['revision']):
            return False
        usage._query(conn, "DELETE FROM kilas_agent_steps WHERE job_id=? AND status!='SUCCEEDED' AND id NOT IN (SELECT step_id FROM kilas_agent_artifacts) AND id NOT IN (SELECT step_id FROM kilas_agent_approvals)", (job['id'],))
        usage._query(conn, "UPDATE kilas_agent_steps SET status='SKIPPED' WHERE job_id=? AND status!='SUCCEEDED'", (job['id'],))
        base = usage._query(conn, 'SELECT COALESCE(MAX(sequence),0) FROM kilas_agent_steps WHERE job_id=?', (job['id'],), one=True)[0]
        if base + len(plan['steps']) > job['max_steps']:
            raise ValueError('step_limit')
        for index, step in enumerate(plan['steps'], base + 1):
            usage._query(conn, 'INSERT INTO kilas_agent_steps(job_id,sequence,worker,action,instruction,input_json,idempotency_key,requires_approval) VALUES (?,?,?,?,?,?,?,?)',
                         (job['id'], index, step['worker'], step['action'], step['instruction'], encode(step['input']), secrets.token_hex(24), int(step['requires_approval'])))
        usage._query(conn, "UPDATE kilas_agent_jobs SET plan_json=?,status='RUNNING',title=?,updated_at=? WHERE id=?", (encode(plan), plan['objective'][:90], stamp(), job['id']))
        event(conn, job['id'], 'PLANNED', 'Rencana tersimpan: ' + str(len(plan['steps'])) + ' langkah.')
    return True


def begin_step(job, token):
    with transaction() as conn:
        if not locked(conn, job['id'], token, job['revision']):
            return None
        row = usage._query(conn, "SELECT id FROM kilas_agent_steps WHERE job_id=? AND status IN ('PENDING','RUNNING','FAILED','WAITING') ORDER BY sequence LIMIT 1", (job['id'],), one=True)
        if not row:
            return None
        daily = usage._query(conn, "SELECT COUNT(*) FROM kilas_agent_events e JOIN kilas_agent_jobs j ON j.id=e.job_id WHERE j.user_id=? AND e.kind='EXECUTING' AND e.created_at>=?", (job['user_id'], stamp(now().replace(hour=0, minute=0, second=0, microsecond=0))), one=True)[0]
        if daily >= 100 and not usage._qa_quota_exempt(conn, job['user_id'], now()):
            raise ValueError('daily_execution_limit')
        attempts = usage._query(conn, 'SELECT attempts FROM kilas_agent_steps WHERE id=?', (row[0],), one=True)[0]
        if attempts >= job['max_attempts']:
            raise ValueError('attempt_limit')
        usage._query(conn, "UPDATE kilas_agent_steps SET status='RUNNING',attempts=attempts+1,started_at=? WHERE id=?", (stamp(), row[0]))
        event(conn, job['id'], 'EXECUTING', 'Langkah dimulai.', unread=False)
    return dict(db.query_one('SELECT * FROM kilas_agent_steps WHERE id=?', (row[0],)))


def release(job_id, token):
    db.execute('UPDATE kilas_agent_jobs SET lease_token=NULL,lease_until=NULL WHERE id=? AND lease_token=?', (job_id, token))


def approval(conn, job_id, step, payload):
    usage._query(conn, 'INSERT INTO kilas_agent_approvals(job_id,step_id,payload_json,digest,expires_at) VALUES (?,?,?,?,?) ON CONFLICT(step_id,digest) DO NOTHING',
                 (job_id, step['id'], encode(payload), digest(payload), stamp(now() + timedelta(minutes=30))))


def approve(user_id, job_id, approval_id, expected_digest):
    with transaction() as conn:
        suffix = ' FOR UPDATE' if db.BACKEND == 'postgres' else ''
        row = usage._query(conn, "SELECT a.step_id,a.payload_json,a.digest FROM kilas_agent_approvals a JOIN kilas_agent_jobs j ON j.id=a.job_id WHERE a.id=? AND j.id=? AND j.user_id=? AND j.status='NEEDS_APPROVAL' AND a.status='PENDING' AND a.expires_at>?" + suffix,
                           (approval_id, job_id, user_id, stamp()), one=True)
        if not row or row[2] != expected_digest or digest(json.loads(row[1])) != row[2]:
            raise ValueError('approval_payload_mismatch')
        current = usage._query(conn, 'SELECT worker,action,input_json FROM kilas_agent_steps WHERE id=?', (row[0],), one=True)
        if digest({'worker': current[0], 'action': current[1], 'input': json.loads(current[2])}) != row[2]:
            raise ValueError('approval_payload_mismatch')
        usage._query(conn, "UPDATE kilas_agent_approvals SET status='APPROVED' WHERE id=?", (approval_id,))
        usage._query(conn, "UPDATE kilas_agent_steps SET status='PENDING' WHERE id=?", (row[0],))
        usage._query(conn, "UPDATE kilas_agent_jobs SET status='RUNNING',next_wake_at=?,revision=revision+1 WHERE id=?", (stamp(), job_id))
        event(conn, job_id, 'APPROVED', 'Isi tindakan disetujui. Ketersediaan kemampuan tetap diperiksa sebelum dijalankan.')
