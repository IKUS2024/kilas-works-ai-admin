"""Small checkpointed pass alongside Automation. Disabled until separately released."""
import json
import os
import re
import time
from datetime import timedelta
import db
from . import autonomous_store as store, autonomous_planner as planner, usage
from . import agent_workers
from .autonomous_notifications import adapter as notifications


def enabled():
    return os.environ.get('KILAS_AI_AUTONOMOUS_ENABLED', '').lower() == 'true'


def finish(job, token, step, result):
    if result.status not in ('SUCCEEDED', 'FAILED', 'WAITING', 'WAITING_CAPABILITY', 'NEEDS_APPROVAL'):
        raise ValueError('invalid_worker_result')
    if result.status == 'SUCCEEDED' and not result.verified:
        raise ValueError('unverified_success')
    output = store.encode(result.output)
    with store.transaction() as conn:
        if not store.locked(conn, job['id'], token, job['revision']):
            return False
        state = 'WAITING' if result.status == 'WAITING_CAPABILITY' else result.status
        failures = job['failures'] + 1 if state == 'FAILED' else 0
        # A normal watch wait is not a failed attempt, and can persist indefinitely within expiry/daily caps.
        usage._query(conn, 'UPDATE kilas_agent_steps SET status=?,output_json=?,error=?,completed_at=?,attempts=CASE WHEN ? THEN 0 ELSE attempts END WHERE id=?',
                     (state, output, result.output.get('reason'), store.stamp() if state == 'SUCCEEDED' else None, int(state == 'WAITING'), step['id']))
        for artifact in result.artifacts[:3]:
            content = artifact['content']
            if not isinstance(content, str) or len(content.encode()) > 24000:
                raise ValueError('artifact_limit')
            usage._query(conn, 'INSERT INTO kilas_agent_artifacts(job_id,step_id,name,media_type,content,digest) VALUES (?,?,?,?,?,?) ON CONFLICT(step_id,name,digest) DO NOTHING',
                         (job['id'], step['id'], artifact['name'][:100], artifact['media_type'], content, store.digest(content)))
        checkpoint = json.loads(job['checkpoint_json'])
        checkpoint_output = result.output if len(output.encode()) < 10000 else {'excerpt': output[:6000], 'full_result': 'Stored in step output/artifacts'}
        checkpoint[str(step['sequence'])] = {'summary': result.summary[:1000], 'output': checkpoint_output, 'verified': result.verified}
        # Keep a bounded recent checkpoint; verified historical outputs remain in steps/artifacts.
        checkpoint = dict(list(checkpoint.items())[-4:])
        state_job, delay = 'RUNNING', 60
        if state == 'NEEDS_APPROVAL':
            state_job = 'NEEDS_APPROVAL'
            store.approval(conn, job['id'], step, {'worker': step['worker'], 'action': step['action'], 'input': json.loads(step['input_json'])})
        elif state == 'WAITING':
            state_job, delay = 'WAITING', max(300, min(result.delay, 86400))
        elif state == 'FAILED':
            if step['attempts'] >= job['max_attempts'] or failures >= 3:
                if job['replans'] < 1:
                    state_job = 'PLANNING'
                    usage._query(conn, 'UPDATE kilas_agent_jobs SET replans=replans+1 WHERE id=?', (job['id'],))
                else:
                    state_job = 'FAILED'
            delay = 300
        remaining = usage._query(conn, "SELECT COUNT(*) FROM kilas_agent_steps WHERE job_id=? AND status NOT IN ('SUCCEEDED','SKIPPED','STOPPED')", (job['id'],), one=True)[0]
        stop_after_tests = (state == 'SUCCEEDED' and step['worker'] == 'CODE' and step['action'] == 'test' and
                            re.search(r'(?i)(?:stop|berhenti|hentikan).{0,40}(?:test|pengujian).{0,25}(?:pass|berhasil|lulus)', job['constraints_json']))
        if stop_after_tests:
            usage._query(conn, "UPDATE kilas_agent_steps SET status='SKIPPED' WHERE job_id=? AND status='PENDING'", (job['id'],))
            remaining = 0
        if state == 'SUCCEEDED' and not remaining:
            if job['mode'] in ('CONTINUOUS', 'RECURRING') and not stop_after_tests:
                # Append the next cycle; completed history never changes. Overall max_steps remains a hard cap.
                state_job, delay = 'PLANNING', job['interval_seconds']
                usage._query(conn, 'UPDATE kilas_agent_jobs SET cycle=cycle+1 WHERE id=?', (job['id'],))
            else:
                state_job = 'COMPLETED'
        wake = None if state_job in store.TERMINAL + ('NEEDS_APPROVAL',) else store.stamp(store.now() + timedelta(seconds=delay))
        usage._query(conn, 'UPDATE kilas_agent_jobs SET status=?,checkpoint_json=?,next_wake_at=?,failures=?,last_error=?,updated_at=?,completed_at=? WHERE id=?',
                     (state_job, store.encode(checkpoint), wake, failures, result.output.get('reason') if state != 'SUCCEEDED' else None, store.stamp(), store.stamp() if state_job == 'COMPLETED' else None, job['id']))
        # Waiting checks are quiet; capability block is recorded only once per step/reason.
        if state != 'WAITING' or result.status == 'WAITING_CAPABILITY':
            key = f"step-{step['id']}-{state}" + ('-' + str(result.output.get('reason')) if state == 'WAITING' else '')
            notifications.publish(conn, job['id'], result.status, result.summary, key)
        if state_job == 'COMPLETED':
            store.event(conn, job['id'], 'COMPLETED', 'Pekerjaan selesai. Hasil terverifikasi tersedia.', f"job-{job['id']}-completed")
    return True


def execute(job_id, token):
    job = dict(db.query_one('SELECT * FROM kilas_agent_jobs WHERE id=?', (job_id,)))
    step = None
    try:
        if job['expires_at'] and usage._as_utc(job['expires_at']) <= store.now():
            store.control(job['user_id'], job_id, 'stop')
            return
        if job['status'] == 'PLANNING':
            completed = [{'instruction': s['instruction'], 'output': json.loads(s['output_json'])} for s in store.steps(job_id) if s['status'] == 'SUCCEEDED'][-4:]
            proposal = planner.propose(job, completed)
            store.install_plan(job, token, proposal)
            return
        step = store.begin_step(job, token)
        if not step:
            return
        with store.transaction() as conn:
            if not store.locked(conn, job_id, token, job['revision']):
                return
        if step['requires_approval'] or agent_workers.sensitive(step['worker'], step['action']):
            # V1 deliberately has no external executor. Exact approval is a future adapter gate.
            approved = db.query_one("SELECT id FROM kilas_agent_approvals WHERE step_id=? AND digest=? AND status='APPROVED' AND expires_at>?", (step['id'], store.digest({'worker': step['worker'], 'action': step['action'], 'input': json.loads(step['input_json'])}), store.stamp()))
            result = agent_workers.execute(job, step) if approved else agent_workers.Result('NEEDS_APPROVAL', 'Tindakan eksternal memerlukan persetujuan untuk isi yang tepat.')
        else:
            result = agent_workers.execute(job, step)
        finish(job, token, step, result)
    except Exception as error:
        if step is not None:
            finish(job, token, step, agent_workers.Result('FAILED', 'Langkah belum berhasil; percobaan dibatasi.', {'reason': 'worker_failed'}))
            return
        # Store fixed public codes only, never provider bodies, credentials or raw exception text.
        code = str(error) if isinstance(error, ValueError) and str(error) in ('daily_execution_limit', 'attempt_limit', 'step_limit', 'replan_limit') else 'worker_failed'
        with store.transaction() as conn:
            if store.locked(conn, job_id, token, job['revision']):
                failures = job['failures'] + 1
                state = 'WAITING' if code == 'daily_execution_limit' else 'FAILED' if failures >= 3 or code == 'step_limit' else 'PLANNING' if job['status'] == 'PLANNING' else 'RUNNING'
                usage._query(conn, 'UPDATE kilas_agent_jobs SET status=?,failures=?,last_error=?,next_wake_at=?,updated_at=? WHERE id=?', (state, failures, code, None if state == 'FAILED' else store.stamp(store.now() + timedelta(hours=1)), store.stamp(), job_id))
                store.event(conn, job_id, 'BLOCKED', 'Pekerjaan belum berhasil; percobaan dibatasi.', f'failure-{job_id}-{failures}')
    finally:
        store.release(job_id, token)
        current = db.query_one('SELECT status FROM kilas_agent_jobs WHERE id=?', (job_id,))
        if current and current['status'] in store.TERMINAL:
            from .agent_workers.code_worker import cleanup
            cleanup(job)


def run_once(limit=2, max_seconds=100):
    if not enabled():
        return {'claimed': 0, 'disabled': True}
    start, count = time.monotonic(), 0
    from .agent_workers.code_worker import cleanup
    for row in db.query_all("SELECT id FROM kilas_agent_jobs WHERE status IN ('COMPLETED','FAILED','STOPPED') AND (lease_until IS NULL OR lease_until<=?) ORDER BY id DESC LIMIT 20", (store.stamp(),)):
        cleanup(row)
    # Claim only when ready to execute, so unstarted jobs never sit locked for an entire batch.
    for _ in range(min(3, max(1, int(limit)))):
        if time.monotonic() - start > min(100, max_seconds) - 75:
            break
        batch = store.claim_due(1)
        if not batch:
            break
        execute(*batch[0])
        count += 1
    return {'claimed': count, 'disabled': False}
