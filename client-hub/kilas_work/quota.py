"""One-time trial and variable-cost Work quota, isolated from Kilas AI."""
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import db
from . import sql

PLANS = {"PLUS": 29000, "PRO": 69000, "MAX": 129000}
TOPUPS = {"MINI": 29000, "EXTRA": 59000, "POWER": 99000}
FORECAST_MICRO = {"CHAT_LUNA": 5000, "CHAT_SOL": 60000, "WEB": 80000,
                  "IMAGE": 80000, "PDF": 30000, "CODE": 50000, "BROWSER": 80000}
MODEL_RATES = {"gpt-6-luna": (Decimal("0.10"), Decimal("0.50")),
               "gpt-6-sol": (Decimal("2"), Decimal("10"))}


class QuotaError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc)


def utc(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _budget(amount_idr):
    fx = Decimal(os.environ.get("KILAS_WORK_USD_IDR", "17000"))
    ratio = Decimal(os.environ.get("KILAS_WORK_COST_RATIO", "0.30"))
    if fx <= 0 or not Decimal("0.1") <= ratio <= Decimal("0.35"):
        raise QuotaError("Konfigurasi Kuota Work tidak tersedia.")
    return int(Decimal(amount_idr) / fx * ratio * 1000000)

