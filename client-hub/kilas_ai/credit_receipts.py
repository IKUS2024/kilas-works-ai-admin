"""Inactive receipt payload contract; never changes Finance records or images.

The physical envelope is followed by a provider token-count preflight.
No generation occurs when counting fails or exceeds the reviewed ceiling.
"""

import io
import json
from PIL import Image
from . import credit_wallet as wallet

CONTRACT = "luna-responses-count-32k-2048-v2"
INPUT_FORECAST = 32000
MAX_SIDE = 2048
MAX_PIXELS = 2048 * 2048
MAX_BYTES = 5 * 1024 * 1024
MAX_CATEGORIES = 64
MAX_TEXT_BYTES = 12000


def bound(raw, mime, categories, system, response_format):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise wallet.WalletError("receipt_payload_outside_bounds")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if (
                image.width > MAX_SIDE
                or image.height > MAX_SIDE
                or image.width * image.height > MAX_PIXELS
                or getattr(image, "n_frames", 1) != 1
                or {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(
                    image.format
                )
                != mime
            ):
                raise ValueError()
            image.verify()
    except (OSError, ValueError, Image.DecompressionBombError):
        raise wallet.WalletError("receipt_payload_outside_bounds") from None
    if (
        not isinstance(categories, list)
        or len(categories) > MAX_CATEGORIES
        or any(
            not isinstance(value, str) or not 1 <= len(value) <= 160
            for value in categories
        )
    ):
        raise wallet.WalletError("receipt_categories_outside_bounds")
    text = json.dumps({"active_expense_category_names": categories}, ensure_ascii=False)
    total = (
        len(system.encode())
        + len(text.encode())
        + len(json.dumps(response_format, ensure_ascii=False).encode())
        + 2048
    )
    if total > MAX_TEXT_BYTES:
        raise wallet.WalletError("receipt_text_outside_bounds")
    return {
        "input_token_bound": INPUT_FORECAST,
        "input_accounting": CONTRACT,
        "receipt_bytes": len(raw),
    }


def payload(raw, mime, categories, system, response_format):
    import base64

    bound(raw, mime, categories, system, response_format)
    schema = response_format["json_schema"]
    value = {
        "model": "gpt-6-luna",
        "instructions": system,
        "reasoning": {"effort": "low"},
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": "data:"
                        + mime
                        + ";base64,"
                        + base64.b64encode(raw).decode("ascii"),
                        "detail": "high",
                    },
                    {
                        "type": "input_text",
                        "text": json.dumps(
                            {"active_expense_category_names": categories},
                            ensure_ascii=False,
                        ),
                    },
                ],
            }
        ],
        "text": {"format": {"type": "json_schema", **schema}},
    }
    # One immutable serialization supplies BOTH count and generation. No history,
    # tools, mutable files or auto truncation can add uncounted input afterward.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def headers():
    import os

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise wallet.WalletError("receipt_counter_unavailable")
    return {
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        **(
            {"OpenAI-Project": os.environ["OPENAI_PROJECT_ID"]}
            if os.environ.get("OPENAI_PROJECT_ID")
            else {}
        ),
    }


def preflight(serialized):
    import requests
    from . import providers

    try:
        with requests.post(
            "https://api.openai.com/v1/responses/input_tokens",
            headers=headers(),
            json=json.loads(serialized),
            timeout=(5, 20),
        ) as response:
            response.raise_for_status()
            if len(response.content) > 65536:
                raise ValueError()
            counted = response.json()
        count = counted["input_tokens"]
        if (
            counted.get("object") != "response.input_tokens"
            or type(count) is not int
            or not 0 < count <= INPUT_FORECAST
        ):
            raise ValueError()
        from .credit_policy import fingerprint

        return {"payload_digest": fingerprint(json.loads(serialized)), "count": count}
    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
        wallet.WalletError,
    ):
        raise providers.ProviderQuotaError("receipt_preflight_denied") from None


def generate(serialized, verified):
    import requests
    from . import providers, credit_policy

    core = json.loads(serialized)
    if (
        verified["payload_digest"] != credit_policy.fingerprint(core)
        or type(verified["count"]) is not int
        or not 0 < verified["count"] <= INPUT_FORECAST
    ):
        raise providers.ProviderQuotaError("receipt_payload_changed")
    try:
        with requests.post(
            "https://api.openai.com/v1/responses",
            headers=headers(),
            json={**core, "max_output_tokens": 2048, "store": False, "stream": False},
            timeout=(10, 90),
        ) as response:
            if 400 <= response.status_code < 500:
                raise providers.ProviderQuotaError("receipt_provider_rejected")
            response.raise_for_status()
            if len(response.content) > 1000000:
                raise providers.ProviderError("receipt_response_unknown")
            data = response.json()
        used = data.get("usage") or {}
        # Supplier cost accounting is retained even when customer success is false.
        yield {
            "type": "usage",
            "input_tokens": used.get("input_tokens", 0),
            "output_tokens": used.get("output_tokens", 0),
        }
        if (
            type(used.get("input_tokens")) is not int
            or not 0 < used["input_tokens"] <= INPUT_FORECAST
            or type(used.get("output_tokens")) is not int
            or not 0 <= used["output_tokens"] <= 2048
        ):
            yield {"type": "refusal"}
            return
        if data.get("status") != "completed":
            yield {"type": "finish", "reason": "length"}
            return
        output = data.get("output", [])
        for message in output:
            if message.get("type") == "reasoning":
                continue
            if message.get("type") != "message" or message.get("role") != "assistant":
                yield {"type": "refusal"}
                return
            for part in message.get("content", []):
                if part.get("type") == "refusal":
                    yield {"type": "refusal"}
                    return
                if part.get("type") != "output_text" or not isinstance(
                    part.get("text"), str
                ):
                    yield {"type": "refusal"}
                    return
                yield {"type": "delta", "text": part["text"]}
        yield {"type": "finish", "reason": "stop"}
    except providers.ProviderError:
        raise
    except (requests.RequestException, ValueError, TypeError, KeyError):
        raise providers.ProviderError("receipt_response_unknown") from None
