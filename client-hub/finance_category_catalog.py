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

def mark(business_id,scope,key,ident,position,name):
    db.execute('INSERT INTO finance_catalog_items VALUES (?,?,?,?,?,?) ON CONFLICT(business_id,scope_key,canonical_key) DO NOTHING',(business_id,scope,key,ident,position,name))


def sync_personal(business_id,actor):
    import finance_service as f
    scope=f._category_scope(business_id,actor)
    if scope['workspace_type']!='PERSONAL':return
    if db.query_one('SELECT 1 FROM finance_catalog_items WHERE business_id=? AND scope_key=? AND canonical_key=?',(business_id,scope['scope_key'],'housing')):return
    # Existing rows have no reliable seed-vs-custom provenance. Never rename,
    # deactivate, reparent or merge them by a matching name. Add the requested
    # catalog with private stable IDs, leaving those rows available for history.
    def node(key,name,order,parent=None):
        rows=db.query_all('SELECT c.id,s.display_name,h.parent_category_id FROM finance_category_workspace_settings s JOIN finance_categories c ON c.id=s.category_id AND c.business_id=s.business_id LEFT JOIN finance_category_hierarchy h ON h.business_id=c.business_id AND h.child_category_id=c.id WHERE s.business_id=? AND s.scope_key=? AND s.is_active=TRUE AND c.direction=? AND lower(s.display_name)=lower(?)',(business_id,scope['scope_key'],'EXPENSE',name))
        matching=[v for v in rows if v['parent_category_id']==parent]
        if len(matching)==1:
            # Reuse an exact existing choice without declaring its customer name
            # system-owned, relabeling it, or moving its historical relationships.
            ident=matching[0]['id'];label='__customer_owned__'
        else:
            ident=f._create_category(business_id,'EXPENSE','__kilas_'+scope['scope_key']+'_'+key,actor)
            f._ensure_category_setting(business_id,ident,name,actor)
            if parent is not None:f._link_category_parent(business_id,ident,parent)
            label=name
        mark(business_id,scope['scope_key'],key,ident,order,label)
        return ident
    for order,(key,name,children) in enumerate(PERSONAL):
        ident=node(key,name,order*100)
        for index,child in enumerate(children):node(key+'.'+str(index),child,order*100+index+1,ident)


def decorate(business_id,scope,rows):
    metadata={v['category_id']:v for v in db.query_all('SELECT * FROM finance_catalog_items WHERE business_id=? AND scope_key=?',(business_id,scope['scope_key']))}
    from flask import has_request_context
    from ui_i18n import translate
    for row in rows:
        item=metadata.get(row['id']);row['display_name']=row['name']
        # Renaming a built-in makes that name customer-owned: leave it verbatim.
        if item and row['name']==item['builtin_name'] and has_request_context():row['display_name']=translate(item['builtin_name'])
        row['catalog_order']=item['sort_order'] if item else 100000
    rows.sort(key=lambda row:(row['direction'],row['catalog_order'],row['name'].casefold(),row['id']))
    return rows
