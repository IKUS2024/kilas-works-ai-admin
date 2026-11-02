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
CHAT_ENDPOINTS = frozenset('''home usage_page capacity_state new_thread thread_page
attachment_download rename delete share revoke regenerate send home_task library
sidebar_history model_catalog workspace_capabilities select_model image_catalog
select_image_model agent_new_chat agent_rename_chat agent_delete_chat agent_home
agent_chat agent_action work_preferences work_push_register work_push_remove
work_notifications_read work_start workspace_job_events work_service_worker
workspace_stream workspace_stream_cancel workspace_stream_active
chat_project_mutate chat_project_download'''.split())


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


def states(user, conn=None):
    """Resolve independent grants with at most one account lookup."""
    text, image = _enabled(CHAT_FREE_FLAG), _enabled(IMAGE_FREE_FLAG)
    exists = (text or image) and account_exists(user, conn)
    return bool(text and exists), bool(image and exists)


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


def admits(user, endpoint):
    """An admission grant only for owned Chat routes; their own guards still apply."""
    return bool(endpoint and endpoint.startswith('kilas_ai.')
                and endpoint.removeprefix('kilas_ai.') in CHAT_ENDPOINTS
                and any(states(user)))
