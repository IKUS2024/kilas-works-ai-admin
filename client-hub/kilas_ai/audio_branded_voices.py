"""Approved existing voice aliases. Never create, rename or alter personal voices.

Production source rows were verified read-only on 2026-10-11: owner 9,
saved voice 5 (irvan Voice), saved voice 7 (putri voice). Provider IDs remain
server-side; disappearance fails closed rather than selecting a stock voice.
"""
import hashlib
import json
from pathlib import Path
import re
import db

SOURCES = (('kilas-male', 9, 5, 'Kilas Male'), ('kilas-female', 9, 7, 'Kilas Female'))
SAMPLE_TEXT = 'Hi, this is a sample of my voice.'
SAMPLE_ROOT = Path(__file__).with_name('voice_samples')


def choices():
    result = []
    for alias, owner, ident, label in SOURCES:
        row = db.query_one('SELECT voice_id FROM kilas_audio_saved_voices WHERE user_id=? AND id=?', (owner, ident))
        if row and re.fullmatch(r'[A-Za-z0-9]{1,80}', row['voice_id'] or ''):
            result.append({'alias': alias, 'id': row['voice_id'], 'name': label, 'style': 'Natural'})
    return result


def public_choices():
    return [{k: row[k] for k in ('alias', 'name', 'style')} for row in choices()]


def resolve(alias):
    return next((row for row in choices() if row['alias'] == alias), None)


def sample(alias):
    """Return only an explicitly published English demo for this exact voice.

    Manifest entries bind the public text and current provider identity to an
    immutable MP3. Missing assets fail closed; listening never generates audio
    or borrows the source owner's private recording or generated job history.
    """
    if alias not in {source[0] for source in SOURCES}:return None
    voice=resolve(alias)
    if not voice:return None
    try:
        entry=json.loads((SAMPLE_ROOT/'manifest.json').read_text())[alias]
        if entry['text']!=SAMPLE_TEXT or entry['voice_sha256']!=hashlib.sha256(voice['id'].encode()).hexdigest():return None
        raw=(SAMPLE_ROOT/(alias+'.mp3')).read_bytes()
        if not 0<len(raw)<=1024*1024 or hashlib.sha256(raw).hexdigest()!=entry['audio_sha256']:return None
        return raw
    except (OSError,ValueError,KeyError,TypeError):return None


def sample_aliases():
    return [alias for alias,_,_,_ in SOURCES if sample(alias)]
