"""Safe billing rejection classification; never expose provider bodies or retry."""
QUOTA_MESSAGE = 'Saldo layanan AI tidak tersedia. Coba lagi setelah pengelola memeriksa saldo.'
IMAGE_REJECTION_MESSAGE = 'Penyedia gambar menolak permintaan ini berdasarkan kebijakan kontennya. Coba permintaan lain yang sesuai kebijakan.'
IMAGE_REJECTION_CODE = 'image_provider_content_rejected'
IMAGE_REJECTION_CODES = frozenset(('content_policy_violation', 'moderation_blocked'))
QUOTA_CODES = frozenset(('insufficient_quota','credit_balance_exhausted',
                         'billing_hard_limit_reached','billing_not_active'))


def quota_rejected(response):
    if getattr(response,'status_code',None) not in (400,402,403,429):return False
    try:
        error=response.json().get('error',{})
        return isinstance(error,dict) and (error.get('code') in QUOTA_CODES or error.get('type') in QUOTA_CODES)
    except (ValueError,TypeError,AttributeError):return False


def image_content_rejected(response):
    """Only explicit provider moderation codes, never an HTTP-400 inference."""
    status = getattr(response, 'status_code', None)
    if type(status) is not int or not 400 <= status <= 599:
        return False
    try:
        error = response.json().get('error', {})
        return isinstance(error, dict) and any(
            isinstance(error.get(field), str) and error[field] in IMAGE_REJECTION_CODES
            for field in ('code', 'type'))
    except (ValueError, TypeError, AttributeError):
        return False
