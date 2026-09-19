"""Disposable, resource-bounded phone image normalizer; stdin/stdout only."""
import io
import sys
import warnings


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (6, 6))
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 80_000_000
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    raw = sys.stdin.buffer.read(20 * 1024 * 1024 + 1)
    if not raw or len(raw) > 20 * 1024 * 1024:
        raise ValueError()
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 80_000_000 or getattr(image, 'n_frames', 1) != 1:
            raise ValueError()
        # JPEG decoder downsampling avoids allocating a full 50MP RGB phone photo.
        image.draft('RGB', (3200, 3200))
        image.load()
        image = ImageOps.exif_transpose(image)
        image.thumbnail((3200, 3200), Image.Resampling.LANCZOS)
        if image.mode in ('RGBA', 'LA') or 'transparency' in image.info:
            rgba = image.convert('RGBA')
            image = Image.new('RGB', rgba.size, 'white')
            image.paste(rgba, mask=rgba.getchannel('A'))
        else:
            image = image.convert('RGB')
        for quality in (88, 76, 60):
            output = io.BytesIO()
            image.save(output, 'JPEG', quality=quality)
            if output.tell() <= 4 * 1024 * 1024:
                sys.stdout.buffer.write(output.getvalue())
                return
            if quality == 76:
                image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
        raise ValueError()


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        sys.exit(1)
