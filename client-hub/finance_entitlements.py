"""Independent Finance access. Reads never advance lifecycle or write audit records."""
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import db
import repo


def flag(name):
    return os.environ.get(name, '').lower().strip() in ('1', 'true', 'yes', 'on')


def self_service():
    return os.environ.get('KILAS_FINANCE_ACCESS_MODE', 'internal_beta') == 'self_service'


def unlimited_trial_mode():
    """Temporary testing mode: every Finance trial stays active with no expiry.
    Controlled by Render env so production billing can be restored without a code change.
    """
    return flag('KILAS_FINANCE_UNLIMITED_TRIAL')


def now():
    return datetime.now(timezone.utc)


def parse(value):
    if value is None: return None
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if value.tzinfo is None: raise ValueError('invalid_entitlement_time')
    return value.astimezone(timezone.utc)


def state(business_id):
    try:
        row = db.query_one('SELECT * FROM finance_entitlements WHERE business_id=?', (business_id,))
    except Exception:
        from finance_service import FinanceError
        raise FinanceError('finance_configuration') from None
    current = now()
    paid = parse(row['paid_until']) if row else None
    trial = parse(row['trial_until']) if row else None
    unlimited = bool(row and row['trial_started_at'] and unlimited_trial_mode())
    status = (
        'PAID_ACTIVE' if paid and current < paid
        else 'TRIAL_ACTIVE' if unlimited or (trial and current < trial)
        else ('EXPIRED' if row else 'NOT_ACTIVATED')
    )
    end = paid if status == 'PAID_ACTIVE' else (None if unlimited and status == 'TRIAL_ACTIVE' else trial if status == 'TRIAL_ACTIVE' else max([x for x in (paid,trial) if x], default=None))
    return dict(
        status=status,
        active=status in ('PAID_ACTIVE','TRIAL_ACTIVE'),
        trial_used=bool(row and row['trial_started_at']),
        unlimited_trial=bool(unlimited and status == 'TRIAL_ACTIVE'),
        until=end.isoformat() if end else None,
        until_local=end.astimezone(ZoneInfo('Asia/Jakarta')).strftime('%d/%m/%Y %H:%M WIB') if end else None
    )


def require_write(business_id, actor_user_id=None):
    import finance_service as finance
    finance._scope(business_id, actor_user_id)
    if flag('KILAS_FINANCE_EMERGENCY_DISABLE') or (self_service() and not state(business_id)['active']):
        raise finance.FinanceError('finance_read_only')
    if os.environ.get('KILAS_FINANCE_ACCESS_MODE','internal_beta') not in ('internal_beta','self_service'):
        raise finance.FinanceError('finance_configuration')


def capability(business_id, name):
    if flag('KILAS_FINANCE_EMERGENCY_DISABLE'): return False
    if self_service():
        return flag('KILAS_FINANCE_'+name+'_ENABLED') and state(business_id)['active']
    if os.environ.get('KILAS_FINANCE_ACCESS_MODE','internal_beta')!='internal_beta':return False
    import finance_ai_safety as safety
    return safety.allowlisted('KILAS_FINANCE_'+name+'_BUSINESS_IDS', business_id)


def require_ai(business_id, actor_user_id, capability_name=None):
    require_write(business_id, actor_user_id)
    if capability_name and not capability(business_id,capability_name):
        import finance_service as finance
        raise finance.FinanceError('finance_ai_unavailable')


def start_trial(business_id, actor_user_id):
    import finance_service as finance
    if not self_service() or flag('KILAS_FINANCE_EMERGENCY_DISABLE'):raise finance.FinanceError('finance_unavailable')
    with db.app_purchase_transaction(business_id,None):
        finance._scope(business_id,actor_user_id)
        row = db.query_one('SELECT * FROM finance_entitlements WHERE business_id=?',(business_id,))
        if row and (row['trial_started_at'] or row['paid_until']): return state(business_id)
        if not db.query_one("SELECT id FROM finance_accounts WHERE business_id=? AND is_active=TRUE AND currency='IDR'",(business_id,)):
            raise finance.FinanceError('account_unavailable')
        current=now()
        end=None if unlimited_trial_mode() else current+timedelta(days=7)
        if row:
            db.execute(
                'UPDATE finance_entitlements SET trial_started_at=?, trial_until=?, updated_at=? WHERE business_id=?',
                (current.isoformat(),end.isoformat() if end else None,current.isoformat(),business_id)
            )
        else:
            db.execute('INSERT INTO finance_entitlements (business_id,trial_started_at,trial_until,updated_at) VALUES (?,?,?,?)',
                       (business_id,current.isoformat(),end.isoformat() if end else None,current.isoformat()))
        repo.write_audit(actor_user_id,business_id,'FINANCE_TRIAL_STARTED','unlimited_testing' if unlimited_trial_mode() else '')
    return state(business_id)


def setup(business_id, actor_user_id, name, account_type, opening_balance_minor=0):
    """Explicit first setup only. No entitlement exemption for later account/balance edits."""
    import finance_service as finance
    if not self_service() or flag('KILAS_FINANCE_EMERGENCY_DISABLE'):raise finance.FinanceError('finance_unavailable')
    name=finance._text(name,160,True);finance._enum(account_type,('CASH','BANK','EWALLET'));finance._money(opening_balance_minor)
    with db.app_purchase_transaction(business_id,None):
        finance._scope(business_id,actor_user_id)
        accounts=[a for a in finance.list_accounts(business_id,actor_user_id=actor_user_id) if a['currency']=='IDR']
        if accounts: return accounts[0]['id']
        if db.query_one('SELECT business_id FROM finance_entitlements WHERE business_id=?',(business_id,)) and not state(business_id)['active']:
            raise finance.FinanceError('finance_read_only')
        account=finance._create_account(business_id,name,account_type,'IDR',opening_balance_minor,actor_user_id)
        for direction,names in finance.DEFAULT_CATEGORIES.items():
            for category in names:
                if not db.query_one('SELECT id FROM finance_categories WHERE business_id=? AND direction=? AND name=?',(business_id,direction,category)):
                    finance._create_category(business_id,direction,category,actor_user_id)
        return account
