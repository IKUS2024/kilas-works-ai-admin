"""Compare legacy UI/Finance failures with the immutable pre-design baseline.

Linux CI only: both trees use the same dependencies and disposable fixtures.
This does not change expectations or turn failed legacy workflows green.
"""
import collections
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

BASELINE = '5f9dac717531d985811bc61b106236bf00fe4c29'
ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    'home': ['test_kilas_home'],
    'workspace': ['test_kilas_workspace'],
    'finance-and-localization': ['test_ui_i18n', 'test_finance_home_dashboard', 'test_finance_style_loading', 'test_finance_ui_integrity', 'test_finance_invoice_editor', 'test_finance_workspace_corrections'],
}

def run(root, modules):
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    environment['PYTHONPATH'] = str(root/'client-hub')+os.pathsep+str(root/'client-hub/tests')
    result = subprocess.run([sys.executable, '-m', 'unittest', *modules], cwd=root/'client-hub/tests', env=environment, text=True, capture_output=True, timeout=240)
    output = result.stdout+'\n'+result.stderr
    if not re.search(r'Ran \d+ tests?', output):
        raise RuntimeError('Test harness did not complete: '+output[-2000:])
    failures = collections.Counter(re.findall(r'^(?:FAIL|ERROR): (.+)$', output, re.M))
    return {'exit_code': result.returncode, 'failures': dict(failures)}

def main():
    if os.name == 'nt':
        raise RuntimeError('Run this comparison on Linux CI; Windows fixtures hold open SQLite files.')
    report = {'baseline': BASELINE, 'groups': {}}
    with tempfile.TemporaryDirectory(prefix='kilas-reference-baseline-') as folder:
        baseline = Path(folder)/'baseline'
        subprocess.run(['git','worktree','add','--detach',str(baseline),BASELINE],cwd=ROOT,check=True,capture_output=True)
        try:
            for name,modules in GROUPS.items():
                before,after = run(baseline,modules),run(ROOT,modules)
                added = collections.Counter(after['failures'])-collections.Counter(before['failures'])
                report['groups'][name] = {'baseline':before,'candidate':after,'new_failures':dict(added)}
        finally:
            if not baseline.resolve().is_relative_to(Path(folder).resolve()):
                raise RuntimeError('Baseline cleanup escaped its temporary directory')
            subprocess.run(['git','worktree','remove','--force',str(baseline)],cwd=ROOT,check=True,capture_output=True)
    print(json.dumps(report,indent=2))
    target = Path(os.environ.get('KILAS_REFERENCE_BASELINE_REPORT','reference-baseline-comparison.json'))
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    if any(group['new_failures'] for group in report['groups'].values()):
        raise SystemExit('Candidate introduced a legacy regression; inspect the comparison artifact.')

if __name__ == '__main__':
    main()
