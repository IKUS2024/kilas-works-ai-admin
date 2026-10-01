"""Focused durable execution/owner controls/capability safety tests; no production IO."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['CLIENT_HUB_DB_PATH'] = tempfile.mktemp(suffix='.sqlite')
os.environ['SECRET_KEY'] = 'autonomous-focused-test-only'
os.environ['KILAS_AI_ENABLED'] = 'true'
os.environ['KILAS_AI_AUTOMATION_ENABLED'] = 'true'
os.environ['KILAS_AI_AUTONOMOUS_ENABLED'] = 'true'
os.environ.pop('DATABASE_URL', None)
import app
import db
import repo
from kilas_ai import autonomous_store as store, autonomous_runner as runner, autonomous_planner as planner, usage
from kilas_ai import agent_workers as workers, automation_runner, google_connection, connectors
from kilas_ai.agent_workers import code_worker, content_worker, market_worker


def proposal(worker='FILE', action='create', data=None, mode='ONE_SHOT'):
    return {'objective': 'Hasil pekerjaan', 'mode': mode, 'stop_condition': 'Hasil terverifikasi', 'next_action': 'Jalankan langkah',
            'steps': [{'worker': worker, 'action': action, 'instruction': 'Siapkan hasil', 'input_json': json.dumps(data or {'name': 'hasil.txt', 'format': 'txt', 'content': 'Hasil benar'}), 'completion_criteria': 'Hasil tersedia', 'requires_approval': False}]}


class AutonomousTests(unittest.TestCase):
    def setUp(self):
        # Remove only synthetic jobs in this isolated test database to avoid due-job interference.
        db.execute('DELETE FROM kilas_agent_jobs')
        self.owner = repo.create_user(self.id() + '@example.test', 'hash')
        self.other = repo.create_user(self.id() + '-other@example.test', 'hash')
        self.job_id = store.create(self.owner, 'Kerjakan riset sampai selesai', constraints=['Jangan deploy'])

    def job(self):
        return store.get(self.owner, self.job_id)

    def plan(self, worker='FILE', action='create', data=None):
        db.execute('UPDATE kilas_agent_jobs SET next_wake_at=? WHERE id=?', (store.stamp(), self.job_id))
        job = self.job()
        claim = store.claim_due(1)[0]
        store.install_plan(job, claim[1], planner.validate(proposal(worker, action, data, job['mode']), job['mode']))
        store.release(*claim)

    def tick(self):
        db.execute('UPDATE kilas_agent_jobs SET next_wake_at=? WHERE id=?', (store.stamp(), self.job_id))
        claim = store.claim_due(1)
        if claim:
            runner.execute(*claim[0])

    def client(self, owner=None):
        app.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        client = app.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=owner or self.owner, role='CLIENT_OWNER', _csrf_token='autonomous-csrf')
        return client

    def test_persistent_create_and_owner_boundary(self):
        self.assertEqual(self.job()['status'], 'PLANNING')
        self.assertIsNone(store.get(self.other, self.job_id))
        self.assertEqual(json.loads(self.job()['constraints_json']), ['Jangan deploy'])

    def test_transactional_claim(self):
        first = store.claim_due(1)
        self.assertEqual(len(first), 1)
        self.assertEqual(store.claim_due(1), [])

    def test_concurrent_claim_only_one_winner(self):
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: store.claim_due(1), range(2)))
        self.assertEqual(sum(len(r) for r in results), 1)

    def test_lease_expiry_fences_old_writer(self):
        old = store.claim_due(1)[0]
        db.execute('UPDATE kilas_agent_jobs SET lease_until=? WHERE id=?', (store.stamp(store.now()-timedelta(seconds=1)), self.job_id))
        new = store.claim_due(1)[0]
        self.assertNotEqual(old[1], new[1])
        self.assertFalse(store.install_plan(self.job(), old[1], planner.validate(proposal(), 'ONE_SHOT')))
        store.release(*old)
        self.assertEqual(self.job()['lease_token'], new[1])

    def test_checkpoint_survives_restart(self):
        self.plan()
        self.tick()
        importlib.reload(store)
        self.assertEqual(self.job()['status'], 'COMPLETED')
        self.assertTrue(json.loads(self.job()['checkpoint_json'])['1']['verified'])

    def test_pause_prevents_claim(self):
        store.control(self.owner, self.job_id, 'pause')
        self.assertIsNone(self.job()['next_wake_at'])
        self.assertEqual(store.claim_due(1), [])

    def test_resume_restores_execution(self):
        store.control(self.owner, self.job_id, 'pause')
        store.control(self.owner, self.job_id, 'resume')
        self.assertEqual(self.job()['status'], 'PLANNING')
        self.assertEqual(len(store.claim_due(1)), 1)

    def test_stop_terminal(self):
        store.control(self.owner, self.job_id, 'stop')
        self.assertEqual(store.claim_due(1), [])
        with self.assertRaises(ValueError):
            store.control(self.owner, self.job_id, 'resume')

    def test_pause_and_resume_fence_inflight_result(self):
        self.plan()
        claim = store.claim_due(1)[0]
        job = self.job()
        step = store.begin_step(job, claim[1])
        store.control(self.owner, self.job_id, 'pause')
        store.control(self.owner, self.job_id, 'resume')
        self.assertFalse(runner.finish(job, claim[1], step, workers.Result('SUCCEEDED', 'Late result', verified=True)))
        self.assertEqual(store.claim_due(1), [])

    def test_retry_bounded_and_replan_once(self):
        self.plan()
        with patch.object(workers, 'execute', return_value=workers.Result('FAILED', 'Failed')):
            for _ in range(3):
                self.tick()
        self.assertEqual(self.job()['status'], 'PLANNING')
        self.assertEqual(self.job()['replans'], 1)
        self.assertEqual(store.steps(self.job_id)[0]['attempts'], 3)
        self.plan()
        with patch.object(workers, 'execute', return_value=workers.Result('FAILED', 'Failed')):
            self.tick()
        self.assertEqual(self.job()['status'], 'FAILED')

    def test_failed_worker_exception_is_bounded(self):
        self.plan()
        with patch.object(workers, 'execute', side_effect=RuntimeError('secret provider body')):
            for _ in range(3):
                self.tick()
        self.assertEqual(self.job()['status'], 'PLANNING')
        self.assertNotIn('secret', self.job()['last_error'])

    def test_unverified_success_rejected(self):
        self.plan()
        with patch.object(workers, 'execute', return_value=workers.Result('SUCCEEDED', 'invented')):
            self.tick()
        self.assertNotEqual(self.job()['status'], 'COMPLETED')

    def test_duplicate_action_cannot_repeat_after_completion(self):
        self.plan()
        self.tick()
        self.assertEqual(store.claim_due(1), [])
        self.assertEqual(db.query_one('SELECT COUNT(*) AS n FROM kilas_agent_artifacts WHERE job_id=?', (self.job_id,))['n'], 1)

    def test_approval_exact_payload_and_replay(self):
        self.plan('EXTERNAL', 'deploy', {'target': 'review-only'})
        self.tick()
        approval = dict(db.query_one('SELECT * FROM kilas_agent_approvals WHERE job_id=?', (self.job_id,)))
        self.assertEqual(self.job()['status'], 'NEEDS_APPROVAL')
        with self.assertRaises(ValueError):
            store.approve(self.owner, self.job_id, approval['id'], 'wrong')
        store.approve(self.owner, self.job_id, approval['id'], approval['digest'])
        with self.assertRaises(ValueError):
            store.approve(self.owner, self.job_id, approval['id'], approval['digest'])
        self.tick()
        self.assertEqual(self.job()['status'], 'WAITING')
        self.assertEqual(json.loads(store.steps(self.job_id)[0]['output_json'])['reason'], 'adapter_not_configured')

    def test_approval_modified_input_rejected(self):
        self.plan('EXTERNAL', 'push', {'repo': 'test'})
        self.tick()
        row = dict(db.query_one('SELECT * FROM kilas_agent_approvals WHERE job_id=?', (self.job_id,)))
        db.execute('UPDATE kilas_agent_steps SET input_json=? WHERE id=?', ('{"repo":"other"}', row['step_id']))
        with self.assertRaises(ValueError):
            store.approve(self.owner, self.job_id, row['id'], row['digest'])

    def test_feedback_keeps_completed_steps(self):
        self.plan()
        db.execute("UPDATE kilas_agent_steps SET status='SUCCEEDED' WHERE job_id=?", (self.job_id,))
        original = store.steps(self.job_id)[0]
        store.feedback(self.owner, self.job_id, 'Stop setelah PR. Jangan deploy.')
        self.plan()
        self.assertEqual(store.steps(self.job_id)[0], original)
        self.assertIn('Stop setelah PR', self.job()['constraints_json'])

    def test_web_source_backed_and_quota(self):
        self.plan('WEB', 'search', {'query': 'Research competitors'})
        with patch.object(usage, 'reserve', return_value=('FREE', ['WEB_SEARCH'])), patch.object(usage, 'finish') as settled, patch.object(content_worker.tools, 'web_search', return_value={'text': 'Source-backed answer', 'citations': [{'url': 'https://example.test/source', 'title': 'Source'}]}):
            self.tick()
        self.assertEqual(self.job()['status'], 'COMPLETED')
        self.assertIn('https://example.test/source', store.steps(self.job_id)[0]['output_json'])
        self.assertTrue(settled.called)

    def test_web_missing_source_never_success(self):
        self.plan('WEB', 'search', {'query': 'Research'})
        with patch.object(usage, 'reserve', return_value=('FREE', ['WEB_SEARCH'])), patch.object(usage, 'finish'), patch.object(content_worker.tools, 'web_search', return_value={'text': 'Unsourced', 'citations': []}):
            self.tick()
        self.assertNotEqual(self.job()['status'], 'COMPLETED')

    def test_watch_wait_quiet_then_trigger_exactly_once(self):
        self.plan('WATCH', 'observe', {'query': 'Observed price', 'operator': 'lt', 'threshold': 10})
        with patch.object(usage, 'reserve', return_value=('FREE', ['CHAT'])), patch.object(usage, 'finish'), patch.object(content_worker.tools, 'web_search', return_value={'text': 'Observed value', 'citations': [{'url': 'https://example.test/price'}]}), patch.object(content_worker, 'text', side_effect=[('{"value":15}', 'model', {}), ('{"value":8}', 'model', {})]):
            self.tick()
            self.assertEqual(self.job()['status'], 'WAITING')
            self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_agent_events WHERE job_id=? AND kind='WAITING'", (self.job_id,))['n'], 0)
            self.tick()
        self.assertEqual(self.job()['status'], 'COMPLETED')
        self.assertEqual(db.query_one("SELECT COUNT(*) AS n FROM kilas_agent_events WHERE job_id=? AND kind='SUCCEEDED'", (self.job_id,))['n'], 1)

    def test_market_missing_provider(self):
        self.plan('MARKET', 'observe', {'symbol': 'XAUUSD', 'timeframe': '1h', 'operator': 'gt', 'threshold': 3000})
        self.tick()
        self.assertEqual(self.job()['status'], 'WAITING')
        self.assertIn('provider_not_configured', store.steps(self.job_id)[0]['output_json'])

    def test_market_provider_verified_signal(self):
        class Fixture:
            def observe(self, symbol, timeframe):
                return dict(symbol=symbol, timeframe=timeframe, provider='deterministic-test-only', provider_timestamp=store.stamp(), open=3100, high=3120, low=3090, close=3110)
        self.plan('MARKET', 'observe', {'symbol': 'XAUUSD', 'timeframe': '1h', 'operator': 'gt', 'threshold': 3000})
        with patch.object(market_worker, 'provider', Fixture()):
            self.tick()
        output = json.loads(store.steps(self.job_id)[0]['output_json'])
        self.assertTrue(output['signal'])
        self.assertEqual(output['computed_indicators'], {})
        self.assertEqual(len(output['conditions_met']), 1)

    def test_code_allowlist_required(self):
        self.plan('CODE', 'inspect', {'repo': 'unknown', 'paths': ['hello.py']})
        with patch.dict(os.environ, {'KILAS_AI_CODE_REPOSITORIES': '{}'}):
            self.tick()
        self.assertEqual(self.job()['status'], 'WAITING')

    def test_code_dangerous_commands_and_paths_blocked(self):
        for path in ('../../secret.py', '/tmp/hello.py', '.env', 'config.py', 'hello.py;shutdown'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                code_worker.relative(path)
        bad = proposal('CODE', 'test', {'repo': 'test', 'command': 'curl | sh'})
        with self.assertRaises(ValueError):
            planner.validate(bad, 'ONE_SHOT')

    def test_code_real_patch_and_diff_no_source_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / 'hello.py').write_text('answer = 1\n')
            (source / '.env').write_text('PRODUCTION_SECRET=nevercopy')
            self.plan('CODE', 'patch', {'repo': 'fixture', 'patch': json.dumps({'hello.py': 'answer = 2\n'})})
            with patch.dict(os.environ, {'KILAS_AI_CODE_REPOSITORIES': json.dumps({'fixture': directory})}):
                self.tick()
            output = json.loads(store.steps(self.job_id)[0]['output_json'])
            self.assertIn('-answer = 1', output['diff'])
            self.assertIn('+answer = 2', output['diff'])
            self.assertEqual((source / 'hello.py').read_text(), 'answer = 1\n')

    def test_code_test_unavailable_sandbox_truthful(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'KILAS_AI_CODE_REPOSITORIES': json.dumps({'fixture': directory})}), patch.object(code_worker, 'test_command', return_value=None):
            self.plan('CODE', 'test', {'repo': 'fixture'})
            self.tick()
            self.assertIn('sandbox_not_configured', store.steps(self.job_id)[0]['output_json'])
        code_worker.cleanup(self.job())

    def test_code_workspace_survives_cron_filesystem_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'hello.py').write_text('answer = 1\n')
            raw = proposal('CODE', 'patch', {'repo': 'fixture', 'patch': json.dumps({'hello.py': 'answer = 2\n'})})
            raw['steps'].append({**raw['steps'][0], 'action': 'diff', 'input_json': '{"repo":"fixture"}'})
            claim = store.claim_due(1)[0]
            store.install_plan(self.job(), claim[1], planner.validate(raw, 'ONE_SHOT'))
            store.release(*claim)
            with patch.dict(os.environ, {'KILAS_AI_CODE_REPOSITORIES': json.dumps({'fixture': directory})}):
                self.tick()
                code_worker.cleanup(self.job())
                self.tick()
            self.assertEqual(self.job()['status'], 'COMPLETED')
            self.assertIn('+answer = 2', store.steps(self.job_id)[1]['output_json'])

    def test_unsupported_format_waits(self):
        self.plan('FILE', 'create', {'name': 'movie.mp4', 'format': 'mp4', 'content': 'unsupported'})
        self.tick()
        self.assertEqual(self.job()['status'], 'WAITING')

    def test_browser_closed_does_not_stop_job(self):
        self.plan()
        client = self.client()
        self.assertEqual(client.get(f'/kilas-ai/agent/jobs/{self.job_id}').status_code, 200)
        del client
        self.tick()
        self.assertEqual(self.job()['status'], 'COMPLETED')

    def test_routes_csrf_and_foreign_owner(self):
        client = self.client()
        self.assertEqual(client.post(f'/kilas-ai/agent/jobs/{self.job_id}/pause').status_code, 400)
        self.assertEqual(self.client(self.other).get(f'/kilas-ai/agent/jobs/{self.job_id}').status_code, 404)
        self.assertEqual(client.post(f'/kilas-ai/agent/jobs/{self.job_id}/pause', data={'csrf_token': 'autonomous-csrf'}).status_code, 303)

    def test_natural_language_create_and_control(self):
        client = self.client()
        client.post('/kilas-ai/agent/chat', data={'csrf_token': 'autonomous-csrf', 'message': 'pause pekerjaan ' + str(self.job_id)})
        self.assertEqual(self.job()['status'], 'PAUSED')
        client.post('/kilas-ai/agent/chat', data={'csrf_token': 'autonomous-csrf', 'message': 'resume pekerjaan ' + str(self.job_id)})
        self.assertEqual(self.job()['status'], 'PLANNING')
        client.post('/kilas-ai/agent/chat', data={'csrf_token': 'autonomous-csrf', 'message': 'stop pekerjaan ' + str(self.job_id)})
        self.assertEqual(self.job()['status'], 'STOPPED')

    def test_stop_after_test_instruction_is_constraint_not_immediate_stop(self):
        client = self.client()
        client.post('/kilas-ai/agent/chat', data={'csrf_token': 'autonomous-csrf', 'message': 'Stop setelah test pass.'})
        self.assertEqual(self.job()['status'], 'PLANNING')
        self.assertIn('Stop setelah test pass', self.job()['constraints_json'])

    def test_no_autonomous_task_preserves_old_control_routing(self):
        from kilas_ai import autonomous_routes
        db.execute('DELETE FROM kilas_agent_jobs')
        with app.app.test_request_context('/kilas-ai/agent/chat', method='POST'):
            self.assertFalse(autonomous_routes.chat(self.owner, 'pause'))

    def test_disabled_default_preserves_existing_agent(self):
        with patch.dict(os.environ, {'KILAS_AI_AUTONOMOUS_ENABLED': ''}):
            self.assertTrue(runner.run_once()['disabled'])
            self.assertEqual(self.client().get(f'/kilas-ai/agent/jobs/{self.job_id}').status_code, 404)
            self.assertEqual(self.client().get('/kilas-ai/agent').status_code, 200)

    def test_google_scope_boundary_unchanged(self):
        self.assertEqual(connectors.ACTIVE_GOOGLE_TOOLS, frozenset(['gmail.send']))
        self.assertEqual(set(google_connection.IDENTITY_SCOPES + connectors.GOOGLE_SCOPES['gmail']), {'openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/gmail.send'})

    def test_existing_automation_runs_first(self):
        with patch.dict(os.environ, {'KILAS_AI_AUTOMATION_RUNNER_ENABLED': 'true'}), patch.object(automation_runner.store, 'recover_stale'), patch.object(automation_runner.store, 'claim_due', return_value=[111]), patch.object(automation_runner, 'execute', return_value=True) as old, patch.object(runner, 'run_once', side_effect=lambda: {'old_called': old.called}) as new:
            result = automation_runner.run_once()
        self.assertTrue(result['autonomous']['old_called'])
        self.assertEqual(result['completed'], 1)

    def test_tick_job_budget(self):
        with patch.object(store, 'claim_due', return_value=[(1, 'token')]), patch.object(runner, 'execute') as execute:
            outcome = runner.run_once(limit=200)
        self.assertLessEqual(outcome['claimed'], 3)
        self.assertLessEqual(execute.call_count, 3)

    def test_planning_tick_persists_validated_plan(self):
        with patch.object(planner, 'propose', return_value=planner.validate(proposal(), 'ONE_SHOT')):
            self.tick()
        self.assertEqual(self.job()['status'], 'RUNNING')
        self.assertEqual(store.steps(self.job_id)[0]['status'], 'PENDING')

    def test_daily_execution_guard(self):
        self.plan()
        with store.transaction() as conn:
            for index in range(100):
                store.event(conn, self.job_id, 'EXECUTING', 'test', key=str(index), unread=False)
        with patch.object(usage, '_qa_quota_exempt', return_value=False):
            self.tick()
        self.assertEqual(self.job()['last_error'], 'daily_execution_limit')
        self.assertEqual(self.job()['status'], 'WAITING')

    def test_scheduled_job_not_claimed_early(self):
        db.execute('DELETE FROM kilas_agent_jobs')
        self.job_id = store.create(self.owner, 'Scheduled work', mode='SCHEDULED', wake_at=store.now()+timedelta(days=1))
        self.assertEqual(store.claim_due(1), [])

    def test_recurring_checkpoint_preserves_completed_cycle(self):
        db.execute("UPDATE kilas_agent_jobs SET mode='RECURRING' WHERE id=?", (self.job_id,))
        self.plan()
        self.tick()
        self.assertEqual(self.job()['status'], 'PLANNING')
        self.assertEqual(self.job()['cycle'], 1)
        self.assertEqual(store.steps(self.job_id)[0]['status'], 'SUCCEEDED')
        self.assertGreater(usage._as_utc(self.job()['next_wake_at']), store.now())

    def test_expired_job_stops_without_worker(self):
        db.execute('UPDATE kilas_agent_jobs SET expires_at=? WHERE id=?', (store.stamp(store.now()-timedelta(days=1)), self.job_id))
        with patch.object(workers, 'execute') as execute:
            self.tick()
        self.assertEqual(self.job()['status'], 'STOPPED')
        execute.assert_not_called()

    def test_condition_mode_requires_observation(self):
        with self.assertRaises(ValueError):
            planner.validate(proposal(mode='CONDITION_WATCH'), 'CONDITION_WATCH')

    def test_continuous_stop_after_verified_tests(self):
        db.execute("UPDATE kilas_agent_jobs SET mode='CONTINUOUS',constraints_json=? WHERE id=?", (json.dumps(['Stop setelah test pass.']), self.job_id))
        self.plan('CODE', 'test', {'repo': 'fixture'})
        with patch.object(workers, 'execute', return_value=workers.Result('SUCCEEDED', 'Actual tests pass', {'exit_code': 0}, verified=True)):
            self.tick()
        self.assertEqual(self.job()['status'], 'COMPLETED')

    def test_feedback_replan_cap(self):
        for index in range(3):
            store.feedback(self.owner, self.job_id, f'New constraint {index}')
        with self.assertRaises(ValueError):
            store.feedback(self.owner, self.job_id, 'No infinite replanning')

    def test_feedback_while_paused_replans_on_resume(self):
        self.plan()
        store.control(self.owner, self.job_id, 'pause')
        store.feedback(self.owner, self.job_id, 'Gunakan pendekatan lain.')
        self.assertEqual(self.job()['status'], 'PAUSED')
        store.control(self.owner, self.job_id, 'resume')
        self.assertEqual(self.job()['status'], 'PLANNING')


if __name__ == '__main__':
    unittest.main()
