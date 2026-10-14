"""The smaller landing logo must retain the original branding and every RGBA pixel."""
import hashlib
import unittest
from pathlib import Path
from PIL import Image


STATIC = Path(__file__).resolve().parents[1] / 'static'


class LogoAssetTests(unittest.TestCase):
    def test_original_is_retained_and_lossless_variant_preserves_pixels_and_alpha(self):
        original = STATIC / 'kilas-new-chat-logo.png'
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),
                         '96cd9f9aebf32edbab60e525a4b0685e9482595cc8d2d0f2f53ae0ddee116e24')
        with Image.open(original) as png, Image.open(STATIC / 'kilas-new-chat-logo-lossless.webp') as webp:
            self.assertEqual(webp.format, 'WEBP')
            self.assertEqual(webp.size, png.size)
            self.assertEqual(webp.size, (1254, 1254))
            self.assertEqual(webp.convert('RGBA').tobytes(), png.convert('RGBA').tobytes())

    def test_variant_substantially_reduces_transfer_size(self):
        original = STATIC / 'kilas-new-chat-logo.png'
        optimized = STATIC / 'kilas-new-chat-logo-lossless.webp'
        self.assertLess(optimized.stat().st_size, original.stat().st_size * .55)


if __name__ == '__main__':
    unittest.main()
