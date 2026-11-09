"""One admin queue over existing manual invoices, never a new credit product.

The owning billing services remain the only settlement authority. Their locks,
idempotency, prices and entitlement rules are deliberately not duplicated here.
"""
import db
from kilas_ai import billing, topups, audio_billing
import finance_subscription

PRODUCTS = (("subscription", "Kilas AI"), ("capacity", "Kapasitas AI"),
            ("translator", "Translator & Voice Over"), ("finance", "Kilas Finance"))
PAGE_SIZE = 30

# Every identifier below is server-owned. Only bound filter values come from requests.
_ORDERS = """
SELECT 'subscription' AS kind,i.id AS record_id,p.id AS payment_id,
       i.invoice_number,i.amount_idr,i.status,REPLACE(CAST(i.created_at AS TEXT),'T',' ') AS created_at,REPLACE(CAST(i.updated_at AS TEXT),'T',' ') AS updated_at,
       u.id AS user_id,u.full_name,u.email,'' AS business_name,i.plan AS package,
       0 AS seconds,CASE WHEN p.proof_content IS NOT NULL AND length(p.proof_content)>0
                       AND p.status=i.status THEN 1 ELSE 0 END AS proof_ready,
       p.admin_note AS note,p.verified_by AS reviewed_by
FROM kilas_ai_invoices i JOIN users u ON u.id=i.user_id
LEFT JOIN kilas_ai_payments p ON p.invoice_id=i.id AND p.user_id=i.user_id
UNION ALL
SELECT 'capacity',o.id,o.id,o.invoice_number,o.amount_idr,o.status,REPLACE(CAST(o.created_at AS TEXT),'T',' '),REPLACE(CAST(o.updated_at AS TEXT),'T',' '),
       u.id,u.full_name,u.email,'','',0,
       CASE WHEN o.proof_content IS NOT NULL AND length(o.proof_content)>0 THEN 1 ELSE 0 END,
       o.admin_note,o.verified_by
FROM kilas_ai_topup_orders o JOIN users u ON u.id=o.user_id
UNION ALL
SELECT 'translator',o.id,o.id,o.invoice_number,o.amount_idr,o.status,REPLACE(CAST(o.created_at AS TEXT),'T',' '),REPLACE(CAST(o.updated_at AS TEXT),'T',' '),
       u.id,u.full_name,u.email,'',o.pack,o.seconds,
       CASE WHEN o.proof_content IS NOT NULL AND length(o.proof_content)>0 THEN 1 ELSE 0 END,
       o.admin_note,o.verified_by
FROM kilas_audio_orders o JOIN users u ON u.id=o.user_id
UNION ALL
SELECT 'finance',f.id,f.id,'FIN-' || CAST(f.id AS TEXT),f.amount_minor,
       CASE WHEN f.status='REVIEW' THEN 'UNDER_REVIEW'
            WHEN f.status='PENDING' THEN 'PAYMENT_PENDING' ELSE f.status END,
       REPLACE(CAST(f.created_at AS TEXT),'T',' '),REPLACE(CAST(f.updated_at AS TEXT),'T',' '),u.id,u.full_name,u.email,b.business_name,f.product_key,0,
       CASE WHEN f.proof_content IS NOT NULL AND length(f.proof_content)>0
                 AND f.proof_hash IS NOT NULL THEN 1 ELSE 0 END,
       '',f.reviewed_by_user_id
FROM finance_subscription_bills f JOIN businesses b ON b.id=f.business_id
JOIN users u ON u.id=f.created_by_user_id
"""


def queue(product="", status="", query="", page=1):
    history = status == "history"
    where = ["status <> 'UNDER_REVIEW'" if history else "status = 'UNDER_REVIEW'"]
    args = []
    if product in dict(PRODUCTS):
        where.append("kind=?")
        args.append(product)
    if query:
        where.append("LOWER(COALESCE(full_name,'') || ' ' || email || ' ' || invoice_number || ' ' || business_name) LIKE ?")
        args.append("%" + query.lower() + "%")
    source = " FROM (" + _ORDERS + ") orders WHERE " + " AND ".join(where)
    total = int(db.query_one("SELECT COUNT(*) AS n" + source, tuple(args))["n"])
    page = min(max(1, page), max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE))
    rows = db.query_all("SELECT *" + source + " ORDER BY created_at " + ("DESC" if history else "ASC") +
                        ",kind,record_id LIMIT ? OFFSET ?", tuple(args + [PAGE_SIZE, (page - 1) * PAGE_SIZE]))
    labels = {"UNDER_REVIEW": "Perlu approval", "PAYMENT_PENDING": "Menunggu bukti",
              "VERIFIED": "Disetujui", "REJECTED": "Ditolak"}
    for row in rows:
        row["product_label"] = dict(PRODUCTS)[row["kind"]]
        row["status_label"] = labels.get(row["status"], row["status"])
        row["effect"] = ("Saldo audio bertambah " + str(row["seconds"]) + " detik" if row["kind"] == "translator" else
                         "Langganan Finance aktif sesuai tagihan" if row["kind"] == "finance" else
                         "Kapasitas AI ditambahkan sesuai tagihan" if row["kind"] == "capacity" else
                         "Langganan " + row["package"] + " aktif selama 30 hari")
    pending = int(db.query_one("SELECT COUNT(*) AS n FROM (" + _ORDERS + ") orders WHERE status='UNDER_REVIEW'")["n"])
    return {"rows": rows, "total": total, "pending": pending, "page": page,
            "has_next": page * PAGE_SIZE < total, "history": history, "products": PRODUCTS}


def proof(kind, payment_id):
    if kind == "subscription":
        return billing.admin_proof(payment_id)
    if kind == "capacity":
        table = "kilas_ai_topup_orders"
    elif kind == "translator":
        table = "kilas_audio_orders"
    elif kind == "finance":
        return db.query_one("SELECT proof_content,proof_mime AS proof_mime_type,'bukti-finance' AS proof_filename "
                            "FROM finance_subscription_bills WHERE id=?", (payment_id,))
    else:
        return None
    return db.query_one("SELECT proof_content,proof_mime_type,proof_filename FROM " + table + " WHERE id=?", (payment_id,))


def review(kind, payment_id, admin_id, decision, note=""):
    if kind not in dict(PRODUCTS) or decision not in ("VERIFIED", "REJECTED"):
        raise ValueError("Keputusan pembayaran tidak valid.")
    actor = db.query_one("SELECT role FROM users WHERE id=?", (admin_id,))
    if not actor or actor["role"] != "KILAS_ADMIN":
        raise ValueError("Hanya admin Kilas dapat memverifikasi pembayaran.")
    # Proof is checked again on POST, never trusted from a rendered button.
    evidence = proof(kind, payment_id)
    if not evidence or not evidence["proof_content"]:
        raise ValueError("Bukti pembayaran belum tersedia. Tidak ada akses atau saldo yang diubah.")
    if kind == "subscription":
        billing.review(payment_id, admin_id, decision, note)
    elif kind == "capacity":
        topups.review(payment_id, admin_id, decision, note)
    elif kind == "translator":
        audio_billing.review(payment_id, admin_id, decision, note)
    else:
        item = db.query_one("SELECT business_id FROM finance_subscription_bills WHERE id=?", (payment_id,))
        finance_subscription.review(item["business_id"], payment_id, admin_id, decision == "VERIFIED")
