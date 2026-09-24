"""Owner Home read models from existing scoped services; never a business engine."""
import repo


def setup(business):
    from routes_client import _human_missing_labels, _step_for_missing_fields
    missing = repo.required_fields_missing(business['id'])
    return dict(missing=_human_missing_labels(missing), step=_step_for_missing_fields(missing))


def finance_attention(business, actor):
    import finance_branches as branches
    import finance_service as finance
    import finance_entitlements as entitlements
    result = dict(unavailable=False, scope_name=None, branch_id=None, invoices=0, bills=0,
                  read_only=False)
    try:
        result['read_only'] = entitlements.flag('KILAS_FINANCE_EMERGENCY_DISABLE') or (
            entitlements.self_service() and not entitlements.state(business['id'])['active'])
        rows = branches.list_branches(business['id'], actor, workspace_type='BUSINESS')
        branch = next((r for r in rows if r['is_active'] and r['is_default']), None)
        if not branch:
            result['unavailable'] = True
            return result
        result.update(scope_name=branch['name'], branch_id=branch['id'])
        with branches.scope(business['id'], branch['id'], actor):
            result['invoices'] = finance.get_receivables_summary(business['id'], actor_user_id=actor)['open_invoice_count']
            today = finance.business_today(business['id']).isoformat()
            result['bills'] = len(finance.preview_due_recurring_expenses(business['id'], today, actor_user_id=actor))
    except finance.FinanceError:
        result['unavailable'] = True
    return result
