"""Run packaged fake regressions, emitting only aggregate verification results."""
import json
import time
import unittest
from pathlib import Path

if __name__ == '__main__':
    started=time.perf_counter()
    suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_*.py')
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    report=dict(offline_only=True,tests=result.testsRun,successful=result.wasSuccessful(),
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        seconds=round(time.perf_counter()-started,3),native_sdk_attachments=0,
        native_order_checks=0,native_order_sends=0,paid_model_requests=0,
        cloud_commit='db035b5da415bed61bed08e2b1cac50d8d31f73c')
    Path(__file__).with_name('offline-test-result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
