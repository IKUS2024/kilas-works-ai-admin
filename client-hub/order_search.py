"""Live web discovery for Kilas Order.

Uses Claude web search to discover purchasable product listings, then validates
every stored source URL against URLs actually returned by the search tool.
Customer-facing pages never receive these source URLs.
"""
import json
import os
import re
import logging
import threading
from urllib.parse import urlparse, urlunparse

import requests
import ai_onboarding
import ai_usage
import order_service

MAX_CANDIDATES = 12
log = logging.getLogger(__name__)

_ACTIVE_SEARCHES = set()
_ACTIVE_LOCK = threading.Lock()
_LAST_ERRORS = {}

_SYSTEM = """Kamu adalah procurement research engine internal Kilas Order.
Cari listing BARANG FISIK yang benar-benar tampak bisa dibeli sekarang berdasarkan kebutuhan customer.

ATURAN:
1. Wajib gunakan web search. Jangan menjawab dari ingatan.
2. Prioritaskan retailer resmi, official store, toko spesialis bereputasi, dan marketplace dengan seller yang punya sinyal reputasi jelas.
3. Fokus pada halaman produk/listing yang bisa dibeli, bukan artikel review, forum, berita, atau halaman kategori umum.
4. Jangan memasukkan produk yang jelas salah model/varian.
5. Jangan menganggap harga termurah sebagai terbaik. Tandai secara naratif jika harga terlihat tidak wajar.
6. Kalau kondisi customer fleksibel, kandidat baru dan second boleh.
7. Jangan menyatakan seller 100% aman.
8. Tolak kategori berbahaya/terlarang: senjata, amunisi, bahan peledak, narkotika, obat resep, nikotin, alkohol, spyware, barang curian/palsu, dan produk ilegal.
9. Cari 3-8 kandidat kuat bila memungkinkan. Maksimal 2 kali web search.
10. Jawaban akhir cukup ringkas: sebut kandidat, harga/kondisi/availability/seller bila terlihat, dan alasan relevan. Selalu gunakan citation dari hasil web search. Jangan keluarkan JSON.
"""

_STRUCTURE_SYSTEM = """Kamu menyusun hasil riset web Kilas Order menjadi data kandidat internal.
Gunakan HANYA source yang diberikan dalam payload. Jangan membuat URL, seller, harga, availability, atau fakta lain yang tidak terlihat di payload.

ATURAN:
1. Hanya pilih halaman yang tampak sebagai listing/halaman produk yang bisa dibeli.
2. Abaikan artikel, forum, berita, halaman kategori umum, dan hasil yang salah produk.
3. Jika harga/seller/kondisi/availability tidak cukup jelas, kosongkan field tersebut dan turunkan trust.
4. trust_score adalah kualitas sinyal internal, bukan jaminan keamanan.
5. HIGH hanya jika source dan listing punya sinyal kuat; MEDIUM jika cukup; REVIEW jika informasi penting kurang jelas.
6. Maksimal 12 kandidat.
7. Output HANYA JSON object valid tanpa markdown.

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
                                "page_age": _clean(result.get("page_age"), 80),
                                "cited_text": "",
                            }
        if block.get("type") == "text":
            for citation in block.get("citations") or []:
                if isinstance(citation, dict) and citation.get("type") == "web_search_result_location":
                    url = citation.get("url")
                    key = _url_key(url)
                    if key:
                        entry = urls.setdefault(key, {
                            "url": url,
                            "title": _clean(citation.get("title"), 300),
                            "page_age": "",
                            "cited_text": "",
                        })
                        cited = _clean(citation.get("cited_text"), 500)
                        if cited and cited not in entry.get("cited_text", ""):
                            existing = entry.get("cited_text", "")
                            entry["cited_text"] = _clean((existing + " " + cited).strip(), 900)
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


def _narrative_text(content):
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = _clean(block.get("text"), 3000)
            if text:
                parts.append(text)
    return _clean("\n".join(parts), 7000)


def _structure_candidates(model, item, observed, narrative):
    evidence = []
    for source in list(observed.values())[:24]:
        evidence.append({
            "url": source.get("url"),
            "title": source.get("title") or "",
            "page_age": source.get("page_age") or "",
            "cited_text": source.get("cited_text") or "",
        })
    payload = {
        "request": {
            "request_text": item.get("request_text"),
            "ai_summary": item.get("ai_summary") or {},
        },
        "research_summary": narrative,
        "sources": evidence,
    }
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
            "system": _STRUCTURE_SYSTEM,
            "messages": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        },
        timeout=(5, 40),
        allow_redirects=False,
    )
    if not 200 <= response.status_code < 300:
        raise ValueError("structure_http_" + str(response.status_code))
    result = response.json()
    ai_usage.record(model, result, tenant_id=None, context="platform_customer", classification="complex")
    blocks = result.get("content") if isinstance(result, dict) else None
    return _final_json(blocks)


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
                "max_tokens": 1000,
                "temperature": 0,
                "system": _SYSTEM,
                "messages": [{"role": "user", "content": _request_prompt(item)}],
                "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            },
            timeout=(5, 120),
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
        narrative = _narrative_text(content)
        value = _structure_candidates(model, item, observed, narrative)
        candidates = _validate_candidates(value, observed)
    except requests.RequestException as exc:
        log.warning("[KILAS_ORDER_SEARCH] structure_network kind=%s", type(exc).__name__)
        order_service.update_request_status(item["id"], "ISSUE")
        return [], "network_failure"
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


def is_background_search_active(request_id):
    try:
        request_id = int(request_id)
    except (TypeError, ValueError):
        return False
    with _ACTIVE_LOCK:
        return request_id in _ACTIVE_SEARCHES


def get_background_search_error(request_id):
    try:
        request_id = int(request_id)
    except (TypeError, ValueError):
        return ""
    with _ACTIVE_LOCK:
        return _LAST_ERRORS.get(request_id, "")


def start_background_search(item):
    """Start one in-process search job and return immediately.

    Render currently runs one web-service instance. The database status is the source of truth;
    the in-memory set only prevents duplicate concurrent runs inside the live worker. If a deploy
    restarts the worker, a later retry can safely start the persisted request again.
    """
    if not item or type(item.get("id")) is not int:
        return False
    request_id = item["id"]
    with _ACTIVE_LOCK:
        if request_id in _ACTIVE_SEARCHES:
            return False
        _ACTIVE_SEARCHES.add(request_id)
        _LAST_ERRORS.pop(request_id, None)

    # Persist SEARCHING before the HTTP response returns so polling immediately sees progress.
    order_service.update_request_status(request_id, "SEARCHING")
    snapshot = dict(item)

    def runner():
        error = ""
        try:
            _, error = search_request(snapshot)
        except Exception as exc:
            error = "internal_error"
            log.warning("[KILAS_ORDER_SEARCH] background_unhandled kind=%s", type(exc).__name__)
            try:
                order_service.update_request_status(request_id, "ISSUE")
            except Exception:
                pass
        finally:
            with _ACTIVE_LOCK:
                if error:
                    _LAST_ERRORS[request_id] = error
                else:
                    _LAST_ERRORS.pop(request_id, None)
                _ACTIVE_SEARCHES.discard(request_id)

    thread = threading.Thread(
        target=runner,
        name="kilas-order-search-%s" % request_id,
        daemon=True,
    )
    thread.start()
    return True
