"""Kilas V2 Phase 3 Customers foundation on disposable SQLite.

Reuses the proven Phase 2 public-chat fixture but applies only additive 0056 on top of 0055.
"""
import os
import unittest
from unittest.mock import patch

import test_public_chat_routes as phase2


class CustomerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        phase2.WebTests.setUpClass.__func__(cls)
        global store, customer_schema, customers
        from public_chat import store
        from kilas_core import customer_schema, customers
        customer_schema.apply_schema()

    tearDown = phase2.WebTests.tearDown

    def setUp(self):
        with store.transaction() as tx:
            for table in ("kw_web_customer_links", "kw_core_customer_identities", "kw_core_customers"):
                tx.execute("DELETE FROM " + table)
        phase2.WebTests.setUp(self)
        # The simulator fixture deliberately shares one owner across both businesses.
        # CRM isolation needs two real, independent owners; do not change the parent fixture.
        self.db.execute('UPDATE business_memberships SET user_id=2 WHERE business_id=8')
        self.customer_flag = patch.dict(os.environ, {"KILAS_CUSTOMERS_V2_ENABLED": "true"})
        self.customer_flag.start()
        self.addCleanup(self.customer_flag.stop)

    def start(self, slug=None, client=None):
        return phase2.WebTests.start(self, slug=slug, client=client)

    def send(self, identity, text="Halo", event="event-00000000001", slug=None, extra=None):
        return phase2.WebTests.send(self, identity, text=text, event=event, slug=slug, extra=extra)

    def test_first_web_visitor_creates_customer_and_same_visitor_reuses_it(self):
        first = self.start().json
        customer = customers.customer_for_conversation(7, first["conversation_id"])
        self.assertIsNotNone(customer)
        self.assertTrue(customer["display_name"].startswith("Pengunjung "))
        second = self.start().json
        self.assertEqual(second["conversation_id"], first["conversation_id"])
        same = customers.customer_for_conversation(7, second["conversation_id"])
        self.assertEqual(same["id"], customer["id"])
        rows, total, _, _ = customers.list_customers(7)
        self.assertEqual(total, 1)
        self.assertEqual(rows[0]["id"], customer["id"])

    def test_different_visitors_are_distinct_and_same_name_never_merges(self):
        first = self.start().json
        other_client = self.app.test_client()
        second = self.start(client=other_client).json
        one = customers.customer_for_conversation(7, first["conversation_id"])
        two = customers.customer_for_conversation(7, second["conversation_id"])
        self.assertNotEqual(one["id"], two["id"])
        customers.update_customer(7, one["id"], display_name="Budi")
        customers.update_customer(7, two["id"], display_name="Budi")
        rows, total, _, _ = customers.list_customers(7, "Budi")
        self.assertEqual(total, 2)
        self.assertEqual({row["id"] for row in rows}, {one["id"], two["id"]})

    def test_tenant_identity_and_owner_access_are_isolated(self):
        first = self.start().json
        customer = customers.customer_for_conversation(7, first["conversation_id"])
        other = self.start(slug=self.other_slug, client=self.app.test_client()).json
        other_customer = customers.customer_for_conversation(8, other["conversation_id"])
        self.assertNotEqual(customer["id"], other_customer["id"])
        self.assertEqual(self.client.get(f"/business/8/customers/{other_customer['id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/business/7/customers/{other_customer['id']}").status_code, 404)
        self.assertEqual(self.client.post(
            f"/business/8/customers/{other_customer['id']}",
            data={"csrf_token":"csrf-test","display_name":"Forged"}).status_code,404)
        with self.client.session_transaction() as session:
            session["user_id"] = 2
        self.assertEqual(self.client.get(f"/business/7/customers/{customer['id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/business/8/customers/{other_customer['id']}").status_code,200)
        self.assertEqual(self.client.post(
            f"/business/7/customers/{customer['id']}",
            data={"csrf_token":"csrf-test","display_name":"Forged"}).status_code,404)
        self.assertEqual(customers.get_customer(7,customer['id'])["display_name"],customer["display_name"])
        self.assertEqual(customers.get_customer(8,other_customer['id'])["display_name"],other_customer["display_name"])

    def test_owner_can_update_profile_without_creating_unverified_identity(self):
        identity = self.start().json
        customer = customers.customer_for_conversation(7, identity["conversation_id"])
        response = self.client.post(
            f"/business/7/customers/{customer['id']}",
            data={
                "csrf_token": "csrf-test",
                "display_name": "Siti Customer",
                "phone": "08123456789",
                "email": "siti@example.com",
                "notes": "Minta follow-up besok",
            },
        )
        self.assertEqual(response.status_code, 302)
        updated = customers.get_customer(7, customer["id"])
        self.assertEqual(updated["display_name"], "Siti Customer")
        self.assertEqual(updated["phone"], "08123456789")
        with customers.transaction() as tx:
            identities = tx.execute(
                "SELECT identity_type FROM kw_core_customer_identities WHERE business_id=? AND customer_id=?",
                (7, customer["id"]),
            )
        self.assertEqual([row["identity_type"] for row in identities], ["WEB_VISITOR"])

    def test_customers_page_and_web_inbox_show_customer_name(self):
        identity = self.start().json
        customer = customers.customer_for_conversation(7, identity["conversation_id"])
        customers.update_customer(7, customer["id"], display_name="Wilson")
        with patch.object(self.ai, "_call_claude", return_value=("Siap Kak", "end_turn", None)):
            self.assertEqual(self.send(identity).status_code, 200)
        listing = self.client.get("/business/7/customers")
        self.assertEqual(listing.status_code, 200)
        self.assertIn(b"Wilson", listing.data)
        inbox = self.client.get(f"/business/7/inbox?channel=web&conversation={identity['conversation_id']}")
        self.assertEqual(inbox.status_code, 200)
        self.assertIn(b"Wilson", inbox.data)
        detail = self.client.get(f"/business/7/customers/{customer['id']}")
        self.assertIn(b"Siap Kak", detail.data)

    def test_flag_off_keeps_phase2_behavior_and_hides_customers_area(self):
        with patch.dict(os.environ, {"KILAS_CUSTOMERS_V2_ENABLED": "false"}):
            identity = self.start().json
            self.assertIsNone(customers.customer_for_conversation(7, identity["conversation_id"]))
            self.assertEqual(self.client.get("/business/7/customers").status_code, 404)
            with patch.object(self.ai, "_call_claude", return_value=("Tetap jalan", "end_turn", None)):
                self.assertEqual(self.send(identity).status_code, 200)

    def test_invalid_profile_fails_closed(self):
        identity = self.start().json
        customer = customers.customer_for_conversation(7, identity["conversation_id"])
        response = self.client.post(
            f"/business/7/customers/{customer['id']}",
            data={"csrf_token": "csrf-test", "display_name": "", "email": "not-an-email"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(customers.get_customer(7, customer["id"])["display_name"], "")


if __name__ == "__main__":
    unittest.main()
