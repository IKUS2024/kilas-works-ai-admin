"""Bounded extractive history: no extra model call, no prompt logging."""
import re


def summary(rows, limit=3000):
    # Preserve original user wording/corrections in chronological order, never invent facts.
    facts = []
    for row in rows:
        if row['role'] != 'user':
            continue
        text = row['content']
        if re.search(r'(?i)password|api.?key|secret|token\s*[:=]|kata sandi', text):
            continue
        facts.append(' '.join(text.split())[:650])
    important = [text for text in facts if re.search(r'(?i)\b(?:jangan|harus|ingat|bukan|koreksi|correction|actually|must|never|budget|modal|pilih|decided)\b', text)]
    selected = set(important[-8:] + facts[-6:])
    chosen = list(dict.fromkeys(text for text in facts if text in selected))
    return '\n'.join(chosen)[-limit:]


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
