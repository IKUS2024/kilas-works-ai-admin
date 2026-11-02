"""Reversible Chat-only offering, independent of audio funding and old trials.

Flags are server configuration, never request/user/plan fields. No expiry is
inferred from the date. Provider billing must be verified before activation;
these flags neither configure billing nor promise a real-time balance cutoff.
"""
import os
import db

CHAT_MODEL = 'gpt-6-luna'
IMAGE_MODEL = 'gpt-image-2.5-sunburst'
MANAGED_FLAG = 'KILAS_AI_MANAGED_MODELS_ENABLED'
CHAT_FREE_FLAG = 'KILAS_AI_CHAT_FREE_TEST_ENABLED'
IMAGE_FREE_FLAG = 'KILAS_AI_IMAGE_FREE_TEST_ENABLED'
TEXT_OPERATIONS = frozenset(('CHAT', 'WEB_SEARCH', 'PDF'))
IMAGE_OPERATIONS = frozenset(('IMAGE_GENERATION', 'IMAGE_EDIT'))


def _enabled(name):
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'on', 'yes')


def managed():
    return _enabled(MANAGED_FLAG)


def account_exists(user, conn=None):
    if type(user) is not int or user <= 0:
        return False
    if conn is not None:
        from . import usage
        return bool(usage._query(conn, 'SELECT id FROM users WHERE id=?', (user,), one=True))
    return bool(db.query_one('SELECT id FROM users WHERE id=?', (user,)))


def text_free(user, conn=None):
    return _enabled(CHAT_FREE_FLAG) and account_exists(user, conn)


def image_free(user, conn=None):
    return _enabled(IMAGE_FREE_FLAG) and account_exists(user, conn)


def sponsored(user, operations, conn=None):
    """Only Chat-related operations; no audio, VM, video or external action grant."""
    operations = tuple(operations)
    allowed = set()
    if _enabled(CHAT_FREE_FLAG):
        allowed.update(TEXT_OPERATIONS)
    if _enabled(IMAGE_FREE_FLAG):
        allowed.update(IMAGE_OPERATIONS)
    return bool(operations and all(op in allowed for op in operations)
                and account_exists(user, conn))
