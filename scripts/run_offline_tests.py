"""Runs existing test runner with all network connections blocked, including child processes."""
import os
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
env = dict(os.environ)
env['PYTHONPATH'] = str(root / 'scripts' / 'offline_tests') + os.pathsep + env.get('PYTHONPATH', '')
raise SystemExit(subprocess.call([sys.executable, str(root / 'run_all_tests.py'), *sys.argv[1:]], cwd=root, env=env))
