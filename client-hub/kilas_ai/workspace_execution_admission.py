"""Early customer-credit check; existing execution accounting remains authoritative.

The existing reservation function runs inside a transaction that ALWAYS rolls
back. No credit is granted, consumed or held here. The executor repeats its
normal atomic reservation immediately before any SDK create.
"""
import json
import logging
from . import usage

QUOTA_MESSAGES={
    'Kapasitas Premium belum cukup untuk permintaan ini. Tambah kapasitas atau lanjutkan Chat biasa.':'execution_quota_exhausted',
    'Aktifkan Kilas Pro untuk melanjutkan fitur premium. Finance tetap gratis.':'execution_entitlement_required',
    'Terlalu banyak permintaan dalam waktu singkat. Coba lagi sebentar.':'execution_rate_limit',
    'Masih ada permintaan yang diproses. Tunggu jawabannya lalu coba lagi.':'execution_concurrency_limit',
}
SAFE_CODES={
    'execution_already_dispatched','execution_capacity_limit','execution_cancelled',
    'isolated_execution_not_configured','invalid_python_entrypoint','python_tests_missing',
    'execution_entrypoint_required','reserved_export_name','unsafe_project_path',
    'protected_project_path','unsupported_project_file','project_dependency_tree',
    'archive_resource_limit','invalid_source_text','project_size','invalid_project',
    'execution_timeout','remote_execution_error','execution_boundary_unverified',
    'execution_output_limit','invalid_execution_report','unsafe_csv_output',
}


def preflight(user_id,step):
    from . import workspace_execution as execution,workspace_execution_credits as credits
    conn=usage._connect()
    try:
        credits.reserve(conn,user_id,'execution:'+step['idempotency_key'],execution.RESERVE_MICRO_USD)
    finally:
        try:conn.rollback()
        finally:conn.close()


def diagnostic(job,step,phase,error):
    # Never persist/log arbitrary exception text, provider bodies or user source.
    text=str(error)
    code=(QUOTA_MESSAGES.get(text,'execution_quota_unavailable') if isinstance(error,usage.UsageLimit)
          else text if text in SAFE_CODES else 'execution_preflight_failed' if phase=='customer_reservation' else 'execution_failed')
    value={'phase':phase,'code':code}
    logging.getLogger(__name__).warning('KILAS_PROJECT_EXECUTION_FAILURE job_id=%s step_id=%s diagnostic=%s',job['id'],step['id'],json.dumps(value,sort_keys=True))
    return value


def message(error):
    if isinstance(error,usage.UsageLimit) and str(error) in QUOTA_MESSAGES:return str(error)
    return 'Eksekusi gagal. Hasil belum terverifikasi; permintaan tidak diulang.'
