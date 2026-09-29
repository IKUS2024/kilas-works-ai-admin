"""The disposable browser process accepts only signed, owner-scoped calls."""
import hashlib
import hmac
import importlib.util
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client-hub"))
spec = importlib.util.spec_from_file_location("kilas_work_browser_worker", ROOT / "work-browser" / "app.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
SECRET = "test-browser-secret-32-characters-long"


def headers(method, path, owner, body=b""):
    timestamp = str(int(time.time()))
    digest = hashlib.sha256(body).hexdigest()
    signed = "\n".join((method, path, digest, timestamp, str(owner))).encode()
    return {"X-Work-Owner": str(owner), "X-Work-Time": timestamp,
            "X-Work-Signature": hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}


class BrowserWorkerTests(unittest.TestCase):
    def setUp(self):
        self.client = worker.app.test_client()

    def test_health_public_but_sessions_signed(self):
        with patch.dict(os.environ, {"KILAS_WORK_BROWSER_SECRET": SECRET}):
            self.assertEqual(self.client.get("/healthz").status_code, 200)
            self.assertEqual(self.client.get("/sessions/1").status_code, 403)
            auth = headers("GET", "/sessions/1", 12)
            with patch.object(worker.runtime, "snapshot", return_value={"url": "https://example.com", "screenshot": "abc"}) as snapshot:
                self.assertEqual(self.client.get("/sessions/1", headers=auth).status_code, 200)
                snapshot.assert_called_once_with(12, 1)
            auth["X-Work-Owner"] = "13"
            self.assertEqual(self.client.get("/sessions/1", headers=auth).status_code, 403)

    def test_body_signature_prevents_action_tampering(self):
        path = "/sessions/7/actions"
        body = json.dumps({"call_id": "call-safe", "actions": [{"type": "screenshot"}]}).encode()
        with patch.dict(os.environ, {"KILAS_WORK_BROWSER_SECRET": SECRET}):
            auth = headers("POST", path, 4, body)
            with patch.object(worker.runtime, "actions", return_value={"decision": "CONTINUE"}) as execute:
                self.assertEqual(self.client.post(path, data=body, headers=auth).status_code, 200)
                execute.assert_called_once()
            changed = json.dumps({"call_id": "call-safe", "actions": [{"type": "click", "x": 1, "y": 1}]}).encode()
            self.assertEqual(self.client.post(path, data=changed, headers=auth).status_code, 403)


if __name__ == "__main__":
    unittest.main()
