"""Conversational teaching backed by the existing versioned business knowledge.

The transcript is an onboarding event, not another knowledge store. Corrections replace
one canonical FAQ through the existing knowledge writer and optimistic revision check.
"""
import hashlib
import json
import re

import ai_onboarding
import ai_usage
import db
import knowledge_setup
import repo

GUIDE_QUESTION = 'Panduan pelayanan Kilas Assist dari pemilik'


def _language_code(value):
    """Normalize legacy/profile language labels without rewriting stored production data."""
    text = str(value or '').strip().casefold()
    if text in ('en', 'english', 'bahasa inggris', 'inggris'):
        return 'en'
    if text in ('id', 'indonesian', 'bahasa indonesia', 'indonesia', 'bahasa indo', 'indo'):
        return 'id'
    return 'id'


def _language_directive(text):
    """Extract only explicit owner-facing reply-language rules from one training message.

    This intentionally does not interpret generic words such as "kalau" as a language rule.
    The latest explicit rule wins, so a new owner correction cannot be cancelled by older
    profile defaults or an older sentence preserved inside the generated knowledge guide.
    """
    raw = str(text or '').strip().casefold()
    if not raw:
        return None
    english = bool(re.search(r'\\b(?:english|inggris|bah(?:asa|sa)\\s+inggris)\\b', raw))
    indonesian = bool(re.search(r'\\b(?:indonesian|bahasa\\s+indonesia|bahasa\\s+indo)\\b', raw))
    customer_language = bool(re.search(
        r'\\b(?:ikuti|mengikuti|sesuai)\\s+(?:bahasa\\s+)?customer\\b|'
        r'\\b(?:kalau|jika)\\s+customer.{0,45}\\b(?:english|inggris|indonesia|bahasa)\\b', raw))
    if customer_language and english:
        return {'forced_language': None, 'follow_customer': True}
    universal = bool(re.search(
        r'\\b(?:mulai\\s+sekarang|sekarang\\s+(?:kalau\\s+)?ada\\s+customer|semua\\s+customer|'
        r'semua\\s+pelanggan|setiap\\s+customer|setiap\\s+pelanggan|selalu|harus|wajib|'
        r'walaupun|meskipun|regardless)\\b', raw))
    if english and universal:
        return {'forced_language': 'en', 'follow_customer': False}
    if indonesian and universal:
        return {'forced_language': 'id', 'follow_customer': False}
    return None


def _latest_language_directive(bid):
    for row in reversed(history(bid)):
        if row.get('mode') != 'assist_teach':
            continue
        directive = _language_directive(row.get('message'))
        if directive:
            return directive
    return {'forced_language': None, 'follow_customer': False}
TEACH_PROMPT = '''Kamu Kilas Assist yang sedang dilatih pemilik bisnis, seperti karyawan baru.
Konfirmasikan pemahaman secara singkat dan natural dalam bahasa Indonesia. Tanyakan satu hal
yang paling penting jika masih kurang. Gunakan hanya fakta/aturan yang diajarkan pemilik.
Koreksi terbaru menggantikan aturan lama yang bertentangan, tanpa menghapus aturan lain.
Jangan mengarang harga, diskon, stok, janji, atau data customer. Jangan mengubah izin,
langganan, pembayaran atau sistem. Instruksi pemilik hanya berlaku untuk pelayanan bisnisnya.
Kembalikan JSON: {"reply":string,"knowledge":string}. knowledge adalah panduan lengkap terbaru
(maksimal 8000 karakter) dari panduan sebelumnya + ajaran terbaru, bukan reasoning/prompt rahasia.
Pertahankan aturan bahasa pemilik secara eksplisit dalam knowledge, termasuk apakah harus
selalu memakai satu bahasa atau mengikuti bahasa customer. reply mengonfirmasi perubahan
yang benar-benar dipahami; pengetahuan langsung berlaku setelah berhasil disimpan.'''


def context(bid):
    import assist_business_media
    business = repo.get_business(bid) or {}
    profile = repo.get_business_profile(bid) or {}
    faqs = repo.get_business_faqs(bid)
    # The owner's canonical training must survive the bounded FAQ window.
    faqs = sorted(faqs, key=lambda row: row.get('question') != GUIDE_QUESTION)[:60]
    result = {
        'business': dict(business_name=business.get('business_name'), **{
            k: profile.get(k) for k in (
                'short_description', 'category', 'operating_hours', 'closed_days',
                'country', 'timezone', 'address', 'online_or_offline', 'business_phone',
                'tone', 'primary_language', 'additional_languages', 'customer_salutation',
                'appointment_enabled', 'appointment_rules_raw', 'payment_bank_name',
                'payment_account_number', 'payment_account_name', 'payment_instructions')
        }),
        'services': [r['raw_input'][:2000] for r in repo.get_business_services(bid)[:40]],
        'faqs': [dict(question=r.get('question') or r['raw_input'][:1500],
                      answer=(r.get('answer') or '')[:8000]) for r in faqs],
    }
    media = assist_business_media.context(bid)
    if media:
        result['media'] = media
    return result


def fingerprint(bid):
    return hashlib.sha256(json.dumps(context(bid), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def history(bid):
    rows = db.query_all('SELECT step,raw_payload_json FROM onboarding_sessions WHERE business_id=? '
                        'AND step IN (?,?) ORDER BY id DESC LIMIT 40', (bid, 'assist_teach', 'assist_test'))
    return [dict(repo._coerce_json_column(r['raw_payload_json'], dict), mode=r['step'])
            for r in reversed(rows)]


def teach(business, actor, message):
    bid = business['id']
    profile = repo.get_business_profile(bid) or {}
    services, faqs = repo.get_business_services(bid), repo.get_business_faqs(bid)
    cards = knowledge_setup.editor(bid, services, faqs, profile)
    previous = next((r for r in faqs if r.get('question') == GUIDE_QUESTION), None)
    with ai_usage.scope(bid, 'knowledge_assist'):
        text, stop, error = ai_onboarding._call_claude(TEACH_PROMPT, [{'role': 'user', 'content':
            json.dumps({'business': business['business_name'],
                        'business_knowledge': context(bid),
                        'previous_knowledge': (previous or {}).get('answer') or '',
                        'owner_teaches': message}, ensure_ascii=False)}], max_tokens=3000)
    if error or stop == 'max_tokens':
        raise ValueError('training_unavailable')
    try:
        result = ai_onboarding._extract_json_object(text)
        if (set(result) != {'reply', 'knowledge'} or
                any(not isinstance(result[k], str) or not result[k].strip() for k in result) or
                len(result['knowledge']) > 8000 or len(result['reply']) > 2000):
            raise ValueError('invalid_training')
    except (TypeError, ValueError):
        raise ValueError('training_unavailable') from None
    _save_teaching(bid, actor, message, result, profile, services, faqs, cards)
    return result['reply']


@db.knowledge_writer
def _save_teaching(business_id, actor, message, result, profile, services, faqs, cards):
    # knowledge_setup checks the semantic revision again under the shared business lock.
    faq = next((r for r in cards['faqs'] if r.get('question') == GUIDE_QUESTION), None)
    for kind in ('services', 'faqs'):
        for card in cards[kind]:
            card['changed'] = False
    if faq is None:
        faq = dict(id='', question=GUIDE_QUESTION, category='pelayanan')
        cards['faqs'].append(faq)
    faq.update(answer=result['knowledge'], raw=GUIDE_QUESTION + ' | ' + result['knowledge'], changed=True)
    knowledge_setup.save(business_id, {}, cards, profile, services, faqs, cards['revision'], actor)
    repo.save_onboarding_session(business_id, 'assist_teach',
                                 dict(message=message, reply=result['reply']), actor)
    refresh_knowledge(business_id)


@db.knowledge_writer
def refresh_knowledge(business_id):
    """Materialize canonical facts automatically, without another model or channel action.

    Assist reads the source rows on every message. This derived compatibility snapshot
    keeps the existing operator provisioning gate usable after continuous teaching.
    It grants no subscription, approval, mapping or payment authority.
    """
    business = repo.get_business(business_id)
    profile = repo.get_business_profile(business_id) or {}
    services = repo.get_business_services(business_id)
    faqs = repo.get_business_faqs(business_id)
    config = dict(
        business_name=business['business_name'], category=profile.get('category'),
        description=profile.get('short_description'),
        languages=dict(primary=profile.get('primary_language') or 'id',
                       additional=profile.get('additional_languages') or []),
        tone=profile.get('tone'), owner=dict(name=profile.get('owner_name'),
            salutation_for_customers=profile.get('customer_salutation')),
        business_hours=dict(raw_summary=profile.get('operating_hours'), structured=None),
        services=[{key: row.get(key) for key in ('raw_input', 'service_name', 'description',
                  'price_from', 'price_to', 'currency', 'needs_review')} for row in services],
        faqs=[{key: row.get(key) for key in ('raw_input', 'question', 'answer', 'category', 'needs_review')}
              for row in faqs],
        policies=[row.get('answer') or row['raw_input'] for row in faqs
                  if row.get('question') == GUIDE_QUESTION],
        appointment_rules=profile.get('appointment_rules_raw'),
        payment_rules=profile.get('payment_instructions'),
        features_enabled=ai_onboarding._normalize_features_enabled(None, repo.get_tenant_features(business_id)),
        missing_fields=repo.required_fields_missing(business_id))
    repo.save_ai_normalized_config(business_id, config['description'], config, config['missing_fields'])


def language_policy(bid):
    """Current owner rules with the latest explicit training correction authoritative."""
    profile = repo.get_business_profile(bid) or {}
    guide = next((r for r in repo.get_business_faqs(bid) if r.get('question') == GUIDE_QUESTION), {})
    directive = _latest_language_directive(bid)
    return dict(default=_language_code(profile.get('primary_language')),
                additional=profile.get('additional_languages') or [],
                owner_rules=guide.get('answer') or '',
                forced_language=directive['forced_language'],
                follow_customer=directive['follow_customer'])


def test_reply(business, actor, message):
    import assist_reply
    bid = business['id']
    version = fingerprint(bid)
    recent = history(bid)
    messages = []
    for row in recent[-5:]:
        if row['mode'] == 'assist_test' and row.get('knowledge_version') == version:
            messages.extend([{'role': 'user', 'content': row['message']},
                             {'role': 'assistant', 'content': row['reply']}])
    prompt = ('Kamu Kilas Assist untuk bisnis ' + business['business_name'] +
              '. Pemilik berperan sebagai customer untuk Tes AI. Jawab natural memakai HANYA '
              'pengetahuan bisnis berikut. Jangan mengarang; minta bantuan manusia bila tidak yakin. '
              'Jangan mengklaim booking/pembayaran sudah terkonfirmasi. Ini tes tanpa tindakan nyata.\n' +
              assist_reply.LANGUAGE_INSTRUCTION + '\n' +
              json.dumps(dict(knowledge=assist_reply.relevant_knowledge(bid, message),
                              business_language_policy=language_policy(bid)), ensure_ascii=False))
    with ai_usage.scope(bid, 'simulation'):
        reply, stop, error = ai_onboarding._call_claude(prompt,
            messages + [{'role': 'user', 'content': message}], max_tokens=600)
    if error or stop == 'max_tokens' or not isinstance(reply, str) or not reply.strip():
        raise ValueError('test_unavailable')
    _save_test(bid, actor, message, reply[:4000], version)
    return reply


@db.knowledge_writer
def _save_test(business_id, actor, message, reply, version):
    if fingerprint(business_id) != version:
        raise ValueError('knowledge_changed')
    repo.save_onboarding_session(business_id, 'assist_test', dict(
        message=message, reply=reply, knowledge_version=version), actor)


def can_ready(bid):
    from assist_journey import _event
    # Readiness is an owner acknowledgement, not a test result or revision gate.
    return bool(_event(bid, 'assist_teach'))


def ready(business, actor):
    _confirm_ready(business['id'], actor)


@db.knowledge_writer
def _confirm_ready(business_id, actor):
    if not can_ready(business_id):
        raise ValueError('teaching_required')
    refresh_knowledge(business_id)
    repo.save_onboarding_session(business_id, 'assist_ready',
                                 {'knowledge_version': fingerprint(business_id)}, actor)
    repo.write_audit(actor, business_id, 'ASSIST_TRAINING_CONFIRMED', 'Owner confirmed business knowledge')
