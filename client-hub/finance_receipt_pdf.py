"""Disposable PDF parser. Receipt bytes enter via stdin only; never written to disk."""
import io
import json
import logging
import sys
import warnings


def main():
    # Fail closed without OS resource limits rather than parse hostile PDFs unbounded.
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    logging.disable(logging.CRITICAL)
    warnings.simplefilter('ignore')
    import pypdf
    bank = '--bank-statement' in sys.argv[1:]
    maximum = (10 if bank else 5) * 1024 * 1024
    pages = 20 if bank else 10
    text_limit = 100000 if bank else 20000
    raw = sys.stdin.buffer.read(maximum + 1)
    if not raw or len(raw) > maximum:
        raise ValueError()
    # Bank exports often contain recoverable xref/font metadata defects. Validate structure
    # and limits here; an unusable text layer must not block the original PDF vision path.
    reader = pypdf.PdfReader(io.BytesIO(raw), strict=False)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= pages:
        raise ValueError()
    if '--validate-only' in sys.argv[1:]:
        print(json.dumps({'text': ''}))
        return
    parts = []
    complete_text = True
    for page in reader.pages:
        try:
            text = page.extract_text() or ''
        except Exception:
            text = ''
        if len(text.strip()) < 40 or len(text) > 20000:
            complete_text = False
        parts.append(text[:20000])
    text = '\n'.join(parts)
    # Mixed scanned/text documents and truncated extraction require the PDF document path.
    # Preserve the receipt worker's original text behavior and limits.
    if not complete_text or len(text) > text_limit:
        text = ''
    print(json.dumps({'text': text[:text_limit]}))


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        # No parser diagnostics, filenames, receipt contents or tracebacks.
        sys.exit(1)
