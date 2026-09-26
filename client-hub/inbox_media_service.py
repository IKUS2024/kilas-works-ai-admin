"""Scoped Inbox media metadata and bounded server-side transport. No binary DB storage."""
import io
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests
from werkzeug.utils import secure_filename
from flask import send_file, Response
import db

TYPES = {
    'image': {'image/jpeg', 'image/png'},
    'video': {'video/mp4', 'video/3gpp'},
    'audio': {'audio/aac', 'audio/mp4', 'audio/mpeg', 'audio/amr', 'audio/ogg'},
    'sticker': {'image/webp'},
    'document': {'application/pdf', 'text/plain', 'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'},
}
MAX_BYTES = 32 * 1024 * 1024
def _graph_base_url():
    version = (os.environ.get('META_GRAPH_API_VERSION') or 'v21.0').strip()
    return 'https://graph.facebook.com/' + version



def scope(business_id):
    return 'platform' if business_id is None else 'tenant:' + str(int(business_id))


def get(media_key, business_id):
    return db.query_one('SELECT * FROM inbox_media WHERE id = ? AND scope_key = ?',
                        (media_key, scope(business_id)))


def record(business_id, phone, event, role='user'):
    kind = event.get('type')
    if kind not in TYPES:
        return None
    if not re.fullmatch(r'[0-9]{6,20}', str(phone)):
        raise ValueError('invalid_scope')
    meta = event.get(kind) or {}
    media_id = str(meta.get('id') or '')
    event_id = str(event.get('id') or '')
    if not event_id or len(event_id) > 512:
        raise ValueError('invalid_event')
    # Invalid IDs remain visible as unavailable; they can never become a URL/path.
    if not re.fullmatch(r'[0-9]{1,128}', media_id):
        media_id = ''
    mime = str(meta.get('mime_type') or '').split(';')[0].strip().lower()[:128]
    filename = secure_filename(str(meta.get('filename') or ''))[:150] or 'media'
    caption = str(meta.get('caption') or '')[:4096]
    try:
        stamp = datetime.fromtimestamp(int(event.get('timestamp')), timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError, OSError):
        stamp = datetime.now(timezone.utc).replace(tzinfo=None)
    number = phone if business_id is None else f'T{int(business_id)}:{phone}'
    conn = db.get_connection()
    cur = conn.cursor()
    try:
        media_key = uuid.uuid4().hex
        cur.execute(db._adapt_placeholders('INSERT INTO inbox_media '
            '(id, scope_key, event_id, media_id, message_type, mime_type, filename, caption, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (scope_key, event_id) DO NOTHING RETURNING id'),
            (media_key, scope(business_id), event_id, media_id, kind, mime, filename, caption, stamp))
        inserted = cur.fetchone()
        if inserted:
            cur.execute(db._adapt_placeholders("INSERT INTO messages (number, mode, role, content, created_at) "
                "VALUES (?, 'customer', ?, ?, ?) RETURNING id"),
                (number, role, caption or f'[{kind}]', stamp))
            message_row_id = cur.fetchone()[0]
            cur.execute(db._adapt_placeholders('UPDATE inbox_media SET message_row_id = ? WHERE id = ?'),
                        (message_row_id, media_key))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    return db.query_one('SELECT * FROM inbox_media WHERE scope_key = ? AND event_id = ?',
                        (scope(business_id), event_id))


def attach(rows, business_id):
    if not rows:
        return rows
    ids = [r['id'] for r in rows]
    try:
        media = db.query_all('SELECT * FROM inbox_media WHERE scope_key = ? AND message_row_id IN ('
            + ','.join('?' for _ in ids) + ')', (scope(business_id), *ids))
    except Exception:
        # Existing text history remains usable during a staggered migration/deploy.
        return rows
    by_id = {m['message_row_id']: m for m in media}
    for row in rows:
        if row['id'] in by_id:
            row['media'] = by_id[row['id']]
    return rows



def attach_events(rows, business_id):
    """Attach shared media metadata to Core Inbox rows by verified WhatsApp event id."""
    if not rows:
        return rows
    event_ids = [str(row.get('event_id') or '') for row in rows if row.get('event_id')]
    if not event_ids:
        return rows
    try:
        media = db.query_all(
            'SELECT * FROM inbox_media WHERE scope_key = ? AND event_id IN ('
            + ','.join('?' for _ in event_ids) + ')',
            (scope(business_id), *event_ids))
    except Exception:
        return rows
    by_event = {str(item['event_id']): item for item in media}
    for row in rows:
        item = by_event.get(str(row.get('event_id') or ''))
        if item:
            row['media'] = item
    return rows

def _read(response):
    if response.status_code != 200:
        raise ValueError('media_unavailable')
    size = response.headers.get('Content-Length')
    if size and int(size) > MAX_BYTES:
        raise ValueError('media_too_large')
    stream = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
    total = 0
    try:
        for chunk in response.iter_content(65536):
            total += len(chunk)
            if total > MAX_BYTES:
                raise ValueError('media_too_large')
            stream.write(chunk)
        if not total:
            raise ValueError('empty_media')
        stream.seek(0)
        return stream
    except Exception:
        stream.close()
        raise


def download(row, token, phone_id):
    """Fetch a fresh Meta URL each time; never accept a browser-provided URL or redirect."""
    if not token or not re.fullmatch(r'[0-9]{1,128}', row['media_id'] or ''):
        raise ValueError('media_unavailable')
    headers = {'Authorization': 'Bearer ' + token}
    with requests.get(_graph_base_url() + '/' + row['media_id'], headers=headers,
                      params={'phone_number_id': phone_id}, timeout=(5, 15), allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError('media_unavailable')
        metadata = response.json()
    mime = str(metadata.get('mime_type') or '').split(';')[0].strip().lower()
    if mime not in TYPES.get(row['message_type'], set()):
        raise ValueError('unsupported_media')
    url = metadata.get('url') or ''
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not (host == 'lookaside.fbsbx.com' or host.endswith('.fbcdn.net'))):
        raise ValueError('unsafe_media_location')
    with requests.get(url, headers=headers, timeout=(5, 20), stream=True, allow_redirects=False) as response:
        stream = _read(response)
    return stream, mime


def serve(row, fetch):
    try:
        stream, mime = fetch()
        response = send_file(stream, mimetype=mime, download_name=row['filename'],
                             as_attachment=row['message_type'] == 'document', max_age=0)
        response.call_on_close(stream.close)
    except Exception:
        # Neither exceptions nor upstream bodies may disclose URLs, tokens or recipient data.
        print('[INBOX_MEDIA] reason=media_unavailable')
        response = Response('Media tidak tersedia', status=404, content_type='text/plain; charset=utf-8')
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


def platform_download(row):
    import os
    import platform_inbox_service as platform
    endpoint = platform._bot_platform_reply_url()
    secret = os.environ.get('INTERNAL_SERVICE_SECRET', '').strip()
    if not endpoint or not secret:
        raise ValueError('bridge_unavailable')
    parsed = urlsplit(endpoint)
    endpoint = f'{parsed.scheme}://{parsed.netloc}/internal/platform-inbox-media/{row["id"]}'
    with requests.get(endpoint, headers={'X-Internal-Service-Secret': secret},
                      timeout=(5, 45), stream=True, allow_redirects=False) as response:
        mime = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
        if mime not in TYPES.get(row['message_type'], set()):
            raise ValueError('unsupported_media')
        return _read(response), mime


def validate_upload(upload):
    if not upload:
        raise ValueError('file_required')
    data = upload.stream.read(10 * 1024 * 1024 + 1)
    if not data or len(data) > 10 * 1024 * 1024:
        raise ValueError('file_too_large')
    if data.startswith(b'%PDF-'):
        kind, mime, extension = 'document', 'application/pdf', '.pdf'
    else:
        from PIL import Image
        try:
            picture = Image.open(io.BytesIO(data))
            if picture.format not in ('JPEG', 'PNG') or picture.width * picture.height > 25_000_000:
                raise ValueError('unsupported_file')
            picture.verify()
            mime = 'image/jpeg' if picture.format == 'JPEG' else 'image/png'
        except Exception:
            raise ValueError('unsupported_file') from None
        if len(data) > 5 * 1024 * 1024:
            raise ValueError('file_too_large')
        kind, extension = 'image', '.jpg' if mime == 'image/jpeg' else '.png'
    filename = secure_filename(upload.filename or 'media')[:140] or 'media'
    filename = filename.rsplit('.', 1)[0] + extension
    return data, kind, mime, filename


def send_upload_detail(business_id, phone, upload, caption, channel, allowed):
    """Send one human-owned image/PDF and return bounded metadata for Core Inbox mirroring.

    The historic send_upload() wrapper below keeps its two-value contract. Core Inbox uses this
    detailed variant only so the accepted provider id can be mirrored into kw_web_messages without
    guessing the newest media row or duplicating the transport.
    """
    if not allowed():
        return False, 'human_mode_and_open_window_required', None
    try:
        data, kind, mime, filename = validate_upload(upload)
        token, phone_id = channel['access_token'], channel['phone_number_id']
        graph = _graph_base_url()
        headers = {'Authorization': 'Bearer ' + token}
        with requests.post(graph + '/' + phone_id + '/media', headers=headers,
                           data={'messaging_product': 'whatsapp', 'type': mime},
                           files={'file': (filename, data, mime)}, timeout=(5, 45), allow_redirects=False) as response:
            if response.status_code not in (200, 201):
                return False, 'media_upload_failed', None
            media_id = str(response.json().get('id') or '')
        if not re.fullmatch(r'[0-9]{1,128}', media_id):
            return False, 'media_upload_failed', None
        if not allowed():
            return False, 'human_mode_and_open_window_required', None
        meta = {'id': media_id}
        caption = str(caption or '')[:1024]
        if caption:
            meta['caption'] = caption
        if kind == 'document':
            meta['filename'] = filename
        with requests.post(graph + '/' + phone_id + '/messages', headers=headers,
                           json={'messaging_product': 'whatsapp', 'to': phone, 'type': kind, kind: meta},
                           timeout=(5, 30), allow_redirects=False) as response:
            body = response.json()
            messages = body.get('messages') if isinstance(body, dict) else None
            if response.status_code != 200 or not messages or not messages[0].get('id'):
                return False, 'media_send_failed', None
        provider_id = str(messages[0]['id'])
        detail = {
            'provider_id': provider_id,
            'kind': kind,
            'mime_type': mime,
            'filename': filename,
            'caption': caption,
        }
        try:
            record(business_id, phone, {'type': kind, 'id': provider_id,
                   'timestamp': int(datetime.now(timezone.utc).timestamp()),
                   kind: {**meta, 'mime_type': mime, 'filename': filename}}, role='assistant')
        except Exception:
            return True, 'accepted_history_unavailable', detail
        return True, 'accepted', detail
    except ValueError:
        return False, 'unsupported_or_oversize_file', None
    except Exception:
        return False, 'media_send_unconfirmed', None


def send_upload(business_id, phone, upload, caption, channel, allowed):
    ok, reason, _detail = send_upload_detail(
        business_id, phone, upload, caption, channel, allowed)
    return ok, reason

def human_window_allowed(business_id, phone):
    if not re.fullmatch(r'[0-9]{6,20}', str(phone or '')):
        return False
    if business_id is None:
        import platform_inbox_service as inbox
        return (inbox.customer_exists(phone) and inbox.get_state(phone) == 'HUMAN_TAKEOVER'
                and inbox.freeform_window_status(phone)['allowed'])
    import inbox_service as inbox
    import wa_takeover_service
    return (inbox.customer_exists(business_id, phone)
            and wa_takeover_service.get_state(business_id, phone) == 'HUMAN_TAKEOVER'
            and inbox.freeform_window_status(business_id, phone)['allowed'])


def platform_send(phone, upload, caption):
    import os
    import platform_inbox_service as platform
    try:
        if not human_window_allowed(None, phone):
            return False, 'human_mode_and_open_window_required'
        data, kind, mime, filename = validate_upload(upload)
        endpoint = platform._bot_platform_reply_url()
        secret = os.environ.get('INTERNAL_SERVICE_SECRET', '').strip()
        if not endpoint or not secret:
            return False, 'bridge_unavailable'
        parsed = urlsplit(endpoint)
        endpoint = f'{parsed.scheme}://{parsed.netloc}/internal/platform-inbox-media'
        with requests.post(endpoint, headers={'X-Internal-Service-Secret': secret},
                           data={'customer_phone': phone, 'caption': str(caption or '')[:1024]},
                           files={'file': (filename, data, mime)}, timeout=(5, 90), allow_redirects=False) as response:
            body = response.json()
            if response.status_code == 200 and body.get('status') == 'ok':
                return True, 'accepted_history_unavailable' if body.get('reason') == 'accepted_history_unavailable' else 'accepted'
        return False, 'media_send_unconfirmed'
    except Exception:
        return False, 'media_send_unconfirmed'


def upload_flash(ok, reason):
    if ok:
        return ('Media diterima WhatsApp untuk dikirim.' +
                (' Riwayat belum tersimpan; jangan kirim ulang.' if reason == 'accepted_history_unavailable' else ''), 'success')
    if reason == 'human_mode_and_open_window_required':
        return 'Ambil Alih dan pastikan masa chat masih aktif sebelum mengirim media.', 'error'
    if reason == 'unsupported_or_oversize_file':
        return 'Gunakan JPG/PNG maksimal 5 MB atau PDF maksimal 10 MB.', 'error'
    return 'Pengiriman media belum terkonfirmasi. Periksa percakapan sebelum mencoba lagi.', 'error'
