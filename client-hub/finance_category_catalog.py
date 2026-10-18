"""Additive built-in identity/order. Custom names and historical category IDs survive."""
import db

PERSONAL=(
 ('housing','Tempat Tinggal',('Sewa','Perawatan')),
 ('food','Makanan & Belanja',('Bahan Makanan','Makan di Luar')),
 ('transport','Transportasi',('Bahan Bakar','Parkir','Tol','Sewa Mobil','Transportasi Umum')),
 ('utilities','Utilitas',('Listrik','Air','Gas','Internet')),
 ('health','Kesehatan',('Perawatan Medis','Obat')),
 ('items','Barang Pribadi',('Pakaian','Perlengkapan Mandi','Perawatan Diri')),
)

# Version2 is the owner's newer reference. Old IDs are reused only with exact
# system identity and unchanged stored name/parent; unknown/custom rows survive.
PERSONAL_V2=(
 ('housing','Rumah / Sewa','home',('Hipotek','Hipotek Kedua','Sewa','Iuran Lingkungan','Pajak Properti')),
 ('utilities','Utilitas','electric',('Listrik','Gas / Pemanas','Telepon','Ponsel','Internet','TV Kabel / Satelit','Air','Sampah','Penatu','Pembersihan')),
 ('food','Makanan / Belanja','food',('Bahan Makanan','Restoran / Makanan Cepat Saji')),
 ('items','Belanja Umum','shopping',('Pakaian','Barang Pribadi','Anak / Mainan','Buku / Majalah','Perawatan Kecantikan')),
 ('entertainment','Hiburan','entertainment',('Film','Sewa DVD','Musik','Appstore','Tune Core','Musik Produce')),
 ('transport','Mobil / Otomotif','transport',('Bensin','Cicilan Mobil','Servis Mobil','e-Toll','Transportasi Online','Parkir')),
 ('health','Asuransi / Medis','health',('Asuransi Mobil','Asuransi Rumah','Asuransi Kesehatan','Biaya Medis / Co-pay','Pengobatan')),
 ('misc','Lain-lain / Sekali Bayar','category',('Tiket Pesawat','Hotel / Penginapan','Hadiah / Amal','Keluarga')),
 ('investment','Investasi','investment',()),('bank','Biaya Bank','bank',()),('salaries','Gaji / Upah','work',()),
)
# Final v3 Personal list. No historical recategorization or permanent deletion.
PERSONAL_V3=(
 ('housing','Rumah / Sewa','home',('Sewa','Iuran Lingkungan','Pajak Properti','Hipotek','Staf Rumah Tangga','Layanan Rumah')),
 ('utilities','Utilitas','electric',('Listrik','Gas / Pemanas','Internet','Sampah','Penatu','Pembersihan')),
 ('items','Barang Pribadi','shopping',('Pakaian','Rias Wajah','Perawatan Kulit','Anak / Mainan')),
 ('food','Makanan','food',('Bahan Makanan','Restoran','Makanan Cepat Saji')),
 ('entertainment','Hiburan','entertainment',('Film','Langganan','Acara','Permainan')),
 ('transport','Transportasi','transport',('Bahan Bakar','Servis Kendaraan','Tol','Transportasi Daring','Parkir','Pembayaran Pinjaman Kendaraan','Sewa Mobil')),
 ('insurance','Asuransi','health',('Asuransi Kesehatan','Asuransi Kendaraan','Asuransi Rumah')),
 ('medical','Medis','health',('Prosedur Kosmetik',)),
 ('misc','Lain-lain / Sekali Bayar','category',('Hadiah & Donasi','Pembelian Khusus','Lainnya')),
 ('holiday','Liburan','transport',('Penerbangan','Akomodasi','Transportasi Lokal','Makanan & Minuman','Aktivitas & Tiket','Visa & Dokumen Perjalanan')),
 ('bank','Biaya Bank','bank',('Pajak','Administrasi')),
)

ICONS=('category','home','rent','shopping','food','transport','electric','water','internet','phone','health','education','digital','entertainment','care','work','investment','bank')

def icon(value):
    if value not in ICONS:
        import finance_service as f
        raise f.FinanceError('category_icon_invalid')
    return value


def preference(business_id,actor,ident,*,icon_key=None,position=None):
    import finance_service as f
    scope=f._category_scope(business_id,actor)
    if not f._category_setting_by_id(business_id,ident,actor,include_inactive=True):raise f.FinanceError('category_unavailable')
    if icon_key is not None:icon(icon_key)
    db.execute('INSERT INTO finance_category_preferences(business_id,scope_key,category_id,icon_key,sort_order) VALUES (?,?,?,?,?) ON CONFLICT(business_id,scope_key,category_id) DO UPDATE SET icon_key=COALESCE(excluded.icon_key,finance_category_preferences.icon_key),sort_order=COALESCE(excluded.sort_order,finance_category_preferences.sort_order)',(business_id,scope['scope_key'],ident,icon_key,position))


def edit(business_id,actor,ident,*,name=None,icon_key=None,deactivate=False):
    import finance_service as f
    with f._write(business_id,actor):
        if icon_key is not None:icon(icon_key)
        row=next((v for v in f.list_categories(business_id,include_inactive=True,include_children=True,actor_user_id=actor) if v['id']==ident),None)
        if not row:raise f.FinanceError('category_unavailable')
        # An unchanged localized built-in label is not a customer rename.
        if name==row['display_name']:name=row['name']
        f.update_category_workspace_setting(business_id,ident,name=name,deactivate=deactivate,actor_user_id=actor)
        if icon_key is not None:preference(business_id,actor,ident,icon_key=icon_key)


def reorder(business_id,actor,ids,*,direction,parent=None):
    import finance_service as f
    if not isinstance(ids,list) or not 1<=len(ids)<=1000:raise f.FinanceError('category_order_invalid')
    with f._write(business_id,actor):
        ids=[f._id(v) for v in ids];parent=f._id(parent) if parent else None
        rows=f.list_categories(business_id,direction,include_children=True,actor_user_id=actor)
        expected={v['id'] for v in rows if v.get('parent_category_id')==parent}
        if len(ids)!=len(set(ids)) or set(ids)!=expected:raise f.FinanceError('category_order_invalid')
        for index,ident in enumerate(ids):preference(business_id,actor,ident,position=index*100)
        f._audit(business_id,actor,'FINANCE_CATEGORY_ORDER_UPDATED',parent)


def _sync_reference(business_id,actor,scope):
    import json
    import finance_service as f
    if db.query_one('SELECT 1 FROM finance_category_catalog_versions WHERE business_id=? AND scope_key=? AND version=2',(business_id,scope['scope_key'])):return
    old={v['canonical_key']:dict(v) for v in db.query_all('SELECT m.*,s.display_name,s.is_active,h.parent_category_id FROM finance_catalog_items m JOIN finance_category_workspace_settings s ON s.business_id=m.business_id AND s.category_id=m.category_id AND s.scope_key=m.scope_key LEFT JOIN finance_category_hierarchy h ON h.business_id=m.business_id AND h.child_category_id=m.category_id WHERE m.business_id=? AND m.scope_key=?',(business_id,scope['scope_key']))}
    used=set();changes=[]
    aliases={'Gas / Pemanas':'Gas','Restoran / Makanan Cepat Saji':'Makan di Luar','Bensin':'Bahan Bakar','e-Toll':'Tol','Transportasi Online':'Transportasi Umum','Pengobatan':'Perawatan Medis'}
    def node(key,name,position,parent,prior_key,default_icon):
        candidate=old.get(prior_key) if prior_key else None
        if candidate and (candidate['builtin_name']!=candidate['display_name'] or candidate['parent_category_id']!=parent):candidate=None
        if candidate:
            ident=candidate['category_id'];changes.append({'before':candidate})
            # Preserve a deliberately archived old built-in; never resurrect it.
            db.execute('UPDATE finance_category_workspace_settings SET display_name=?,updated_at=? WHERE business_id=? AND scope_key=? AND category_id=?',(name,f.repo._now(),business_id,scope['scope_key'],ident))
            db.execute('UPDATE finance_catalog_items SET sort_order=?,builtin_name=? WHERE business_id=? AND scope_key=? AND category_id=?',(position,name,business_id,scope['scope_key'],ident))
        else:
            ident=f._create_category(business_id,'EXPENSE','__kilas_'+scope['scope_key']+'_'+key,actor)
            f._ensure_category_setting(business_id,ident,name,actor)
            if parent is not None:f._link_category_parent(business_id,ident,parent)
            mark(business_id,scope['scope_key'],key,ident,position,name);changes.append({'created':ident})
        used.add(ident)
        if not db.query_one('SELECT 1 FROM finance_category_preferences WHERE business_id=? AND scope_key=? AND category_id=?',(business_id,scope['scope_key'],ident)):
            preference(business_id,actor,ident,icon_key=default_icon)
        return ident
    for order,(oldkey,name,default_icon,children) in enumerate(PERSONAL_V2):
        parent=node('v2.'+oldkey,name,order*100,None,oldkey,default_icon)
        for index,child in enumerate(children):
            prior=next((key for key,value in old.items() if value['parent_category_id']==parent and value['builtin_name']==aliases.get(child,child)),None)
            node('v2.'+oldkey+'.'+str(index),child,index*100,parent,prior,default_icon)
    for key,row in old.items():
        if row['category_id'] in used or row['builtin_name']!=row['display_name'] or row['builtin_name']=='__customer_owned__' or key.startswith('INCOME'):continue
        parent_before=next((v for v in old.values() if v['category_id']==row['parent_category_id']),None)
        if parent_before and parent_before['builtin_name']!=parent_before['display_name']:continue
        # Keep a required active Bill category selectable rather than detach it.
        if db.query_one('SELECT 1 FROM finance_recurring_expenses WHERE business_id=? AND category_id=? AND is_active=TRUE',(business_id,row['category_id'])):continue
        changes.append({'archived_before':row})
        db.execute('UPDATE finance_category_workspace_settings SET is_active=FALSE,updated_at=? WHERE business_id=? AND scope_key=? AND category_id=?',(f.repo._now(),business_id,scope['scope_key'],row['category_id']))
    db.execute('INSERT INTO finance_category_catalog_versions VALUES (?,?,2,?)',(business_id,scope['scope_key'],json.dumps(changes,sort_keys=True)))
    f._audit(business_id,actor,'FINANCE_PERSONAL_REFERENCE_CATALOG_V2',None)

def _sync_final(business_id,actor,scope):
    import json
    import finance_service as f
    if db.query_one('SELECT 1 FROM finance_category_catalog_versions WHERE business_id=? AND scope_key=? AND version=3',(business_id,scope['scope_key'])):return
    old=[dict(v) for v in db.query_all('SELECT m.*,s.display_name,s.is_active,h.parent_category_id FROM finance_catalog_items m JOIN finance_category_workspace_settings s ON s.business_id=m.business_id AND s.category_id=m.category_id AND s.scope_key=m.scope_key LEFT JOIN finance_category_hierarchy h ON h.business_id=m.business_id AND h.child_category_id=m.category_id WHERE m.business_id=? AND m.scope_key=?',(business_id,scope['scope_key']))]
    used=set();changes=[]
    prior_version=db.query_one('SELECT changes_json FROM finance_category_catalog_versions WHERE business_id=? AND scope_key=? AND version=2',(business_id,scope['scope_key']))
    system_retired={v['archived_before']['category_id'] for v in json.loads(prior_version['changes_json']) if v.get('archived_before',{}).get('is_active')} if prior_version else set()
    def restore_system_retirement(row):
        # Only the prior catalog's own logged retirement, never a user archive.
        if not row['is_active'] and row['category_id'] in system_retired and not db.query_one('SELECT 1 FROM audit_log WHERE business_id=? AND action=? AND detail=?',(business_id,'FINANCE_CATEGORY_DEACTIVATED','finance_record_id='+str(row['category_id']))):
            db.execute('UPDATE finance_category_workspace_settings SET is_active=TRUE WHERE business_id=? AND scope_key=? AND category_id=?',(business_id,scope['scope_key'],row['category_id']))
    def proven(row):return row['builtin_name']!='__customer_owned__' and row['builtin_name']==row['display_name']
    # Only unambiguous SAME-parent semantics reuse a leaf. Combined medical/food
    # categories are retired, not guessed into a narrower new category.
    aliases={'Bahan Bakar':('Bensin',),'Servis Kendaraan':('Servis Mobil',),'Tol':('e-Toll',),'Transportasi Daring':('Transportasi Online',),'Pembayaran Pinjaman Kendaraan':('Cicilan Mobil',)}
    for order,(key,name,default_icon,children) in enumerate(PERSONAL_V3):
        candidates=[r for r in old if r['canonical_key'] in (key,'v2.'+key,'v3.'+key) and r['parent_category_id'] is None and proven(r)]
        root=candidates[0] if len(candidates)==1 else None
        if root:
            parent=root['category_id'];changes.append({'before':root});restore_system_retirement(root)
            db.execute('UPDATE finance_category_workspace_settings SET display_name=?,updated_at=? WHERE business_id=? AND scope_key=? AND category_id=?',(name,f.repo._now(),business_id,scope['scope_key'],parent))
            db.execute('UPDATE finance_catalog_items SET builtin_name=?,sort_order=? WHERE business_id=? AND scope_key=? AND category_id=?',(name,order*100,business_id,scope['scope_key'],parent))
        else:
            parent=f._create_category(business_id,'EXPENSE','__kilas_'+scope['scope_key']+'_v3.'+key,actor);f._ensure_category_setting(business_id,parent,name,actor);mark(business_id,scope['scope_key'],'v3.'+key,parent,order*100,name);changes.append({'created':parent})
        used.add(parent);preference(business_id,actor,parent,icon_key=default_icon,position=order*100)
        for index,child in enumerate(children):
            candidates=[r for r in old if r['parent_category_id']==parent and proven(r) and r['builtin_name'] in (child,*aliases.get(child,()))]
            row=candidates[0] if len(candidates)==1 else None
            if row:
                ident=row['category_id'];changes.append({'before':row});restore_system_retirement(row)
                db.execute('UPDATE finance_category_workspace_settings SET display_name=?,updated_at=? WHERE business_id=? AND scope_key=? AND category_id=?',(child,f.repo._now(),business_id,scope['scope_key'],ident))
                db.execute('UPDATE finance_catalog_items SET builtin_name=?,sort_order=? WHERE business_id=? AND scope_key=? AND category_id=?',(child,index*100,business_id,scope['scope_key'],ident))
            else:
                ident=f._create_category(business_id,'EXPENSE','__kilas_'+scope['scope_key']+'_v3.'+key+'.'+str(index),actor);f._ensure_category_setting(business_id,ident,child,actor);f._link_category_parent(business_id,ident,parent);mark(business_id,scope['scope_key'],'v3.'+key+'.'+str(index),ident,index*100,child);changes.append({'created':ident})
            used.add(ident);preference(business_id,actor,ident,icon_key=default_icon,position=index*100)
    for row in old:
        if row['category_id'] in used or not proven(row) or row['canonical_key'].startswith('INCOME'):continue
        parent=next((v for v in old if v['category_id']==row['parent_category_id']),None)
        if parent and not proven(parent):continue
        if db.query_one('SELECT 1 FROM finance_recurring_expenses WHERE business_id=? AND category_id=? AND is_active=TRUE',(business_id,row['category_id'])):continue
        changes.append({'archived_before':row})
        db.execute('UPDATE finance_category_workspace_settings SET is_active=FALSE,updated_at=? WHERE business_id=? AND scope_key=? AND category_id=?',(f.repo._now(),business_id,scope['scope_key'],row['category_id']))
    db.execute('INSERT INTO finance_category_catalog_versions VALUES (?,?,3,?)',(business_id,scope['scope_key'],json.dumps(changes,sort_keys=True)))
    f._audit(business_id,actor,'FINANCE_PERSONAL_REFERENCE_CATALOG_V3',None)


def mark(business_id,scope,key,ident,position,name):
    db.execute('INSERT INTO finance_catalog_items VALUES (?,?,?,?,?,?) ON CONFLICT(business_id,scope_key,canonical_key) DO NOTHING',(business_id,scope,key,ident,position,name))


def sync_personal(business_id,actor):
    import finance_service as f
    scope=f._category_scope(business_id,actor)
    if scope['workspace_type']!='PERSONAL':return
    # A completed final catalog is authoritative, including deliberate archives
    # and the exact approved cleanup. Never bootstrap superseded versions again.
    if db.query_one('SELECT 1 FROM finance_category_catalog_versions WHERE business_id=? AND scope_key=? AND version=3',(business_id,scope['scope_key'])):return
    # Upgrade known legacy identities directly. In particular food.1 remains
    # Dining Out; the deprecated v2 combined-label transition must not run first.
    _sync_final(business_id,actor,scope)


def decorate(business_id,scope,rows):
    metadata={v['category_id']:v for v in db.query_all('SELECT * FROM finance_catalog_items WHERE business_id=? AND scope_key=?',(business_id,scope['scope_key']))}
    prefs={v['category_id']:v for v in db.query_all('SELECT * FROM finance_category_preferences WHERE business_id=? AND scope_key=?',(business_id,scope['scope_key']))}
    from flask import has_request_context
    from ui_i18n import translate
    for row in rows:
        item=metadata.get(row['id']);row['display_name']=row['name']
        # Renaming a built-in makes that name customer-owned: leave it verbatim.
        if item and row['name']==item['builtin_name'] and has_request_context():row['display_name']=translate(item['builtin_name'])
        pref=prefs.get(row['id']) or {};row['icon_key']=pref.get('icon_key') or 'category'
        row['catalog_order']=pref.get('sort_order') if pref.get('sort_order') is not None else item['sort_order'] if item else 100000
    rows.sort(key=lambda row:(row['direction'],row['catalog_order'],row['name'].casefold(),row['id']))
    return rows
