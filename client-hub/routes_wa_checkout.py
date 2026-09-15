"""Order-only capability routes; never establish a normal user login."""
import io
import json
import time
from flask import Blueprint, request, session, render_template, redirect, url_for, abort, jsonify, make_response, send_file
import db
import security
import wa_checkout as flow
import catalog_service as catalog
import projects_repo
import payment_service
import quotation_service
import file_utils
import ai_payment_review

wa_checkout_bp=Blueprint('wa_checkout',__name__)

def grant():
    row=flow.by_hash(session.get('wa_order_grant',''))
    if not row: abort(410,description='Link tidak valid atau sudah kedaluwarsa. Minta bantuan tim untuk order yang sama.')
    return row

@wa_checkout_bp.after_request
def private(response):
    response.headers['Cache-Control']='no-store'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    return response

@wa_checkout_bp.route('/wa-checkout/access',methods=['POST'])
def access():
    # Existing limiter, separate namespace; no token/phone in keys or logs.
    if request.content_length and request.content_length>512:abort(413)
    key='wa-checkout-access'
    if security.is_login_rate_limited(key): abort(429)
    body=request.get_json(silent=True) or {}
    token=body.get('token')
    if not isinstance(token,str) or not 60<=len(token)<=180:
        security.record_failed_login(key)
        abort(410)
    row=flow.by_hash(flow.digest(token))
    if not row:
        security.record_failed_login(key)
        abort(410)
    security.clear_login_attempts(key)
    session['wa_order_grant']=row['token_hash']
    return jsonify(ok=True)

@wa_checkout_bp.route('/wa-checkout',methods=['GET','POST'])
def page():
    if request.method=='GET' and not flow.by_hash(session.get('wa_order_grant','')):
        expired=bool(session.pop('wa_order_grant',None))
        return render_template('wa_checkout.html',project=None), (410 if expired else 200)
    row=grant()
    error=None
    if request.method=='POST':
        if request.content_length and request.content_length>6*1024*1024: abort(413)
        try:
            with db.commerce_transaction(row['phone_hash']):
                row=grant() # expiry and binding rechecked after acquiring lock
                project=projects_repo.get_project(row['project_id'])
                item=catalog.get_catalog_item(row['catalog_key'])
                action=request.form.get('action')
                if action=='attach':
                    user=security.current_user()
                    if not user or project['created_by_user_id'] not in (None,user['id']):abort(403)
                    db.execute('UPDATE projects SET created_by_user_id=? WHERE id=?',(user['id'],project['id']))
                elif action=='brief' and project['status']=='REQUESTED':
                    if not item or not item['is_active'] or item['category'] in ('BUNDLE','AI_ADMIN'):raise ValueError('service_unavailable')
                    brief=flow.clean(request.form,item)
                    if flow.missing(item,brief):raise ValueError('missing_brief')
                    upload=request.files.get('reference_file')
                    if upload and upload.filename:
                        data=upload.read(file_utils.MAX_ATTACHMENT_UPLOAD_BYTES+1)
                        name,mime=file_utils.validate_project_attachment_upload(upload.filename,data)
                        db.insert_returning_id("INSERT INTO project_files(business_id,project_id,kind,original_filename,mime_type,size_bytes,content) VALUES(NULL,?,'REFERENCE',?,?,?,?)",(project['id'],name,mime,len(data),data))
                    db.execute('UPDATE projects SET requirements_json=? WHERE id=?',(json.dumps(brief,ensure_ascii=False),project['id']))
                    next_status='APPROVED' if project['pricing_mode']=='FIXED_PRICE' else 'WAITING_FOR_QUOTE'
                    projects_repo.set_project_status(project['id'],next_status,None,None,'WhatsApp brief submitted')
                    db.execute('UPDATE wa_checkout_sessions SET pending_field=NULL WHERE session_id=?',(row['session_id'],))
                elif action=='checkout':
                    if project['pricing_mode']!='FIXED_PRICE' and project['status'] not in ('APPROVED','PAYMENT_PENDING'):raise ValueError('quote_required')
                    payment_service.checkout(project['id'],None,None)
                elif action=='approve':
                    flow.approve_current_quote(row,int(request.form.get('quotation_id','0')))
                elif action=='proof':
                    invoice=payment_service.get_latest_invoice_for_project(project['id'])
                    if not invoice:raise ValueError('invoice_missing')
                    payment=payment_service.get_payment_for_invoice(invoice['id'])
                    if payment['status'] in ('PAYMENT_PENDING','REJECTED'):
                        upload=request.files.get('proof_file')
                        if not upload or not upload.filename:raise ValueError('proof_missing')
                        data=upload.read(file_utils.MAX_ATTACHMENT_UPLOAD_BYTES+1)
                        name,mime=file_utils.validate_project_attachment_upload(upload.filename,data)
                        file_id=db.insert_returning_id("INSERT INTO project_files(business_id,project_id,kind,original_filename,mime_type,size_bytes,content) VALUES(NULL,?,'PAYMENT_PROOF',?,?,?,?)",(project['id'],name,mime,len(data),data))
                        # Existing review/verification rules; pass bytes as regular checkout does.
                        payment_service.upload_payment_proof(payment['id'],None,file_id,None,proof_file_hash=ai_payment_review.compute_file_hash(data),image_bytes=data,image_mime=mime)
                elif action not in ('brief','proof'):raise ValueError('action_invalid')
            if action=='brief':
                try:
                    import owner_notifications
                    owner_notifications.notify_custom_project_submitted(project['id'],None,project['project_type'],project['title'])
                except Exception:pass
            if action=='proof' and invoice:
                try:
                    import owner_notifications
                    owner_notifications.notify_payment_proof_uploaded(payment['id'],invoice['id'],None,None,invoice['amount'])
                except Exception:pass
            return redirect(url_for('wa_checkout.page'))
        except (ValueError,file_utils.UploadRejected):
            error='Belum bisa diproses. Periksa isian/file atau muat ulang untuk melihat status terbaru.'
    project=projects_repo.get_project(row['project_id'])
    item=catalog.get_catalog_item(row['catalog_key'])
    invoice=payment_service.get_latest_invoice_for_project(project['id'])
    payment=payment_service.get_payment_for_invoice(invoice['id']) if invoice else None
    quote=quotation_service.get_latest_quotation_for_project(project['id'])
    return render_template('wa_checkout.html',project=project,item=item,brief=project.get('requirements') or {},
        required=flow.fields(item)[0],optional=flow.fields(item)[1],labels=flow.FIELDS,error=error,
        price=catalog.format_price(project['final_price'],item['price_unit']) if project['final_price'] is not None else 'Penawaran sesuai brief',
        description=catalog.service_description(item),invoice=invoice,payment=payment,quote=quote,bank=payment_service.BANK_DETAILS,
        user=security.current_user())

@wa_checkout_bp.route('/wa-checkout/file/<int:file_id>')
def file(file_id):
    row=grant()
    data=db.query_one('SELECT * FROM project_files WHERE id=? AND project_id=?',(file_id,row['project_id']))
    if not data:abort(404)
    return send_file(io.BytesIO(bytes(data['content'])),mimetype=data['mime_type'],as_attachment=True,download_name=data['original_filename'])
