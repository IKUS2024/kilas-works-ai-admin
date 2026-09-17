"""Run Finance and foundation regressions in isolated, offline Python processes.

Usage: python client-hub/tests/run_finance_regressions.py [test_module ...]
Legacy function-based suites and unittest suites are both collected. Each module gets
its own process because the existing fixtures configure different global databases.
Only disposable SQLite databases are used; inherited production DB/provider settings
are removed. Socket blocking is inherited by Python subprocesses via sitecustomize.
"""
import importlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SUITES = [
    'test_finance_phase' + phase for phase in
    ('1a', '1b', '2a', '2b', '3', '4a', '4b', '4c', '5ab', '5c', '6a', '6b', '6c')
] + [
    'test_final_product_flow', 'test_service_selection_purchase_flow', 'test_app_service_briefs',
    'test_subscription_lifecycle', 'test_subscription_backfill', 'test_ux_catalog_final',
    'test_client_hub_v1', 'test_production_foundation', 'test_client_hub_batch1',
    'test_client_hub_batch2_3', 'test_client_hub_ux_batch',
    'test_postgres_sql_adapter_external_audit',
    'test_repo_ai_settings_postgres_json_compat',
]


def child(name):
    root_suite=name.startswith('root:')
    sys.path[:0] = [str(ROOT.parent)] if root_suite else [str(ROOT / 'tests'), str(ROOT)]
    module = importlib.import_module(name.removeprefix('root:'))
    suite = unittest.TestSuite()
    for key, value in sorted(vars(module).items()):
        if getattr(value, '__module__', None) != module.__name__:
            continue
        if inspect.isclass(value) and issubclass(value, unittest.TestCase):
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(value))
        elif key.startswith('test_') and inspect.isfunction(value):
            suite.addTest(unittest.FunctionTestCase(value))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    # One historical tracked test file is empty. Report discovery explicitly;
    # it is neither a passing test nor a failed implementation check.
    empty_module = result.testsRun == 0 and Path(module.__file__).stat().st_size == 0
    print('FINANCE_TEST_RESULT ' + json.dumps(dict(
        suite=name, tests=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), skipped=len(result.skipped),
        script_checks=1 if root_suite and result.testsRun==0 and not empty_module else 0,
        empty_modules=int(empty_module))), flush=True)
    return 0 if result.wasSuccessful() and (result.testsRun or root_suite or empty_module) else 1


def main(names):
    failed = False
    results = []
    with tempfile.TemporaryDirectory(prefix='kilas-finance-tests-') as directory:
        guard = Path(directory)
        (guard / 'sitecustomize.py').write_text(
            "import socket\n"
            "def offline(*args, **kwargs):\n"
            "    raise AssertionError('Live network disabled during tests')\n"
            "socket.socket.connect = offline\n"
            "socket.socket.connect_ex = offline\n"
            "socket.create_connection = offline\n"
        )
        env = dict(os.environ)
        for key in ('DATABASE_URL', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'APP_ENV', 'RENDER',
                    'KILAS_FINANCE_ACCESS_MODE', 'KILAS_FINANCE_EMERGENCY_DISABLE',
                    'KILAS_FINANCE_ANALYST_ENABLED','KILAS_FINANCE_OPERATOR_ENABLED'):
            env.pop(key, None)
        env['PYTHONPATH'] = os.pathsep.join((str(guard), str(ROOT), str(ROOT / 'tests')))
        env['CLIENT_HUB_ENV'] = 'test'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        env['SECRET_KEY'] = 'offline-disposable-test-secret'
        for name in names:
            if name not in SUITES and name not in {p.stem for p in (ROOT/'tests').glob('test_*.py')}:
                raise ValueError('Unknown regression suite')
            env['CLIENT_HUB_DB_PATH'] = str(guard / (name + '.db'))
            run = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child', name],
                                 cwd=ROOT.parent if name.startswith('root:') else ROOT, env=env, capture_output=True, text=True, timeout=180)
            marker = [line for line in run.stdout.splitlines() if line.startswith('FINANCE_TEST_RESULT ')]
            if marker:
                result = json.loads(marker[-1].split(' ', 1)[1])
                results.append(result)
                print(json.dumps(result), flush=True)
            if run.returncode or not marker:
                failed = True
                print(run.stdout + run.stderr, flush=True)
        print('TOTAL ' + json.dumps({key: sum(r[key] for r in results)
                                    for key in ('tests', 'failures', 'errors', 'skipped','script_checks','empty_modules')}), flush=True)
    return int(failed)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--child']:
        sys.exit(child(sys.argv[2]))
    if sys.argv[1:] == ['--all-root']:
        SUITES[:] = sorted('root:'+path.stem for path in ROOT.parent.glob('test_*.py'))
        sys.exit(main(SUITES))
    if sys.argv[1:] == ['--all-client-hub']:
        SUITES[:] = sorted(path.stem for path in (ROOT/'tests').glob('test_*.py'))
        sys.exit(main(SUITES))
    sys.exit(main(sys.argv[1:] or SUITES))
