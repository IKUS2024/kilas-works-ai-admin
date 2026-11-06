"""Run one existing synthetic browser journey under pytest's socket guard."""
import os
from pathlib import Path
import runpy
import unittest


def test_credit_browser(request):
    cases = {
        'wallet': 'credit_wallet_browser.py',
        'work': 'credit_work_browser.py',
        'work_steps': 'credit_work_steps_browser.py',
        'popup_repro': 'credit_popup_repro.py',
    }
    selected = os.environ.get('KILAS_CREDIT_BROWSER_CASE')
    if not selected:
        raise unittest.SkipTest('Select an explicit synthetic credit browser case')
    assert request.config.getoption('disable_socket'), 'Browser QA requires the socket guard'
    runpy.run_path(str(Path(__file__).with_name(cases[selected])), run_name='__main__')
