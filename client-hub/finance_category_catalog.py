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

# Owner's ten expense defaults. Child meanings are the existing approved v3
# list translated into English; Business retains only its existing utility set.
EXPENSE_V4=(
 ('housing','Home/Rent','home',(('Sewa','Rent'),('Iuran Lingkungan','Association Fee'),('Pajak Properti','Property Tax'),('Hipotek','Mortgage'),('Staf Rumah Tangga','Household Staff'),('Layanan Rumah','Home Services'))),
 ('food','Food','food',(('Bahan Makanan','Groceries'),('Restoran','Restaurants'),('Makanan Cepat Saji','Fast Food'))),
 ('utilities','Utilities','electric',(('Listrik','Electricity'),('Gas / Pemanas','Gas / Heating'),('Internet','Internet'),('Sampah','Garbage'),('Penatu','Laundry'),('Pembersihan','Cleaning'))),
 ('items','Personal Item','shopping',(('Pakaian','Clothing'),('Rias Wajah','Makeup'),('Perawatan Kulit','Skincare'),('Anak / Mainan','Kids / Toys'))),
 ('transport','Transportation','transport',(('Bahan Bakar','Fuel'),('Servis Kendaraan','Vehicle Servicing'),('Tol','Tolls'),('Transportasi Daring','Ride-hailing'),('Parkir','Parking'),('Pembayaran Pinjaman Kendaraan','Vehicle Loan Payment'),('Sewa Mobil','Car Rental'))),
 ('entertainment','Entertainment','entertainment',(('Film','Movies'),('Langganan','Subscriptions'),('Acara','Events'),('Permainan','Games'))),
 ('medical','Medical','health',(('Prosedur Kosmetik','Cosmetic Procedures'),)),
 ('holiday','Holiday','transport',(('Penerbangan','Flights'),('Akomodasi','Accommodation'),('Transportasi Lokal','Local Transport'),('Makanan & Minuman','Food & Drinks'),('Aktivitas & Tiket','Activities & Tickets'),('Visa & Dokumen Perjalanan','Visa & Travel Documents'))),
 ('bank','Bank Charge','bank',(('Pajak','Tax'),('Administrasi','Administration'))),
 ('misc','Misc/one-time','category',(('Hadiah & Donasi','Gifts & Donations'),('Pembelian Khusus','Special Purchases'),('Lainnya','Other'))),
)
BUSINESS_UTILITY_V4=(('Listrik','Electricity'),('Air','Water'),('Internet','Internet'),('Telepon','Telephone'),('Gas','Gas'),('Laundry','Laundry'),('Sampah / Kebersihan','Garbage / Cleaning'))

def _expense_policy(business_id,scope):
    import json
    row=db.query_one('SELECT changes_json FROM finance_category_catalog_versions WHERE business_id=? AND scope_key=? AND version=4',(business_id,scope['scope_key']))
    return json.loads(row['changes_json']) if row else None

def sync_expense(business_id,actor):
    """Reversible picker policy; never rename, delete or reparent legacy data.

    Caller owns the scoped write lock. Only a persisted seed identity plus an
    unchanged name and parent can be reused/hidden. Unknown/custom rows survive.
    Retired defaults remain usable by their existing schedules and edit paths.
    """
    import json
    import finance_service as f
    if f._finance_write.get()!=(business_id,actor):raise f.FinanceError('business_unavailable')
    scope=f._category_scope(business_id,actor)
    if _expense_policy(business_id,scope):return
    old=[dict(v) for v in db.query_all('SELECT m.*,s.display_name,s.is_active,c.direction,h.parent_category_id FROM finance_catalog_items m JOIN finance_categories c ON c.business_id=m.business_id AND c.id=m.category_id JOIN finance_category_workspace_settings s ON s.business_id=m.business_id AND s.category_id=m.category_id AND s.scope_key=m.scope_key LEFT JOIN finance_category_hierarchy h ON h.business_id=m.business_id AND h.child_category_id=m.category_id WHERE m.business_id=? AND m.scope_key=? AND c.direction=?',(business_id,scope['scope_key'],'EXPENSE'))]
    proven=lambda r:r['builtin_name']!='__customer_owned__' and r['builtin_name']==r['display_name']
    originals={key:name for key,name,_,_ in PERSONAL_V3}
    approved={};created=[];preferences_before=[]
    def node(key,name,aliases,parent,position,icon_key):
        candidates=[r for r in old if proven(r) and r['parent_category_id']==parent and r['builtin_name'] in (name,*aliases)]
        row=candidates[0] if len(candidates)==1 else None
        if row:ident=row['category_id'];original=row['builtin_name']
        else:
            ident=f._create_category(business_id,'EXPENSE','__kilas_'+scope['scope_key']+'_v4.'+key,actor)
            f._ensure_category_setting(business_id,ident,name,actor)
            if parent is not None:f._link_category_parent(business_id,ident,parent)
            mark(business_id,scope['scope_key'],'v4.'+key,ident,position,name);created.append(ident);original=name
        previous=db.query_one('SELECT * FROM finance_category_preferences WHERE business_id=? AND scope_key=? AND category_id=?',(business_id,scope['scope_key'],ident))
        preferences_before.append(dict(previous) if previous else {'category_id':ident,'missing':True})
        preference(business_id,actor,ident,icon_key=icon_key,position=position)
        approved[str(ident)]={'name':name,'builtin_name':original,'parent_category_id':parent,'key':key}
        return ident
    for order,(key,name,icon_key,children) in enumerate(EXPENSE_V4):
        root=node(key,name,(originals[key],),None,order*100,icon_key)
        if scope['workspace_type']=='BUSINESS':children=BUSINESS_UTILITY_V4 if key=='utilities' else ()
        for index,(before,english) in enumerate(children):node(key+'.'+str(index),english,(before,),root,index*100,icon_key)
    # No raw active flags change: this mapping hides old proven defaults only
    # from new choices. A false enabled flag reverses the policy without deleting
    # any category, setting, hierarchy, transaction, allocation, budget or rule.
    policy={'enabled':True,'approved':approved,'retired':[r['category_id'] for r in old if proven(r) and str(r['category_id']) not in approved], 'created':created,'before':old,'preferences_before':preferences_before}
    db.execute('INSERT INTO finance_category_catalog_versions VALUES (?,?,4,?)',(business_id,scope['scope_key'],json.dumps(policy,sort_keys=True)))
    f._audit(business_id,actor,'FINANCE_EXPENSE_REFERENCE_CATALOG_V4',None)


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
    sync_expense(business_id,actor)


def decorate(business_id,scope,rows,*,include_inactive=False):
    metadata={v['category_id']:v for v in db.query_all('SELECT * FROM finance_catalog_items WHERE business_id=? AND scope_key=?',(business_id,scope['scope_key']))}
    prefs={v['category_id']:v for v in db.query_all('SELECT * FROM finance_category_preferences WHERE business_id=? AND scope_key=?',(business_id,scope['scope_key']))}
    policy=_expense_policy(business_id,scope)
    approved=policy['approved'] if policy and policy.get('enabled') else {}
    retired=set(policy['retired'] if policy.get('enabled') else policy['created']) if policy else set()
    if policy and not policy.get('enabled'):
        for previous in policy['preferences_before']:
            if previous.get('missing'):prefs.pop(previous['category_id'],None)
            else:prefs[previous['category_id']]=previous
    settings={v['category_id']:dict(v) for v in db.query_all('SELECT s.category_id,s.display_name,h.parent_category_id FROM finance_category_workspace_settings s LEFT JOIN finance_category_hierarchy h ON h.business_id=s.business_id AND h.child_category_id=s.category_id WHERE s.business_id=? AND s.scope_key=?',(business_id,scope['scope_key']))}
    def proven(ident):
        item=metadata.get(ident);setting=settings.get(ident)
        return bool(item and setting and item['builtin_name']!='__customer_owned__' and item['builtin_name']==setting['display_name'])
    # A custom descendant protects its old parent from disappearing. Such rows
    # remain custom context, not additional defaults; names alone prove nothing.
    protected={v['parent_category_id'] for ident,v in settings.items() if v['parent_category_id'] and not proven(ident)}
    retired={ident for ident in retired if ident not in protected and proven(ident) and (not settings[ident]['parent_category_id'] or proven(settings[ident]['parent_category_id']))}
    from flask import has_request_context
    from ui_i18n import translate
    for row in rows:
        item=metadata.get(row['id']);row['display_name']=row['name']
        # Renaming a built-in makes that name customer-owned: leave it verbatim.
        if item and row['name']==item['builtin_name'] and has_request_context():row['display_name']=translate(item['builtin_name'])
        alias=approved.get(str(row['id']))
        row['builtin_default']=False
        if alias and proven(row['id']) and row.get('parent_category_id')==alias['parent_category_id']:
            row['display_name']=alias['name'];row['builtin_default']=True
        row['default_retired']=row['id'] in retired
        if row['default_retired']:row['is_active']=False
        pref=prefs.get(row['id']) or {};row['icon_key']=pref.get('icon_key') or 'category'
        row['catalog_order']=pref.get('sort_order') if pref.get('sort_order') is not None else item['sort_order'] if item else 100000
    if not include_inactive:rows=[row for row in rows if row['is_active']]
    rows.sort(key=lambda row:(row['direction'],row['catalog_order'],row['name'].casefold(),row['id']))
    return rows
