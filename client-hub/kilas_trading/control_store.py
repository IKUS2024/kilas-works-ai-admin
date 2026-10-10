"""Explicit control coordination migration; never installed by request/startup."""
import hashlib
from pathlib import Path
import db
from .store import query

NAME = 'kilas_trading_control_v2'
RELEASES = ('kilas_trading_control_v1',NAME)
from .bridge_store import transaction

TABLES = {
    RELEASES[0]: {
        'kilas_trading_control_credentials': 'user_id session_id credential_hash scope symbol server created_at expires_at revoked',
        'kilas_trading_controls': 'user_id revision command_id desired_state instrument lot issued_at expires_at worker_session_id worker_sequence worker_challenge_hash worker_challenge_expires ack_json ack_received_at',
        'kilas_trading_control_receipts': 'user_id command_id revision payload_hash intent_json',
    },
    NAME: {
        'kilas_trading_control_credentials_v2': 'user_id session_id credential_hash scope symbol server max_run_seconds created_at expires_at revoked',
        'kilas_trading_controls_v2': 'user_id revision command_id desired_state instrument lot issued_at command_expires_at run_seconds run_expires_at run_started_at worker_lease_expires_at run_status end_reason worker_session_id worker_sequence worker_challenge_hash worker_challenge_expires ack_json ack_received_at',
        'kilas_trading_control_receipts_v2': 'user_id command_id revision payload_hash intent_json',
    },
}
PREREQUISITES = {'users', 'oauth_identities', 'kilas_trading_accounts',
                 'kilas_trading_events', 'kilas_trading_bridges',
                 'kilas_trading_releases', 'kilas_trading_bridge_releases'}

def tables(conn):
    if db.BACKEND=='postgres':
        return {row['table_name'] for row in query(conn,"SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE'")}
    return {row['name'] for row in query(conn,"SELECT name FROM sqlite_master WHERE type='table'")}

def check_columns(conn,name):
    if not set(TABLES[name])<=tables(conn):raise RuntimeError('control_schema_shape_mismatch')
    for table,expected in TABLES[name].items():
        if db.BACKEND=='postgres':
            columns={row['column_name'] for row in query(conn,'SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?',(table,))}
        else:
            # All identifiers come from the fixed TABLES mapping, never input.
            columns={row['name'] for row in query(conn,f'PRAGMA table_info({table})')}
        if columns!=set(expected.split()):raise RuntimeError('control_schema_shape_mismatch')

def apply_release():
    """Explicit offline/reviewed release only; retain immutable v1 checksums."""
    suffix='postgres' if db.BACKEND=='postgres' else 'sqlite'
    applied=[]
    with transaction() as conn:
        existing=tables(conn)
        if not PREREQUISITES<=existing:raise RuntimeError('control_schema_prerequisite_missing')
        from . import schema, bridge_store
        if not query(conn,'SELECT 1 AS present FROM kilas_trading_releases WHERE name=?',(schema.NAME,),one=True) or not query(conn,'SELECT 1 AS present FROM kilas_trading_bridge_releases WHERE name=?',(bridge_store.NAME,),one=True):
            raise RuntimeError('control_schema_prerequisite_missing')
        pending=[]
        for name in RELEASES:
            script=(Path(__file__).resolve().parents[1]/'migrations'/f'{name}_{suffix}.sql').read_text()
            digest=hashlib.sha256(script.encode()).hexdigest()
            row=query(conn,'SELECT checksum FROM kilas_trading_bridge_releases WHERE name=?',(name,),one=True)
            if row and row['checksum']!=digest:raise RuntimeError('control_schema_checksum_mismatch')
            if row:check_columns(conn,name)
            elif existing.intersection(TABLES[name]):raise RuntimeError('control_schema_untracked_tables')
            else:pending.append((name,script,digest))
        for name,script,digest in pending:
            for statement in script.split(';'):
                if statement.strip():query(conn,statement)
            check_columns(conn,name)
            query(conn,'INSERT INTO kilas_trading_bridge_releases VALUES (?,?)',(name,digest));applied.append(name)
    return applied

if __name__ == '__main__':
    import os
    if os.environ.get('KILAS_TRADING_CONTROL_SCHEMA_APPLY') != 'true':
        raise SystemExit('Explicit control schema release flag required.')
    print(apply_release())
