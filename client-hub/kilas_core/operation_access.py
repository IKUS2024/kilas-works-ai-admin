"""Default-off operational gates, usable in a transaction without Flask/session IO."""
import os
from . import customers, jobs
from .flags import enabled_for_business
from .operation_contracts import OperationError


def enabled():
    return os.environ.get('KILAS_OPERATIONS_V2_ENABLED','').lower() == 'true'


def eligible(tx, bid):
    if (type(bid) is not int or bid<=0 or not enabled() or not jobs.enabled() or not customers.enabled()
            or os.environ.get('KILAS_WEB_CHAT_ENABLED','').lower()!='true' or not enabled_for_business(bid)):
        return False
    row = tx.one('SELECT b.package,b.status AS business_status,s.status AS subscription_status '
                 'FROM businesses b LEFT JOIN subscriptions s ON s.business_id=b.id WHERE b.id=?',(bid,))
    return bool(row and row['package'] in customers.AI_PACKAGES
                and row['business_status'] not in ('ARCHIVED','SUSPENDED','CANCELLED')
                and row['subscription_status'] in ('ACTIVE','GRACE'))


def require(tx,bid):
    if not eligible(tx,bid): raise OperationError('not_found',404)
