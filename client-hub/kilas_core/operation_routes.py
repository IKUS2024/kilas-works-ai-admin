"""Owner-only Attention and small automation settings; no cron or public mutation API."""
from flask import Blueprint, abort, redirect, render_template, request, session, url_for, flash
import security
from werkzeug.exceptions import NotFound
from . import attention, automations, jobs, operation_access
from .operation_contracts import OperationError

operations_bp=Blueprint('core_operations',__name__)


def business_for_owner(bid):
    business=security.require_business_access(bid)
    if session.get('active_product')=='finance': abort(404)
    with jobs.transaction() as tx: operation_access.require(tx,bid)
    return business


@operations_bp.before_app_request
def limit_body():
    if (request.endpoint or '').startswith('core_operations.'):
        request.max_content_length=4096


@operations_bp.errorhandler(OperationError)
@operations_bp.errorhandler(jobs.JobError)
def error_response(error):
    if error.status==404: return NotFound().get_response()
    return render_template('job_error.html',bid=request.view_args['bid'],
        message='Periksa pengaturan atau muat ulang halaman sebelum menyimpan.'),error.status


def form(allowed):
    if request.is_json or set(request.form)-set(allowed)-{'csrf_token'} or any(len(request.form.getlist(k))!=1 for k in request.form):
        raise OperationError('invalid_form')
    return request.form


def summary(business):
    if not operation_access.enabled() or session.get('active_product')=='finance': return None
    try:
        business_for_owner(business['id'])
        return attention.listing(business['id'],limit=3)
    except OperationError:
        return None


@operations_bp.get('/business/<int:bid>/attention')
@security.login_required
def list_page(bid):
    business=business_for_owner(bid)
    data=attention.listing(bid,page=request.args.get('page',1),status=request.args.get('status','OPEN'))
    return render_template('attention.html',business=business,attention_data=data)


@operations_bp.post('/business/<int:bid>/attention/<aid>/resolve')
@security.login_required
def resolve(bid,aid):
    business_for_owner(bid);form([])
    attention.resolve(bid,aid,security.current_user()['id'])
    return redirect(url_for('core_operations.list_page',bid=bid),code=303)


@operations_bp.route('/business/<int:bid>/automations',methods=['GET','POST'])
@security.login_required
def settings(bid):
    business=business_for_owner(bid)
    if request.method=='POST':
        data=form(['followup_enabled','review_enabled','delay_hours','max_attempts','version'])
        try:
            if data.get('followup_enabled','false') not in ('true','false') or data.get('review_enabled','false') not in ('true','false'):
                raise ValueError()
            payload=dict(followup_enabled=data.get('followup_enabled')=='true',review_enabled=data.get('review_enabled')=='true',
                         delay_hours=int(data.get('delay_hours','')),max_attempts=int(data.get('max_attempts','')))
            version=int(data.get('version',''))
        except ValueError: raise OperationError('invalid_config')
        automations.set_config(bid,payload,actor_id=security.current_user()['id'],expected_version=version)
        return redirect(url_for('core_operations.settings',bid=bid,saved=1),code=303)
    return render_template('automations.html',business=business,config=automations.get_config(bid),saved=request.args.get('saved')=='1')


@operations_bp.post('/business/<int:bid>/automations/run')
@security.login_required
def run(bid):
    business_for_owner(bid)
    data=form(['conversation_after','job_after'])
    result=automations.run(bid,conversation_after=data.get('conversation_after',''),job_after=data.get('job_after',''))
    flash('Pemeriksaan selesai. Pesan hanya tersimpan pada percakapan WEB yang memenuhi syarat.','success')
    # Cursors are server-produced and available for another bounded owner-triggered page.
    return render_template('automations.html',business=security.require_business_access(bid),config=automations.get_config(bid),
                           saved=False,next_conversation=result['next_conversation'],next_job=result['next_job'])
