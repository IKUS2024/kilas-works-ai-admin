"""Isolated bounded rasterization; never runs PDF JavaScript or external links."""
import base64
import io
import json
import math
import os
import subprocess
import sys
from contextlib import closing

MAX_PAGES=3
MAX_PIXELS=1_500_000
MAX_BYTES=3*1024*1024


def _isolated(raw,mode):
    child=subprocess.run([sys.executable,os.path.abspath(__file__),mode],input=raw,
                         stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=15,
                         env={k:v for k,v in os.environ.items() if k in ('PATH','SYSTEMROOT','WINDIR','TEMP','TMP','PYTHONPATH')})
    if child.returncode or len(child.stdout)>5*1024*1024:raise ValueError('pdf_render_failed')
    return json.loads(child.stdout)


def native(raw):
    return _isolated(raw,'--text')


def render(raw):
    data=_isolated(raw,'--images')
    return [{'mime_type':'image/jpeg','content':base64.b64decode(p,validate=True)} for p in data['pages']]


def _worker():
    if os.name!='nt':
        import resource
        resource.setrlimit(resource.RLIMIT_AS,(192*1024*1024,192*1024*1024))
        resource.setrlimit(resource.RLIMIT_CPU,(10,10))
    raw=sys.stdin.buffer.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise ValueError('pdf_size')
    if '--text' in sys.argv:
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(raw),strict=True)
        if reader.is_encrypted:raise ValueError('pdf_locked')
        texts=[];scan=False
        for number,page in enumerate(reader.pages[:15],1):
            text=(page.extract_text() or '')[:12000]
            if number<=3 and '/XObject' in (page.get('/Resources') or {}) and len(text.strip())<30:scan=True
            texts.append('Page '+str(number)+':\n'+text)
            if sum(map(len,texts))>=12000:break
        actual=any(value.split(':\n',1)[1].strip() for value in texts)
        sys.stdout.write(json.dumps({'text':'\n'.join(texts)[:12000].strip(),'scan':scan or not actual,'has_text':actual}))
        return
    import pypdfium2 as pdfium
    pages=[];total=0
    with closing(pdfium.PdfDocument(raw)) as document:
        for number in range(min(len(document),MAX_PAGES)):
            with closing(document[number]) as page:
                width,height=page.get_size()
                if not 0<width<=20000 or not 0<height<=20000:raise ValueError('pdf_dimensions')
                scale=min(1.8,math.sqrt(MAX_PIXELS/(width*height))*0.99)
                with closing(page.render(scale=scale,may_draw_forms=False)) as bitmap:
                    with bitmap.to_pil().convert('RGB') as picture:
                        output=io.BytesIO();picture.save(output,'JPEG',quality=82)
                        total+=len(output.getvalue())
                        if total>MAX_BYTES:raise ValueError('pdf_render_budget')
                        pages.append(base64.b64encode(output.getvalue()).decode('ascii'))
    if not pages:raise ValueError('empty_pdf')
    sys.stdout.write(json.dumps({'pages':pages}))


if __name__=='__main__':
    _worker()
