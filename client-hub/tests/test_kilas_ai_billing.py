"""Focused account-owned Kilas AI manual transfer and admin activation checks."""
import io
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIENT_HUB_DB_PATH"] = tempfile.mktemp(prefix="kilas-ai-billing-", suffix=".sqlite")
os.environ["SECRET_KEY"] = "kilas-ai-billing-test-only"
os.environ["KILAS_AI_ENABLED"] = "true"
os.environ.pop("DATABASE_URL", None)

import app  # noqa: E402
import db  # noqa: E402
import repo  # noqa: E402
from kilas_ai import billing, usage  # noqa: E402


class BillingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app.app
        cls.app.config.update(TESTING=True, CLIENT_HUB_FORCE_CSRF_IN_TESTS=True)
        cls.owner = repo.create_user("ai-billing-owner@example.test", "hash")
        cls.other = repo.create_user("ai-billing-other@example.test", "hash")
        cls.admin = repo.create_user("ai-billing-admin@example.test", "hash", role="KILAS_ADMIN")

    def client_for(self, user, role="CLIENT_OWNER"):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=user, role=role, _csrf_token="billing-csrf")
        return client

    def test_checkout_owner_isolation_and_manual_activation(self):
        owner = self.client_for(self.owner)
        other = self.client_for(self.other)
        admin = self.client_for(self.admin, "KILAS_ADMIN")
        response = owner.post("/kilas-ai/checkout", data={"plan": "PLUS", "csrf_token": "billing-csrf"})
        self.assertEqual(response.status_code, 303)
        item = billing.owner_invoices(self.owner)[0]
        self.assertEqual(item["amount_idr"], 99000)
        self.assertEqual(usage.effective_plan(self.owner)["plan"], "FREE")
        self.assertEqual(other.get(f"/kilas-ai/invoices/{item['id']}").status_code, 404)
        self.assertEqual(owner.get(f"/kilas-ai/invoices/{item['id']}").status_code, 200)
        self.assertEqual(owner.get("/admin/kilas-ai/payments").status_code, 404)
        self.assertIn(b"7610267551", owner.get(f"/kilas-ai/invoices/{item['id']}").data)
        self.assertEqual(billing.create_invoice(self.owner, "PLUS"), item["id"])
        bad = owner.post(f"/kilas-ai/invoices/{item['id']}/proof", data={"csrf_token": "billing-csrf",
            "proof": (io.BytesIO(b"<script>bad</script>"), "proof.pdf", "application/pdf")})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(usage.effective_plan(self.owner)["plan"], "FREE")
        with patch("file_utils.validate_project_attachment_upload", return_value=("proof.png", "image/png")):
            submitted = owner.post(f"/kilas-ai/invoices/{item['id']}/proof", data={"csrf_token": "billing-csrf",
                "proof": (io.BytesIO(b"test image bytes"), "proof.png", "image/png")})
        self.assertEqual(submitted.status_code, 303)
        self.assertEqual(usage.effective_plan(self.owner)["plan"], "FREE")
        pending = billing.pending_payments()
        self.assertEqual(len(pending), 1)
        payment_id = pending[0]["id"]
        economics_page = admin.get("/admin/kilas-ai/payments")
        self.assertEqual(economics_page.status_code, 200)
        self.assertIn(b"Perkiraan biaya provider/tool", economics_page.data)
        self.assertIn(b"Review pembayaran Kilas AI", admin.get("/platform/subscriptions").data)
        self.assertEqual(other.get(f"/admin/kilas-ai/payments/{payment_id}/proof").status_code, 404)
        verified = admin.post(f"/admin/kilas-ai/payments/{payment_id}/review",
                              data={"decision": "VERIFIED", "csrf_token": "billing-csrf"})
        self.assertEqual(verified.status_code, 303)
        state = usage.effective_plan(self.owner)
        self.assertEqual(state["plan"], "PLUS")
        self.assertEqual((state["period_end"] - state["period_start"]).days, 30)
        self.assertEqual(admin.post(f"/admin/kilas-ai/payments/{payment_id}/review",
            data={"decision": "VERIFIED", "csrf_token": "billing-csrf"}).status_code, 303)
        self.assertEqual(usage.effective_plan(self.owner)["period_end"], state["period_end"])

    def test_rejection_renewal_and_plan_change(self):
        invoice_id = billing.create_invoice(self.other, "PRO")
        with patch("file_utils.validate_project_attachment_upload", return_value=("proof.png", "image/png")):
            from werkzeug.datastructures import FileStorage
            billing.submit_proof(self.other, invoice_id, FileStorage(stream=io.BytesIO(b"proof"),
                filename="proof.png", content_type="image/png"))
        payment_id = next(row["id"] for row in billing.pending_payments() if row["invoice_id"] == invoice_id)
        with self.assertRaises(billing.BillingError):
            billing.review(payment_id, self.owner, "VERIFIED")
        billing.review(payment_id, self.admin, "REJECTED", "Bukti kurang jelas")
        self.assertEqual(usage.effective_plan(self.other)["plan"], "FREE")
        self.assertEqual(billing.proof_status(self.other, invoice_id)["admin_note"], "Bukti kurang jelas")
        with patch("file_utils.validate_project_attachment_upload", return_value=("proof.png", "image/png")):
            billing.submit_proof(self.other, invoice_id, FileStorage(stream=io.BytesIO(b"proof2"),
                filename="proof.png", content_type="image/png"))
        billing.review(payment_id, self.admin, "VERIFIED")
        first_end = usage.effective_plan(self.other)["period_end"]
        renewed_invoice = billing.create_invoice(self.other, "PRO")
        with patch("file_utils.validate_project_attachment_upload", return_value=("proof.png", "image/png")):
            billing.submit_proof(self.other, renewed_invoice, FileStorage(stream=io.BytesIO(b"proof3"),
                filename="proof.png", content_type="image/png"))
        billing.review(next(row["id"] for row in billing.pending_payments() if row["invoice_id"] == renewed_invoice),
                       self.admin, "VERIFIED")
        self.assertEqual(usage.effective_plan(self.other)["period_end"], first_end + timedelta(days=30))
        new_invoice = billing.create_invoice(self.other, "MAX")
        with patch("file_utils.validate_project_attachment_upload", return_value=("proof.png", "image/png")):
            billing.submit_proof(self.other, new_invoice, FileStorage(stream=io.BytesIO(b"proof4"),
                filename="proof.png", content_type="image/png"))
        billing.review(next(row["id"] for row in billing.pending_payments() if row["invoice_id"] == new_invoice),
                       self.admin, "VERIFIED")
        self.assertEqual(usage.effective_plan(self.other)["plan"], "MAX")
        self.assertEqual((usage.effective_plan(self.other)["period_end"] -
                          usage.effective_plan(self.other)["period_start"]).days, 30)


if __name__ == "__main__":
    unittest.main()
