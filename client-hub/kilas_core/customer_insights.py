"""AI Customer Insight: tenant-scoped structured memory derived only from actual chat text."""
import json
import time
import ai_onboarding
import ai_usage
import db
from kilas_core import customers


SYSTEM_PROMPT = """Kamu menganalisis percakapan customer untuk pemilik bisnis.
Buat Customer Insight berdasarkan HANYA fakta yang benar-benar tertulis dalam percakapan.
JANGAN menebak nama, bisnis, lokasi, budget, kebutuhan, niat beli, atau fakta lain.
Jika belum diketahui gunakan null atau masukkan ke unknowns.
Pesan berlabel CUSTOMER adalah ucapan customer. Pesan BUSINESS adalah balasan bisnis/AI dan bukan fakta tentang customer kecuali customer sendiri mengonfirmasinya.
Ringkas dalam Bahasa Indonesia, singkat dan berguna untuk sales/admin.
Balas HANYA JSON valid dengan struktur:
{
 "summary": string|null,
 "known_name": string|null,
 "business_name": string|null,
 "location": string|null,
 "needs": string|null,
 "budget": string|null,
 "intent": string|null,
 "important_questions": [string],
 "buying_signals": [string],
 "unknowns": [string],
 "follow_up": string|null
}
Array maksimal 5 item. Jangan sertakan markdown."""


def _json_list(value):
    if not isinstance(value,list):
        return []
    return [str(x).strip()[:300] for x in value[:5] if str(x).strip()]


def _clean(value, maximum=1000):
    if value is None:
        return None
    value=str(value).strip()
    return value[:maximum] if value else None


def _demo_messages(bid, customer):
    phone=customer.get("phone")
    if not phone:
        return []
    try:
        row=db.query_one(
            "SELECT detail FROM audit_log WHERE business_id=? AND action='demo_whatsapp_bound' ORDER BY id DESC LIMIT 1",
            (bid,))
        detail=json.loads(row["detail"]) if row and row.get("detail") else {}
        if detail.get("phone") != phone:
            return []
        start=max(0,int(detail.get("start_message_id") or 0))
        rows=db.query_all(
            "SELECT id,role,content,created_at FROM messages WHERE number=? AND id>=? "
            "AND mode='customer' ORDER BY id ASC LIMIT 300",(phone,start))
        return [{"source":"DEMO_WHATSAPP","id":int(r["id"]),"role":r["role"],
                 "content":r.get("content") or "","created_at":r.get("created_at")} for r in rows]
    except Exception:
        return []


def _core_messages(bid, customer_id):
    with customers.transaction() as tx:
        rows=tx.execute(
            "SELECT m.id,m.role,m.content,m.created_at,w.id AS conversation_id "
            "FROM kw_web_customer_links l JOIN kw_web_conversations w "
            "ON w.business_id=l.business_id AND w.id=l.conversation_id "
            "JOIN kw_web_messages m ON m.business_id=w.business_id AND m.conversation_id=w.id "
            "WHERE l.business_id=? AND l.customer_id=? ORDER BY m.created_at,m.id LIMIT 300",
            (bid,customer_id))
    return [{"source":"WHATSAPP" if str(r["conversation_id"]).startswith("wa_") else "WEB",
             "id":int(r["id"]),"role":r["role"],"content":r.get("content") or "",
             "created_at":r.get("created_at")} for r in rows]


def messages(bid, customer_id):
    customer=customers.get_customer(bid,customer_id)
    rows=_core_messages(bid,customer_id)+_demo_messages(bid,customer)
    # Stable de-duplication by source/id; demo mirror and Core are intentionally separate sources.
    rows.sort(key=lambda r:(str(r.get("created_at") or ""),r["source"],r["id"]))
    return rows


def conversation_count(bid, customer_id):
    rows=messages(bid,customer_id)
    return len({r["source"] + (":" + str(r.get("conversation_id",""))) for r in rows}) if rows else 0


def get(bid,customer_id):
    with customers.transaction() as tx:
        row=tx.one("SELECT * FROM kw_core_customer_insights WHERE business_id=? AND customer_id=?",
                   (bid,customer_id))
    if not row:
        return None
    for key in ("important_questions","buying_signals","unknowns"):
        try: row[key]=json.loads(row.get(key) or "[]")
        except Exception: row[key]=[]
    return row


def refresh(bid,customer_id,*,force=False):
    customer=customers.get_customer(bid,customer_id)
    rows=messages(bid,customer_id)
    if not rows:
        return get(bid,customer_id)
    last=max([int(r.get("id") or 0) for r in rows] or [0])
    current=get(bid,customer_id)
    if current and not force and current["status"]=="READY" and int(current["source_message_count"])==len(rows):
        return current

    # Keep the model request bounded. Existing structured memory + latest messages preserves
    # longitudinal context without resending an unbounded transcript forever.
    recent=rows[-80:]
    transcript=[]
    for r in recent:
        role="CUSTOMER" if r["role"] in ("user","customer") else "BUSINESS"
        transcript.append(f"{role}: {(r['content'] or '')[:1200]}")
    prior=""
    if current and current.get("status")=="READY":
        prior="\nINSIGHT SEBELUMNYA:\n"+json.dumps(
            {k:current.get(k) for k in ("summary","known_name","business_name","location","needs","budget","intent",
                                        "important_questions","buying_signals","unknowns","follow_up")},
            ensure_ascii=False)
    prompt=prior+"\nPERCAKAPAN TERBARU:\n"+"\n".join(transcript)
    with ai_usage.scope(bid,"customer_insight"):
        raw,stop,error=ai_onboarding._call_claude(
            SYSTEM_PROMPT,[{"role":"user","content":prompt}],max_tokens=1200,
            model=ai_onboarding.CLIENT_HUB_SIMULATION_MODEL)
    now=int(time.time())
    if error or stop=="max_tokens":
        with customers.transaction() as tx:
            tx.execute(
                "INSERT INTO kw_core_customer_insights(business_id,customer_id,status,updated_at) "
                "VALUES (?,?,'FAILED',?) ON CONFLICT(business_id,customer_id) DO UPDATE SET status='FAILED',updated_at=excluded.updated_at",
                (bid,customer_id,now))
        return get(bid,customer_id)
    try:
        data=ai_onboarding._extract_json_object(raw)
        if not isinstance(data,dict): raise ValueError("shape")
    except Exception:
        with customers.transaction() as tx:
            tx.execute(
                "INSERT INTO kw_core_customer_insights(business_id,customer_id,status,updated_at) "
                "VALUES (?,?,'FAILED',?) ON CONFLICT(business_id,customer_id) DO UPDATE SET status='FAILED',updated_at=excluded.updated_at",
                (bid,customer_id,now))
        return get(bid,customer_id)

    clean={
      "summary":_clean(data.get("summary"),1500),"known_name":_clean(data.get("known_name"),160),
      "business_name":_clean(data.get("business_name"),200),"location":_clean(data.get("location"),300),
      "needs":_clean(data.get("needs"),1000),"budget":_clean(data.get("budget"),300),
      "intent":_clean(data.get("intent"),700),"important_questions":_json_list(data.get("important_questions")),
      "buying_signals":_json_list(data.get("buying_signals")),"unknowns":_json_list(data.get("unknowns")),
      "follow_up":_clean(data.get("follow_up"),1000)
    }
    with customers.transaction() as tx:
        tx.execute(
          "INSERT INTO kw_core_customer_insights"
          "(business_id,customer_id,summary,known_name,business_name,location,needs,budget,intent,"
          "important_questions,buying_signals,unknowns,follow_up,source_message_count,source_last_at,status,updated_at) "
          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'READY',?) "
          "ON CONFLICT(business_id,customer_id) DO UPDATE SET summary=excluded.summary,known_name=excluded.known_name,"
          "business_name=excluded.business_name,location=excluded.location,needs=excluded.needs,budget=excluded.budget,"
          "intent=excluded.intent,important_questions=excluded.important_questions,buying_signals=excluded.buying_signals,"
          "unknowns=excluded.unknowns,follow_up=excluded.follow_up,source_message_count=excluded.source_message_count,"
          "source_last_at=excluded.source_last_at,status='READY',updated_at=excluded.updated_at",
          (bid,customer_id,clean["summary"],clean["known_name"],clean["business_name"],clean["location"],
           clean["needs"],clean["budget"],clean["intent"],json.dumps(clean["important_questions"],ensure_ascii=False),
           json.dumps(clean["buying_signals"],ensure_ascii=False),json.dumps(clean["unknowns"],ensure_ascii=False),
           clean["follow_up"],len(rows),last,now))
    return get(bid,customer_id)
