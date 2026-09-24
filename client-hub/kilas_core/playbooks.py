"""Pure state decisions; never resolves IDs, executes writes, or calls a model."""
from dataclasses import dataclass
from types import MappingProxyType
from .playbook_definitions import FIELD_LABELS
from .understanding import validate_fields, UnderstandingError


@dataclass(frozen=True)
class Decision:
    fields: object
    missing: tuple[str, ...]
    uncertain: tuple[str, ...]
    target_status: str | None
    write: bool
    reason: str


def missing_fields(book, fields):
    missing = [key for key in book.required if not fields.get(key)]
    for alternatives in book.alternatives:
        if not any(fields.get(key) for key in alternatives):
            missing.append('|'.join(alternatives))
    if book.code == 'SIMPLE_ORDER' and fields.get('fulfillment') == 'delivery' and not fields.get('location'):
        missing.append('location')
    return tuple(missing)


def decide(book, interpretation, *, known=None, uncertain=(), current_status=None, has_job=False):
    known = validate_fields(dict(known or {}))
    if set(known) - set(book.fields) or set(interpretation.fields) - set(book.fields) or set(uncertain) - set(book.fields):
        raise UnderstandingError('wrong_workflow_fields')
    if set(interpretation.ambiguous) - set(book.fields):
        raise UnderstandingError('wrong_workflow_fields')
    reason = interpretation.intent.lower()
    if interpretation.intent not in ('REQUEST', 'CONTINUE', 'NEW_REQUEST'):
        return Decision(MappingProxyType(known), missing_fields(book, known), tuple(uncertain), None, False, reason)
    if (has_job and interpretation.intent == 'NEW_REQUEST') or (has_job and current_status not in ('NEW', 'NEEDS_INFORMATION', 'READY_FOR_QUOTE')):
        return Decision(MappingProxyType(known), missing_fields(book, known), tuple(uncertain), None, False, 'needs_owner')
    pending = set(uncertain) | set(interpretation.ambiguous)
    merged = dict(known)
    for key, value in interpretation.fields.items():
        if key in interpretation.ambiguous:
            continue
        if key in known and known[key] != value and key not in interpretation.corrections:
            pending.add(key)  # Retain old fact until explicitly clarified; never guess.
            continue
        merged[key] = value
        if key not in known or key in interpretation.corrections:
            pending.discard(key)
    missing = missing_fields(book, merged)
    target = 'NEEDS_INFORMATION' if missing or pending else 'READY_FOR_QUOTE'
    # Phase 4 does not permit READY_FOR_QUOTE -> NEEDS_INFORMATION. Retain lifecycle,
    # expose outstanding clarification, and never auto-advance owner-controlled states.
    if current_status == 'READY_FOR_QUOTE' and target == 'NEEDS_INFORMATION':
        target = current_status
    write = bool(merged) and (not has_job or merged != known or set(uncertain) != pending or target != current_status)
    return Decision(MappingProxyType(merged), missing, tuple(sorted(pending)), target, write, 'operational')


def labels(keys):
    return ', '.join(' atau '.join(FIELD_LABELS[key] for key in group.split('|')) for group in keys)


def response(decision, *, committed=False):
    """Only a committed action can justify the word 'tercatat'. Never confirms fulfilment."""
    if decision.reason == 'unrelated':
        return 'Saya membantu kebutuhan terkait bisnis ini. Ada produk atau layanan yang ingin ditanyakan?'
    if decision.reason in ('human', 'unsupported', 'needs_owner'):
        return 'Permintaan ini perlu bantuan tim. Silakan jelaskan kebutuhan Anda; tim dapat menindaklanjuti di percakapan ini.'
    if decision.reason == 'business_question':
        return 'Untuk informasi produk, layanan, harga atau ketersediaan, mohon sebutkan kebutuhan Anda agar tim dapat mengonfirmasi.'
    if decision.uncertain:
        return 'Mohon pastikan ' + labels(decision.uncertain) + '. Sebutkan koreksinya agar rincian permintaan tidak keliru.'
    prefix = 'Rincian permintaan sudah tercatat. ' if committed else ''
    if decision.missing:
        return prefix + 'Boleh informasikan ' + labels(decision.missing) + '?'
    return prefix + 'Rincian sudah lengkap untuk ditinjau tim. Harga dan ketersediaan masih perlu konfirmasi; belum ada pesanan atau booking yang dikonfirmasi.'
