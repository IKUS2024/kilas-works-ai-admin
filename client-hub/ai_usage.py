"""PII-free Anthropic usage accounting; no provider calls and no quota enforcement."""
import contextlib
import contextvars
import functools
import json
import logging
import math
import os
import sqlite3
from datetime import datetime, timezone

import db
from pricing_config import BRAIN_PLAN

# USD per million tokens, first-party standard inference, verified 2026-09-15:
# https://platform.claude.com/docs/en/about-claude/pricing
PRICING_DATE = os.environ.get('AI_PRICING_DATE', '2026-09-15')
MODEL_PRICING = {
    'claude-haiku-4-5-20251001': dict(input=1, output=5, read=.10, write=1.25, write_1h=2),
    'claude-sonnet-4-6': dict(input=3, output=15, read=.30, write=3.75, write_1h=6),
}
_scope = contextvars.ContextVar('ai_usage_scope', default=(None, 'platform_helper'))
log = logging.getLogger(__name__)


def number(name, default, minimum=0):
    try:
        value = float(os.environ.get(name, default))
        return value if math.isfinite(value) and value > minimum else float(default)
    except (ValueError, TypeError):
        return float(default)


def fair_use_limit():
    return int(number('KILAS_BRAIN_FAIR_USE_RESPONSES', 2000))


@contextlib.contextmanager
def scope(tenant_id, context):
    token = _scope.set((tenant_id, context))
    try:
        yield
    finally:
        _scope.reset(token)


def for_business(context):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(business, *args, **kwargs):
            with scope(business.get('id'), context):
                return fn(business, *args, **kwargs)
        return wrapped
    return decorate


def estimate(model, usage):
    """Unknown model/config/usage -> unknown; never apply a guessed family rate."""
    try:
        rates = json.loads(os.environ['AI_MODEL_PRICING_JSON']) if os.environ.get('AI_MODEL_PRICING_JSON') else MODEL_PRICING
        rate = rates.get(model)
        if not rate or usage.get('input_tokens') is None or usage.get('output_tokens') is None:
            return None
        values = [float(rate[k]) for k in ('input','output','read','write','write_1h')]
        if any(not math.isfinite(v) or v < 0 for v in values):
            return None
        created = usage.get('cache_creation_input_tokens', 0)
        hour = (usage.get('cache_creation') or {}).get('ephemeral_1h_input_tokens', 0)
        if hour > created:
            return None
        return (usage['input_tokens']*rate['input'] + usage['output_tokens']*rate['output']
                + usage.get('cache_read_input_tokens',0)*rate['read']
                + (created-hour)*rate['write'] + hour*rate['write_1h'])/1_000_000
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def _insert(values):
    # Never reuse a caller's DB transaction: accounting cannot commit or roll it back.
    if db.BACKEND == 'sqlite':
        conn = sqlite3.connect(db.SQLITE_PATH, timeout=1)
        conn.execute('PRAGMA foreign_keys=ON')
    else:
        options = dict(db._postgres_connect_kwargs())
        options['connect_timeout'] = 2
        options['options'] = '-c statement_timeout=1500 -c lock_timeout=1000'
        conn = db.psycopg2.connect(db.DATABASE_URL, **options)
    try:
        cur = conn.cursor()
        cur.execute(db._adapt_placeholders('INSERT INTO ai_usage_ledger '
            '(tenant_id,context_type,model,classification,is_reply,input_tokens,output_tokens,'
            'cache_read_input_tokens,cache_creation_input_tokens,estimated_cost_usd,estimated_cost_idr,pricing_date,created_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)'), values)
        conn.commit()
        cur.close()
    finally:
        conn.close()


def record(model, response, *, tenant_id=None, context=None, classification='normal'):
    """Count actual returned usage, even when content parsing later fails. No content stored."""
    try:
        if context is None:
            tenant_id, context = _scope.get()
        usage = (response or {}).get('usage')
        if not isinstance(usage, dict):
            return False  # Missing provider usage is not a fabricated zero-cost call.
        keys = ('input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens')
        counts = [usage.get(k, 0) for k in keys]
        if any(type(v) is not int or v < 0 for v in counts):
            return False
        if tenant_id is not None and (type(tenant_id) is not int or tenant_id <= 0):
            raise ValueError('invalid_scope')
        # Context/model come from code/config, never customer text.
        allowed = {'platform_customer','tenant_customer','owner','tenant_owner','demo','demo_fallback',
                   'normalization','simulation','writing','faq','knowledge_assist','payment_review','platform_helper'}
        if context not in allowed or classification not in ('normal','vision','complex'):
            raise ValueError('invalid_classification')
        if not isinstance(model,str) or len(model)>100 or not all(c.isalnum() or c in '-_.' for c in model):
            raise ValueError('invalid_model')
        usd = estimate(model, usage)
        fx = number('AI_COST_USD_IDR', 0)
        idr = usd*fx if usd is not None and fx>0 else None
        log.info('[AI_USAGE] %s', json.dumps(dict(context=context, tenant_id=tenant_id, model=model,
            classification=classification, **dict(zip(keys,counts)))))
        blocks = response.get('content') or []
        is_reply = context in ('tenant_customer','tenant_owner','platform_customer','owner','simulation') and isinstance(blocks,list) and any(
            isinstance(block,dict) and isinstance(block.get('text'),str) and block['text'].strip() for block in blocks)
        _insert((tenant_id,context,model,classification,bool(is_reply),*counts,usd,idr,PRICING_DATE,
                 datetime.now(timezone.utc).isoformat()))
        return True
    except Exception:
        log.warning('[AI_USAGE] persistence_failed')
        return False


# Explicit projection used by monthly(); no row values are read by the probe.
MONTHLY_COLUMNS = (
    'tenant_id', 'context_type', 'model', 'classification', 'is_reply',
    'input_tokens', 'output_tokens', 'cache_read_input_tokens',
    'cache_creation_input_tokens', 'estimated_cost_usd', 'estimated_cost_idr', 'created_at',
)


def log_dashboard_failure(exc, phase):
    """Allowlisted diagnostic text, never a scrubbed copy of a raw DB exception.

    Driver messages may contain SQL parameters, DSNs or user data anywhere, so regex
    replacement alone is insufficient. Unknown messages are intentionally redacted.
    """
    import re
    if phase == 'monthly' and getattr(exc, '_ai_usage_monthly_logged', False) is True:
        return  # The inner query/transform boundary already logged the safe cause.
    known_types = {'OperationalError', 'ProgrammingError', 'DatabaseError', 'InterfaceError',
        'UndefinedTable', 'UndefinedColumn', 'InsufficientPrivilege', 'QueryCanceled',
        'InvalidTextRepresentation', 'DatatypeMismatch', 'UndefinedFunction', 'InvalidColumnReference',
        'GroupingError', 'InvalidDatetimeFormat', 'NumericValueOutOfRange', 'InFailedSqlTransaction',
        'InternalError', 'DataError', 'Error', 'TypeError', 'ValueError',
        'KeyError', 'AttributeError', 'RuntimeError', 'ConnectionError', 'TimeoutError',
        'TemplateNotFound', 'UndefinedError', 'InvalidOperation', 'OverflowError'}
    kind = type(exc).__name__
    if kind not in known_types:
        kind = 'Exception'
    state = getattr(exc, 'pgcode', None) or getattr(exc, 'sqlstate', None)
    valid_state = isinstance(state, str) and re.fullmatch(r'[0-9A-Z]{5}', state) is not None
    postgres = valid_state or hasattr(exc, 'pgcode') or type(exc).__module__.startswith(('psycopg2', 'psycopg'))
    reason = 'details_redacted'
    if postgres:
        # Never inspect str(exc), diag, query or parameters for PostgreSQL errors.
        reason = {
            '42P01':'required_relation_missing', '42703':'required_column_missing',
            '42501':'database_permission_denied', '57014':'database_timeout',
            '28P01':'database_authentication_failed', '08001':'database_connection_unavailable',
            '08006':'database_connection_unavailable', '42883':'undefined_function_or_operator',
            '42804':'datatype_mismatch', '22P02':'invalid_text_representation',
            '22007':'invalid_datetime_format', '22003':'numeric_value_out_of_range',
            '42803':'grouping_error', '42P10':'invalid_column_reference',
            '25P02':'transaction_already_failed', 'XX000':'database_internal_error',
        }.get(state if valid_state else None, 'database_error')
    else:
        # Preserve existing non-PG allowlisted categories, never log raw text.
        try:
            raw = str(exc).lower()
        except Exception:
            raw = ''
        if 'no such table:' in raw:
            reason = 'required_relation_missing'
        elif 'no such column:' in raw:
            reason = 'required_column_missing'
            match = re.search(r'no such column:\s+["\']?([a-z_]+)', raw)
            if match and match.group(1) in MONTHLY_COLUMNS:
                reason += ':' + match.group(1)
        elif 'permission denied' in raw:
            reason = 'database_permission_denied'
        elif 'timeout' in raw or 'timed out' in raw:
            reason = 'database_timeout'
        elif 'authentication failed' in raw:
            reason = 'database_authentication_failed'
        elif 'could not connect' in raw or 'connection refused' in raw or 'unable to open database file' in raw:
            reason = 'database_connection_unavailable'
        elif 'unsupported operand type' in raw:
            reason = 'incompatible_calculation_types'
    if phase not in ('startup_schema', 'request_schema', 'monthly', 'monthly_query',
                     'monthly_transform', 'monthly_schema_types', 'businesses', 'render', 'fallback_render'):
        phase = 'dashboard'
    log.error('[AI_USAGE_DIAGNOSTIC] phase=%s exception_type=%s message=%s sqlstate=%s',
              phase, kind, reason, state if valid_state else 'unknown')
    if phase in ('monthly_query', 'monthly_transform'):
        try:
            exc._ai_usage_monthly_logged = True
        except Exception:
            pass  # Unusual immutable exception objects must still propagate unchanged.


# Only built-in PostgreSQL type names are emitted. Custom/domain/enum names are redacted.
_PG_MONTHLY_TYPES = frozenset(('bool', 'int2', 'int4', 'int8', 'numeric', 'float4', 'float8',
    'text', 'varchar', 'bpchar', 'date', 'timestamp', 'timestamptz', 'json', 'jsonb', 'bytea', 'uuid'))


def _log_postgres_monthly_types(cursor):
    """Metadata only, same search_path relation as monthly(), no business row values."""
    cursor.execute("SELECT a.attname, t.typname FROM pg_catalog.pg_attribute a "
        "LEFT JOIN pg_catalog.pg_type t ON t.oid=a.atttypid "
        "AND t.typnamespace='pg_catalog'::regnamespace "
        "WHERE a.attrelid=pg_catalog.to_regclass('ai_usage_ledger') "
        "AND a.attnum>0 AND NOT a.attisdropped AND a.attname=ANY(%s)", (list(MONTHLY_COLUMNS),))
    safe = {column:'unknown' for column in MONTHLY_COLUMNS}
    for column, typename in cursor.fetchall():
        if column in safe and typename in _PG_MONTHLY_TYPES:
            safe[column] = typename
    log.warning('[AI_USAGE_DIAGNOSTIC] phase=monthly_schema_types types=%s', json.dumps(safe, sort_keys=True))


def check_monthly_schema():
    """Read-only, zero-row probe on an independent connection; raises the real error.

    Never create a SQLite database, run migrations, or touch a caller transaction.
    PostgreSQL is explicitly read-only with bounded connect/query/lock timeouts.
    """
    if db.BACKEND == 'sqlite':
        from pathlib import Path
        conn = sqlite3.connect(Path(db.SQLITE_PATH).resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    else:
        options = dict(db._postgres_connect_kwargs())
        options['connect_timeout'] = 2
        options['options'] = '-c statement_timeout=1500 -c lock_timeout=1000'
        conn = db.psycopg2.connect(db.DATABASE_URL, **options)
    try:
        if db.BACKEND != 'sqlite':
            conn.set_session(readonly=True, autocommit=True)
        cursor = conn.cursor()
        try:
            if db.BACKEND == 'postgres':
                try:
                    _log_postgres_monthly_types(cursor)
                except Exception as exc:
                    log_dashboard_failure(exc, 'monthly_schema_types')
                    # Optional metadata logging must not change the existing probe outcome.
            cursor.execute('SELECT ' + ', '.join(MONTHLY_COLUMNS) + ' FROM ai_usage_ledger WHERE 1=0')
        finally:
            cursor.close()
    finally:
        conn.close()


def startup_schema_check():
    try:
        check_monthly_schema()
        log.info('[AI_USAGE_DIAGNOSTIC] phase=startup_schema schema=ready')
        return True
    except Exception as exc:
        log_dashboard_failure(exc, 'startup_schema')
        return False  # Dashboard diagnostics must not prevent unrelated routes from starting.


def month_bounds(now=None):
    now = now or datetime.now(timezone.utc)
    start = now.astimezone(timezone.utc).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    end = start.replace(year=start.year+1,month=1) if start.month==12 else start.replace(month=start.month+1)
    return start.isoformat(),end.isoformat()


def monthly(tenant_id=None, *, admin=False, now=None):
    """Callers enforce authentication; non-admin reads always have one explicit tenant scope."""
    if not admin and (type(tenant_id) is not int or tenant_id <= 0):
        raise ValueError('tenant_required')
    start,end = month_bounds(now)
    where = 'created_at >= ? AND created_at < ?'
    params = [start,end]
    if not admin:
        where += ' AND tenant_id = ?'
        params.append(tenant_id)
    # SQL aggregation bounds memory regardless of number of monthly calls.
    try:
        rows = db.query_all("SELECT tenant_id, COUNT(*) AS calls, "
            "SUM(CASE WHEN is_reply THEN 1 ELSE 0 END) AS replies, "
            "SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens, "
            "SUM(cache_read_input_tokens) AS cache_read_input_tokens,SUM(cache_creation_input_tokens) AS cache_creation_input_tokens, "
            "SUM(CASE WHEN cache_read_input_tokens>0 THEN 1 ELSE 0 END) AS cache_hits, "
            "SUM(CASE WHEN model LIKE 'claude-haiku-%' THEN 1 ELSE 0 END) AS haiku_calls, "
            "SUM(CASE WHEN model LIKE 'claude-sonnet-%' THEN 1 ELSE 0 END) AS sonnet_calls, "
            "SUM(estimated_cost_usd) AS cost_usd,SUM(estimated_cost_idr) AS cost_idr, "
            "SUM(CASE WHEN estimated_cost_usd IS NULL THEN 1 ELSE 0 END) AS unknown_usd, "
            "SUM(CASE WHEN estimated_cost_idr IS NULL THEN 1 ELSE 0 END) AS unknown_idr, "
            "AVG(CASE WHEN classification='normal' AND context_type IN ('tenant_customer','tenant_owner','platform_customer','owner','simulation') "
            "THEN input_tokens+cache_read_input_tokens+cache_creation_input_tokens ELSE NULL END) AS normal_input "
            "FROM ai_usage_ledger WHERE " + where + ' GROUP BY tenant_id', params)
    except Exception as exc:
        log_dashboard_failure(exc, 'monthly_query')
        raise
    try:
        if not admin and not rows:
            rows = [dict(tenant_id=tenant_id,calls=0,replies=0,cost_usd=0,cost_idr=0)]
        result=[]
        for row in rows:
            row=dict(row)
            for k in ('calls','replies','input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens','cache_hits','haiku_calls','sonnet_calls'):
                row[k]=int(row.get(k) or 0)
            if row.get('unknown_usd'): row['cost_usd']=None
            if row.get('unknown_idr'): row['cost_idr']=None
            row['cache_hit_ratio']=row['cache_hits']/row['calls'] if row['calls'] else 0
            row['cost_per_reply']=row['cost_usd']/row['replies'] if row['cost_usd'] is not None and row['replies'] else None
            row['reference_revenue_idr']=BRAIN_PLAN['harga'] if row['tenant_id'] is not None else None
            row['gross_contribution_idr']=(BRAIN_PLAN['harga']-row['cost_idr']) if row['tenant_id'] is not None and row['cost_idr'] is not None else None
            row['fair_use']=fair_use_limit()
            row['status']='HIGH' if row['replies']>=row['fair_use'] else ('WARNING' if row['replies']>=row['fair_use']*.75 else 'NORMAL')
            warnings=[]
            if row['status']!='NORMAL': warnings.append('Pemakaian respons mencapai batas pemantauan; tindak lanjut manual, tanpa penghentian otomatis.')
            if row['cost_usd'] is not None and row['cost_usd']>=number('AI_COST_WARNING_USD',10): warnings.append('Estimasi biaya AI tinggi.')
            if row['calls']>=10 and row['sonnet_calls']/row['calls']>number('AI_SONNET_WARNING_RATIO',.25): warnings.append('Proporsi Sonnet tinggi; periksa pemakaian vision/analisis.')
            if (row.get('normal_input') or 0)>number('AI_NORMAL_INPUT_WARNING_TOKENS',8000): warnings.append('Input teks normal tinggi (termasuk cache).')
            if warnings and row['status']=='NORMAL': row['status']='WARNING'
            row['warnings']=warnings
            result.append(row)
        return result
    except Exception as exc:
        log_dashboard_failure(exc, 'monthly_transform')
        raise


def client_summary(tenant_id):
    try:
        row=monthly(tenant_id)[0]
        return {k:row[k] for k in ('replies','status','fair_use')}
    except Exception:
        log.warning('[AI_USAGE] summary_unavailable')
        return None
