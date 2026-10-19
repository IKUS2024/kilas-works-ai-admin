"""Offline download/cache boundary tests; never create an E2B sandbox."""
import concurrent.futures
import hashlib
import io
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import urllib.request

from kilas_ai import workspace_document_bundle as bundle


class Response(io.BytesIO):
    status = 200

    def __init__(self, raw, *, declared=None, url="https://files.pythonhosted.org/test.whl"):
        super().__init__(raw)
        self.headers = {} if declared is None else {"Content-Length": str(declared)}
        self.url = url

    def geturl(self):
        return self.url


class DocumentBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / "cache"
        self.raw = b"synthetic inert wheel payload"
        self.wheel = {
            "filename": "synthetic.whl", "size": len(self.raw),
            "sha256": hashlib.sha256(self.raw).hexdigest(),
            "url": "https://files.pythonhosted.org/test.whl",
        }
        self.manifest = {"wheels": {"synthetic.whl": self.wheel},
                         "abis": {abi: ["synthetic.whl"] for abi in bundle.SUPPORTED_ABIS}}

    def run_prepare(self, opener):
        with patch.object(bundle, "_manifest", return_value=self.manifest), \
                patch.object(bundle.urllib.request, "build_opener", return_value=opener):
            return bundle.prepare(self.cache)

    def test_reviewed_lock_contains_exact_ten_packages_for_every_supported_abi(self):
        self.assertEqual(bundle.manifest_digest(), bundle.LOCK_SHA256)
        unique = set()
        for abi in ("cp310", "cp311", "cp312", "cp313", "cp314"):
            description = bundle.describe(abi)
            wheels = description["wheels"]
            self.assertEqual({w["project"]: w["version"] for w in wheels}, bundle.VERSIONS)
            self.assertLess(description["total_size_bytes"], 16 * 1024 * 1024)
            self.assertEqual(description["platform"]["minimum_glibc"], "2.28")
            normalizer = next(w for w in wheels if w["project"] == "charset-normalizer")
            self.assertTrue(normalizer["filename"].endswith("py3-none-any.whl"))
            unique.update(w["filename"] for w in wheels)
        self.assertEqual(len(unique), 18)
        for abi in ("cp39", "cp313t", "pypy310", "cp315", ""):
            with self.assertRaisesRegex(bundle.BundleError, "unsupported_document_abi"):
                bundle.describe(abi)

    def test_modified_lock_rejected_before_cache_or_network(self):
        bad = Path(self.temp.name) / "lock.json"
        bad.write_text('{}')
        with patch.object(bundle, "LOCK_PATH", bad), patch.object(bundle.urllib.request, "build_opener") as network:
            with self.assertRaisesRegex(bundle.BundleError, "wheel_lock_mismatch"):
                bundle.prepare(self.cache)
        network.assert_not_called()
        self.assertFalse(self.cache.exists())

    def test_download_is_unique_across_abis_and_cached_content_is_reverified(self):
        opener = Mock()
        opener.open.return_value = Response(self.raw, declared=len(self.raw))
        paths = self.run_prepare(opener)
        self.assertEqual(set(paths), set(bundle.SUPPORTED_ABIS))
        self.assertTrue(all(p == (self.cache / "synthetic.whl",) for p in paths.values()))
        self.assertEqual((self.cache / "synthetic.whl").read_bytes(), self.raw)
        self.assertEqual(self.cache.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.cache / "synthetic.whl").stat().st_mode & 0o777, 0o600)
        self.run_prepare(opener)
        opener.open.assert_called_once()
        (self.cache / "synthetic.whl").write_bytes(b"x" * len(self.raw))
        with self.assertRaisesRegex(bundle.BundleError, "cached_wheel_invalid"):
            self.run_prepare(opener)
        opener.open.assert_called_once()

    def test_bad_length_truncation_and_hash_never_publish_a_partial_file(self):
        for raw, declared in ((self.raw + b"x", None), (self.raw[:-1], None),
                              (b"x" * len(self.raw), None), (self.raw, len(self.raw) + 1)):
            with self.subTest(length=len(raw), declared=declared):
                opener = Mock()
                opener.open.return_value = Response(raw, declared=declared)
                with self.assertRaises(bundle.BundleError):
                    self.run_prepare(opener)
                self.assertEqual(list(self.cache.iterdir()), [])

    def test_destination_only_appears_after_hash_verification(self):
        response = Response(self.raw)
        original = response.read1
        def read(size):
            self.assertFalse((self.cache / "synthetic.whl").exists())
            return original(size)
        response.read1 = read
        opener = Mock()
        opener.open.return_value = response
        self.run_prepare(opener)
        self.assertEqual([p.name for p in self.cache.iterdir()], ["synthetic.whl"])

    def test_cache_symlink_and_world_readable_directory_are_rejected(self):
        opener = Mock()
        self.cache.symlink_to(self.temp.name, target_is_directory=True)
        with self.assertRaises(bundle.BundleError):
            self.run_prepare(opener)
        self.cache.unlink()
        self.cache.mkdir(mode=0o755)
        self.cache.chmod(0o755)
        with self.assertRaisesRegex(bundle.BundleError, "wheel_cache_not_private"):
            self.run_prepare(opener)
        opener.open.assert_not_called()

    def test_wheel_symlinks_and_hardlinks_cannot_be_cache_hits(self):
        self.cache.mkdir(mode=0o700)
        outside = Path(self.temp.name) / "outside"
        outside.write_bytes(self.raw)
        outside.chmod(0o600)
        target = self.cache / "synthetic.whl"
        opener = Mock()
        target.symlink_to(outside)
        with self.assertRaises(bundle.BundleError):
            self.run_prepare(opener)
        target.unlink()
        os.link(outside, target)
        with self.assertRaisesRegex(bundle.BundleError, "cached_wheel_invalid"):
            self.run_prepare(opener)
        opener.open.assert_not_called()
        self.assertEqual(outside.read_bytes(), self.raw)

    def test_redirects_reject_unapproved_host_protocol_and_credentials(self):
        redirect = bundle._RestrictedRedirect()
        req = urllib.request.Request("https://pypi.org/original")
        for destination in ("http://files.pythonhosted.org/a", "https://evil.test/a",
                            "https://files.pythonhosted.org.evil.test/a",
                            "https://user:secret@pypi.org/a", "file:///tmp/a",
                            "https://pypi.org:444/a", "https://pypi.org/a\nInjected: yes"):
            with self.subTest(destination=destination), self.assertRaisesRegex(bundle.BundleError, "wheel_url_denied"):
                redirect.redirect_request(req, None, 302, "Found", {}, destination)
        accepted = redirect.redirect_request(req, None, 302, "Found", {}, "https://files.pythonhosted.org/a")
        self.assertEqual(accepted.full_url, "https://files.pythonhosted.org/a")

    def test_final_url_and_compressed_response_are_rejected(self):
        for response in (Response(self.raw, url="https://evil.test/a"), Response(self.raw)):
            if response.url.endswith("test.whl"):
                response.headers["Content-Encoding"] = "gzip"
            opener = Mock()
            opener.open.return_value = response
            with self.assertRaises(bundle.BundleError):
                self.run_prepare(opener)
            self.assertEqual(list(self.cache.iterdir()), [])

    def test_transport_errors_are_sanitized_and_partial_files_removed(self):
        opener = Mock()
        opener.open.side_effect = OSError("proxy-password-sensitive")
        with self.assertRaisesRegex(bundle.BundleError, "^wheel_prepare_failed$") as failure:
            self.run_prepare(opener)
        self.assertIsNone(failure.exception.__cause__)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_file_deadline_stops_a_dripping_response(self):
        clock = [0.0]
        response = Response(self.raw)
        def drip(size):
            clock[0] = 31.0
            return b"s"
        response.read1 = drip
        opener = Mock()
        opener.open.return_value = response
        with patch.object(bundle.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(bundle.BundleError, "wheel_prepare_timeout"):
                self.run_prepare(opener)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_concurrent_preparations_share_one_atomic_download(self):
        opener = Mock()
        def fetch(*args, **kwargs):
            time.sleep(0.1)
            return Response(self.raw)
        opener.open.side_effect = fetch
        with patch.object(bundle, "_manifest", return_value=self.manifest), \
                patch.object(bundle.urllib.request, "build_opener", return_value=opener), \
                concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(bundle.prepare, self.cache) for _ in range(2)]
            results = [future.result(timeout=3) for future in futures]
        self.assertEqual(results[0], results[1])
        opener.open.assert_called_once()
        self.assertEqual(list(self.cache.glob("*.part")), [])


if __name__ == "__main__":
    unittest.main()
