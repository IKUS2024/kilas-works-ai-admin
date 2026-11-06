"""Inactive receipt payload contract; never changes Finance records or images.

The32k allowance is a forecast, NOT a provider-enforced input token limit.
Activation additionally requires review of the exact model's image accounting.
"""
import io
import json
from PIL import Image
from . import credit_wallet as wallet

CONTRACT='luna-high-2048-text12k-v1'
INPUT_FORECAST=32000
MAX_SIDE=2048
MAX_PIXELS=2048*2048
MAX_BYTES=5*1024*1024
MAX_CATEGORIES=64
MAX_TEXT_BYTES=12000


def bound(raw,mime,categories,system,response_format):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:
        raise wallet.WalletError('receipt_payload_outside_bounds')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if (image.width>MAX_SIDE or image.height>MAX_SIDE or image.width*image.height>MAX_PIXELS
                    or getattr(image,'n_frames',1)!=1
                    or {'JPEG':'image/jpeg','PNG':'image/png','WEBP':'image/webp'}.get(image.format)!=mime):raise ValueError()
            image.verify()
    except (OSError,ValueError,Image.DecompressionBombError):
        raise wallet.WalletError('receipt_payload_outside_bounds') from None
    if (not isinstance(categories,list) or len(categories)>MAX_CATEGORIES
            or any(not isinstance(value,str) or not 1<=len(value)<=160 for value in categories)):
        raise wallet.WalletError('receipt_categories_outside_bounds')
    text=json.dumps({'active_expense_category_names':categories},ensure_ascii=False)
    total=len(system.encode())+len(text.encode())+len(json.dumps(response_format,ensure_ascii=False).encode())+2048
    if total>MAX_TEXT_BYTES:raise wallet.WalletError('receipt_text_outside_bounds')
    return {'input_token_bound':INPUT_FORECAST,'input_accounting':CONTRACT,'receipt_bytes':len(raw)}
