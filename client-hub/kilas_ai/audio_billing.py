"""Audio prepaid packs using existing manual-transfer verification conventions."""
import secrets
import db
import file_utils
from . import audio_store as store, usage


def order(user,ident):
    return db.query_one('SELECT id,invoice_number,pack,seconds,amount_idr,status,admin_note FROM kilas_audio_orders WHERE user_id=? AND id=?',(user,ident))


def create(user,pack):
    if pack not in store.PACKS:raise store.AudioError('Pilih paket Saldo Audio yang tersedia.')
    seconds,price=store.PACKS[pack]
    with store.locked(user) as conn:
        existing=usage._query(conn,"SELECT id FROM kilas_audio_orders WHERE user_id=? AND pack=? AND status IN ('PAYMENT_PENDING','UNDER_REVIEW')",(user,pack),one=True)
        if existing:return existing[0]
        now=usage._now().isoformat()
        sql='INSERT INTO kilas_audio_orders(user_id,invoice_number,pack,seconds,amount_idr,created_at,updated_at) VALUES (?,?,?,?,?,?,?)'
        args=(user,'KAU-'+secrets.token_hex(8).upper(),pack,seconds,price,now,now)
        if db.BACKEND=='postgres':return usage._query(conn,sql+' RETURNING id',args,one=True)[0]
        return conn.execute(sql,args).lastrowid


def proof(user,ident,item):
    if not item or not item.filename:raise store.AudioError('Pilih bukti transfer berupa gambar atau PDF.')
    raw=item.stream.read(5*1024*1024+1)
    if not raw or len(raw)>5*1024*1024:raise store.AudioError('Bukti transfer maksimal 5 MB.')
    try:name,mime=file_utils.validate_project_attachment_upload(item.filename,raw)
    except file_utils.UploadRejected:raise store.AudioError('Bukti transfer tidak valid.') from None
    if item.mimetype not in (mime,'application/octet-stream'):raise store.AudioError('Jenis file bukti transfer tidak sesuai.')
    with store.locked(user) as conn:
        row=usage._query(conn,'SELECT status FROM kilas_audio_orders WHERE user_id=? AND id=?',(user,ident),one=True)
        if not row or row[0] not in ('PAYMENT_PENDING','REJECTED'):raise store.AudioError('Bukti pembayaran sudah dalam review atau tagihan tidak ditemukan.')
        usage._query(conn,"UPDATE kilas_audio_orders SET status='UNDER_REVIEW',proof_filename=?,proof_mime_type=?,proof_content=?,updated_at=? WHERE user_id=? AND id=?",(name,mime,raw,usage._now().isoformat(),user,ident))


def pending():
    return db.query_all("SELECT o.id,o.invoice_number,o.seconds,o.amount_idr,u.email,o.proof_filename FROM kilas_audio_orders o JOIN users u ON u.id=o.user_id WHERE o.status='UNDER_REVIEW' ORDER BY o.id LIMIT 100")


def review(ident,admin,decision,note=''):
    row=db.query_one('SELECT role FROM users WHERE id=?',(admin,))
    if not row or row['role']!='KILAS_ADMIN':raise store.AudioError('Hanya admin Kilas dapat memverifikasi pembayaran.','forbidden',404)
    if decision not in ('VERIFIED','REJECTED'):raise store.AudioError('Keputusan pembayaran tidak valid.')
    seed=db.query_one('SELECT user_id FROM kilas_audio_orders WHERE id=?',(ident,))
    if not seed:raise store.AudioError('Tagihan tidak ditemukan.','not_found',404)
    user=seed['user_id']
    with store.locked(user) as conn:
        item=usage._query(conn,'SELECT status,seconds,pack,amount_idr FROM kilas_audio_orders WHERE user_id=? AND id=?',(user,ident),one=True)
        if item[0]==decision:return
        if item[0]!='UNDER_REVIEW':raise store.AudioError('Pembayaran tidak siap diverifikasi.')
        if (item[1],item[3])!=store.PACKS.get(item[2]):raise store.AudioError('Paket pembayaran tidak sesuai.')
        if decision=='VERIFIED':
            usage._query(conn,'INSERT INTO kilas_audio_balances(user_id,seconds) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET seconds=kilas_audio_balances.seconds+excluded.seconds',(user,item[1]))
        usage._query(conn,'UPDATE kilas_audio_orders SET status=?,verified_by=?,verified_at=?,admin_note=?,updated_at=? WHERE user_id=? AND id=?',
                     (decision,admin,usage._now().isoformat(),str(note or '').strip()[:1000],usage._now().isoformat(),user,ident))
