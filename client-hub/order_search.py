"""Live web discovery for Kilas Order.

Uses Claude web search to discover purchasable product listings, then validates
every stored source URL against URLs actually returned by the search tool.
Customer-facing pages never receive these source URLs.
"""
import json
import os
import re
import logging
from urllib.parse import urlparse, urlunparse

import requests
import ai_onboarding
import ai_usage
import order_service

MAX_CANDIDATES = 12
log = logging.getLogger(__name__)

_SYSTEM = """Kamu adalah procurement research engine internal Kilas Order.
Cari listing BARANG FISIK yang benar-benar tampak bisa dibeli sekarang berdasarkan kebutuhan customer.

ATURAN:
1. Wajib gunakan web search. Jangan menjawab dari ingatan.
2. Prioritaskan retailer resmi, official store, toko spesialis bereputasi, dan marketplace dengan seller yang punya sinyal reputasi jelas.
3. Jangan memasukkan artikel review, forum, halaman kategori umum, berita, atau halaman yang bukan listing/halaman produk yang bisa dibeli.
4. Jangan memasukkan produk yang jelas salah model/varian.
5. Jangan menganggap harga termurah sebagai terbaik. Harga yang terlalu murah dibanding kandidat lain harus diberi risk flag.
6. Kalau kondisi customer fleksibel, kandidat baru dan second boleh, tetapi condition harus dijelaskan.
7. Jangan menyatakan seller 100% aman. Nilai hanya dari sinyal yang terlihat di sumber.
8. source_url HARUS URL sumber yang benar-benar kamu buka/temukan lewat web search pada turn ini. Jangan membuat URL.
9. Maksimal 12 kandidat. Lebih baik 3-8 kandidat kuat daripada banyak hasil lemah.
10. Jangan menghitung markup Kilas, pajak, fee, atau harga jual customer. Ini hanya discovery harga sumber.
11. Tolak kategori berbahaya/terlarang: senjata, amunisi, bahan peledak, narkotika, obat resep, nikotin, alkohol, spyware, barang curian/palsu, dan produk ilegal.
12. Final response harus SATU JSON object valid, tanpa markdown atau kalimat lain.

Schema:
{
  "candidates": [
    {
      "product_name": "string",
      "price_text": "string",
      "currency": "string",
      "condition": "string",
      "seller_name": "string",
      "source_url": "https://...",
      "availability": "string",
      "trust_score": 0,
      "trust_level": "HIGH|MEDIUM|REVIEW",
      "trust_reason": "string",
      "match_reason": "string",
      "risk_flags": ["string"],
      "evidence_text": "string"
    }
  ]
}

trust_score adalah kualitas sinyal pembelian internal, bukan jaminan. HIGH hanya jika seller/retailer dan listing punya sinyal kuat. REVIEW jika data seller, stok, harga, atau kondisi kurang jelas.
"""


def _clean(value, maximum=500):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:maximum]


def _url_key(value):
    try:
        parsed = urlparse(value)
    except Exception:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    host = parsed.netloc.lower().split("@")[-1]
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    return urlunparse(("https", host, path, "", "", ""))


def _domain(value):
    try:
        host = urlparse(value).netloc.lower().split("@")[-1].split(":")[0]
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _parse_json_text(text):
    raw = (text or "").strip()
    fence = chr(96) * 3
    if raw.startswith(fence):
        match = re.fullmatch(re.escape(fence) + r"(?:json)?\s*\n(.*?)\n" + re.escape(fence), raw, re.DOTALL)
        if not match:
            raise ValueError("invalid_fence")
        raw = match.group(1).strip()
    return json.loads(raw)


def _search_urls(content):
    urls = {}
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "web_search_tool_result":
            results = block.get("content")
            if isinstance(results, list):
                for result in results:
                    if isinstance(result, dict) and result.get("type") == "web_search_result":
                        url = result.get("url")
                        key = _url_key(url)
                        if key:
                            urls[key] = {
                                "url": url,
                                "title": _clean(result.get("title"), 300),
                            }
        if block.get("type") == "text":
            for citation in block.get("citations") or []:
                if isinstance(citation, dict) and citation.get("type") == "web_search_result_location":
                    url = citation.get("url")
                    key = _url_key(url)
                    if key:
                        urls.setdefault(key, {
                            "url": url,
                            "title": _clean(citation.get("title"), 300),
                        })
    return urls


def _final_json(content):
    for block in reversed(content or []):
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text")
        if not isinstance(text, str):
            continue
        try:
            value = _parse_json_text(text)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("candidates"), list):
            return value
    raise ValueError("json_not_found")


def _validate_candidates(value, observed):
    candidates = []
    seen = set()
    for raw in value.get("candidates", [])[:MAX_CANDIDATES]:
        if not isinstance(raw, dict):
            continue
        url = _clean(raw.get("source_url"), 2000)
        key = _url_key(url)
        if not key or key not in observed or key in seen:
            continue
        seen.add(key)
        actual = observed[key]
        trust_level = _clean(raw.get("trust_level"), 20).upper()
        if trust_level not in ("HIGH", "MEDIUM", "REVIEW"):
            trust_level = "REVIEW"
        try:
            trust_score = int(raw.get("trust_score") or 0)
        except (TypeError, ValueError):
            trust_score = 0
        trust_score = max(0, min(trust_score, 100))
        flags = raw.get("risk_flags")
        if not isinstance(flags, list):
            flags = []
        flags = [_clean(flag, 180) for flag in flags[:8] if _clean(flag, 180)]
        product_name = _clean(raw.get("product_name"), 260) or actual.get("title") or "Produk"
        candidates.append({
            "product_name": product_name,
            "price_text": _clean(raw.get("price_text"), 120),
            "currency": _clean(raw.get("currency"), 12).upper(),
            "condition": _clean(raw.get("condition"), 80),
            "seller_name": _clean(raw.get("seller_name"), 180),
            "source_url": actual["url"],
            "source_domain": _domain(actual["url"]),
            "source_title": actual.get("title") or product_name,
            "availability": _clean(raw.get("availability"), 180),
            "trust_score": trust_score,
            "trust_level": trust_level,
            "trust_reason": _clean(raw.get("trust_reason"), 500),
            "match_reason": _clean(raw.get("match_reason"), 500),
            "risk_flags": flags,
            "evidence_text": _clean(raw.get("evidence_text"), 500),
        })
    return candidates


def _request_prompt(item):
    summary = item.get("ai_summary") or {}
    location = "Lokasi belum dipilih."
    if item.get("location_source") == "manual" and item.get("location_label"):
        location = "Area customer: " + str(item["location_label"])
    elif item.get("location_source") == "gps":
        if item.get("latitude") is not None and item.get("longitude") is not None:
            location = "Koordinat perkiraan customer: %s, %s" % (item["latitude"], item["longitude"])
        else:
            location = "GPS customer aktif, tetapi nama area tidak tersedia."
    payload = {
        "request_code": item.get("request_code"),
        "permintaan_asli": item.get("request_text"),
        "ringkasan_ai": summary,
        "lokasi": location,
        "instruksi": "Cari listing yang benar-benar relevan dan bisa dibeli. Gunakan beberapa query/sumber bila perlu.",
    }
    return json.dumps(payload, ensure_ascii=False)


def search_request(item):
    """Search and persist internal candidates. Returns (candidates, error)."""
    if not item or type(item.get("id")) is not int:
        return [], "invalid_request"
    if not ai_onboarding.ANTHROPIC_API_KEY:
        return [], "not_configured"

    order_service.update_request_status(item["id"], "SEARCHING")
    model = os.environ.get("KILAS_ORDER_SEARCH_MODEL") or ai_onboarding.CLIENT_HUB_MODEL
    try:
        response = requests.post(
            ai_onboarding.ANTHROPIC_API_URL,
            headers={
                "x-api-key": ai_onboarding.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2200,
                "temperature": 0,
                "system": _SYSTEM,
                "messages": [{"role": "user", "content": _request_prompt(item)}],
                "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
            },
            timeout=(5, 45),
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            safe_error_type = "unknown"
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    error_obj = payload.get("error")
                    if isinstance(error_obj, dict):
                        candidate = error_obj.get("type")
                        if isinstance(candidate, str) and re.fullmatch(r"[a-z0-9_]{1,80}", candidate):
                            safe_error_type = candidate
            except (ValueError, TypeError):
                pass
            log.warning("[KILAS_ORDER_SEARCH] provider_http status=%s type=%s", response.status_code, safe_error_type)
            order_service.update_request_status(item["id"], "ISSUE")
            if response.status_code == 400:
                return [], "provider_invalid_request"
            if response.status_code in (401, 403):
                return [], "provider_access_denied"
            if response.status_code == 429:
                return [], "provider_rate_limited"
            return [], "provider_http_" + str(response.status_code)
        result = response.json()
        ai_usage.record(model, result, tenant_id=None, context="platform_customer", classification="complex")
    except requests.RequestException as exc:
        log.warning("[KILAS_ORDER_SEARCH] network_failure kind=%s", type(exc).__name__)
        order_service.update_request_status(item["id"], "ISSUE")
        return [], "network_failure"
    except (ValueError, TypeError):
        order_service.update_request_status(item["id"], "ISSUE")
        return [], "invalid_response"

    content = result.get("content") if isinstance(result, dict) else None
    observed = _search_urls(content)
    if not observed:
        log.warning("[KILAS_ORDER_SEARCH] no_search_results")
        order_service.update_request_status(item["id"], "ISSUE")
        return [], "no_search_results"
    try:
        value = _final_json(content)
        candidates = _validate_candidates(value, observed)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        log.warning("[KILAS_ORDER_SEARCH] invalid_schema kind=%s", type(exc).__name__)
        order_service.update_request_status(item["id"], "ISSUE")
        return [], "invalid_schema"
    if not candidates:
        log.warning("[KILAS_ORDER_SEARCH] no_valid_candidates observed=%s", len(observed))
        order_service.update_request_status(item["id"], "ISSUE")
        return [], "no_valid_candidates"

    order_service.replace_candidates(item["id"], candidates)
    order_service.update_request_status(item["id"], "RESULTS_READY")
    return candidates, None
