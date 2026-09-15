"""Platform-only WhatsApp order intake and limited bearer capabilities over existing projects."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import urlsplit
import db
import catalog_service as catalog
import projects_repo
import payment_service
import quotation_service

# (key, label, choices); no customer price fields, credentials, or executable instructions.
FIELDS = {
 'name': ('Nama brand / project', ()), 'product': ('Produk / layanan yang dipromosikan', ()),
 'platform': ('Platform utama', ('Instagram','TikTok','Keduanya')),
 'location': ('Lokasi produksi (boleh belum ditentukan)', ()),
 'goal': ('Tujuan', ()), 'contact': ('Kontak / WhatsApp', ()),
 'event': ('Nama / jenis acara', ()), 'date': ('Tanggal / perkiraan waktu', ()),
 'objective': ('Tujuan iklan', ('WhatsApp','Leads','Sales','Traffic','Awareness')),
 'destination': ('Tujuan pengunjung iklan', ('WhatsApp','Website','Landing Page','Instagram')),
 'area': ('Area target', ()), 'ad_budget': ('Budget iklan per hari / bulan', ()),
 'quantity': ('Perkiraan jumlah produk / output', ()), 'features': ('Fitur / halaman utama', ()),
 'niche': ('Jenis / niche talent', ()), 'domain': ('Domain yang diinginkan (ketersediaan belum dijamin)', ()),
 'extension': ('Ekstensi domain', ('.com','.id')), 'alternatives': ('Alternatif domain', ()),
 'associated_project': ('Website / project terkait (opsional)', ()),
 'reference': ('Link referensi', ()), 'maps': ('Link Maps', ()), 'audience': ('Target audiens', ()),
 'talent': ('Butuh talent?', ('Ya','Tidak','Belum tahu')),
 'notes': ('Catatan / rundown / kebutuhan khusus', ()),
 'system_needs': ('Kebutuhan login, dashboard/admin, pembayaran, integrasi/API', ()),
 'final_photos': ('Jumlah foto final diinginkan', ()),
 'props': ('Kebutuhan background, properti, atau model', ()),
 'duration': ('Perkiraan durasi video', ()), 'usage': ('Penggunaan hasil foto', ()),
 'assets': ('Aset tersedia: logo, foto, teks, creative', ()),
 'domain_status': ('Sudah memiliki domain?', ('Ya','Tidak','Belum tahu')),
 'social': ('Instagram / link sosial', ()),
 'access': ('Page / Instagram / Business Manager / Ad Account tersedia? Pernah beriklan?', ()),
 'voice': ('Kebutuhan voice-over', ()), 'timing': ('Jam mulai / tanggal pilihan', ()),
 'talent_details': ('Preferensi gender/usia/lokasi, deliverables dan budget talent', ()),
}
OPTIONAL = ('reference','maps','date','goal','audience','talent','notes','duration','usage','assets','domain_status','social','access','voice','timing','talent_details')

def fields(item):
    key, cat = item['catalog_key'], item['category']
    if key.startswith('website_domain_'): required=('domain','extension','alternatives')
    elif cat=='CONTENT': required=('name','product','platform','location')
    elif cat=='EVENT': required=('event','date','location','contact')
    elif cat=='ADS': required=('product','objective','destination','area','ad_budget')
    elif cat=='PHOTO': required=('product','quantity','location')
    elif cat=='VIDEO': required=('goal','quantity','location')
    elif cat=='TALENT': required=('name','niche','date')
    elif cat in ('WEBSITE','APPLICATION'):
        required=('name','goal','features') if item['pricing_mode']=='CUSTOM_QUOTE' else ('name','goal','contact')
    else: required=('name','goal')
    options={
        'CONTENT':('date','goal','audience','reference','talent','maps','notes'),
        'EVENT':('maps','timing','reference','notes'),
        'ADS':('reference','contact','audience','access','assets','date','notes'),
        'PHOTO':('final_photos','usage','date','reference','props','maps','notes'),
        'VIDEO':('duration','platform','date','reference','talent','voice','maps','notes'),
        'TALENT':('talent_details','location','platform','audience','reference','notes'),
        'WEBSITE':('features','reference','domain_status','domain','assets','social','contact','notes'),
        'APPLICATION':('system_needs','contact','reference','date','domain_status','assets','notes'),
    }
    optional=tuple(k for k in options.get(cat,('notes',)) if k not in required)
    if key.startswith('website_domain_'): optional=('associated_project','notes')
    return required, optional

def secret():
    value=os.environ.get('INTERNAL_SERVICE_SECRET','')
    if len(value)<32: raise ValueError('checkout_not_configured')
    return value.encode()

def base_url():
    value=os.environ.get('PUBLIC_APP_BASE_URL','').rstrip('/')
    parts=urlsplit(value)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('checkout_not_configured')
    return value

def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def sender_hash(phone): return hmac.new(secret(), phone.encode(), hashlib.sha256).hexdigest()
def raw_token(sid): return sid+'.'+hmac.new(secret(),sid.encode(),hashlib.sha256).hexdigest()
def link(row): return base_url()+'/wa-checkout#'+raw_token(row['session_id'])
def session_for_project(project_id): return db.query_one('SELECT * FROM wa_checkout_sessions WHERE project_id=?',(project_id,))
def by_hash(token_hash):
    row=db.query_one('SELECT * FROM wa_checkout_sessions WHERE token_hash=?',(token_hash,))
    return row if row and row['expires_at']>int(time.time()) else None

def parse_fields(text):
    """Only explicit labelled facts are harvested; never infer facts from assistant messages."""
    aliases={'brand':'name','nama':'name','produk':'product','platform':'platform','lokasi':'location','tujuan':'goal','kontak':'contact','tanggal':'date','acara':'event','fitur':'features','jumlah':'quantity','budget iklan':'ad_budget','area':'area','domain':'domain'}
    result={}
    for segment in re.split(r'[;\n]',text[:5000]):
        match=re.fullmatch(r'\s*([^:]{1,30}):\s*(.{1,1000})\s*',segment)
        if match and match[1].lower() in aliases: result[aliases[match[1].lower()]]=match[2].strip()
    for key,pattern in {
        'name': r'(?:nama brand|brand saya|nama bisnis)(?: saya)?(?: adalah)?\s+([^.;\n]{1,100})',
        'product': r'(?:produk saya|produk yang dipromosikan)(?: adalah)?\s+([^.;\n]{1,150})',
        'location': r'(?:lokasinya|lokasi produksi)(?: di)?\s+([^.;\n]{1,150})',
    }.items():
        match=re.search(pattern,text[:5000],re.I)
        if match:result.setdefault(key,match[1].strip())
    if re.search(r'\b(?:platform|pakai|untuk|di)\s+instagram\b',text,re.I):result.setdefault('platform','Instagram')
    if re.search(r'\b(?:platform|pakai|untuk|di)\s+tiktok\b',text,re.I):result['platform']='Keduanya' if result.get('platform')=='Instagram' else 'TikTok'
    return result

def clean(values,item):
    required,optional=fields(item)
    out={}
    for key in required+optional:
        value=values.get(key,'')
        if not isinstance(value,str) or len(value)>1500: raise ValueError('brief_invalid')
        value=value.strip()
        choices=FIELDS[key][1]
        if value and choices:
            value=next((c for c in choices if c.lower()==value.lower()),'')
        if value: out[key]=value
    if sum(map(len,out.values()))>16000: raise ValueError('brief_too_large')
    return out

def missing(item,brief):return [key for key in fields(item)[0] if not brief.get(key)]

def purchase_item(text):
    q=text.lower()
    if not re.search(r'\b(mau|beli|pesan|ambil|order|lanjut|checkout)\b',q): return None
    matches=[]
    for item in catalog.list_active_catalog():
        name=catalog.public_name(item).lower()
        alias={'custom_photo':'custom photo|foto custom|custom foto','custom_video':'custom video|video custom','custom_website_app':'custom website|custom app|aplikasi custom','talent_management':'talent management|jasa talent','ads_management':'meta ads management|ads management','ads_setup_only':'meta ads setup|ads setup','website_domain_com_hosting':r'hosting.*\.com|domain.*\.com','website_domain_id_hosting':r'hosting.*\.id|domain.*\.id'}.get(item['catalog_key'])
        if name in q or (alias and re.search(alias,q)): matches.append(item)
    return matches[0] if len(matches)==1 else None

def intake(phone,text,history=(),tenant=False,customer_name=None):
    if tenant: return None
    if not re.fullmatch(r'\+?\d{8,16}',phone or ''): return None
    item=purchase_item(text)
    if item and item['category']=='AI_ADMIN':
        import repo
        return 'Kilas Brain memakai Setup Awal bisnis. Pilih/daftarkan bisnis di '+repo.get_official_links()['app']
    # Configuration checked only for an actual purchase or an existing intake.
    try: ph=sender_hash(phone)
    except ValueError:
        return 'Link order belum tersedia. Tim perlu menyelesaikan konfigurasi checkout.' if item else None
    active=db.query_one('SELECT s.* FROM wa_checkout_sessions s JOIN wa_checkout_customers c ON c.active_session_id=s.session_id WHERE c.phone_hash=?',(ph,))
    if not item:
        if active and re.search(r'\b(link(?:nya)?|bayar|order|penawaran|lanjut|checkout)\b',text.lower()):
            return 'Cek order/penawaran kakak di sini: '+link(active) if by_hash(active['token_hash']) else 'Link order sudah kedaluwarsa. Minta tim memperbarui akses order yang sama.'
        if not active or not active['pending_field']:
            return None
        if '?' in text or re.search(r'\b(berapa|brp|dapet|termasuk|mahal|diskon)\b',text.lower()):
            return None  # Keep draft; let existing factual/sales handling answer the question.
    base_url()
    with db.commerce_transaction(ph):
        if item:
            if item['category'] in ('BUNDLE','AI_ADMIN'): return None
            row=db.query_one('SELECT * FROM wa_checkout_sessions WHERE phone_hash=? AND catalog_key=?',(ph,item['catalog_key']))
            if not row:
                if item['pricing_mode']=='FIXED_PRICE': pid=projects_repo.create_fixed_price_project(None,item,None)
                else: pid=projects_repo.create_custom_project(None,projects_repo._project_type_for_category(item['category']),item['name'],{},None,None,None,item['catalog_key'])
                db.execute("UPDATE projects SET status='REQUESTED' WHERE id=?",(pid,))
                sid=secrets.token_urlsafe(32)
                db.execute('INSERT INTO wa_checkout_sessions(session_id,phone_hash,customer_phone,catalog_key,project_id,token_hash,expires_at) VALUES(?,?,?,?,?,?,?)',(sid,ph,phone,item['catalog_key'],pid,digest(raw_token(sid)),int(time.time())+7*86400))
                row=session_for_project(pid)
        else:
            row=db.query_one('SELECT * FROM wa_checkout_sessions WHERE session_id=?',(active['session_id'],))
            item=catalog.get_catalog_item(row['catalog_key'])
        if customer_name and isinstance(customer_name,str):
            db.execute('UPDATE wa_checkout_sessions SET customer_name=? WHERE session_id=?',(customer_name[:120],row['session_id']))
        db.execute('UPDATE wa_checkout_customers SET active_session_id=? WHERE phone_hash=?',(row['session_id'],ph))
        if not item['is_active'] or item['category'] in ('BUNDLE','AI_ADMIN'):return 'Layanan ini tidak tersedia untuk checkout WhatsApp.'
        if row['expires_at']<=int(time.time()):return 'Link order sudah kedaluwarsa. Tim perlu memperbarui akses order yang sama.'
        project=projects_repo.get_project(row['project_id'])
        if project['status']!='REQUESTED': return 'Order ini sudah diproses. Cek statusnya di sini: '+link(row)
        brief=project.get('requirements') or {}
        incoming=digest(text)
        if row['last_message_hash']!=incoming:
            for turn in history[-8:]:
                if turn.get('role')=='user' and isinstance(turn.get('content'),str):
                    for k,v in parse_fields(turn['content']).items():brief.setdefault(k,v)
            supplied=parse_fields(text)
            if not supplied and not purchase_item(text) and row['pending_field']:
                # A free-text answer is accepted only while awaiting a field. Commands/questions are not answers.
                if '?' not in text and not re.search(r'\b(batal|kirim|berapa|link|bayar)\b',text.lower()):supplied[row['pending_field']]=text[:1500]
            brief.update(supplied);brief=clean(brief,item)
            db.execute('UPDATE projects SET requirements_json=? WHERE id=?',(json.dumps(brief,ensure_ascii=False),project['id']))
            db.execute('UPDATE wa_checkout_sessions SET last_message_hash=? WHERE session_id=?',(incoming,row['session_id']))
        remaining=missing(item,brief)
        # Ask at most three essentials on WhatsApp; all remaining fields live on the linked form.
        first=fields(item)[0][:3]
        pending=next((k for k in first if k in remaining),None)
        db.execute('UPDATE wa_checkout_sessions SET pending_field=? WHERE session_id=?',(pending,row['session_id']))
        if pending:
            summary=catalog.public_name(item)+' '+catalog.display_price(item)+'. ' if purchase_item(text) else ''
            return 'Siap kak. '+summary+FIELDS[pending][0]+'?'
        return 'Brief awal sudah disiapkan. Cek/lengkapi lalu lanjut '+('pembayaran' if item['pricing_mode']=='FIXED_PRICE' else 'permintaan penawaran')+' di sini: '+link(row)

def approve_current_quote(row,quotation_id):
    latest=db.query_one('SELECT * FROM quotations WHERE project_id=? ORDER BY id DESC LIMIT 1',(row['project_id'],))
    if not latest or latest['id']!=quotation_id:raise ValueError('quote_changed')
    if latest.get('expires_at'):
        from datetime import datetime, timezone
        expiry=latest['expires_at']
        if isinstance(expiry,str):expiry=datetime.fromisoformat(expiry.replace('Z','+00:00'))
        if expiry.tzinfo is None:expiry=expiry.replace(tzinfo=timezone.utc)
        if expiry<=datetime.now(timezone.utc):raise ValueError('quote_expired')
    if latest['status']!='APPROVED': quotation_service.approve_quotation(latest['id'],None,None)
    return payment_service.checkout(row['project_id'],None,None)


def admin_quote(project_id,business_id,**kwargs):
    row=session_for_project(project_id)
    if not row:return quotation_service.create_quotation(project_id,business_id,**kwargs)
    with db.commerce_transaction(row['phone_hash']):
        project=projects_repo.get_project(project_id)
        if project['status'] not in ('WAITING_FOR_QUOTE','REQUESTED'):
            existing=quotation_service.get_latest_quotation_for_project(project_id)
            if existing:return existing['id']
            raise ValueError('quote_not_ready')
        if project['status']=='REQUESTED':raise ValueError('brief_incomplete')
        return quotation_service.create_quotation(project_id,business_id,**kwargs)


def renew(project_id):
    row=session_for_project(project_id)
    if not row:raise ValueError('order_missing')
    with db.commerce_transaction(row['phone_hash']):
        sid=secrets.token_urlsafe(32)
        db.execute('UPDATE wa_checkout_sessions SET session_id=?,token_hash=?,expires_at=? WHERE project_id=?',(sid,digest(raw_token(sid)),int(time.time())+7*86400,project_id))
        db.execute('UPDATE wa_checkout_customers SET active_session_id=? WHERE phone_hash=?',(sid,row['phone_hash']))
    return session_for_project(project_id)
