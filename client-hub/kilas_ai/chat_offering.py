"""Reversible Chat-only offering, independent of audio funding and old trials.

Flags are server configuration, never request/user/plan fields. No expiry is
inferred from the date. Provider billing must be verified before activation;
these flags neither configure billing nor promise a real-time balance cutoff.
"""
import os
import json
from dataclasses import dataclass
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


def sponsored(user, operations, conn=None, *, origin=None):
    """Only Chat-related operations; no audio, VM, video or external action grant."""
    operations = tuple(operations)
    allowed = set()
    if _enabled(CHAT_FREE_FLAG):
        allowed.update(TEXT_OPERATIONS)
    if _enabled(IMAGE_FREE_FLAG):
        allowed.update(IMAGE_OPERATIONS)
    if not isinstance(origin, _InteractiveOrigin) or origin.user_id != user:
        return False
    granted=(TEXT_OPERATIONS if origin.text_grant else frozenset()) | (IMAGE_OPERATIONS if origin.image_grant else frozenset())
    # A persisted grant belongs to the already accepted interactive operation.
    # Workers need no global free flag, and rollback never charges that customer.
    if origin.job_id is not None:allowed=granted
    return bool(operations and all(op in allowed and op in granted for op in operations)
                and account_exists(user, conn))


def admits(user, endpoint):
    """An admission grant only for owned Chat routes; their own guards still apply."""
    return bool(endpoint and endpoint.startswith('kilas_ai.')
                and endpoint.removeprefix('kilas_ai.') in CHAT_ENDPOINTS
                and any(states(user)))


@dataclass(frozen=True)
class _InteractiveOrigin:
    """Trusted server value, never constructed from a request JSON grant."""
    user_id: int
    surface: str
    surface_id: int
    request_key: str
    text_grant: bool
    image_grant: bool
    job_id: int | None = None

    @property
    def label(self):
        return ('interactive-job:'+str(self.job_id) if self.job_id else
                'interactive-'+self.surface+':'+str(self.surface_id)+':'+self.request_key)


def for_request(user, surface, ident, key):
    """Explicit Chat handler origin; work/start, Automation and cron cannot infer it."""
    from flask import has_request_context, request, session
    if not has_request_context() or request.endpoint not in ('kilas_ai.send','kilas_ai.regenerate','kilas_ai.agent_chat') or session.get('user_id') != user:
        return None
    text,image=states(user)
    if not (text or image):return None
    from . import chat_models
    chat_models.owned(user,surface,ident)
    if not isinstance(key,str) or not 1<=len(key)<=180:return None
    return _InteractiveOrigin(user,surface,ident,key,text,image)


def register_job(conn, job_id, origin):
    """Persist grant only at trusted, immediate Chat-artifact creation."""
    if not isinstance(origin,_InteractiveOrigin) or origin.job_id is not None:return
    from . import usage
    row=usage._query(conn,'SELECT mode,schedule_json,origin_conversation_id,checkpoint_json FROM kilas_agent_jobs WHERE id=? AND user_id=?',
                     (job_id,origin.user_id),one=True)
    if not row or row[0]!='ONE_SHOT' or json.loads(row[1] or '{}'):return
    if origin.surface=='conversation' and row[2]!=origin.surface_id:return
    if origin.surface=='thread' and json.loads(row[3] or '{}').get('origin_thread_id')!=origin.surface_id:return
    usage._query(conn,'INSERT INTO kilas_ai_interactive_job_origins(job_id,user_id,surface,surface_id,request_key,text_grant,image_grant) VALUES (?,?,?,?,?,?,?) ON CONFLICT(job_id) DO NOTHING',
                 (job_id,origin.user_id,origin.surface,origin.surface_id,origin.request_key,int(origin.text_grant),int(origin.image_grant)))


def for_job(job, worker):
    """Read persisted provenance; origin conversation alone never grants funding."""
    if worker not in ('DOCUMENT','PROJECT','IMAGE','AI_TEXT','WEB'):return None
    if job.get('mode')!='ONE_SHOT':return None
    row=db.query_one('SELECT o.*,j.mode,j.schedule_json FROM kilas_ai_interactive_job_origins o JOIN kilas_agent_jobs j ON j.id=o.job_id AND j.user_id=o.user_id WHERE o.job_id=? AND o.user_id=?',
                     (job['id'],job['user_id']))
    if not row or row['mode']!='ONE_SHOT' or json.loads(row['schedule_json'] or '{}'):return None
    return _InteractiveOrigin(row['user_id'],row['surface'],row['surface_id'],row['request_key'],bool(row['text_grant']),bool(row['image_grant']),row['job_id'])
