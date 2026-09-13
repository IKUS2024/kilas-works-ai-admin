"""Knowledge Setup phase 1: explicit owner input only; no model calls or normalization."""
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
import db
import repo
import provisioning

SECTION_FIELDS = {
    'business': ('short_description', 'category', 'address', 'business_phone', 'operating_hours', 'closed_days'),
    'communication': ('tone', 'primary_language', 'customer_salutation'),
    'services': ('name', 'description', 'pricing', 'inclusions', 'duration', 'notes'),
    'faqs': ('question', 'answer', 'category'),
}
PROFILE_FIELDS = SECTION_FIELDS['business'] + SECTION_FIELDS['communication']


def latest(business_id):
    return db.query_one('SELECT * FROM business_knowledge_revisions WHERE business_id = ? ORDER BY id DESC LIMIT 1', (business_id,))


PROFILE_KNOWLEDGE = (
    'category', 'short_description', 'country', 'timezone', 'address', 'business_phone',
    'owner_name', 'primary_language', 'additional_languages', 'tone', 'customer_salutation',
    'operating_hours', 'closed_days', 'online_or_offline', 'appointment_rules_raw',
    'appointment_enabled', 'payment_bank_name', 'payment_account_number',
    'payment_account_name', 'payment_instructions',
)
SERVICE_KNOWLEDGE = ('raw_input', 'service_name', 'description', 'price_from', 'price_to', 'currency', 'notes', 'needs_review')
FAQ_KNOWLEDGE = ('raw_input', 'question', 'answer', 'category', 'needs_review')
JSON_FIELDS = {'additional_languages', 'additional', 'language', 'operating_hours', 'raw',
               'business_hours_raw', 'missing_fields', 'qualification_questions'}
BOOL_FIELDS = {'needs_review', 'appointment_enabled'}
CONFIG_KNOWLEDGE = {
    'business_name': None, 'business_type': None,
    'ai': {'language': {'primary': None, 'additional': None}, 'tone': None,
           'system_instructions': None, 'business_description': None, 'customer_salutation': None},
    'business_info': {'address': None, 'business_hours': {'raw': None, 'closed_days': None},
                      'contact_info': {'business_phone': None, 'owner_name': None}},
    'knowledge': {'services': {k: None for k in SERVICE_KNOWLEDGE},
                  'products': {k: None for k in (*SERVICE_KNOWLEDGE, 'name', 'price')},
                  'faq': {k: None for k in FAQ_KNOWLEDGE}, 'pricing_notes': None},
    'appointment_behavior': {'appointment_rules': None, 'business_hours_raw': None, 'closed_days': None},
    'payment_config': {'bank_name': None, 'account_number': None, 'account_name': None, 'instructions': None},
    'lead_behavior': {'qualification_questions': None, 'handoff_rules': None},
}


def canonical_value(value, key=''):
    if isinstance(value, (bytes, bytearray)):
        value = value.decode('utf-8')
    if key in JSON_FIELDS and isinstance(value, str):
        # Hours also legitimately contain plain owner-written text.
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
    if key in BOOL_FIELDS:
        return None if value is None else value not in (False, 0, '0', 'false', 'off', '')
    if isinstance(value, dict):
        return {k: canonical_value(v, k) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical_value(v) for v in value]
    return value


def project(value, fields):
    if isinstance(value, (str, bytes, bytearray)):
        value = repo._coerce_json_column(value, (dict, list))
    if isinstance(value, list):
        return [project(item, fields) for item in value]
    value = value or {}
    if not isinstance(value, dict):
        raise ValueError('Konfigurasi bisnis tidak valid.')
    return {key: project(value.get(key), child) if child is not None else canonical_value(value.get(key), key)
            for key, child in fields.items()}


def revision_token(business_id, revision_id, profile, services, faqs, select=db.query_all):
    """Semantic knowledge only; revision_id is retained as a compatible call argument.

    Explicit projections exclude timestamps, physical IDs and runtime/credential config.
    The transaction caller supplies cursor reads that never release its business lock.
    """
    business = select('SELECT business_name FROM businesses WHERE id = ?', (business_id,))
    normalized = select('SELECT normalized_config_json FROM ai_settings WHERE business_id = ?', (business_id,))
    configs = select('SELECT config_json FROM tenant_configs WHERE business_id = ?', (business_id,))
    files = select('SELECT extracted_text FROM business_files WHERE business_id = ? ORDER BY id', (business_id,))
    config = repo._coerce_json_column(configs[0]['config_json'], (dict, list)) if configs else {}
    if not isinstance(config, dict):
        raise ValueError('Konfigurasi bisnis tidak valid.')
    state = {
        'business_id': business_id,
        'business_name': business[0]['business_name'] if business else None,
        'normalized': project(normalized[0]['normalized_config_json'] if normalized else {},
                              {'description': None, 'missing_fields': None}),
        'profile': project(profile, dict.fromkeys(PROFILE_KNOWLEDGE)),
        'services': [project(row, dict.fromkeys(SERVICE_KNOWLEDGE)) for row in sorted(services, key=lambda r: (r.get('sort_order') or 0, r['id']))],
        'faqs': [project(row, dict.fromkeys(FAQ_KNOWLEDGE)) for row in sorted(faqs, key=lambda r: r['id'])],
        'config': project(config, CONFIG_KNOWLEDGE),
        'files': [canonical_value(row['extracted_text']) for row in files],
    }
    payload = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return 'k1:' + hashlib.sha256(payload.encode('utf-8')).hexdigest()


def editor(business_id, services, faqs, profile=None):
    revision = latest(business_id)
    stored = json.loads(revision['editor_json']) if revision else {}
    result = {'revision': revision_token(business_id, revision['id'] if revision else 0,
        profile if profile is not None else (repo.get_business_profile(business_id) or {}), services, faqs)}
    for kind, rows in [('services', services), ('faqs', faqs)]:
        saved = {str(r['id']): r for r in stored.get(kind, [])}
        cards = []
        for row in rows:
            old = saved.get(str(row['id']))
            if old and old.get('raw') == row['raw_input']:
                card = dict(old)
            elif kind == 'services':
                card = dict(id=str(row['id']), name=row.get('service_name') or '',
                    description=row.get('description') or '', pricing='', inclusions='', duration='', notes='')
                if row.get('price_from') is not None:
                    card['pricing'] = f"{row.get('currency') or ''} {row['price_from']}".strip()
                    if row.get('price_to') is not None:
                        card['pricing'] += f" – {row['price_to']}"
            else:
                question, separator, answer = (row['raw_input'] or '').partition('|')
                card = dict(id=str(row['id']), question=row.get('question') or (question.strip() if separator else ''),
                    answer=row.get('answer') or (answer.strip() if separator else ''), category=row.get('category') or '')
            card['id'] = str(row['id'])
            card['raw'] = row['raw_input'] or ''
            cards.append(card)
        result[kind] = cards
    return result


def parse_rows(form, kind, current):
    keys = SECTION_FIELDS[kind]
    ids = form.getlist(kind + '_id')
    if len(ids) > 50:
        raise ValueError('Maksimal 50 layanan atau FAQ.')
    columns = {key: form.getlist(kind + '_' + key) for key in keys}
    if any(len(values) != len(ids) for values in columns.values()):
        raise ValueError('Form belum lengkap. Muat ulang halaman dan coba lagi.')
    known = {row['id']: row for row in current}
    seen, output = set(), []
    for index, row_id in enumerate(ids):
        if row_id and (row_id not in known or row_id in seen):
            raise ValueError('Daftar telah berubah. Muat ulang halaman sebelum menyimpan.')
        seen.add(row_id)
        values = {key: columns[key][index].strip() for key in keys}
        if any(len(value) > 4000 for value in values.values()):
            raise ValueError('Informasi terlalu panjang. Ringkas setiap isian.')
        if not row_id and not any(values.values()):
            continue
        old = known.get(row_id)
        unchanged = old and all(values[key] == old.get(key, '') for key in keys)
        if unchanged:
            raw = old['raw']
        elif kind == 'services':
            if not values['name']:
                raise ValueError('Isi nama produk atau layanan yang ingin diperbarui.')
            parts = [values['name']]
            for key, label in [('description','Deskripsi'),('pricing','Harga/ketentuan harga'),
                               ('inclusions','Termasuk'),('duration','Proses/durasi'),('notes','Catatan')]:
                if values[key]: parts.append(label + ': ' + values[key])
            raw = ' — '.join(parts)
        else:
            if not values['question'] or not values['answer']:
                raise ValueError('Isi pertanyaan dan jawaban FAQ yang ingin diperbarui.')
            raw = values['question'] + ' | ' + values['answer']
        card = dict(values, id=row_id, raw=raw, changed=not unchanged)
        if kind == 'services':
            card['pricing_changed'] = not old or values['pricing'] != old.get('pricing', '')
        output.append(card)
    if set(known) - seen:
        raise ValueError('Ada catatan lama yang tidak ikut terkirim. Muat ulang halaman.')
    return output


def readiness(profile, services, faqs, features, cards):
    checks = []
    def check(key, complete, missing):
        checks.append({'key': key, 'complete': bool(complete), 'missing': missing})
    check('description', (profile.get('short_description') or '').strip(), 'Ceritakan singkat apa yang ditawarkan bisnismu.')
    check('services', services, 'Tambahkan minimal satu produk atau layanan.')
    prices = 0
    for row, card in zip(services, cards['services']):
        raw = (row.get('raw_input') or '').lower()
        rule = card.get('pricing', '').strip().lower()
        known = row.get('price_from') is not None or bool(rule and not re.search(r'belum|tidak tahu|tbd|nanti', rule))
        known = known or bool(re.search(r'(?:rp\.?\s*\d|idr\s*\d|usd\s*\d|gratis|sesuai penawaran|harga berdasarkan)', raw))
        if not known: prices += 1
    check('prices', services and not prices, f'{prices} layanan belum memiliki informasi harga atau ketentuan penawaran.' if services else 'Isi harga atau ketentuan penawaran setelah menambah layanan.')
    check('hours', (profile.get('operating_hours') or '').strip(), 'Jam operasional belum diisi.')
    complete_faq = any((c.get('question') or '').strip() and (c.get('answer') or '').strip() for c in cards['faqs'])
    check('faqs', complete_faq, 'Belum ada FAQ dengan pertanyaan dan jawaban lengkap.')
    check('communication', all((profile.get(k) or '').strip() for k in ('tone','primary_language','customer_salutation')), 'Lengkapi gaya bicara, bahasa, dan sapaan customer.')
    if (profile.get('online_or_offline') or '').lower() in ('offline','both','hybrid'):
        check('address', (profile.get('address') or '').strip(), 'Isi alamat agar customer tahu lokasi kunjungan.')
    enabled = profile.get('appointment_enabled')
    if features.get('appointment') and enabled not in (False, 0, '0', 'false', 'off'):
        check('booking', (profile.get('appointment_rules_raw') or '').strip(), 'Lengkapi aturan booking di Pengaturan operasional.')
    if features.get('payment_conversation'):
        complete = (profile.get('payment_instructions') or '').strip() or all((profile.get(k) or '').strip() for k in ('payment_bank_name','payment_account_name','payment_account_number'))
        check('payment', complete, 'Lengkapi petunjuk pembayaran customer di Pengaturan operasional.')
    return {'score': round(100 * sum(c['complete'] for c in checks) / len(checks)), 'checks': checks,
            'missing': [c['missing'] for c in checks if not c['complete']]}


@db.knowledge_writer
def save(business_id, fields, cards, old_profile, old_services, old_faqs, revision, actor):
    """Update only explicitly edited rows, archive previous state, retain stable IDs. Atomic."""
    if set(fields) - set(PROFILE_FIELDS):
        raise ValueError('Isian tidak didukung.')
    initial_config = repo.get_tenant_config_row(business_id)
    fallback_config = provisioning.build_tenant_config(business_id) if not initial_config else None
    conn = db.get_connection()
    cur = conn.cursor()
    def execute(sql, params=()): cur.execute(db._adapt_placeholders(sql), params)
    def select(sql, params=()):
        execute(sql, params)
        columns = [d[0] for d in cur.description]
        return [db._row_to_dict(row, columns) for row in cur.fetchall()]
    try:
        revisions = select('SELECT id FROM business_knowledge_revisions WHERE business_id = ? ORDER BY id DESC LIMIT 1', (business_id,))
        current = revisions[0] if revisions else None
        # Reload after acquiring the lock so onboarding/settings changes are not overwritten.
        actual_profile = select('SELECT * FROM business_profiles WHERE business_id = ?', (business_id,))[0]
        actual_services = select('SELECT * FROM business_services WHERE business_id = ? ORDER BY sort_order, id', (business_id,))
        actual_faqs = select('SELECT * FROM business_faqs WHERE business_id = ? ORDER BY id', (business_id,))
        expected = revision_token(business_id, current['id'] if current else 0,
                                  actual_profile, actual_services, actual_faqs, select)
        if expected != str(revision):
            raise ValueError('Informasi sudah diperbarui. Muat ulang sebelum menyimpan.')
        if actual_profile != old_profile or actual_services != old_services or actual_faqs != old_faqs:
            raise ValueError('Informasi sudah berubah. Muat ulang sebelum menyimpan.')
        configs = select('SELECT * FROM tenant_configs WHERE business_id = ?', (business_id,))
        config_row = configs[0] if configs else None
        original_config = repo._coerce_json_column(config_row['config_json'], (dict, list)) if config_row else fallback_config
        if not isinstance(original_config, dict): raise ValueError('Konfigurasi bisnis tidak valid.')
        config = copy.deepcopy(original_config)
        changed_fields = {k:v for k,v in fields.items() if v != (old_profile.get(k) or '')}
        dirty = changed_fields or any(c['changed'] for kind in ('services','faqs') for c in cards[kind])
        if not dirty:
            return
        if changed_fields:
            execute('UPDATE business_profiles SET ' + ', '.join(k+' = ?' for k in changed_fields) + ' WHERE business_id = ?', (*changed_fields.values(), business_id))
        ai = config.setdefault('ai', {})
        info = config.setdefault('business_info', {})
        for k,v in changed_fields.items():
            if k in ('tone','customer_salutation'): ai[k] = v
            elif k == 'primary_language': ai.setdefault('language', {})['primary'] = v
            elif k == 'short_description': ai['business_description'] = v; ai['system_instructions'] = v
            elif k in ('operating_hours','closed_days'):
                info.setdefault('business_hours', {})['raw' if k == 'operating_hours' else k] = v
            elif k == 'business_phone': info.setdefault('contact_info', {})[k] = v
            elif k == 'address': info[k] = v
            elif k == 'category': config['business_type'] = v
        for kind, old_rows, table in [('services', old_services, 'business_services'),('faqs', old_faqs, 'business_faqs')]:
            for index, card in enumerate(cards[kind]):
                if not card['changed']: continue
                if kind == 'services':
                    values = {'raw_input':card['raw'], 'service_name':card['name'], 'description':card['description'],
                              'price_from':None, 'price_to':None, 'currency':None, 'needs_review':True}
                    previous = next((r for r in old_rows if str(r['id']) == card['id']), None)
                    if previous and not card['pricing_changed']:
                        for key in ('price_from','price_to','currency','needs_review'):
                            values[key] = previous.get(key)
                else:
                    values = {'raw_input':card['raw'], 'question':card['question'], 'answer':card['answer'],
                              'category':card['category'] or None, 'needs_review':False}
                if card['id']:
                    execute('UPDATE '+table+' SET '+', '.join(k+' = ?' for k in values)+' WHERE id = ? AND business_id = ?', (*values.values(),card['id'],business_id))
                    if cur.rowcount != 1: raise ValueError('Catatan tidak ditemukan.')
                else:
                    values = dict(values, business_id=business_id)
                    if kind == 'services': values['sort_order'] = index
                    execute('INSERT INTO '+table+' ('+', '.join(values)+') VALUES ('+', '.join('?' for _ in values)+') RETURNING id',tuple(values.values()))
                    card['id'] = str(cur.fetchone()[0])
            if any(c['changed'] for c in cards[kind]):
                knowledge = config.setdefault('knowledge', {})
                if kind == 'services':
                    rows = select('SELECT * FROM business_services WHERE business_id = ? ORDER BY sort_order, id', (business_id,))
                    preserved = {item.get('raw_input'): item for item in knowledge.get('services', []) if isinstance(item, dict)}
                    knowledge['services'] = [preserved.get(r['raw_input']) or {k:r.get(k) for k in
                        ('raw_input','service_name','description','price_from','price_to','currency','needs_review')} for r in rows]
                else:
                    rows = select('SELECT * FROM business_faqs WHERE business_id = ? ORDER BY id', (business_id,))
                    knowledge['faq'] = [{'question':r.get('question') or r['raw_input'],'answer':r.get('answer'),
                                         'needs_review':bool(r['needs_review'])} for r in rows]
        now = datetime.now(timezone.utc).isoformat()
        snapshot = {'profile':old_profile, 'services':old_services, 'faqs':old_faqs, 'config':original_config}
        execute('INSERT INTO business_knowledge_revisions (business_id, snapshot_json, editor_json, created_at) VALUES (?, ?, ?, ?)',
                (business_id,json.dumps(snapshot,ensure_ascii=False,default=str),json.dumps(cards,ensure_ascii=False),now))
        payload = json.dumps(config,ensure_ascii=False,sort_keys=True)
        if config_row:
            execute('UPDATE tenant_configs SET config_json = ?, config_version = config_version + 1, updated_at = ? WHERE business_id = ?', (payload,now,business_id))
        else:
            execute('INSERT INTO tenant_configs (business_id, config_version, config_json, provisioned_at, updated_at) VALUES (?, 1, ?, ?, ?)', (business_id,payload,now,now))
        db._knowledge_commit(conn)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
    repo.write_audit(actor,business_id,'BUSINESS_MEMORY_UPDATED','Owner updated business knowledge')
