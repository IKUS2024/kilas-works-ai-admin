"""Bounded extractive history: no extra model call, no prompt logging."""
import re


CORRECTION = re.compile(r"\b(?:koreksi|correction|bukan itu|maksud (?:gw|gue|gua|lu|saya|aku)|yang tadi salah|ganti jadi|eh bukan|sebenarnya|actually|instead|changed my mind)\b", re.I)
CONSTRAINT = re.compile(r"\b(?:jangan|gak mau|nggak mau|tidak mau|ga mau|harus|ingat|bukan|must|never|don't|do not|budget|modal|pilih|decided|prefer|keputusan)\b", re.I)


def summary(rows, limit=3000):
    # Extract original wording only; chronological quotes let the latest correction win.
    # Select whole entries by priority rather than slicing through a correction at the end.
    facts = []
    for row in rows:
        if row['role'] != 'user':
            continue
        text = row['content']
        if not isinstance(text, str) or re.search(r'(?i)password|api.?key|secret|token\s*[:=]|kata sandi', text):
            continue
        text = ' '.join(text.split())
        if text:
            facts.append(text if len(text) <= 650 else text[:300] + ' … ' + text[-347:])
    last_occurrence = {text: i for i, text in enumerate(facts)}
    candidates = [text for i, text in enumerate(facts) if last_occurrence[text] == i]
    ranked = sorted(range(len(candidates)), key=lambda i: (
        2 if CORRECTION.search(candidates[i]) else 1 if CONSTRAINT.search(candidates[i]) else 0, i), reverse=True)
    chosen, remaining = [], max(0, limit)
    for i in ranked:
        size = len(candidates[i]) + (1 if chosen else 0)
        if size <= remaining:
            chosen.append(i)
            remaining -= size
    return '\n'.join(candidates[i] for i in sorted(chosen))


def bounded(messages, budget):
    remaining = budget
    selected = []
    for item in reversed(messages):
        text = item['content']
        size = len(text) if isinstance(text,str) else sum(len(b.get('text','')) for b in text)
        if size > remaining:
            if not selected:
                # Preserve current multimodal input; existing attachment caps remain authoritative.
                selected.append(item)
            break
        selected.append(item)
        remaining -= size
    return list(reversed(selected))
