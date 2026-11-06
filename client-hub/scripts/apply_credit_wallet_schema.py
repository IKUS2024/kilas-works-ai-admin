"""Explicit additive migration. Requires separate activation-checkpoint approval."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if os.environ.get('KILAS_CREDIT_SCHEMA_APPLY')!='customer-credit-v1':
    raise SystemExit('Refusing wallet migration without explicit reviewed release marker')
from kilas_ai.credit_wallet_schema import apply_release
print('CREDIT_SCHEMA applied='+str(apply_release()).lower()+' legacy_conversion=false')
