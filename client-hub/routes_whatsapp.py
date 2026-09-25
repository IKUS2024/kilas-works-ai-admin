"""Authenticated, CSRF-protected Embedded Signup. No credentials in customer responses."""
import logging
import os
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException
import security
import repo
import provisioning
import payment_service
import whatsapp_signup as signup

whatsapp_bp = Blueprint('whatsapp', __name__)
log = logging.getLogger(__name__)

def _meta_review_test_asset(business_id):
    """Return the one explicitly configured Meta test asset for the dedicated reviewer demo.

    This path is disabled by default and only available when the exact business is also covered by
    the review-only payment bypass. It never falls back to production WhatsApp ids.
    """
    if not payment_service.meta_review_payment_bypass_enabled(business_id):
        return None
    waba_id = (os.environ.get("META_REVIEW_TEST_WABA_ID") or "").strip()
    phone_id = (os.environ.get("META_REVIEW_TEST_PHONE_ID") or "").strip()
    phone = signup.normalize_phone_digits(os.environ.get("META_REVIEW_TEST_PHONE"))
    if (not waba_id.isdigit() or not phone_id.isdigit() or not phone):
        return None
    return {"waba_id": waba_id, "phone_number_id": phone_id, "display_phone": phone}


MESSAGES = {
    'configuration_missing': 'Hubungkan WhatsApp belum tersedia. Hubungi Kilas Works.',
    'approval_required': 'Setup bisnis sedang direview. Tunggu persetujuan Kilas Works.',
    'payment_verification_required': 'Pembayaran menunggu verifikasi Kilas Works.',
    'provisioning_required': 'Persiapan bisnis belum selesai. Hubungi Kilas Works.',
    'package_ineligible': 'Bisnis ini belum menggunakan Kilas Assist.',
    'invalid_state': 'Sesi koneksi sudah digunakan atau berakhir. Muat ulang halaman untuk mencoba lagi.',
    'coexistence_phone_missing': 'Nomor WhatsApp Business di HP belum terdeteksi. Pastikan proses di Meta dan konfirmasi di HP selesai.',
    'coexistence_phone_ambiguous': 'Ada lebih dari satu nomor WhatsApp Business yang cocok. Hubungi Kilas Works untuk memilih nomor yang benar.',
    'coexistence_not_ready': 'WhatsApp Business di HP belum selesai terhubung ke Cloud API. Selesaikan langkah Meta/QR di HP lalu coba lagi.',
}


@whatsapp_bp.route('/business/<int:business_id>/whatsapp/connect')
@security.login_required
def embedded_signup_start(business_id):
    user = security.current_user()
    business = security.require_business_access(business_id, user=user)
    error = None
    config = None
    state = None
    review_test_asset = _meta_review_test_asset(business_id)
    channel = repo.get_whatsapp_config(business_id) or {}
    connected = channel.get('connection_status') == 'CONNECTED'
    if not connected:
        try:
            signup.eligible(business_id, user)
            # Dedicated Meta App Review demo uses the app's existing Meta test WABA/phone.
            # Do not open Embedded Signup here: that flow itself is what requires the Advanced
            # Access currently under review. Production businesses still use the normal flow below.
            if review_test_asset is None:
                config = signup.settings()
                state = signup.new_state(business_id, user['id'])
        except signup.SignupError as exc:
            error = MESSAGES.get(str(exc), signup.PUBLIC_ERROR)
    public_config = None if not config else {
        'appId': config['META_APP_ID'], 'configId': config['META_EMBEDDED_SIGNUP_CONFIG_ID'],
        'version': config['version'], 'state': state,
        'endpoint': url_for('whatsapp.embedded_signup_complete', business_id=business_id),
    }
    channel = repo.get_whatsapp_config(business_id) or {}
    retry_activation = business['status'] == 'APPROVED' and channel.get('connection_status') == 'CONNECTED' and not channel.get('credentials_reference')
    response = render_template(
        'whatsapp_connect.html',
        business=business,
        signup_config=public_config,
        error=error,
        retry_activation=retry_activation,
        review_test_asset=review_test_asset,
        whatsapp_connected=connected,
    )
    return response, 200, {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}


@whatsapp_bp.route('/business/<int:business_id>/whatsapp/review-test-connect', methods=['POST'])
@security.login_required
def review_test_connect(business_id):
    """Connect only the dedicated Meta test WABA/phone for App Review.

    The IDs come from server-side env and the route is enabled only for the exact review demo
    business. It performs the same live Meta reachability, display-number match, duplicate guard,
    tenant-config write, and activation path as normal self-service onboarding.
    """
    user = security.current_user()
    business = security.require_business_access(business_id, user=user)
    asset = _meta_review_test_asset(business_id)
    if asset is None:
        abort(404)
    if business['status'] not in ('APPROVED', 'ACTIVE'):
        flash('Bisnis demo harus berstatus APPROVED sebelum aset test dihubungkan.', 'error')
        return redirect(url_for('whatsapp.embedded_signup_start', business_id=business_id), code=303)
    if business['status'] == 'ACTIVE':
        flash('Aset test Meta sudah aktif untuk bisnis reviewer ini.', 'success')
        return redirect(url_for('client.dashboard'), code=303)

    try:
        result = provisioning.complete_self_service_whatsapp(
            business_id,
            user,
            asset['waba_id'],
            asset['phone_number_id'],
            connection_mode='CLOUD_API',
        )
    except signup.SignupError as exc:
        log.warning('META_REVIEW_TEST_CONNECT reason=%s', str(exc))
        reason = str(exc)
        message = {
            'channel_validation_failed': (
                'Aset test Meta belum bisa divalidasi oleh credential server. '
                'Tidak ada nomor produksi yang diubah.'
            ),
            'duplicate_phone': 'Phone Number ID test sudah dipakai oleh bisnis lain.',
            'approval_required': 'Bisnis demo belum APPROVED.',
            'payment_verification_required': 'Akses reviewer belum diaktifkan.',
            'provisioning_required': 'Tenant config reviewer belum tersedia.',
        }.get(reason, signup.PUBLIC_ERROR)
        flash(message, 'error')
        return redirect(url_for('whatsapp.embedded_signup_start', business_id=business_id), code=303)

    flash(
        'Aset test Meta berhasil terhubung.'
        if result.get('status') in ('ACTIVE', 'CONNECTED')
        else 'Aset test Meta tersimpan; aktivasi masih menunggu pemeriksaan.',
        'success',
    )
    return redirect(url_for('client.dashboard'), code=303)


@whatsapp_bp.route('/business/<int:business_id>/whatsapp/complete', methods=['POST'])
@security.login_required
def embedded_signup_complete(business_id):
    user = security.current_user()
    security.require_business_access(business_id, user=user)
    if not request.is_json or not request.content_length or request.content_length > 8192:
        return jsonify(error=signup.PUBLIC_ERROR), 400
    try:
        data = request.get_json(silent=True)
        required = {'state', 'code', 'waba_id', 'phone_number_id'}
        allowed = required | {'coexistence'}
        if (not isinstance(data, dict) or not required.issubset(data) or set(data) - allowed
                or type(data.get('coexistence', False)) is not bool):
            raise signup.SignupError('invalid_payload')
        coexistence = data.get('coexistence', False)
        signup.consume_state(business_id, user['id'], data['state'])
        signup.eligible(business_id, user)
        # Local duplicate guard when Meta supplied the phone ID. Coexistence can omit it, so the
        # authoritative duplicate check is repeated after server-side discovery and again atomically
        # during provisioning.
        if (data['phone_number_id'] and
                repo.find_business_id_by_phone_number_id(data['phone_number_id'], exclude_business_id=business_id) is not None):
            raise signup.SignupError('duplicate_phone')
        waba, phone, connection_mode = signup.verify_and_prepare(
            data['code'], data['waba_id'], data['phone_number_id'], coexistence=coexistence)
        if repo.find_business_id_by_phone_number_id(phone, exclude_business_id=business_id) is not None:
            raise signup.SignupError('duplicate_phone')
        result = provisioning.complete_self_service_whatsapp(
            business_id, user, waba, phone, connection_mode=connection_mode)
        active = result['status'] == 'ACTIVE'
        if connection_mode == 'COEXISTENCE':
            message = ('Kilas Assist aktif. WhatsApp Business tetap bisa digunakan di HP.' if active else
                       'WhatsApp Business di HP sudah terhubung. Aktivasi Kilas Assist masih menunggu pemeriksaan.')
        else:
            message = ('Kilas Assist aktif.' if active else
                       'WhatsApp terhubung. Aktivasi masih menunggu pemeriksaan Kilas Works.')
        return jsonify(status='active' if active else 'connected',
                       connection_mode=connection_mode.lower(), message=message)
    except signup.SignupError as exc:
        # Only locally constructed categories, never Graph messages/payloads or identifiers.
        log.warning('WHATSAPP_SIGNUP reason=%s', str(exc))
        if str(exc) != 'invalid_state':
            try:
                repo.write_audit(user['id'], business_id, 'WHATSAPP_SIGNUP_FAILED', str(exc))
            except Exception:
                log.warning('WHATSAPP_SIGNUP reason=audit_unavailable')
        return jsonify(error=MESSAGES.get(str(exc), signup.PUBLIC_ERROR)), 400
    except HTTPException:
        raise
    except Exception:
        log.warning('WHATSAPP_SIGNUP reason=internal_failure')
        return jsonify(error=signup.PUBLIC_ERROR), 503


@whatsapp_bp.route('/whatsapp/embedded-signup/callback')
@security.login_required
def embedded_signup_callback():
    # Legacy registered URL remains safe, but never treats unverified query data as success.
    flash('Lanjutkan Hubungkan WhatsApp dari halaman bisnis. Koneksi belum dikonfirmasi.', 'error')
    return redirect(url_for('client.dashboard'))


@whatsapp_bp.route('/business/<int:business_id>/whatsapp/activate', methods=['POST'])
@security.login_required
def retry_activation(business_id):
    user = security.current_user()
    business = security.require_business_access(business_id, user=user)
    if business['status'] == 'ACTIVE':
        return redirect(url_for('client.dashboard'))
    channel = repo.get_whatsapp_config(business_id) or {}
    try:
        signup.eligible(business_id, user)
        if channel.get('connection_status') != 'CONNECTED' or channel.get('credentials_reference'):
            raise signup.SignupError('channel_validation_failed')
        result = provisioning.complete_self_service_whatsapp(business_id, user, channel['waba_id'], channel['phone_number_id'])
        flash('Kilas Assist aktif.' if result['status'] == 'ACTIVE' else
              'WhatsApp terhubung. Aktivasi masih menunggu pemeriksaan Kilas Works.', 'success' if result['status'] == 'ACTIVE' else 'error')
    except HTTPException:
        raise
    except Exception:
        log.warning('WHATSAPP_SIGNUP reason=activation_pending')
        flash('Aktivasi belum selesai. Hubungi Kilas Works untuk memeriksa kesiapan bisnis.', 'error')
    return redirect(url_for('whatsapp.embedded_signup_start', business_id=business_id))
