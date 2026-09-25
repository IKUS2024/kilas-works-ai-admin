"""Manual owner Jobs UI. Future actions must use the same deterministic service."""
from datetime import datetime, timezone
import uuid
from werkzeug.exceptions import NotFound
from flask import Blueprint, abort, redirect, render_template, request, session, url_for
import repo
import security
import subscription_service
from kilas_core import customers, jobs
from kilas_core.flags import enabled_for_business
from kilas_core.playbook_definitions import PLAYBOOKS

jobs_bp = Blueprint('core_jobs', __name__)


def available(business):
    if (not jobs.enabled() or not customers.enabled() or not business
            or session.get('active_product') == 'finance'
            or business.get('package') not in customers.AI_PACKAGES
            or business.get('status') in ('ARCHIVED','SUSPENDED','CANCELLED')
            or not enabled_for_business(business['id'])):
        return False
    try:
        sub = subscription_service.get_subscription(business['id'])
        return bool(sub and sub['status'] in ('ACTIVE','GRACE'))
    except Exception:
        return False


def _business(bid):
    business = security.require_business_access(bid)
    if not available(business):
        abort(404)
    return business


def labels(business):
    profile = repo.get_business_profile(business['id']) or {}
    return jobs.presentation(profile.get('category'))


@jobs_bp.app_template_filter('job_time')
def job_time(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime('%d %b %Y, %H:%M UTC')


@jobs_bp.errorhandler(jobs.JobError)
@jobs_bp.errorhandler(customers.CustomerError)
def error_response(error):
    if error.status == 404:
        return NotFound().get_response()
    message = ('Data berubah atau permintaan ini sudah digunakan. Muat ulang sebelum menyimpan.'
               if error.status == 409 else 'Periksa judul, status, jumlah, dan rincian yang diisi.')
    return render_template('job_error.html', message=message, bid=request.view_args['bid']), error.status


@jobs_bp.before_app_request
def limit_body():
    # Register before the hub CSRF hook reads form data; scope strictly to this blueprint.
    if (request.endpoint or '').startswith('core_jobs.'):
        request.max_content_length = 24 * 1024


def _form(allowed):
    if request.is_json or set(request.form) - set(allowed) - {'csrf_token'}:
        raise jobs.JobError('invalid_form')
    if any(len(request.form.getlist(key)) != 1 for key in request.form):
        raise jobs.JobError('invalid_form')
    return request.form


def _fields(form):
    fields = {key: form['field_'+key] for key in jobs.FIELD_LABELS if form.get('field_'+key)}
    if 'quantity' in fields:
        try:
            fields['quantity'] = float(fields['quantity'])
        except ValueError:
            raise jobs.JobError('invalid_fields')
    return fields


def _context(business, **extra):
    job = extra.get('job')
    book = PLAYBOOKS.get(job['fields'].get('playbook')) if job else None
    field_labels = ({key: jobs.FIELD_LABELS[key] for key in book.fields}
                    if book else jobs.LEGACY_FIELD_LABELS)
    if book:
        field_labels.update({key: jobs.FIELD_LABELS[key] for key in jobs.LEGACY_FIELD_LABELS
                             if key in job['fields'] and key != 'missing_information'})
    return dict(business=business, labels=labels(business), status_labels=jobs.STATUS_LABELS,
                field_labels=field_labels, workflow=book, operation_key=uuid.uuid4().hex, **extra)


def _source(bid, customer_id, conversation_id):
    if conversation_id:
        linked = customers.customer_for_conversation(bid, conversation_id)
        if not linked or (customer_id and customer_id != linked['id']):
            abort(404)
        customer_id = linked['id']
    customer = customers.get_customer(bid, customer_id)
    return customer, conversation_id or None


@jobs_bp.get('/business/<int:bid>/jobs')
@security.login_required
def list_page(bid):
    business = _business(bid)
    q, status = request.args.get('q',''), request.args.get('status','')
    customer_id = request.args.get('customer_id')
    if customer_id:
        customers.get_customer(bid,customer_id)
    rows,total,page,pages = jobs.list_jobs(bid,search=q,status=status,customer_id=customer_id,
                                         page=request.args.get('page',1))
    return render_template('jobs.html',**_context(business,rows=rows,total=total,page=page,pages=pages,
                                                search=q,status=status,customer_id=customer_id))


@jobs_bp.get('/business/<int:bid>/jobs/new')
@security.login_required
def new_page(bid):
    business = _business(bid)
    customer, conversation_id = _source(bid,request.args.get('customer_id'),request.args.get('conversation_id'))
    return render_template('job_form.html',**_context(business,job=None,customer=customer,
                                                    conversation_id=conversation_id,fields={}))


@jobs_bp.post('/business/<int:bid>/jobs')
@security.login_required
def create(bid):
    business = _business(bid)
    form = _form(['customer_id','conversation_id','title','summary','operation_key']+
                 ['field_'+key for key in jobs.FIELD_LABELS])
    customer, conversation_id = _source(bid,form.get('customer_id'),form.get('conversation_id'))
    job = jobs.create_job(bid,customer['id'],conversation_id=conversation_id,
                          kind=labels(business)['kind'],title=form.get('title'),summary=form.get('summary',''),
                          fields=_fields(form),actor_id=security.current_user()['id'],
                          operation_key=form.get('operation_key'))
    return redirect(url_for('core_jobs.detail_page',bid=bid,job_id=job['id'],saved=1),code=303)


@jobs_bp.get('/business/<int:bid>/jobs/<job_id>')
@security.login_required
def detail_page(bid,job_id):
    business = _business(bid)
    job = jobs.get_job(bid,job_id)
    customer = customers.get_customer(bid,job['customer_id'])
    return render_template('job_form.html',**_context(business,job=job,customer=customer,
                           conversation_id=job['conversation_id'],fields=job['fields'],
                           transitions=jobs.TRANSITIONS[job['status']],saved=request.args.get('saved')=='1'))


@jobs_bp.post('/business/<int:bid>/jobs/<job_id>')
@security.login_required
def update(bid,job_id):
    _business(bid)
    jobs.get_job(bid,job_id)
    form = _form(['title','summary','status','version','operation_key']+['field_'+key for key in jobs.FIELD_LABELS])
    try:
        version = int(form.get('version',''))
    except ValueError:
        raise jobs.JobError('invalid_version')
    jobs.update_job(bid,job_id,expected_version=version,title=form.get('title'),summary=form.get('summary',''),
                    status=form.get('status'),fields=_fields(form),actor_id=security.current_user()['id'],
                    operation_key=form.get('operation_key'))
    return redirect(url_for('core_jobs.detail_page',bid=bid,job_id=job_id,saved=1),code=303)


def linked_context(business, customer_id, conversation_id=None):
    """Bounded owner-only panel; never read Jobs tables when the rollout is off."""
    if not available(business):
        return None
    rows, total, _, _ = jobs.list_jobs(business['id'],customer_id=customer_id,conversation_id=conversation_id)
    for row in rows:
        book = PLAYBOOKS.get(row['fields'].get('playbook'))
        row['workflow_label'] = book.label if book else None
        row['known_details'] = [(jobs.FIELD_LABELS[key], row['fields'][key]) for key in book.fields if key in row['fields']] if book else []
    return dict(rows=rows,total=total,labels=labels(business),customer_id=customer_id,conversation_id=conversation_id)
