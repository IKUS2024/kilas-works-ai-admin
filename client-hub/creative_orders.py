"""Creative Services order snapshots on the existing project/invoice infrastructure.

The approved public Creative Services catalog is deliberately separate from legacy
Content/Event offers, whose prices AND deliverables differ. No legacy prices change.
"""
import hashlib
import io
import json
import re
import secrets
import warnings
from datetime import date
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from flask import current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature

import db
import payment_service
import projects_repo

CATALOG = json.loads(Path(__file__).with_name('creative_catalog.json').read_text())
BANK = {'bank_name': 'Bank Mega', 'account_number': '010180016000684',
        'account_holder': 'KILAS TEKNOLOGI KREA'}
MAX_PROOF_BYTES = 5 * 1024 * 1024


def money(amount):
    return 'Rp' + format(int(amount), ',').replace(',', '.')


def requires_quote(item):
    return bool(item.get('quotation_required') or item.get('price_type') in
                ('range', 'starting_from', 'quote_only') or item.get('amount') is None)


def checkout_addons(service):
    return {key: value for key, value in CATALOG['addons'].items()
            if key == 'none' or (value.get('service') == service and not requires_quote(value))}


def offer(key, addon='none'):
    if key not in CATALOG['packages'] or addon not in CATALOG['addons']:
        raise ValueError('Pilihan paket tidak tersedia.')
    result = dict(CATALOG['packages'][key])
    extra = CATALOG['addons'][addon]
    if addon != 'none' and result['service'] != extra.get('service'):
        raise ValueError('Add-on hanya tersedia untuk layanan editing.')
    # Reference prices are not payable totals. Percentage/custom items need a quote.
    quote_required = requires_quote(result) or (addon != 'none' and requires_quote(extra))
    total = None if quote_required else result['amount'] + extra['amount']
    result['quotation_required'] = quote_required
    result.update(key=key, addon=addon, addon_name=extra['name'], addon_amount=extra['amount'],
                  total=total)
    return result


def signer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='creative-checkout-v1')


def catalog_version():
    return hashlib.sha256(json.dumps(CATALOG, sort_keys=True).encode()).hexdigest()


def checkout_token(user_id, key):
    return signer().dumps({'owner': user_id, 'key': key, 'nonce': secrets.token_hex(24), 'catalog_version': catalog_version()})


def validate_fields(form, service):
    labels = {'name':'Nama lengkap', 'whatsapp':'Nomor WhatsApp', 'event_date':'Tanggal acara',
              'location':'Lokasi acara', 'brand':'Nama bisnis / brand', 'social_account':'Akun media sosial',
              'notes':'Catatan'}
    fields = {key: (form.get(key) or '').strip() for key in labels}
    required = ['name', 'whatsapp'] + (['event_date', 'location'] if service == 'event' else
                                        ['brand', 'social_account'] if service == 'social' else ['brand'])
    for key, value in fields.items():
        if key in required and not value:
            raise ValueError(labels[key] + ' wajib diisi.')
        if len(value) > (2000 if key == 'notes' else 200) or any(ord(c) < 32 and c not in '\n\r\t' for c in value):
            raise ValueError(labels[key] + ' terlalu panjang atau mengandung karakter tidak valid.')
    phone = re.sub(r'[ +()-]', '', fields['whatsapp'])
    if not re.fullmatch(r'\d{8,15}', phone):
        raise ValueError('Masukkan nomor WhatsApp yang valid (8–15 digit).')
    if service == 'event':
        try:
            if date.fromisoformat(fields['event_date']) < date.today():
                raise ValueError()
        except ValueError:
            raise ValueError('Pilih tanggal acara hari ini atau setelahnya.') from None
    return {labels[key]: value for key, value in fields.items() if key in required or key == 'notes'}


def find_draft(user_id, nonce):
    if db.BACKEND == 'postgres':
        return db.query_one("SELECT id FROM projects WHERE created_by_user_id=? AND requirements_json->>'checkout_nonce'=?", (user_id, nonce))
    return db.query_one('SELECT id FROM projects WHERE created_by_user_id=? AND requirements_json LIKE ?',
                        (user_id, '%"checkout_nonce": "' + nonce + '"%'))


def create_order(user_id, key, form):
    try:
        token = signer().loads(form.get('order_token', ''), max_age=86400)
        if token['owner'] != user_id or token['key'] != key or not re.fullmatch('[a-f0-9]{48}', token['nonce']):
            raise ValueError()
    except (BadSignature, KeyError, TypeError, ValueError):
        raise ValueError('Sesi checkout berakhir. Muat ulang halaman, lalu coba lagi.') from None
    # Serialize on the existing owner row. Every nested insert and audit commits together.
    with db.app_purchase_transaction(None, user_id):
        previous = find_draft(user_id, token['nonce'])
        if previous:
            return payment_service.get_latest_invoice_for_project(previous['id'])['id']
        selected = offer(key, form.get('addon', 'none'))
        if selected['quotation_required']:
            raise ValueError('Paket ini memerlukan quotation tertulis sebelum invoice dapat dibuat.')
        if token.get('catalog_version') != catalog_version():
            raise ValueError('Pilihan atau harga paket berubah. Buka kembali paket untuk melihat harga terbaru.')
        customer = validate_fields(form, selected['service'])
        snapshot = dict(selected, bank=dict(BANK), customer=customer, checkout_nonce=token['nonce'], creative_order=1)
        pid = projects_repo.create_fixed_price_project(None, {
            'category': 'EVENT' if selected['service'] == 'event' else 'CONTENT',
            'catalog_key': key, 'name': selected['name'] + (' + ' + selected['addon_name'] if selected['addon'] != 'none' else ''),
            'price_amount': selected['total']}, user_id)
        db.execute('UPDATE projects SET requirements_json=? WHERE id=?', (json.dumps(snapshot, ensure_ascii=False), pid))
        return payment_service.checkout(pid, None, user_id)


def sanitize_proof(upload):
    if not upload or not upload.filename:
        raise ValueError('Pilih foto bukti transfer terlebih dahulu.')
    name = upload.filename
    extension = Path(name).suffix.lower()
    if '/' in name or '\\' in name or '..' in name or extension not in ('.png', '.jpg', '.jpeg'):
        raise ValueError('Gunakan foto PNG atau JPEG dengan nama file biasa.')
    raw = upload.stream.read(MAX_PROOF_BYTES + 1)
    if len(raw) > MAX_PROOF_BYTES:
        raise ValueError('Ukuran foto maksimal 5 MB.')
    fmt = 'PNG' if extension == '.png' else 'JPEG'
    mime = 'image/png' if fmt == 'PNG' else 'image/jpeg'
    if upload.mimetype != mime:
        raise ValueError('Jenis file tidak sesuai. Gunakan foto PNG atau JPEG asli.')
    if (fmt == 'PNG' and (not raw.startswith(b'\x89PNG\r\n\x1a\n') or not raw.endswith(b'\0\0\0\0IEND\xaeB`\x82'))) or (fmt == 'JPEG' and (not raw.startswith(b'\xff\xd8') or not raw.endswith(b'\xff\xd9'))):
        raise ValueError('File foto rusak atau berisi data tambahan.')
    if any(marker in raw.lower() for marker in (b'<script', b'<?php', b'<svg', b'<!doctype', b'<html')):
        raise ValueError('File foto berisi konten yang tidak diizinkan.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != fmt or image.width * image.height > 20_000_000 or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError()
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
                clean = image.convert('RGB')
                clean.thumbnail((4096, 4096))
                out = io.BytesIO()
                clean.save(out, format='JPEG', quality=92)
                content = out.getvalue()
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('Foto tidak dapat dibaca. Pilih PNG atau JPEG lain (maksimal 20 megapiksel).') from None
    return content


def payment_open(project, invoice):
    return project['status'] == 'PAYMENT_PENDING' and invoice['status'] == 'ISSUED'


def lock_payment(invoice_id):
    # Same row order as customer cancellation, including callers already in a transaction.
    if db.BACKEND == 'postgres':
        db.query_all('SELECT id FROM payments WHERE invoice_id=? ORDER BY id FOR UPDATE', (invoice_id,))
        db.query_one('SELECT id FROM invoices WHERE id=? FOR UPDATE', (invoice_id,))
        db.query_one('SELECT p.id FROM projects p JOIN invoices i ON i.project_id=p.id WHERE i.id=? FOR UPDATE OF p', (invoice_id,))


def submit_proof(invoice_id, user_id, upload):
    content = sanitize_proof(upload)
    with db.app_purchase_transaction(None, user_id):
        lock_payment(invoice_id)
        invoice = payment_service.get_invoice(invoice_id)
        project = projects_repo.get_project(invoice['project_id']) if invoice else None
        if not project or project['created_by_user_id'] != user_id or not project.get('requirements', {}).get('creative_order'):
            raise ValueError('Pesanan tidak tersedia.')
        if not payment_open(project, invoice):
            raise ValueError('Pesanan sudah ditutup dan tidak menerima bukti transfer.')
        payment = payment_service.get_payment_for_invoice(invoice_id)
        if payment['status'] not in ('PAYMENT_PENDING', 'REJECTED'):
            return  # repeated submit cannot create files or change review/verified state
        file_id = db.insert_returning_id(
            "INSERT INTO project_files (business_id, project_id, kind, original_filename, mime_type, size_bytes, content, uploaded_by_user_id) VALUES (NULL, ?, 'PAYMENT_PROOF', 'bukti-transfer.jpg', 'image/jpeg', ?, ?, ?)",
            (project['id'], len(content), content, user_id))
        # No OCR/provider call and no financial transition: existing admin review remains authoritative.
        payment_service.upload_payment_proof(payment['id'], None, file_id, user_id,
                                             proof_file_hash=hashlib.sha256(content).hexdigest())
