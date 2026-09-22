"""Customer account profile metadata and profile-photo links.

This module is intentionally separate from Finance ledger/accounting. Personal invoice contact
defaults are account-owned metadata; business invoice branch defaults remain in
finance_invoice_settings. Profile photos reuse the existing platform_assets blob store and only
store a small owner->asset pointer here.
"""
import db
import repo
import platform_assets_service as assets

OWNER_KINDS = ("USER", "BUSINESS")
ASSET_KIND = {
    "USER": "USER_PROFILE_PHOTO",
    "BUSINESS": "BUSINESS_PROFILE_PHOTO",
}

PERSONAL_FIELDS = (
    "phone", "address", "tax_id", "website",
    "payment_method", "payment_bank_name", "payment_account_number",
    "payment_account_name", "payment_instructions",
)


def _owner_type(value):
    value = (value or "").strip().upper()
    if value not in OWNER_KINDS:
        raise ValueError("invalid_owner_type")
    return value


def _text(value, limit):
    value = (value or "").strip()
    if len(value) > limit or "\x00" in value:
        raise ValueError("invalid_profile_text")
    return value


def get_personal_profile(user_id):
    row = db.query_one(
        "SELECT * FROM account_personal_profiles WHERE user_id=?",
        (user_id,),
    )
    if row:
        return dict(row)
    return {
        "user_id": user_id,
        "phone": "", "address": "", "tax_id": "", "website": "",
        "payment_method": "", "payment_bank_name": "",
        "payment_account_number": "", "payment_account_name": "",
        "payment_instructions": "", "updated_at": None,
    }


def has_personal_profile(user_id):
    return bool(db.query_one(
        "SELECT 1 FROM account_personal_profiles WHERE user_id=?",
        (user_id,),
    ))


def save_personal_profile(user_id, values):
    cleaned = {
        "phone": _text(values.get("phone"), 254),
        "address": _text(values.get("address"), 2000),
        "tax_id": _text(values.get("tax_id"), 254),
        "website": _text(values.get("website"), 254),
        "payment_method": _text(values.get("payment_method"), 254),
        "payment_bank_name": _text(values.get("payment_bank_name"), 254),
        "payment_account_number": _text(values.get("payment_account_number"), 254),
        "payment_account_name": _text(values.get("payment_account_name"), 254),
        "payment_instructions": _text(values.get("payment_instructions"), 2000),
    }
    now = repo._now()
    db.execute(
        """INSERT INTO account_personal_profiles
           (user_id,phone,address,tax_id,website,payment_method,payment_bank_name,
            payment_account_number,payment_account_name,payment_instructions,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
             phone=excluded.phone,address=excluded.address,tax_id=excluded.tax_id,
             website=excluded.website,payment_method=excluded.payment_method,
             payment_bank_name=excluded.payment_bank_name,
             payment_account_number=excluded.payment_account_number,
             payment_account_name=excluded.payment_account_name,
             payment_instructions=excluded.payment_instructions,
             updated_at=excluded.updated_at""",
        (
            user_id, cleaned["phone"], cleaned["address"], cleaned["tax_id"], cleaned["website"],
            cleaned["payment_method"], cleaned["payment_bank_name"],
            cleaned["payment_account_number"], cleaned["payment_account_name"],
            cleaned["payment_instructions"], now,
        ),
    )
    return dict(cleaned, user_id=user_id, updated_at=now)


def profile_asset_meta(owner_type, owner_id):
    owner_type = _owner_type(owner_type)
    return db.query_one(
        """SELECT p.id,p.kind,p.original_filename,p.mime_type,p.size_bytes,p.created_at
           FROM account_profile_assets l
           JOIN platform_assets p ON p.id=l.asset_id
           WHERE l.owner_type=? AND l.owner_id=? AND p.kind=?""",
        (owner_type, owner_id, ASSET_KIND[owner_type]),
    )


def profile_asset(owner_type, owner_id):
    owner_type = _owner_type(owner_type)
    return db.query_one(
        """SELECT p.*
           FROM account_profile_assets l
           JOIN platform_assets p ON p.id=l.asset_id
           WHERE l.owner_type=? AND l.owner_id=? AND p.kind=?""",
        (owner_type, owner_id, ASSET_KIND[owner_type]),
    )


def save_profile_photo(owner_type, owner_id, filename, mime_type, content, uploaded_by_user_id):
    owner_type = _owner_type(owner_type)
    asset_id = assets.save_asset(
        ASSET_KIND[owner_type], filename, mime_type, len(content), content, uploaded_by_user_id,
    )
    db.execute(
        """INSERT INTO account_profile_assets(owner_type,owner_id,asset_id,updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT(owner_type,owner_id) DO UPDATE SET
             asset_id=excluded.asset_id,updated_at=excluded.updated_at""",
        (owner_type, owner_id, asset_id, repo._now()),
    )
    return asset_id
