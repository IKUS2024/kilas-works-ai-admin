"""Approved existing voice aliases. Never create, rename or alter personal voices.

Production source rows were verified read-only on 2026-10-11: owner 9,
saved voice 5 (irvan Voice), saved voice 7 (putri voice). Provider IDs remain
server-side; disappearance fails closed rather than selecting a stock voice.
"""
import re
import db

SOURCES = (('kilas-male', 9, 5, 'Kilas Male'), ('kilas-female', 9, 7, 'Kilas Female'))


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
