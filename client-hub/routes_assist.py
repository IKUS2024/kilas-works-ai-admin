"""Authenticated owner training; never a public customer chat channel."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
import assist_journey
import assist_training
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
                                step=_step_for_missing_fields(repo.required_fields_missing(business_id))))
    if request.method == 'POST':
        action = request.form.get('action')
        try:
            if action == 'start_demo':
                assist_journey.start_demo(business_id, user['id'])
            else:
                if not (journey['paid'] or journey['demo_active']):
                    raise ValueError('demo_expired')
                if not knowledge_assist.allow_click(user['id'], business_id):
                    raise ValueError('too_many_requests')
                if action == 'ready':
                    assist_training.ready(business, user['id'])
                    flash('Saya sudah memahami cara Anda ingin customer dilayani. Jika tidak yakin, saya akan meminta bantuan Anda.', 'success')
                elif action in ('teach', 'test'):
                    message = (request.form.get('message') or '').strip()
                    if not 1 <= len(message) <= 4000:
                        raise ValueError('invalid_message')
                    (assist_training.teach if action == 'teach' else assist_training.test_reply)(
                        business, user['id'], message)
                else:
                    abort(400)
        except ValueError as error:
            messages = {'test_required': 'Tes AI terlebih dahulu sebelum menyatakan siap.',
                        'knowledge_changed': 'Pengetahuan baru saja berubah. Silakan tes ulang.',
                        'demo_expired': 'Demo belum aktif atau sudah berakhir. Periksa paket Anda.',
                        'too_many_requests': 'Tunggu sebentar sebelum mengirim lagi.',
                        'invalid_message': 'Tulis pesan antara 1 dan 4.000 karakter.'}
            flash(messages.get(str(error), 'Belum berhasil memproses. Pengetahuan Anda tetap tersimpan; coba lagi.'), 'error')
        return redirect(url_for('assist.training', business_id=business_id), code=303)
    return render_template('assist_training.html', business=business, journey=journey,
                           history=assist_training.history(business_id),
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
