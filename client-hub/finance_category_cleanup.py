"""Read-only cleanup review contract. This module has NO deletion executor/route."""
import hashlib,json
import db
import finance_service as finance


def snapshot(business_id,actor,ids):
    finance._scope(business_id,actor)
    scope=finance._category_scope(business_id,actor)
    if scope['workspace_type']!='PERSONAL':raise finance.FinanceError('workspace_unavailable')
    if not isinstance(ids,list) or not ids or len(ids)>100 or any(type(v) is not int for v in ids) or len(ids)!=len(set(ids)):raise ValueError('cleanup_candidates_invalid')
    records=[];selected=set(ids)
    for ident in sorted(ids):
        meta=db.query_one('SELECT m.*,s.display_name FROM finance_catalog_items m JOIN finance_category_workspace_settings s ON s.business_id=m.business_id AND s.scope_key=m.scope_key AND s.category_id=m.category_id WHERE m.business_id=? AND m.scope_key=? AND m.category_id=?',(business_id,scope['scope_key'],ident))
        if not meta or meta['builtin_name']=='__customer_owned__' or meta['builtin_name']!=meta['display_name']:raise ValueError('cleanup_provenance_changed')
        parent=db.query_one('SELECT parent_category_id FROM finance_category_hierarchy WHERE business_id=? AND child_category_id=?',(business_id,ident))
        if parent:
            owner=db.query_one('SELECT m.builtin_name,s.display_name FROM finance_catalog_items m JOIN finance_category_workspace_settings s ON s.business_id=m.business_id AND s.scope_key=m.scope_key AND s.category_id=m.category_id WHERE m.business_id=? AND m.scope_key=? AND m.category_id=?',(business_id,scope['scope_key'],parent['parent_category_id']))
            if not owner or owner['builtin_name']=='__customer_owned__' or owner['builtin_name']!=owner['display_name']:raise ValueError('cleanup_custom_parent')
        refs={table:db.query_one('SELECT count(*) n FROM '+table+' WHERE category_id=?',(ident,))['n'] for table in ('finance_transactions','finance_expense_allocations','finance_budgets','finance_recurring_expenses','finance_installment_plans')}
        children=[dict(v) for v in db.query_all('SELECT * FROM finance_category_hierarchy WHERE parent_category_id=? OR child_category_id=?',(ident,ident))]
        if any(refs.values()) or any(v['child_category_id'] not in selected for v in children if v['parent_category_id']==ident):raise ValueError('cleanup_references_changed')
        settings=[dict(v) for v in db.query_all('SELECT * FROM finance_category_workspace_settings WHERE category_id=? ORDER BY business_id,scope_key',(ident,))]
        if len(settings)!=1:raise ValueError('cleanup_shared_category')
        records.append(dict(category=dict(db.query_one('SELECT * FROM finance_categories WHERE id=?',(ident,))),settings=settings,catalog=dict(meta),preferences=[dict(v) for v in db.query_all('SELECT * FROM finance_category_preferences WHERE category_id=?',(ident,))],hierarchy=children,references=refs))
    payload=dict(version=1,business_id=business_id,scope_key=scope['scope_key'],records=records)
    payload['sha256']=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
    return payload


def dry_run(business_id,actor,expected):
    # The immutable snapshot and every reference are checked again; no implicit
    # approval flag, transaction mutation, or destructive code exists here.
    actual=snapshot(business_id,actor,[v['category']['id'] for v in expected['records']])
    if actual!=expected:raise ValueError('cleanup_snapshot_changed')
    return {'matches':True,'permanent_deletion_authorized':False,'count':len(actual['records']),'sha256':actual['sha256']}
