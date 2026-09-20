"""Authenticated, CSRF-protected Embedded Signup. No credentials in customer responses."""
import logging
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException
import security
import repo
import provisioning
import whatsapp_signup as signup

whatsapp_bp = Blueprint('whatsapp', __name__)
log = logging.getLogger(__name__)

MESSAGES = {
    'configuration_missing': 'Hubungkan WhatsApp belum tersedia. Hubungi Kilas Works.',
    'approval_required': 'Setup bisnis sedang direview. Tunggu persetujuan Kilas Works.',
    'payment_verification_required': 'Pembayaran menunggu verifikasi Kilas Works.',
    'provisioning_required': 'Persiapan bisnis belum selesai. Hubungi Kilas Works.',
    'package_ineligible': 'Bisnis ini belum menggunakan Kilas Brain.',
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
    if business['status'] != 'ACTIVE':
        try:
            signup.eligible(business_id, user)
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
    response = render_template('whatsapp_connect.html', business=business, signup_config=public_config, error=error, retry_activation=retry_activation)
    return response, 200, {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}


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
            message = ('Kilas Brain aktif. WhatsApp Business tetap bisa digunakan di HP.' if active else
                       'WhatsApp Business di HP sudah terhubung. Aktivasi Kilas Brain masih menunggu pemeriksaan.')
        else:
            message = ('Kilas Brain aktif.' if active else
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
        flash('Kilas Brain aktif.' if result['status'] == 'ACTIVE' else
              'WhatsApp terhubung. Aktivasi masih menunggu pemeriksaan Kilas Works.', 'success' if result['status'] == 'ACTIVE' else 'error')
    except HTTPException:
        raise
    except Exception:
        log.warning('WHATSAPP_SIGNUP reason=activation_pending')
        flash('Aktivasi belum selesai. Hubungi Kilas Works untuk memeriksa kesiapan bisnis.', 'error')
    return redirect(url_for('whatsapp.embedded_signup_start', business_id=business_id))
