"""Server environment rollout gate; independent of paid entitlements, default closed."""
import os
import re
from collections.abc import Mapping


def enabled_for_business(business_id: int, environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    if type(business_id) is not int or business_id <= 0:
        return False
    if env.get("KILAS_CORE_V2_ENABLED", "").strip().lower() not in ("1", "true", "yes", "on"):
        return False
    entries = env.get("KILAS_CORE_V2_TEST_BUSINESS_IDS", "").split(",")
    # A missing/malformed list fails closed, including wildcard and mixed valid/invalid IDs.
    if not all(re.fullmatch(r"[1-9][0-9]*", value.strip()) for value in entries):
        return False
    return str(business_id) in {value.strip() for value in entries}
