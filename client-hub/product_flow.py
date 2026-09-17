"""Allowlisted continuation metadata only; no arbitrary redirects or implicit purchases."""
import re
import db
import repo
from pricing_config import CATALOG_ITEMS, RETIRED_BRAIN_KEYS

KEYS={'finance','brain'} | {x['key'] for x in CATALOG_ITEMS if x['category'] not in ('AI_ADMIN','BUNDLE') and x['key'] not in RETIRED_BRAIN_KEYS}


def intent(value):
    return value if isinstance(value,str) and value in KEYS else None


def create_business(user_id,name,identity):
    if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{32}',identity):raise ValueError('invalid_setup')
    if not isinstance(name,str) or not 1<=len(name.strip())<=160 or '\x00' in name:raise ValueError('invalid_name')
    with db.app_purchase_transaction(None,user_id):
        old=db.query_one('SELECT business_id FROM product_business_setups WHERE user_id=? AND intent_key=?',(user_id,identity))
        if old:return old['business_id']
        business_id=repo.create_business(user_id,name.strip(),package='NONE')
        db.execute('INSERT INTO product_business_setups (user_id,intent_key,business_id) VALUES (?,?,?)',(user_id,identity,business_id))
        return business_id
