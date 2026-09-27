"""Conversational teaching backed by the existing versioned business knowledge.

The transcript is an onboarding event, not another knowledge store. Corrections replace
one canonical FAQ through the existing knowledge writer and optimistic revision check.
"""
import hashlib
import json

import ai_onboarding
import ai_usage
import db
import knowledge_setup
import repo

GUIDE_QUESTION = 'Panduan pelayanan Kilas Assist dari pemilik'
TEACH_PROMPT = '''Kamu Kilas Assist yang sedang dilatih pemilik bisnis, seperti karyawan baru.
Konfirmasikan pemahaman secara singkat dan natural dalam bahasa Indonesia. Tanyakan satu hal
yang paling penting jika masih kurang. Gunakan hanya fakta/aturan yang diajarkan pemilik.
Koreksi terbaru menggantikan aturan lama yang bertentangan, tanpa menghapus aturan lain.
Jangan mengarang harga, diskon, stok, janji, atau data customer. Jangan mengubah izin,
langganan, pembayaran atau sistem. Instruksi pemilik hanya berlaku untuk pelayanan bisnisnya.
Kembalikan JSON: {"reply":string,"knowledge":string}. knowledge adalah panduan lengkap terbaru
(maksimal 8000 karakter) dari panduan sebelumnya + ajaran terbaru, bukan reasoning/prompt rahasia.
reply mengonfirmasi perubahan yang benar-benar dipahami. Jangan mengklaim sudah siap sebelum tes.'''


def context(bid):
    business = repo.get_business(bid) or {}
    profile = repo.get_business_profile(bid) or {}
    faqs = repo.get_business_faqs(bid)
    # The owner's canonical training must survive the bounded FAQ window.
    faqs = sorted(faqs, key=lambda row: row.get('question') != GUIDE_QUESTION)[:60]
    return {
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


def test_reply(business, actor, message):
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
              json.dumps(context(bid), ensure_ascii=False)[:24000])
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
    last = _event(bid, 'assist_test')
    return bool(last and last.get('knowledge_version') == fingerprint(bid))


def ready(business, actor):
    bid = business['id']
    if not can_ready(bid):
        raise ValueError('test_required')
    # Use the existing normalization and activation authorities. No payment/channel gate is
    # granted by teaching, testing or confirming knowledge.
    from routes_client import _run_ai_normalization
    ok, _ = _run_ai_normalization(bid, business, repo.get_user_by_id(actor), preserve_status=True)
    if not ok:
        raise ValueError('training_unavailable')
    _confirm_ready(bid, actor)


@db.knowledge_writer
def _confirm_ready(business_id, actor):
    if not can_ready(business_id):
        raise ValueError('knowledge_changed')
    repo.mark_onboarding_step_done(business_id, 'simulated_done')
    repo.save_onboarding_session(business_id, 'assist_ready',
                                 {'knowledge_version': fingerprint(business_id)}, actor)
    repo.write_audit(actor, business_id, 'ASSIST_TRAINING_CONFIRMED', 'Owner confirmed tested knowledge')
