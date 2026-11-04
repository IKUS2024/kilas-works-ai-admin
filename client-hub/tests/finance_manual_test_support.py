"""Disposable manual-Finance fixtures with the current receipt provider contract."""
import hashlib
import json
from unittest.mock import patch
import test_finance_phase2a as prior
from test_finance_phase6a import image_bytes
import finance_ai_safety as safety
import finance_receipts as receipts


def set_up_manual_finance(case):
    prior.ReceivablesTests.setUp(case)
    safety._RATE.clear()
    case.addCleanup(safety._RATE.clear)
    signing = patch.dict(prior.app.config, SECRET_KEY='receipt-test-signing-key-at-least-32-characters')
    signing.start(); case.addCleanup(signing.stop)
    # Changing the signing key invalidates the original cookie; issue a real session.
    from auth_test_helpers import authenticate
    import repo
    authenticate(case.client, repo.get_user_by_id(case.uid))
    case.client.set_cookie('kilas_language', 'id')
    case.expense = receipts.options(case.b, case.uid)[1][0]
    case.raw = image_bytes()
    case.hash = hashlib.sha256(case.raw).hexdigest()
    result = dict(merchant_name='Synthetic shop', transaction_date='2026-09-17',
                  total_minor=125000, currency='IDR', receipt_number='R-1',
                  description='Office supplies', suggested_category_name=None, readable=True)
    for target, value in (
        ('kilas_ai.workspace_execution_access.entitled', True),
        ('kilas_ai.chat_models.check', {'available': True, 'images': True}),
        ('kilas_ai.usage.reserve', ('PRO', ('CHAT',))),
        ('kilas_ai.usage.finish', None),
    ):
        mock = patch(target, return_value=value)
        mock.start(); case.addCleanup(mock.stop)
    provider = patch('kilas_ai.providers._openai', side_effect=lambda *a, **kw: iter([
        {'type': 'delta', 'text': json.dumps(result)}, {'type': 'finish', 'reason': 'stop'}]))
    case.http = provider.start(); case.addCleanup(provider.stop)
