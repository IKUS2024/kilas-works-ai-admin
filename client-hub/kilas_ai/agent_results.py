"""Bounded, deterministic customer presentation over existing verified task outputs."""
import json
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def task_title(instruction):
    text = ' '.join((str(instruction).splitlines() or [''])[0].split())
    if re.search(r'(?i)\b(?:apa yang viral|apa yang ramai|yang lagi ramai|topik yang sedang viral|tren terbaru)\b', text):
        if not re.search(r'(?i)\b(?:di|in|global|dunia|worldwide|internasional)\b', text):
            return 'Riset Tren Viral Indonesia'
    text = re.sub(r'(?i)^(?:(?:bantu (?:aku|saya)|tolong|kerjain|kerjakan|tetap kerjakan|coba)\s+)+', '', text)
    text = re.split(r'(?i)\b(?:setiap|tiap|sampai|until|tetap|besok|tomorrow)\b', text)[0]
    text = re.sub(r'(?i)\b(?:tentang|untuk|sekarang)\b', '', text)
    words = text.strip(' .,!?').split()
    title = ' '.join(w if w.isupper() else w.capitalize() for w in words[:8])
    if not title:
        return 'Pekerjaan Kilas'
    if len(title) <= 55 and len(words) <= 8:
        return title
    selected = []
    for word in words[:8]:
        word = word if word.isupper() else word.capitalize()
        if len(' '.join(selected + [word])) > 54:
            break
        selected.append(word)
    return (' '.join(selected) or 'Pekerjaan') + '…'


def step_label(step):
    worker, action = step.get('worker'), step.get('action')
    if worker == 'WEB':
        return 'Memeriksa sumber' if re.search(r'(?i)cross.?check|verify|verifikasi|periksa|banding', step.get('instruction','')) else 'Mencari sumber terbaru'
    return {('AI_TEXT','write'):'Menyusun hasil', ('CODE','inspect'):'Memeriksa kode',
            ('CODE','patch'):'Menerapkan perbaikan', ('CODE','test'):'Menjalankan test',
            ('CODE','diff'):'Meninjau perubahan', ('FILE','create'):'Menyiapkan file',
            ('WATCH','observe'):'Memeriksa kondisi', ('MARKET','observe'):'Memeriksa kondisi market',
            ('UNAVAILABLE','request'):'Menunggu kemampuan yang diperlukan',
            ('EXTERNAL','deploy'):'Menyiapkan deployment', ('EXTERNAL','publish'):'Menyiapkan publikasi',
            ('EXTERNAL','push'):'Menyiapkan push', ('EXTERNAL','merge'):'Menyiapkan merge'}.get((worker,action),'Menyiapkan langkah berikutnya')


def compact_sources(citations):
    sources, seen = [], set()
    for source in citations:
        if not isinstance(source, dict):
            continue
        try:
            url = str(source.get('url',''))
            parsed = urlsplit(url)
            if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or re.search(r'[\s\x00-\x1f]', url):
                continue
            query = urlencode([(k,v) for k,v in parse_qsl(parsed.query,keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')])
            clean = urlunsplit((parsed.scheme,parsed.netloc,parsed.path,query,''))
            if clean in seen:
                continue
            seen.add(clean)
            title = str(source.get('title') or parsed.hostname)
            if re.search(r'https?://',title):
                title = parsed.hostname
            sources.append({'url':clean,'original_url':url,'title':title[:100],'host':parsed.hostname.removeprefix('www.')})
        except ValueError:
            continue
        if len(sources) == 32:
            break
    return sources


def readable_text(text, sources):
    # Keep full execution output intact. Display bare known URLs as titled Markdown links.
    by_url = {s[key]:s for s in sources for key in ('url','original_url')}
    def replace(match):
        raw = match[0];url = raw.rstrip('.,;')
        source = by_url.get(url)
        if not source:
            return raw
        name = source['title'].replace('[','').replace(']','')
        return '['+name+']('+source['url']+')'+raw[len(url):]
    return re.sub(r'(?<!\]\()https?://[^\s<>\)]+', replace, str(text))


def primary_result(steps):
    outputs, citations = [], []
    for step in steps:
        if step['status'] != 'SUCCEEDED':
            continue
        output = json.loads(step['output_json'])
        citations.extend(output.get('citations') or [])
        if output.get('text'):
            outputs.append((step,output['text']))
    sources = compact_sources(citations)
    # Prefer the last synthesis, then the last actual written/search result. No model call.
    synthesis = [item for item in outputs if item[0]['worker']=='AI_TEXT']
    chosen = (synthesis or outputs)[-1] if outputs else None
    return {'text':readable_text(chosen[1],sources) if chosen else '', 'sources':sources}
