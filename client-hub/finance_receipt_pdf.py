"""Disposable PDF parser. Receipt bytes enter via stdin only; never written to disk."""
import io
import json
import logging
import sys
import warnings


class PDFRejected(Exception):
    pass


def main():
    # Fail closed without OS resource limits rather than parse hostile PDFs unbounded.
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    logging.disable(logging.CRITICAL)
    warnings.simplefilter('ignore')
    import pypdf
    document = '--bank-statement' in sys.argv[1:] or '--document' in sys.argv[1:]
    maximum = (10 if document else 5) * 1024 * 1024
    pages = 20 if document else 10
    text_limit = 100000 if document else 20000
    raw = sys.stdin.buffer.read(maximum + 1)
    if len(raw) > maximum:
        raise PDFRejected('size_limit')
    # Bank exports often contain recoverable xref/font metadata defects. Validate structure
    # and limits here; an unusable text layer must not block the original PDF vision path.
    try:
        reader = pypdf.PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted and not reader.decrypt(''):
            raise PDFRejected('encrypted/password_required')
        count = len(reader.pages)
        if count > pages:
            raise PDFRejected('page_limit')
        if count < 1:
            raise ValueError('empty')
        # Force lazy page dictionaries while still inside the bounded process.
        for page in reader.pages:
            if page.get('/Type') != '/Page':
                raise ValueError('page')
    except (PDFRejected, MemoryError):
        raise
    except Exception:
        # Independent QPDF structure recovery; never executes JS, renders, or OCRs.
        # A parser failure alone is not proof of corruption. Raw bytes stay unchanged.
        import pikepdf
        try:
            with pikepdf.Pdf.open(io.BytesIO(raw), password='', attempt_recovery=True,
                                 suppress_warnings=True) as secondary:
                count = len(secondary.pages)
                if count > pages:
                    raise PDFRejected('page_limit')
                if count < 1:
                    raise PDFRejected('malformed_pdf')
                for page in secondary.pages:
                    if str(page.obj.get('/Type')) != '/Page' or len(page.mediabox) != 4:
                        raise PDFRejected('malformed_pdf')
        except pikepdf.PasswordError:
            raise PDFRejected('encrypted/password_required') from None
        except pikepdf.PdfError:
            raise PDFRejected('malformed_pdf') from None
        sys.stderr.write('vision_fallback\n')
        print(json.dumps({'text': ''}))
        return
    if '--validate-only' in sys.argv[1:]:
        print(json.dumps({'text': ''}))
        return
    parts = []
    complete_text = True
    for page in reader.pages:
        try:
            text = page.extract_text() or ''
        except MemoryError:
            raise
        except Exception:
            text = ''
            # Only a fixed diagnostic leaves the parser; never exception strings.
            sys.stderr.write('text_extraction_failed\n')
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
    except PDFRejected as error:
        print(json.dumps({'error': str(error)}))
    except MemoryError:
        print(json.dumps({'error': 'resource_limit'}))
    except BaseException:
        # No parser diagnostics, filenames, receipt contents or tracebacks.
        print(json.dumps({'error': 'malformed_pdf'}))
