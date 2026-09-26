import json
import os
import tempfile
import unittest
from unittest.mock import patch


class CustomerInsightTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        os.environ["DATABASE_URL"]="sqlite:///"+self.tmp.name+"/test.db"
        os.environ["KILAS_CUSTOMERS_V2_ENABLED"]="true"
        import importlib,db
        importlib.reload(db)
        db.init_schema()
        global customers,customer_schema,customer_insight_schema,insights
        from kilas_core import customers,customer_schema,customer_insight_schema
        from kilas_core import customer_insights as insights
        customer_schema.apply_schema()
        customer_insight_schema.apply_schema()
        db.execute("INSERT INTO users(id,email,password_hash,role,created_at) VALUES (1,'x','x','CLIENT',1)")
        db.execute("INSERT INTO businesses(id,user_id,business_name,package,status,created_at,updated_at) VALUES (7,1,'Demo','AI_ADMIN','ACTIVE',1,1)")
        db.execute("INSERT INTO messages(number,mode,role,content,created_at) VALUES ('14048836437','customer','user','Demo ID: AAAA-BBBB',1)")
        db.execute("INSERT INTO messages(number,mode,role,content,created_at) VALUES ('14048836437','customer','assistant','Demo aktif',2)")
        db.execute("INSERT INTO messages(number,mode,role,content,created_at) VALUES ('14048836437','customer','user','kamu punya paket apa saja',3)")
        db.execute("INSERT INTO audit_log(actor_user_id,business_id,action,detail) VALUES (1,7,'demo_whatsapp_bound',?)",
                   (json.dumps({"phone":"14048836437","start_message_id":1,"bound_at":1}),))
        self.customer=customers.ensure_whatsapp_lead(7,"14048836437")

    def tearDown(self):
        self.tmp.cleanup()

    def test_inbox_only_incremental_insight(self):
        snap=insights.inbox_snapshot(7,self.customer["id"])
        self.assertEqual(snap["conversation_count"],1)
        self.assertEqual(snap["message_count"],1)
        self.assertEqual(snap["messages"][0]["content"],"kamu punya paket apa saja")

        answer=json.dumps({
          "summary":"Lead menanyakan paket yang tersedia.","known_name":None,"business_name":None,
          "location":None,"needs":"Informasi paket Kilas","budget":None,
          "intent":"Sedang mengeksplorasi layanan","important_questions":["Paket apa saja yang tersedia?"],
          "buying_signals":["Menanyakan paket"],"unknowns":["Nama","Jenis bisnis","Budget"],
          "follow_up":"Tanyakan jenis bisnis dan kebutuhan utamanya."
        })
        with patch("ai_onboarding._call_claude",return_value=(answer,"end_turn",None)) as call:
            row=insights.refresh(7,self.customer["id"],snapshot=snap)
            self.assertEqual(row["status"],"READY")
            self.assertEqual(row["known_name"],None)
            self.assertEqual(row["needs"],"Informasi paket Kilas")
            self.assertEqual(call.call_count,1)
            # Same Inbox snapshot: no second model call.
            insights.refresh(7,self.customer["id"],snapshot=snap)
            self.assertEqual(call.call_count,1)

        import db
        db.execute("INSERT INTO messages(number,mode,role,content,created_at) VALUES ('14048836437','customer','user','nama saya Budi, saya punya coffee shop',4)")
        changed=insights.inbox_snapshot(7,self.customer["id"])
        self.assertEqual(changed["message_count"],2)
        self.assertNotEqual(changed["source_version"],snap["source_version"])

    def test_web_chat_is_not_customer_insight_source(self):
        from public_chat import store
        store.ensure_channel(7)
        with store.transaction() as tx:
            now=10
            tx.execute("INSERT INTO kw_web_conversations(id,business_id,visitor_hash,expires_at,created_at,updated_at) VALUES ('webx',7,'hashx',9999999999,?,?)",(now,now))
            web=customers.ensure_web_customer(tx,7,"webx","hashx",now=now)
            tx.execute("INSERT INTO kw_web_messages(business_id,conversation_id,event_id,role,content,created_at) VALUES (7,'webx','e1','user','nama saya Salah',?)",(now,))
        snap=insights.inbox_snapshot(7,web["id"])
        self.assertEqual(snap["message_count"],0)
        self.assertEqual(snap["conversation_count"],0)


if __name__=="__main__":
    unittest.main()
