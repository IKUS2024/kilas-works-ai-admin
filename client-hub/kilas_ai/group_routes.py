"""Existing AI blueprint/auth/CSRF; polling deliberately replaces public streams."""
from flask import abort, redirect, render_template, request, session, url_for
import security
from ui_i18n import translate
from .routes import ai_bp, enabled
from . import group_chat as groups

ERRORS = {
 'not_found':'Grup tidak tersedia atau akses sudah dicabut.',
 'removed':'Akses grup Anda sudah dicabut oleh pemilik.',
 'invalid_name':'Isi nama grup, maksimal 100 karakter.',
 'invalid_message':'Isi pesan, maksimal 6.000 karakter.',
 'invalid_request':'Permintaan tidak valid.',
 'invalid_member':'Anggota tidak valid.',
 'key_conflict':'Pesan berubah. Muat ulang lalu kirim kembali.',
 'group_limit':'Batas jumlah grup tercapai.',
 'member_limit':'Grup ini sudah mencapai batas 50 anggota.',
 'ai_paused':'AI dijeda oleh pemilik grup.',
 'ai_busy':'AI sedang menjawab. Tunggu sebelum meminta lagi.',
 'too_many':'Terlalu banyak pesan. Coba lagi sebentar.',
 'owner_quota':'Kapasitas AI pemilik grup tidak cukup. Pemilik dapat memeriksa Settings.',
 'ai_failed':'AI belum berhasil menjawab. Pesan tersimpan; permintaan yang sama tidak ditagih ulang.',
 'ai_uncertain':'Status AI belum pasti. Permintaan yang sama tidak dijalankan ulang.',
 'empty_summary':'Belum ada pesan untuk diringkas.',
}


def body():
    value=request.get_json(silent=True)
    if not isinstance(value,dict): raise groups.GroupError('invalid_request')
    return value


def failure(exc):
    return {'error':translate(ERRORS.get(exc.code,ERRORS['invalid_request'])),'code':exc.code},exc.status


@ai_bp.after_app_request
def group_response(response):
    # A short-lived invitation cookie survives password/signup/OAuth session rotation.
    # Only an exact local invitation path can become the post-login destination.
    token=request.cookies.get('kilas_group_invite')
    if enabled() and request.endpoint in ('auth.login_page','auth.register_page','auth.oauth_callback') and response.status_code in (302,303) and session.get('role')=='CLIENT_OWNER' and session.get('user_id') and groups.valid_token(token):
        response.headers['Location']=url_for('kilas_ai.group_invitation',token=token)
        response.delete_cookie('kilas_group_invite',path='/')
    if (request.endpoint or '').startswith('kilas_ai.group_'):
        response.headers['Cache-Control']='no-store, private'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Robots-Tag']='noindex, nofollow'
    return response


@ai_bp.get('/groups')
def group_home():
    return render_template('kilas_ai/groups.html',groups=groups.groups(session['user_id']),selected_group=None)


@ai_bp.post('/groups')
def group_create():
    try: ident=groups.create(session['user_id'],body().get('name'))
    except groups.GroupError as exc: return failure(exc)
    return {'url':url_for('kilas_ai.group_page',ident=ident)},201


@ai_bp.get('/groups/<int:ident>')
def group_page(ident):
    try: selected=groups.state(session['user_id'],ident)
    except groups.GroupError: abort(404)
    return render_template('kilas_ai/groups.html',groups=groups.groups(session['user_id']),selected_group=selected)


@ai_bp.get('/groups/<int:ident>/messages')
def group_messages(ident):
    try:
        after=int(request.args.get('after',0));before=int(request.args.get('before',0))
        if after<0 or before<0 or (after and before): raise ValueError()
        return groups.state(session['user_id'],ident,after=after,before=before)
    except ValueError as exc:
        return failure(exc if isinstance(exc,groups.GroupError) else groups.GroupError('invalid_request'))


@ai_bp.post('/groups/<int:ident>/messages')
def group_send(ident):
    try:
        data=body()
        result=groups.send(session['user_id'],ident,data.get('content',''),data.get('operation_key'),data.get('kind','TEXT'))
        if result.get('error'): result['error']=translate(ERRORS.get(result['error'],ERRORS['ai_failed']))
        return result
    except groups.GroupError as exc: return failure(exc)


@ai_bp.post('/groups/<int:ident>/settings')
def group_settings(ident):
    try:
        data=body()
        groups.manage(session['user_id'],ident,data.get('action'),data.get('user_id'),data.get('enabled'))
        return {'ok':True}
    except groups.GroupError as exc: return failure(exc)


@ai_bp.post('/groups/<int:ident>/invitation')
def group_invite(ident):
    try:
        data=body()
        token=groups.invitation(session['user_id'],ident,revoke=data.get('revoke') is True)
        # Relative URL; the browser uses its origin, never an untrusted Host header.
        return {'url':url_for('kilas_ai.group_invitation',token=token) if token else None}
    except groups.GroupError as exc: return failure(exc)


@ai_bp.route('/group-invitation/<token>',methods=['GET','POST'])
def group_invitation(token):
    if not groups.preview(token): abort(404)
    user=security.current_user()
    if user and (user['role']!='CLIENT_OWNER' or session.get('role')!=user['role']): abort(404)
    if request.method=='POST':
        if not user: abort(401)
        try: ident=groups.join(user['id'],token)
        except groups.GroupError as exc: return render_template('kilas_ai/group_invitation.html',joined_error=translate(ERRORS[exc.code]),authenticated=True),exc.status
        response=redirect(url_for('kilas_ai.group_page',ident=ident),code=303)
        response.delete_cookie('kilas_group_invite',path='/')
        return response
    response=render_template('kilas_ai/group_invitation.html',authenticated=bool(user))
    if not user:
        from flask import make_response
        response=make_response(response)
        response.set_cookie('kilas_group_invite',token,max_age=1800,httponly=True,secure=request.is_secure,samesite='Lax',path='/')
    return response


@ai_bp.context_processor
def group_labels():
    if not (request.endpoint or "").startswith("kilas_ai.group_"): return {}
    return {"group_ui": {key:translate(key) for key in ['AI sedang menjawab…', 'Anggota', 'Cabut akses anggota ini ke seluruh riwayat grup?', 'Grup tidak tersedia atau akses sudah dicabut.', 'Hapus anggota', 'Kirim ulang pesan yang tertunda sebelum mengubah pesan.', 'Kirim ulang untuk memeriksa status tanpa menggandakan pesan.', 'Mengirim…', 'Pembaruan terputus. Mencoba kembali…', 'Pemilik', 'Permintaan gagal. Muat ulang halaman lalu coba lagi.', 'Salin tautan yang dipilih.', 'Tautan baru siap. Tautan sebelumnya tidak berlaku.', 'Tautan disalin.', 'Tautan undangan dicabut.', 'article', 'button', 'li', 'p', 'small', 'span', 'strong', 'time']}}
