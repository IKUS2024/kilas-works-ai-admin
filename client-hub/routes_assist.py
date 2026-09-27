"""Authenticated owner training; never a public customer chat channel."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
import assist_journey
import assist_training
import assist_business_media
import knowledge_assist
import security

assist_bp = Blueprint('assist', __name__)


@assist_bp.route('/business/<int:business_id>/train', methods=['GET', 'POST'])
@security.login_required
def training(business_id):
    user = security.current_user()
    business = security.require_business_access(business_id, user)
    if business['package'] not in ('AI_ADMIN', 'AI_ADMIN_BASIC', 'AI_ADMIN_PRO'):
        abort(404)
    journey = assist_journey.state(business)
    if not journey['onboarding_complete']:
        from routes_client import _step_for_missing_fields
        import repo
        return redirect(url_for('client.wizard_step', business_id=business_id,
                                step='basics'))
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            # Older completed onboarding may predate the automatic trial event. Resume
            # it on the first normal training action, with no extra customer-facing step.
            if not journey['demo_started'] and not journey['paid']:
                journey = assist_journey.start_demo(business_id, user['id'])
            if action == 'start_demo':
                assist_journey.start_demo(business_id, user['id'])
            else:
                if action not in ('ready', 'ready_whatsapp') and not (journey['paid'] or journey['demo_active']):
                    raise ValueError('demo_expired')
                if action not in ('ready', 'ready_whatsapp') and not knowledge_assist.allow_click(user['id'], business_id):
                    raise ValueError('too_many_requests')
                if action in ('ready', 'ready_whatsapp'):
                    assist_training.ready(business, user['id'])
                    # Old forms may still send ready_whatsapp. Confirmation never launches
                    # a channel; the separate CTA uses the authoritative launch/reuse path.
                    flash('Saya sudah memahami cara kamu ingin customer dilayani.', 'success')
                elif action == 'remove_media':
                    assist_business_media.remove(business_id, request.form.get('file_id', type=int), user['id'])
                elif action in ('teach', 'test', 'instruct_media', 'replace_media'):
                    message = (request.form.get('message') or '').strip()
                    if not 1 <= len(message) <= 4000:
                        raise ValueError('invalid_message')
                    upload = request.files.get('attachment')
                    approved = request.form.get('approved_send') == '1'
                    fid = request.form.get('file_id', type=int)
                    if action == 'instruct_media':
                        assist_business_media.instruct(business_id, fid, user['id'], message, approved)
                    elif upload and upload.filename and action in ('teach', 'replace_media'):
                        if action == 'replace_media' and not fid:
                            raise ValueError('media_not_found')
                        assist_business_media.teach(business, user['id'], message, upload, approved,
                                                   fid if action == 'replace_media' else None)
                    elif action == 'replace_media':
                        raise ValueError('invalid_training_file')
                    elif upload and upload.filename:
                        raise ValueError('teach_attachment_first')
                    else:
                        (assist_training.teach if action == 'teach' else assist_training.test_reply)(
                            business, user['id'], message)
                    if action != 'test':
                        flash(('Pengetahuan terbaru sudah aktif di WhatsApp bisnis Anda.' if journey['connected']
                               else 'Pengetahuan terbaru sudah aktif di Demo WhatsApp.' if journey['demo_bound']
                               else 'Pengetahuan terbaru sudah tersimpan.'), 'success')
                else:
                    abort(400)
        except ValueError as error:
            messages = {'teaching_required': 'Ajari Kilas dulu setidaknya sekali.',
                        'knowledge_changed': 'Ada perubahan bersamaan. Silakan kirim ajaran Anda lagi.',
                        'demo_expired': 'Demo belum aktif atau sudah berakhir. Periksa paket Anda.',
                        'too_many_requests': 'Tunggu sebentar sebelum mengirim lagi.',
                        'invalid_training_file': 'Gunakan gambar JPG/PNG atau PDF maksimal 5 MB dan 10 halaman.',
                        'media_limit': 'Maksimal 20 file. Hapus atau ganti file yang tidak diperlukan.',
                        'media_not_found': 'File tidak ditemukan di bisnis ini.',
                        'teach_attachment_first': 'Pilih Ajari Kilas untuk mengajarkan lampiran ini terlebih dahulu.',
                        'invalid_message': 'Tulis pesan antara 1 dan 4.000 karakter.'}
            flash(messages.get(str(error), 'Belum berhasil memproses. Pengetahuan Anda tetap tersimpan; coba lagi.'), 'error')
        return redirect(url_for('assist.training', business_id=business_id,
                                **({'preview': '1'} if action == 'test' else {})), code=303)
    return render_template('assist_training.html', business=business, journey=journey,
                           history=assist_training.history(business_id),
                           confirmation=assist_journey._event(business_id, 'assist_teach'),
                           taught_files=assist_business_media.files(business_id),
                           can_ready=assist_training.can_ready(business_id))


@assist_bp.route('/business/<int:business_id>/assist-whatsapp',methods=['GET','POST'])
@security.login_required
def whatsapp(business_id):
    import repo, assist_connections
    user=security.current_user()
    business=security.require_business_access(business_id,user)
    if business['package'] not in ('AI_ADMIN','AI_ADMIN_BASIC','AI_ADMIN_PRO'):abort(404)
    journey=assist_journey.state(business)
    if request.method=='POST':
        try:
            with assist_connections.binding_lock():assist_connections.enqueue(business_id,user['id'])
            flash('Permintaan koneksi Anda sudah masuk antrean Kilas.','success')
        except ValueError:
            flash('Lengkapi nomor bisnis dan pastikan pembayaran paket sudah terverifikasi.','error')
        return redirect(url_for('assist.whatsapp',business_id=business_id),code=303)
    row=assist_connections.get(business_id) or {}
    status={'Pending':'Menunggu tim Kilas','Processing':'Sedang dihubungkan',
            'Waiting OTP':'Menunggu kode verifikasi bersama operator','Error':'Tim Kilas sedang memeriksa koneksi',
            'Disconnected':'Koneksi terputus; hubungi Support','Connected':'Terhubung'}.get(row.get('state'),'Menunggu tim Kilas')
    return render_template('assist_whatsapp.html',business=business,journey=journey,
        profile=repo.get_business_profile(business_id) or {},customer_status=status)


@assist_bp.route('/business/<int:business_id>/media/<media_key>/review',methods=['GET','POST'])
@security.login_required
def media_review(business_id,media_key):
    import assist_media,repo
    user=security.current_user();business=security.require_business_access(business_id,user)
    try:row,is_demo=assist_media.owned(business_id,media_key)
    except ValueError:abort(404)
    if request.method=='POST':
        if not knowledge_assist.allow_click(user['id'],business_id):
            flash('Tunggu sebentar sebelum memeriksa lampiran lagi.','error')
        else:
            try:assist_media.analyze(business_id,media_key,user['id'])
            except ValueError:flash('Lampiran belum berhasil dibaca. Anda tetap dapat memeriksa file asli dan mengisi pembayaran secara manual.','error')
        return redirect(url_for('assist.media_review',business_id=business_id,media_key=media_key),code=303)
    candidate=assist_media.cached(business_id,media_key)
    comparisons=assist_media.comparisons(business_id,media_key,user['id'],candidate)
    return render_template('assist_media_review.html',business=business,media=row,candidate=candidate,
        comparisons=comparisons,original_url=url_for('client.demo_inbox_media' if is_demo else 'client.inbox_media',business_id=business_id,media_key=media_key))
