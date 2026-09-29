"""Deterministic boundaries for Work computer actions and public web access."""
import ipaddress
import re
import socket
from urllib.parse import urlparse


class BrowserSafetyError(ValueError):
    pass


BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "instance-data"}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".test", ".invalid")
SENSITIVE_ACTION = re.compile(
    r"\b(?:pay|purchase|checkout|buy now|delete|remove account|publish|post publicly|"
    r"send message|send email|submit application|submit form|confirm transfer|"
    r"bayar|beli|hapus|terbitkan|publikasikan|kirim pesan|kirim email|"
    r"ajukan permohonan|kirim formulir|konfirmasi pembayaran)\b", re.I)
HANDOFF = re.compile(
    r"\b(?:captcha|recaptcha|verify you are human|two.factor|2fa|one.time password|"
    r"verification code|kode verifikasi|kode otp|autentikasi dua langkah)\b", re.I)


def require_public_url(url, resolver=socket.getaddrinfo):
    url = str(url or "")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in ("http", "https") or not host or parsed.username or parsed.password:
        raise BrowserSafetyError("Alamat website tidak didukung.")
    if host in BLOCKED_HOSTS or host.endswith(BLOCKED_SUFFIXES) or len(url) > 2048:
        raise BrowserSafetyError("Alamat website tidak dapat dibuka.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise BrowserSafetyError("Alamat IP langsung tidak didukung.")
    try:
        addresses = {entry[4][0] for entry in resolver(host, parsed.port or 443, type=socket.SOCK_STREAM)}
    except (socket.gaierror, OSError, ValueError):
        raise BrowserSafetyError("Alamat website tidak dapat diperiksa.") from None
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise BrowserSafetyError("Alamat website tidak dapat dibuka.")
    return url


def classify_action(action, *, target_text="", target_type="", page_text=""):
    """Return ALLOW, CONFIRM, or HANDOFF before applying a model action."""
    kind = str(action.get("type") or "")
    if kind not in {"click", "double_click", "drag", "move", "scroll", "keypress", "type", "wait", "screenshot"}:
        raise BrowserSafetyError("Aksi browser tidak dikenal.")
    if HANDOFF.search(page_text[:3000]) or target_type.lower() in ("password", "one-time-code", "file"):
        return "HANDOFF"
    if kind == "type" and (target_type.lower() in ("password", "tel") or
                           re.search(r"\b(?:otp|verification|kode)\b", target_text, re.I)):
        return "HANDOFF"
    if kind in ("click", "double_click", "keypress") and SENSITIVE_ACTION.search(target_text[:300]):
        return "CONFIRM"
    if kind == "type" and len(str(action.get("text") or "")) > 2000:
        raise BrowserSafetyError("Teks terlalu panjang untuk satu langkah browser.")
    if kind == "wait":
        try:
            value = float(action.get("ms") or 0)
        except (ValueError, TypeError):
            raise BrowserSafetyError("Waktu tunggu browser tidak valid.") from None
        if not 0 <= value <= 10000:
            raise BrowserSafetyError("Waktu tunggu browser terlalu lama.")
    return "ALLOW"
