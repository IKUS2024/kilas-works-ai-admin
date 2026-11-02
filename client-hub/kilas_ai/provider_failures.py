"""Safe billing rejection classification; never expose provider bodies or retry."""
QUOTA_MESSAGE = 'Saldo layanan AI tidak tersedia. Coba lagi setelah pengelola memeriksa saldo.'
QUOTA_CODES = frozenset(('insufficient_quota','credit_balance_exhausted',
                         'billing_hard_limit_reached','billing_not_active'))


def quota_rejected(response):
    if getattr(response,'status_code',None) not in (400,402,403,429):return False
    try:
        error=response.json().get('error',{})
        return isinstance(error,dict) and (error.get('code') in QUOTA_CODES or error.get('type') in QUOTA_CODES)
    except (ValueError,TypeError,AttributeError):return False
