"""Service catalog — Business Hub V2, Phase B.

Single source of truth for pricing shown anywhere in the app: pricing_config.py defines the
canonical figures, this module seeds them into service_catalog (idempotently — safe to call on
every boot, like db.init_schema()) and provides the only read/write functions any route should use.
Never hardcode a price in a template or route — always go through here.
"""
import json
import re
import uuid

import db
import pricing_config


def seed_catalog_if_needed():
    """Idempotent: inserts any catalog_key from pricing_config.py that doesn't exist yet. Does NOT
    overwrite an existing row's price/name for routine admin edits — if Kilas Works wants to
    change a price day-to-day, that happens via the admin catalog-edit screen (routes_admin.py),
    not by re-seeding. This function only ever adds rows that are missing, so pricing_config.py
    additions (e.g. a brand new service) show up automatically on next boot without clobbering
    any admin edits already made to existing ones.

    Existing active/archive decisions remain authoritative. Retired keys start inactive only
    when first inserted; subsequent admin reactivation is preserved."""
    for item in pricing_config.CATALOG_ITEMS:
        existing = db.query_one("SELECT id FROM service_catalog WHERE catalog_key = ?", (item["key"],))
        if existing is None:
            db.execute(
                "INSERT INTO service_catalog (catalog_key, category, name, pricing_mode, "
                "price_amount, price_unit, is_active) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item["key"], item["category"], item["name"], item["pricing_mode"],
                 item["price_amount"], item["price_unit"], item["key"] not in pricing_config.RETIRED_BUNDLE_KEYS),
            )
    _apply_rebrand_corrections()
    _apply_content_launch()


def _apply_content_launch():
    """Atomic one-time commercial update; never updates historical order tables."""
    conn = db.get_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO platform_settings(key,value) VALUES ('content_packages_202609_v1','applied') ON CONFLICT(key) DO NOTHING")
        if cur.rowcount == 1:
            for key, facts in pricing_config.CONTENT_PACKAGES.items():
                cur.execute(db._adapt_placeholders("UPDATE service_catalog SET price_amount=?, pricing_mode='FIXED_PRICE', price_unit='per bulan' WHERE catalog_key=?"),
                            (facts['harga'], 'content_'+key))
        cur.execute("UPDATE service_catalog SET is_active = FALSE WHERE category = 'BUNDLE' AND is_active = TRUE")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def _apply_rebrand_corrections():
    """2026 Kilas Brain rebrand — one-time, narrowly-scoped canonical corrections (see
    seed_catalog_if_needed()'s own docstring for why this is a deliberate exception, not a
    reusable overwrite-everything mechanism). Each statement below only touches a row if it still
    has the OLD value, so re-running this on every boot is safe/idempotent and never re-fights an
    admin who has since made their own further edit to the display name."""
    db.execute(
        "UPDATE service_catalog SET name = 'Kilas Brain Basic' "
        "WHERE catalog_key = 'ai_admin_basic' AND name = 'AI Admin Basic'"
    )
    db.execute(
        "UPDATE service_catalog SET name = 'Kilas Brain Pro' "
        "WHERE catalog_key = 'ai_admin_pro' AND name = 'AI Admin Pro'"
    )


def list_active_catalog():
    return db.query_all(
        "SELECT * FROM service_catalog WHERE is_active = ? AND category <> 'BUNDLE' ORDER BY category, sort_order, name",
        (True,),
    )


def list_all_catalog():
    return db.query_all("SELECT * FROM service_catalog ORDER BY category, sort_order, name")


def get_catalog_item(catalog_key):
    return db.query_one("SELECT * FROM service_catalog WHERE catalog_key = ?", (catalog_key,))


# Routine "Tambah Layanan" (UX pass, Section F/G/H/I) — categories a NEW dashboard-created service
# is safely allowed to use. Deliberately EXCLUDES "AI_ADMIN" (has its own special onboarding/
# payment/activation workflow — see routes_client.py's ai_admin_checkout()/start_fixed_checkout()'s
# own guard, which independently blocks instant-checkout for this category regardless of this
# whitelist, so this is defense-in-depth, not the only safeguard) and "TALENT" (managed through its
# own dedicated admin_talent.html page with its own request/quote flow, not this generic catalog
# form). Every other category maps to one of the two genuinely generic workflows already supported
# end-to-end: FIXED_PRICE/STARTING_FROM (instant checkout) or CUSTOM_QUOTE (brief -> quotation ->
# approval -> checkout) — no new workflow type is invented here.
SAFE_NEW_ITEM_CATEGORIES = ("CONTENT", "VIDEO", "PHOTO", "WEBSITE", "APPLICATION", "EVENT", "ADS")


def create_catalog_item(category, name, pricing_mode, price_amount=None, price_unit=None,
                         description=None, cta_text=None):
    """New routine service/package creation from the admin dashboard (Section G: "Tambah Layanan /
    Paket", explicitly NOT "Tambah Project" — a project is a customer ORDER, this creates a
    LAYANAN/PAKET a customer can later order). Auto-generates a unique catalog_key from the name
    (slugified + a short random suffix to avoid collisions) — admins never type a raw key by hand.
    Raises InvalidCatalogState for an unsafe category/pricing_mode combination, or the same
    price-consistency violations update_catalog_item() already guards against, so both the create
    and edit paths enforce identical invariants (one set of rules, not two)."""
    if category not in SAFE_NEW_ITEM_CATEGORIES:
        raise InvalidCatalogState(
            f"unsupported_category_for_dashboard_creation: {category!r} — categories with a "
            "special workflow (AI_ADMIN, TALENT) cannot be created from this generic form."
        )
    if pricing_mode not in pricing_config.VALID_PRICING_MODES:
        raise InvalidCatalogState(f"invalid_pricing_mode: {pricing_mode!r}")
    if pricing_mode in ("FIXED_PRICE", "STARTING_FROM") and not price_amount:
        raise InvalidCatalogState("fixed_price_requires_amount: harga wajib diisi untuk mode harga tetap")
    if pricing_mode == "CUSTOM_QUOTE":
        price_amount = None
        price_unit = None

    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "layanan"
    catalog_key = f"{slug}_{uuid.uuid4().hex[:6]}"
    max_sort = db.query_one("SELECT COALESCE(MAX(sort_order), 0) AS m FROM service_catalog WHERE category = ?", (category,))
    sort_order = (max_sort["m"] if max_sort else 0) + 1

    new_id = db.insert_returning_id(
        "INSERT INTO service_catalog (catalog_key, category, name, pricing_mode, price_amount, "
        "price_unit, description, cta_text, sort_order, is_active) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (catalog_key, category, name.strip(), pricing_mode, price_amount, price_unit,
         description, cta_text, sort_order, True),
    )
    import catalog_cache
    catalog_cache.bump_version()
    return new_id


def get_catalog_item_by_id(catalog_id):
    return db.query_one("SELECT * FROM service_catalog WHERE id = ?", (catalog_id,))


class InvalidCatalogState(Exception):
    pass


def update_catalog_item(catalog_id, price_amount=None, price_unit=None, is_active=None,
                         description=None, name=None, cta_text=None, sort_order=None,
                         pricing_mode=None):
    """Admin-only edit path (Section 20 / Final Operations Polish Section 6: 'admin actions' must
    not require code/DB changes for routine operations). Only touches fields explicitly passed —
    None means "leave unchanged".

    PRICE CHANGE SAFETY (Final Operations Polish, Section 7): this function only ever touches the
    service_catalog row itself. It NEVER reaches into projects/quotations/invoices to update a
    historical final_price — those are already copied onto the project at creation time
    (projects_repo.create_fixed_price_project copies catalog_item['price_amount'] into
    projects.final_price once, at checkout time) and are never re-read from the catalog afterwards.
    Changing a price here only affects future `create_fixed_price_project()` calls, which read the
    catalog fresh each time — existing orders/invoices/approved quotations are structurally
    unreachable from this function and keep their original amount forever.

    Raises InvalidCatalogState (Section 6: 'Do not allow invalid pricing state') if the requested
    change would leave the item as FIXED_PRICE/STARTING_FROM with no price, or as CUSTOM_QUOTE with
    a price still set (which would look like a real, checkout-able number to a customer)."""
    row = get_catalog_item_by_id(catalog_id)
    if row is None:
        return None
    if row['category'] == 'BUNDLE' and is_active:
        raise InvalidCatalogState('Bundle sudah diarsipkan; pilih layanan secara terpisah.')
    new_price_amount = row["price_amount"] if price_amount is None else price_amount
    new_price_unit = row["price_unit"] if price_unit is None else price_unit
    new_is_active = row["is_active"] if is_active is None else is_active
    new_description = row["description"] if description is None else description
    new_name = row["name"] if name is None else name
    new_cta_text = row["cta_text"] if cta_text is None else cta_text
    new_sort_order = row["sort_order"] if sort_order is None else sort_order
    new_pricing_mode = row["pricing_mode"] if pricing_mode is None else pricing_mode

    if new_pricing_mode not in pricing_config.VALID_PRICING_MODES:
        raise InvalidCatalogState(f"invalid_pricing_mode: {new_pricing_mode!r}")
    if new_pricing_mode in ("FIXED_PRICE", "STARTING_FROM") and not new_price_amount:
        raise InvalidCatalogState("fixed_price_requires_amount: harga wajib diisi untuk mode harga tetap")
    if new_pricing_mode == "CUSTOM_QUOTE":
        # Never let a CUSTOM_QUOTE item carry a leftover number — that would read as a real,
        # checkout-able price to a customer even though the flow always goes through quotation.
        new_price_amount = None
        new_price_unit = None

    db.execute(
        "UPDATE service_catalog SET name = ?, price_amount = ?, price_unit = ?, is_active = ?, "
        "description = ?, cta_text = ?, sort_order = ?, pricing_mode = ?, "
        "updated_at = datetime('now') WHERE id = ?"
        if db.BACKEND == "sqlite" else
        "UPDATE service_catalog SET name = ?, price_amount = ?, price_unit = ?, is_active = ?, "
        "description = ?, cta_text = ?, sort_order = ?, pricing_mode = ?, "
        "updated_at = now() WHERE id = ?",
        (new_name, new_price_amount, new_price_unit, bool(new_is_active), new_description,
         new_cta_text, new_sort_order, new_pricing_mode, catalog_id),
    )
    try:
        import catalog_cache
        catalog_cache.bump_version()
    except Exception:
        pass
    return get_catalog_item_by_id(catalog_id)


def format_price(price_amount, price_unit):
    """Customer-facing price formatting — used by the public catalog page and the PDF export
    (live_catalog_pdf.py). CUSTOM_QUOTE items (price_amount is None) get a natural, professional
    Indonesian sentence rather than a raw two-word label or an invented number (Unified Brand +
    Catalog task, Section 4)."""
    if price_amount is None:
        return "Penawaran disesuaikan dengan kebutuhan project."
    formatted = f"Rp{price_amount:,}".replace(",", ".")
    return f"{formatted} {price_unit}" if price_unit else formatted


def public_name(item):
    if item['catalog_key'] in ('website_domain_com_hosting', 'website_domain_id_hosting'):
        suffix = '.com' if item['catalog_key'] == 'website_domain_com_hosting' else '.id'
        return 'Managed ' + suffix + ' + Hosting'
    return item["name"].replace("AI Admin", "Kilas Brain")


def display_price(item):
    if item["pricing_mode"] == "CUSTOM_QUOTE":
        return "Penawaran sesuai kebutuhan"
    label = format_price(item.get("price_amount"), item.get("price_unit"))
    return ("Mulai dari " if item["pricing_mode"] == "STARTING_FROM" else "") + label


def service_description(item):
    """Copy fallback only. Admin descriptions and the live price/status always win."""
    key = item['catalog_key']
    if key in {'event_' + tier for tier in pricing_config.EVENT_PACKAGES}:
        return pricing_config.event_description(key.removeprefix('event_'))
    if key in ('website_domain_com_hosting', 'website_domain_id_hosting'):
        return pricing_config.MANAGED_HOSTING_DESCRIPTION
    if key in ('ads_setup_only', 'ads_management'):
        return pricing_config.ADS_DESCRIPTION
    content = pricing_config.CONTENT_PACKAGES.get(item['catalog_key'].removeprefix('content_')) if item['catalog_key'].startswith('content_') else None
    if content:
        return f"{content['reels']} Reels / short-form videos + {content['photos']} foto final per bulan. " + pricing_config.CONTENT_SCOPE
    if item['catalog_key'] == 'talent_management':
        return pricing_config.TALENT_FEE_RULE
    if (item.get("description") or "").strip():
        return item["description"].replace("AI Admin", "Kilas Brain")
    package = {"ai_admin_basic": "AI_ADMIN_BASIC", "ai_admin_pro": "AI_ADMIN_PRO"}.get(item["catalog_key"])
    if package:
        from feature_flags import features_for_package
        flags = features_for_package(package)
        labels = {
            "faq": "menjawab pertanyaan umum", "business_info": "menjelaskan informasi bisnis",
            "catalog": "memberi informasi layanan", "basic_lead_capture": "mencatat calon customer",
            "owner_commands": "perintah owner", "advanced_history": "riwayat percakapan lanjutan",
            "image_understanding": "pemahaman gambar", "voice_note": "voice note",
            "lead_qualification": "kualifikasi prospek", "appointment": "alur booking",
            "payment_conversation": "percakapan pembayaran",
        }
        return "Asisten bisnis berbasis AI dari Kilas Works untuk " + ", ".join(v for k,v in labels.items() if flags.get(k)) + ". Tim dapat mengambil alih chat melalui Kilas Inbox."
    descriptions = {
        "CONTENT": "Produksi konten untuk kebutuhan brand dan media sosial. Detail output dan scope mengikuti paket/brief.",
        "VIDEO": "Produksi video untuk kebutuhan brand, termasuk arah kreatif short-form sesuai brief. Detail output dan scope mengikuti paket/brief.",
        "PHOTO": "Fotografi untuk kebutuhan visual brand, produk atau menu sesuai brief. Detail output dan scope mengikuti paket/brief.",
        "WEBSITE": "Website atau landing page untuk menyajikan informasi bisnis. Fitur dan scope mengikuti layanan yang dipilih serta brief.",
        "APPLICATION": "Sistem atau aplikasi untuk proses bisnis. Fitur dan integrasi ditentukan berdasarkan brief.",
    }
    return descriptions.get(item["category"], "Layanan " + public_name(item) + ". Detail output dan scope mengikuti paket/brief.")


def _sales_topic(text, history):
    query = (text or '').lower()
    if re.search(r'content|konten|reels|growth|kilas brain|ai admin|website|talent|photo|foto|video', query):
        return query
    recent = ' '.join(m.get('content','')[-500:] for m in history[-4:] if isinstance(m.get('content'), str))
    return query + ' ' + recent.lower()


def exact_sales_answer(text, history=()):
    """Platform callers only. Exact public facts/actions never invoke a model."""
    query = re.sub(r'[?!.]+$', '', (text or '').lower().strip())
    topic = _sales_topic(query, history)
    service_fact = exact_service_fact(query)
    if service_fact is not None:
        return service_fact
    if re.search(r'\b(bundle|bundling)\b', query) and not re.search(r'kirim|follow up|buat invoice', query):
        return 'Content dan Kilas Brain bisa dibeli terpisah kak. Tidak ada paket bundle atau diskon otomatis.'
    if query in ('udah termasuk talent', 'sudah termasuk talent', 'termasuk talent', 'talent management itu apa'):
        return 'Belum termasuk fee talent kak. ' + pricing_config.TALENT_FEE_RULE
    if query in ('kalian bisa bikin website', 'bisa bikin website', 'bisa buat website'):
        rows = [r for r in list_active_catalog() if r['category'] in ('WEBSITE','APPLICATION')]
        return ('Bisa kak, pilih layanan Website yang tersedia atau ajukan Custom Website sesuai brief untuk penawaran.' if rows
                else 'Layanan Website belum tersedia di katalog aktif saat ini.')
    if re.fullmatch(r'(?:content |konten )?(basic|growth|pro)(?: sekarang)? (?:dapet apa|dapat apa|dapat apaan|isinya apa|berapa|brp|harganya berapa|harganya brp)', query):
        key = re.search(r'\b(basic|growth|pro)\b', query)[1]
        if re.search(r'kilas brain|ai admin', topic) and not re.search(r'content|konten', query):
            return None
        item = get_catalog_item('content_'+key)
        if not item or not item['is_active']:
            return 'Paket Content itu sedang tidak tersedia kak.'
        facts = pricing_config.CONTENT_PACKAGES[key]
        return f"{public_name(item)} {display_price(item)}: {facts['reels']} Reels/short-form + {facts['photos']} foto final. Sesuai brief sosial biasa; produksi kompleks lewat penawaran custom."
    if query in ('mahal', 'bisa kurang', 'yg murah', 'yang murah') or re.fullmatch(r'(?:rp\s*)?\d+(?:[.,]\d+)?\s*(?:juta|jt|ribu|rb) bisa', query):
        cheaper = 'basic' if 'growth' in topic else ('growth' if re.search(r'\bpro\b',topic) else None)
        item = get_catalog_item('content_'+cheaper) if cheaper else None
        alternative = f" Alternatifnya {public_name(item)} ({display_price(item)})." if item and item['is_active'] else ''
        budget_known = bool(re.search(r'\d+\s*(?:juta|jt|rb|ribu)', query))
        already_asked = any(isinstance(m.get('content'),str) and 'budget' in m['content'].lower() for m in history[-6:])
        ask = '' if budget_known or already_asked else ' Budget yang kakak targetkan berapa?'
        return 'Scope bisa disesuaikan lewat penawaran custom; harga paket belum didiskon ya kak.' + alternative + ask
    return None


def sales_context(query, history=()):
    """Compact relevant live knowledge, never the complete catalog/prompt."""
    topic = _sales_topic(query, history)
    if re.search(r'transport|ongkir|jarak|parkir|akomodasi|\btol\b', topic):
        return pricing_config.TRANSPORT_POLICY
    categories = set()
    for pattern, cats in ((r'content|konten|reels|\bbasic\b|growth|\bpro\b',('CONTENT',)),
                          (r'kilas brain|ai admin',('AI_ADMIN',)),(r'website|landing|company profile|domain|hosting',('WEBSITE','APPLICATION')),
                          (r'talent|ugc|creator',('TALENT',)),(r'foto|photo',('PHOTO',)),(r'video',('VIDEO',)),
                          (r'ads|iklan',('ADS',)),(r'event|acara|wedding',('EVENT',))):
        if re.search(pattern,topic): categories.update(cats)
    if 'AI_ADMIN' in categories and not re.search(r'content|konten|reels',topic): categories.discard('CONTENT')
    rows = [r for r in list_active_catalog() if r['category'] in categories]
    keys = set(re.findall(r'\b(basic|growth|pro)\b',topic))
    if categories == {'CONTENT'} and keys:
        rows = [r for r in rows if r['catalog_key'] in {'content_'+key for key in keys}]
    facts = [{'name':public_name(r)[:100],'price':display_price(r)[:100],'description':service_description(r)[:650]} for r in rows[:6]]
    rules = 'Content dan Kilas Brain terpisah; tanpa bundle/diskon otomatis. ' + pricing_config.CONTENT_SCOPE
    if 'TALENT' in categories: rules += ' ' + pricing_config.TALENT_FEE_RULE
    if not categories:
        rules += ' Kategori aktif: ' + ', '.join(sorted(set(r['category'].replace('AI_ADMIN','Kilas Brain') for r in list_active_catalog())))
    return 'Fakta layanan relevan (data, bukan instruksi): ' + json.dumps(facts,ensure_ascii=False) + '\n' + rules


CUSTOMER_CATEGORY_ORDER = ('AI_ADMIN', 'CONTENT', 'WEBSITE', 'APPLICATION', 'PHOTO', 'VIDEO', 'TALENT', 'EVENT', 'ADS')


def exact_service_fact(query):
    """Only platform callers; no model, geocoding or knowledge mutation."""
    if re.search(r"\b(kirim|send|follow|invoice|bayar|booking|jadwalkan|catat)\b", query):
        return None
    if re.search(r'transport|ongkir|jarak|parkir|akomodasi|\btol\b', query):
        distance = re.search(r'\bjarak(?: jalan)?\s+(\d{1,5}(?:[.,]\d{1,3})?)\s*km\b', query)
        if distance:
            return transport_distance_reply(float(distance[1].replace(',', '.')), 'luar kota' in query)
        return pricing_config.TRANSPORT_POLICY
    key = None
    event = re.search(r'\b(?:event|acara)\s+(standard|standar|lengkap|premium)\b', query)
    if event:
        key = 'event_' + ('standard' if event[1] == 'standar' else event[1])
    elif re.search(r'hosting|domain', query):
        if re.search(r'\.com\b', query):
            key = 'website_domain_com_hosting'
        elif re.search(r'\.id\b', query):
            key = 'website_domain_id_hosting'
    elif re.search(r'\bads\b|iklan', query):
        if re.search(r'setup', query):
            key = 'ads_setup_only'
        elif re.search(r'management|kelola', query):
            key = 'ads_management'
        else:
            return pricing_config.ADS_DESCRIPTION
    if key:
        item = get_catalog_item(key)
        if item and item['is_active']:
            return public_name(item) + ' ' + display_price(item) + '. ' + service_description(item)
        return 'Layanan ini belum tersedia di katalog aktif kak.'
    return None


def transport_distance_reply(distance, out_of_town=False):
    fee = pricing_config.transport_fee(distance, out_of_town)
    zone = 'Custom Quote' if fee is None else ('termasuk/gratis' if fee == 0 else format_price(fee, None))
    condition = ' dan luar kota' if out_of_town else ''
    return (f"Jika jarak jalan dari base Tangerang terkonfirmasi {distance:g} km{condition}, transport {zone}. "
            "Tol/parkir sesuai biaya aktual; akomodasi terpisah/custom. Ini perhitungan zona, bukan verifikasi jarak dari alamat/Maps.")


def is_exact_transport_reply(reply):
    if reply == pricing_config.TRANSPORT_POLICY:
        return True
    match = re.match(r'^Jika jarak jalan dari base Tangerang terkonfirmasi (\d{1,5}(?:\.\d{1,3})?) km( dan luar kota)?,', reply)
    return bool(match and reply == transport_distance_reply(float(match[1]), bool(match[2])))
