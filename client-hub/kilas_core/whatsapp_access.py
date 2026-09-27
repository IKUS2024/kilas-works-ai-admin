"""Server-only channel readiness. No implicit platform or other-tenant credential fallback."""
import json
import os
import re
import repo
from public_chat import security
from . import conversation, operation_access


def selected(bid):
    if os.environ.get('KILAS_WHATSAPP_CORE_ENABLED','').lower() != 'true': return False
    try:
        if os.environ.get('KILAS_ASSIST_RUNTIME_ENABLED', '').lower() == 'true':
            import assist_connections
            row = assist_connections.get(bid)
            cfg = repo.get_whatsapp_config(bid) or {}
            if row and row['state'] == 'Connected' and row['mapping_fingerprint'] == assist_connections.fingerprint(cfg):
                return dict(selected=True, assisted=True, official_access_verified=True,
                            phone_number_id=cfg.get('phone_number_id'))
        rows = json.loads(os.environ.get('KILAS_WHATSAPP_CORE_CHANNELS','{}'))
        row = rows.get(str(bid))
        return dict(row, selected=True) if isinstance(row,dict) else False
    except Exception:
        return False


def channel(bid, phone_id=None):
    gate = selected(bid)
    if not gate or gate.get('official_access_verified') is not True: return None
    business = repo.get_business(bid)
    cfg = repo.get_whatsapp_config(bid) or {}
    pid = str(cfg.get('phone_number_id') or '')
    ref = cfg.get('credentials_reference')
    if (not security.available(business) or not conversation.enabled() or not operation_access.enabled()
            or business.get('status') != 'ACTIVE' or cfg.get('connection_status') != 'CONNECTED'
            or not re.fullmatch(r'[0-9]{1,32}',pid)
            or pid != str(business.get('whatsapp_phone_number_id') or '')
            or pid != str(gate.get('phone_number_id') or '')
            or (phone_id is not None and pid != phone_id)
            or pid == os.environ.get('WHATSAPP_PHONE_NUMBER_ID')):
        return None
    if gate.get('assisted'):
        if ref not in (None, '', 'WHATSAPP_TOKEN__TENANT_'+str(bid)):
            return None
        token = os.environ.get(ref or 'WHATSAPP_ACCESS_TOKEN', '').strip()
        return dict(phone_number_id=pid, access_token=token) if token else None
    if not isinstance(ref, str) or ref != 'WHATSAPP_TOKEN__TENANT_'+str(bid):
        return None
    token = os.environ.get(ref,'').strip()
    if not token or token == os.environ.get('WHATSAPP_ACCESS_TOKEN'): return None
    if any(k.startswith('WHATSAPP_TOKEN__TENANT_') and k != ref and v.strip() == token
           for k,v in os.environ.items()): return None
    return dict(phone_number_id=pid,access_token=token)
