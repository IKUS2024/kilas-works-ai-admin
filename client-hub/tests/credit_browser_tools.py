"""Select and attest the actual synthetic-test browser, never application policy."""
import json
import os
import shutil


def launch(playwright):
    bundled = os.environ.get('KILAS_CREDIT_BROWSER_BUNDLED') == 'yes'
    executable = None if bundled else shutil.which('chromium')
    browser = playwright.chromium.launch(**({'executable_path': executable} if executable else {'channel': 'chromium'}))
    expected = os.environ.get('KILAS_CREDIT_BROWSER_MAJOR')
    actual = browser.version
    print('CREDIT_BROWSER_SELECTED '+json.dumps({'version': actual, 'bundled': bundled}), flush=True)
    if expected and actual.split('.')[0] != expected:
        browser.close()
        raise AssertionError(f'Expected Chromium {expected}, actually launched {actual}')
    return browser
