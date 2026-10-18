"""Operator-only exact33 cleanup. Never imported or run by application startup.
Use the existing Render Shell/DB environment; no new credentials. Initialize and
snapshot do not delete. Apply requires a reviewed fresh snapshot digest and a
protected off-host backup acknowledgement. Exact pinned non-PII manifest; no retries.
"""
import argparse,hashlib,json,os
from pathlib import Path
import sys

MANIFEST_SHA='8780cc110c00fcf220da1237205257482497e0675d129d48526d14a0ce9b2255'
TABLES={'categories':'finance_categories','settings':'finance_category_workspace_settings','catalog':'finance_catalog_items','preferences':'finance_category_preferences','hierarchy':'finance_category_hierarchy'}

def manifest():
    raw=Path(__file__).with_name('finance_approved33_manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA:raise Stop('finite_manifest_checksum_mismatch')
    value=json.loads(raw)
    if len(value['targets'])!=33 or len({v['id'] for v in value['targets']})!=33:raise Stop('finite_manifest_invalid')
    return value


class Stop(Exception):pass

APPROVED=manifest()
IDS=sorted(v['id'] for v in APPROVED['targets'])
COUNTS=APPROVED['counts']
GROUPS={(v['business_id'],v['scope_key'],v['owner_id'],v['branch_id']):tuple(r['id'] for r in APPROVED['targets'] if r['business_id']==v['business_id'] and r['scope_key']==v['scope_key']) for v in APPROVED['groups']}


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def collect(cur):
 # SQL JSON conversion keeps timestamp representation identical to the read-only export.
 result={}
 for key,table in TABLES.items():
  field='id' if key=='categories' else 'category_id'
  where='parent_category_id=ANY(%s) OR child_category_id=ANY(%s)' if key=='hierarchy' else field+'=ANY(%s)'
  cur.execute('SELECT COALESCE(json_agg(q),\'[]\'::json) FROM (SELECT * FROM '+table+' WHERE '+where+' ORDER BY '+('business_id,child_category_id' if key=='hierarchy' else 'id' if key=='categories' else 'business_id,scope_key,category_id')+') q',(IDS,IDS) if key=='hierarchy' else (IDS,))
  result[key]=cur.fetchone()[0]
 return result

def protected(cur):
 out={}
 for table in ('finance_transactions','finance_accounts','finance_category_catalog_versions','audit_log'):
  cur.execute('SELECT count(*),md5(COALESCE(string_agg(row_to_json(q)::text,\'\' ORDER BY row_to_json(q)::text),\'\')) FROM '+table+' q');out[table]=cur.fetchone()
 for key,table in TABLES.items():
  field='id' if key=='categories' else 'category_id'
  where='NOT (parent_category_id=ANY(%s) OR child_category_id=ANY(%s))' if key=='hierarchy' else 'NOT ('+field+'=ANY(%s))'
  cur.execute('SELECT count(*),md5(COALESCE(string_agg(row_to_json(q)::text,\'\' ORDER BY row_to_json(q)::text),\'\')) FROM '+table+' q WHERE '+where,(IDS,IDS) if key=='hierarchy' else (IDS,));out[table+'__outside_targets']=cur.fetchone()
 return out

def validate(cur,current,*,require_v3=True):
 if set(v['id'] for v in current['categories'])!=set(IDS):raise Stop('target_set_changed')
 if {k:len(v) for k,v in current.items()}!=COUNTS:raise Stop('related_metadata_counts_changed')
 # A new initialization can change active flags, but any name/identity/parent
 # change requires explicit reconciliation rather than silently changing the plan.
 approved={v['id']:v for v in APPROVED['targets']}
 for row in current['categories']:
  item=approved[row['id']]
  if row['business_id']!=item['business_id'] or row['direction']!='EXPENSE' or row['name']!=item['storage_name']:raise Stop('reviewed_storage_identity_changed')
 for row in current['catalog']:
  item=approved[row['category_id']]
  if any(row[k]!=item[k] for k in ('business_id','scope_key','canonical_key','builtin_name')):raise Stop('reviewed_catalog_identity_changed')
 for row in current['settings']:
  item=approved[row['category_id']]
  if row['workspace_type']!='PERSONAL' or row['display_name']!=item['builtin_name'] or any(row[k]!=item[k] for k in ('business_id','scope_key','owner_user_id')):raise Stop('reviewed_scope_or_name_changed')
 for row in current['preferences']:
  item=approved[row['category_id']]
  if (row['business_id'],row['scope_key'])!=(item['business_id'],item['scope_key']):raise Stop('preference_scope_changed')
 for row in current['hierarchy']:
  if row['business_id']!=approved[row['child_category_id']]['business_id']:raise Stop('hierarchy_scope_changed')
 actual_parents={r['child_category_id']:r['parent_category_id'] for r in current['hierarchy']}
 if actual_parents!={r['id']:r['parent_category_id'] for r in APPROVED['targets'] if r['parent_category_id'] is not None}:raise Stop('reviewed_hierarchy_changed')
 for (bid,scope,owner,branch),ids in GROUPS.items():
  cur.execute("SELECT count(*) FROM finance_branch_workspaces WHERE business_id=%s AND branch_id=%s AND owner_user_id=%s AND workspace_type='PERSONAL'",(bid,branch,owner))
  if cur.fetchone()[0]!=1:raise Stop('personal_owner_association_changed')
  actual={r['category_id'] for r in current['settings'] if (r['business_id'],r['scope_key'],r['owner_user_id'])==(bid,scope,owner)}
  if actual!=set(ids):raise Stop('scope_target_set_changed')
  cur.execute('SELECT count(*) FROM finance_category_catalog_versions WHERE business_id=%s AND scope_key=%s AND version=3',(bid,scope))
  if cur.fetchone()[0]!=1 and require_v3:raise Stop('final_v3_initialization_required')
 for row in APPROVED['targets']:
  if row['parent_category_id'] is not None:
   cur.execute('SELECT m.builtin_name,s.display_name FROM finance_catalog_items m JOIN finance_category_workspace_settings s ON s.business_id=m.business_id AND s.scope_key=m.scope_key AND s.category_id=m.category_id WHERE m.business_id=%s AND m.scope_key=%s AND m.category_id=%s',(row['business_id'],row['scope_key'],row['parent_category_id']))
   parent=cur.fetchone()
   if not parent or parent[0]=='__customer_owned__' or parent[0]!=parent[1]:raise Stop('parent_is_custom_or_changed')
 for table in ('finance_transactions','finance_expense_allocations','finance_budgets','finance_recurring_expenses','finance_installment_plans'):
  cur.execute('SELECT count(*) FROM '+table+' WHERE category_id=ANY(%s)',(IDS,))
  if cur.fetchone()[0]:raise Stop('new_financial_reference')
 cur.execute('SELECT count(*) FROM finance_category_hierarchy WHERE parent_category_id=ANY(%s) AND NOT child_category_id=ANY(%s)',(IDS,IDS))
 if cur.fetchone()[0]:raise Stop('outside_child_found')
 cur.execute('SELECT category_id FROM finance_category_workspace_settings WHERE category_id=ANY(%s) GROUP BY category_id HAVING count(*)<>1',(IDS,))
 if cur.fetchone():raise Stop('shared_scope_found')

def write_backup(path,payload):
 path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
 if path.parent.stat().st_mode&0o077:raise Stop('backup_directory_not_private')
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as file:
  json.dump(payload,file,ensure_ascii=False,sort_keys=True,indent=2);file.write('\n');file.flush();os.fsync(file.fileno())


def connect():
    import psycopg2
    try:return psycopg2.connect(os.environ['DATABASE_URL'],connect_timeout=10)
    except Exception:raise Stop('database_connection_unavailable') from None


def lock(cur):
    cur.execute("SET LOCAL lock_timeout='5s'");cur.execute("SET LOCAL statement_timeout='30s'")
    # Stabilize the FK graph and block new category writes/DDL during this short
    # operator transaction. Existing financial inserts are guarded by target-row
    # FK/key-share locks, including inserts attempted after the zero-ref check.
    cur.execute('LOCK TABLE finance_categories IN SHARE ROW EXCLUSIVE MODE')
    cur.execute("SELECT c.conrelid::regclass::text,ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(num,ord) JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.num ORDER BY k.ord),c.confdeltype,c.convalidated FROM pg_constraint c WHERE c.contype='f' AND c.confrelid='finance_categories'::regclass")
    expected={(table,('category_id',)) for table in ('finance_budgets','finance_catalog_items','finance_category_preferences','finance_category_workspace_settings','finance_expense_allocations','finance_installment_plans','finance_recurring_expenses')}
    expected.update({('finance_category_hierarchy',('child_category_id',)),('finance_category_hierarchy',('parent_category_id',)),('finance_transactions',('business_id','category_id','direction'))})
    constraints=cur.fetchall()
    if len(constraints)!=len(expected) or {(r[0],tuple(r[1])) for r in constraints}!=expected or any(r[2] not in ('a','r') or not r[3] for r in constraints):raise Stop('category_reference_schema_changed')
    cur.execute('SELECT id FROM businesses WHERE id=ANY(%s) ORDER BY id FOR UPDATE',([2,10],))
    if [r[0] for r in cur.fetchall()]!=[2,10]:raise Stop('business_set_changed')
    cur.execute('SELECT id FROM users WHERE id=ANY(%s) ORDER BY id FOR UPDATE',([2,9],))
    if [r[0] for r in cur.fetchall()]!=[2,9]:raise Stop('owner_set_changed')
    cur.execute('SELECT id FROM finance_categories WHERE id=ANY(%s) ORDER BY id FOR UPDATE',(IDS,))
    found=[r[0] for r in cur.fetchall()]
    if not found:raise Stop('all_targets_already_absent_no_replay')
    if found!=IDS:raise Stop('partial_target_set_abort')
    parents=sorted({v['parent_category_id'] for v in APPROVED['targets'] if v['parent_category_id'] is not None})
    cur.execute('SELECT id FROM finance_categories WHERE id=ANY(%s) ORDER BY id FOR UPDATE',(parents,));cur.fetchall()
    for key in ('settings','catalog','preferences','hierarchy'):
        field='category_id' if key!='hierarchy' else 'child_category_id'
        cur.execute('SELECT '+field+' FROM '+TABLES[key]+' WHERE '+field+'=ANY(%s) ORDER BY '+field+' FOR UPDATE',(IDS,));cur.fetchall()
    for key in ('settings','catalog'):
        cur.execute('SELECT category_id FROM '+TABLES[key]+' WHERE category_id=ANY(%s) ORDER BY category_id FOR UPDATE',(parents,));cur.fetchall()


def snapshot_only(path):
    conn=connect()
    try:
        with conn.cursor() as cur:
            lock(cur);current=collect(cur);before=protected(cur)
            write_backup(path,{'snapshot':current,'protected_fingerprints':before,'approved_ids':IDS})
            validate(cur,current)
        conn.rollback()
        return {'mode':'snapshot','deleted':0,'snapshot_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    finally:conn.rollback();conn.close()


def initialize(path):
    # Separate normal catalog operation; NEVER deletes or posts money/accounts.
    # Existing source now goes directly to v3, preserving all approved identities.
    conn=connect()
    try:
        with conn.cursor() as cur:
            lock(cur);current=collect(cur);validate(cur,current,require_v3=False)
            before=protected(cur)
            write_backup(path,{'snapshot':current,'protected_fingerprints':before,'approved_ids':IDS})
        conn.rollback()
    finally:conn.close()
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import finance_service as finance,finance_branches as branches,finance_category_catalog as catalog
    for (bid,scope,owner,branch) in GROUPS:
        with branches.scope(bid,branch,owner),finance._write(bid,owner):catalog.sync_personal(bid,owner)
    conn=connect()
    try:
        with conn.cursor() as cur:
            lock(cur);validate(cur,collect(cur));after=protected(cur)
            if any(after[t]!=before[t] for t in ('finance_transactions','finance_accounts')):raise Stop('financial_state_changed_during_initialization')
        conn.rollback()
    finally:conn.close()
    return {'mode':'initialize','deleted':0,'v3_initialized':True,'before_snapshot_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def apply(path,reviewed,expected_sha,durable_ack):
    if not durable_ack:raise Stop('protected_off_host_backup_ack_required')
    raw=reviewed.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha:raise Stop('reviewed_snapshot_checksum_mismatch')
    expected=json.loads(raw)
    conn=connect()
    try:
        with conn.cursor() as cur:
            lock(cur);current=collect(cur);validate(cur,current);before=protected(cur)
            if expected['snapshot']!=current or expected['approved_ids']!=IDS:raise Stop('post_v3_snapshot_changed')
            write_backup(path,{'snapshot':current,'protected_fingerprints':before,'approved_ids':IDS})
            deleted={}
            for key in ('preferences','catalog','settings','hierarchy'):
                where='parent_category_id=ANY(%s) OR child_category_id=ANY(%s)' if key=='hierarchy' else 'category_id=ANY(%s)'
                cur.execute('DELETE FROM '+TABLES[key]+' WHERE '+where,(IDS,IDS) if key=='hierarchy' else (IDS,));deleted[key]=cur.rowcount
                if cur.rowcount!=COUNTS[key]:raise Stop('unexpected_delete_count')
            cur.execute('DELETE FROM finance_categories WHERE id=ANY(%s) AND id<>18544',(IDS,))
            if cur.rowcount!=32:raise Stop('unexpected_category_delete_count')
            cur.execute('DELETE FROM finance_categories WHERE id=18544 AND business_id=2')
            if cur.rowcount!=1:raise Stop('unexpected_parent_delete_count')
            deleted['categories']=33
            if any(collect(cur).values()) or protected(cur)!=before:raise Stop('post_delete_integrity_failed')
        try:conn.commit()
        except Exception:raise Stop('commit_outcome_unknown_no_retry') from None
        return {'committed':True,'deleted':deleted,'by_owner':{'2':29,'9':4},'execution_backup_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    except Exception:
        try:conn.rollback()
        except Exception:pass  # Preserve unknown-commit classification on a broken connection.
        raise
    finally:conn.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('initialize','snapshot','apply'))
    parser.add_argument('--backup-output',type=Path,required=True)
    parser.add_argument('--reviewed-snapshot',type=Path)
    parser.add_argument('--reviewed-snapshot-sha256')
    parser.add_argument('--protected-off-host-backup-confirmed',action='store_true')
    args=parser.parse_args()
    try:
        if args.mode=='initialize':result=initialize(args.backup_output)
        elif args.mode=='snapshot':result=snapshot_only(args.backup_output)
        else:
            if not args.reviewed_snapshot or not args.reviewed_snapshot_sha256:raise Stop('reviewed_post_v3_snapshot_required')
            result=apply(args.backup_output,args.reviewed_snapshot,args.reviewed_snapshot_sha256,args.protected_off_host_backup_confirmed)
        print(json.dumps(result));return 0
    except Exception as error:
        unknown=isinstance(error,Stop) and str(error)=='commit_outcome_unknown_no_retry'
        print(json.dumps({'committed':None if unknown else False,'deleted':None if unknown else 0,'reason':str(error) if isinstance(error,Stop) else 'unexpected_error_rolled_back'}));return 2

if __name__=='__main__':raise SystemExit(main())
