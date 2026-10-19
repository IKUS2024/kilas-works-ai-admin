"""Download pinned document wheels as inert files before creating a sandbox.

No package is installed, imported, or extracted here. ``prepare`` returns all
supported ABI bundles; callers select one only after checking the guest's
CPython ABI, x86_64 architecture, and glibc >= 2.28. The guest must independently
verify each hash and safely extract the selected wheels into a root-owned,
non-writable directory before starting the confined child.
"""
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import urllib.parse
import urllib.request
import uuid


LOCK_PATH = Path(__file__).with_name("workspace_document_bundle.lock.json")
LOCK_SHA256 = "ad90a2bfc5f563e5595d748acedcd826eb7e4e4488d80993b6aa0158538596c6"
SUPPORTED_ABIS = ("cp310", "cp311", "cp312", "cp313", "cp314")
MAX_WHEEL_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 80 * 1024 * 1024
MAX_PREPARE_SECONDS = 180
MAX_FILE_SECONDS = 30
SOCKET_TIMEOUT = 5
CHUNK_SIZE = 128 * 1024
ALLOWED_HOSTS = frozenset({"pypi.org", "files.pythonhosted.org"})
VERSIONS = {
    "reportlab": "4.4.9", "python-docx": "1.2.0", "openpyxl": "3.1.5",
    "python-pptx": "1.0.2", "pillow": "12.3.0", "lxml": "6.1.1",
    "charset-normalizer": "3.4.4", "et-xmlfile": "2.0.0",
    "typing-extensions": "4.16.0", "xlsxwriter": "3.2.9",
}


class BundleError(ValueError):
    """The bundle cannot be safely prepared; do not create a sandbox."""


def _checked_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS
                 and parsed.port in (None, 443) and not parsed.username
                 and not parsed.password and not parsed.fragment
                 and not any(c.isspace() or ord(c) < 32 for c in url))
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise BundleError("wheel_url_denied")
    return url


class _RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 1

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _checked_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _manifest():
    raw = LOCK_PATH.read_bytes()
    if len(raw) > 100_000 or hashlib.sha256(raw).hexdigest() != LOCK_SHA256:
        raise BundleError("wheel_lock_mismatch")
    data = json.loads(raw)
    if data.get("schema_version") != 1 or set(data.get("abis", {})) != set(SUPPORTED_ABIS):
        raise BundleError("wheel_lock_schema")
    if data.get("platform") != {
        "os": "linux", "machine": "x86_64", "implementation": "cpython",
        "libc": "glibc", "minimum_glibc": "2.28",
    }:
        raise BundleError("wheel_lock_platform")
    wheels = data["wheels"]
    used = set()
    for abi, names in data["abis"].items():
        if len(names) != len(VERSIONS) or len(set(names)) != len(names):
            raise BundleError("wheel_lock_count")
        projects = {}
        for name in names:
            wheel = wheels[name]
            if not re.fullmatch(r"[A-Za-z0-9_.-]+\.whl", name) or wheel["filename"] != name:
                raise BundleError("wheel_lock_filename")
            project = wheel["project"]
            if project in projects:
                raise BundleError("wheel_lock_project")
            projects[project] = wheel["version"]
            if (type(wheel["size"]) is not int or not 0 < wheel["size"] <= MAX_WHEEL_BYTES
                    or not re.fullmatch(r"[0-9a-f]{64}", wheel["sha256"])):
                raise BundleError("wheel_lock_integrity")
            _checked_url(wheel["url"])
            if project in {"pillow", "lxml"}:
                if f"-{abi}-{abi}-" not in name or "manylinux_2_28_x86_64" not in name:
                    raise BundleError("wheel_lock_abi")
            elif not name.endswith("-none-any.whl"):
                raise BundleError("wheel_lock_abi")
            used.add(name)
        if projects != VERSIONS:
            raise BundleError("wheel_lock_versions")
    if used != set(wheels) or sum(w["size"] for w in wheels.values()) > MAX_TOTAL_BYTES:
        raise BundleError("wheel_lock_total")
    return data


def manifest_digest():
    """Return the reviewed lock digest, verifying the packaged lock first."""
    _manifest()
    return LOCK_SHA256


def describe(abi):
    """Describe the exact inert wheels for one supported, non-free-threaded ABI."""
    if abi not in SUPPORTED_ABIS:
        raise BundleError("unsupported_document_abi")
    data = _manifest()
    wheels = [copy.deepcopy(data["wheels"][n]) for n in data["abis"][abi]]
    return {"abi": abi, "platform": data["platform"], "lock_sha256": LOCK_SHA256,
            "total_size_bytes": sum(w["size"] for w in wheels), "wheels": wheels}


def _deadline(deadline):
    if time.monotonic() >= deadline:
        raise BundleError("wheel_prepare_timeout")


@contextmanager
def _private_cache(path, deadline):
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise BundleError("wheel_cache_not_private")
        while True:
            _deadline(deadline)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.05)
        yield fd
    finally:
        os.close(fd)


def _cached(fd, wheel, deadline):
    try:
        handle = os.open(wheel["filename"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return False
    with os.fdopen(handle, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                or info.st_size != wheel["size"]):
            raise BundleError("cached_wheel_invalid")
        digest = hashlib.sha256()
        remaining = wheel["size"]
        while remaining:
            _deadline(deadline)
            chunk = stream.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                raise BundleError("cached_wheel_invalid")
            digest.update(chunk)
            remaining -= len(chunk)
        if stream.read(1) or digest.hexdigest() != wheel["sha256"]:
            raise BundleError("cached_wheel_invalid")
    return True


def _download(fd, wheel, opener, deadline):
    deadline = min(deadline, time.monotonic() + MAX_FILE_SECONDS)
    _deadline(deadline)
    request = urllib.request.Request(_checked_url(wheel["url"]), headers={
        "User-Agent": "Kilas-Document-Wheels/1", "Accept-Encoding": "identity",
    })
    name = ".wheel-" + uuid.uuid4().hex + ".part"
    handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=fd)
    try:
        with os.fdopen(handle, "wb") as output:
            with opener.open(request, timeout=min(SOCKET_TIMEOUT, deadline - time.monotonic())) as response:
                _checked_url(response.geturl())
                if response.status != 200 or response.headers.get("Content-Encoding", "identity") != "identity":
                    raise BundleError("wheel_download_response")
                declared = response.headers.get("Content-Length")
                if declared is not None and declared != str(wheel["size"]):
                    raise BundleError("wheel_download_size")
                digest = hashlib.sha256()
                count = 0
                while True:
                    _deadline(deadline)
                    # Read at most the expected size plus one sentinel byte.
                    # read1 returns after one socket read, allowing the total
                    # deadline to be checked even when a peer drips bytes.
                    chunk = response.read1(min(CHUNK_SIZE, wheel["size"] - count + 1))
                    _deadline(deadline)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > wheel["size"] or count > MAX_WHEEL_BYTES:
                        raise BundleError("wheel_download_size")
                    digest.update(chunk)
                    output.write(chunk)
                if count != wheel["size"] or digest.hexdigest() != wheel["sha256"]:
                    raise BundleError("wheel_download_integrity")
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, wheel["filename"], src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(name, dir_fd=fd)
        except FileNotFoundError:
            pass


def prepare(cache_dir=None):
    """Prewarm and reverify all ABI bundles; return ``{abi: tuple[Path, ...]}``.

    Run before any paid sandbox operation. Downloads are unique across ABIs and
    serialized across processes. Cache hits are rehashed, incomplete downloads
    are never published, and an invalid existing file fails closed. HTTP work
    has a 180-second total deadline, 30 seconds per file, and five-second socket
    timeouts; an in-flight socket read may finish up to five seconds later.
    """
    data = _manifest()
    deadline = time.monotonic() + MAX_PREPARE_SECONDS
    path = Path(cache_dir) if cache_dir is not None else Path(tempfile.gettempdir()) / (
        f"kilas-document-wheels-{os.getuid()}-{LOCK_SHA256[:16]}"
    )
    opener = urllib.request.build_opener(_RestrictedRedirect())
    try:
        with _private_cache(path, deadline) as fd:
            for wheel in data["wheels"].values():
                if not _cached(fd, wheel, deadline):
                    _download(fd, wheel, opener, deadline)
            # Reverify before returning paths used by the caller's upload.
            for wheel in data["wheels"].values():
                if not _cached(fd, wheel, deadline):
                    raise BundleError("cached_wheel_missing")
    except BundleError:
        raise
    except Exception:
        # Do not surface arbitrary transport/proxy messages or credentials.
        raise BundleError("wheel_prepare_failed") from None
    return {abi: tuple(path / name for name in names) for abi, names in data["abis"].items()}
