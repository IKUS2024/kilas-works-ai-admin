"""Execute every Finance regression in a fresh, network-blocked unittest process.

Install client-hub/requirements.txt first. Existing PYTHONPATH entries are retained
so an external dependency directory can be used. Logs are disposable synthetic-test
artifacts; a failing, timed-out, skipped, or zero-test file always fails this gate.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--logs', type=Path, help='Directory for per-file logs and results.json')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    logs = args.logs or Path(tempfile.mkdtemp(prefix='kilas-finance-baseline-'))
    logs.mkdir(parents=True, exist_ok=True)
    tests = root / 'client-hub' / 'tests'
    files = sorted(tests.glob('test_finance_*.py')) + [tests / 'test_kilas_finance_baseline.py']
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([
        str(root / 'scripts' / 'offline_tests'), str(root / 'client-hub'),
        str(tests), env.get('PYTHONPATH', '')])
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    # Force the existing test-only credential cleanup in each fresh parent process.
    env.pop('KILAS_OFFLINE_ENV_CLEAN', None)
    results = []
    for path in files:
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'unittest', 'discover', '-s', str(tests),
                 '-p', path.name, '-v'], cwd=root, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=240)
            output, code = result.stdout, result.returncode
        except subprocess.TimeoutExpired as error:
            output = error.stdout or b''
            if isinstance(output, bytes):
                output = output.decode('utf-8', errors='replace')
            output += '\nFINANCE_BASELINE_TIMEOUT\n'
            code = 124
        (logs / (path.stem + '.log')).write_text(output)
        count = re.search(r'^Ran (\d+) tests?', output, re.M)
        count = int(count[1]) if count else 0
        skipped = re.search(r'\bskipped=(\d+)', output)
        skipped = int(skipped[1]) if skipped else 0
        row = dict(file=path.name, tests=count, skipped=skipped,
                   ok=code == 0 and count > 0 and skipped == 0,
                   failures=re.findall(r'^(?:FAIL|ERROR): (.+)', output, re.M))
        results.append(row)
        print(json.dumps(row), flush=True)
    (logs / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    green = all(row['ok'] for row in results)
    print(f"Finance baseline: {'PASS' if green else 'FAIL'}; "
          f"{len(results)} files; {sum(row['tests'] for row in results)} tests; logs={logs.resolve()}")
    return 0 if green else 1


if __name__ == '__main__':
    raise SystemExit(main())
