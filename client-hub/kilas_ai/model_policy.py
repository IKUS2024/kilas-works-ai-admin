"""Server-owned model and reasoning decisions; no classifier API call."""
import os
import re

LUNA = 'gpt-6-luna'
SOL = 'gpt-6.1-sol'
TIERS = {'QUICK': ('none', 600), 'NORMAL': ('low', 1000), 'DEEP': ('medium', 1500)}


def luna_model():
    model = os.environ.get('KILAS_AI_CHAT_MODEL', LUNA).strip()
    if model != LUNA:
        raise ValueError('invalid_chat_model')
    return model


def chat_tier(text):
    text = str(text).lower()
    if len(text) > 3500 or re.search(r'\b(?:analisis|analyze|analyse|analysis|strategi|strategy|debug|refactor|sql|arsitektur|architecture|risiko|trade.?offs?|business plan)\b', text):
        return 'DEEP'
    if re.search(r'\b(?:mending|bandingkan|compare|comparison|lebih bagus|lebih baik)\b', text) and re.search(r'\b(?:modal|budget|usaha|bisnis|cafe|laundry|investasi|dokumen)\b', text):
        return 'DEEP'
    if len(text) < 250 and re.search(r'^(?:halo|hai|hi|hello|thanks|makasih|terima kasih|translate|terjemah|ubah format|formatkan|apa itu|what is)\b', text.strip()):
        return 'QUICK'
    return 'NORMAL'


class ChatContext(list):
    """Private request profile, not part of the JSON messages or user parameters."""
    def __init__(self, messages, level='NORMAL'):
        super().__init__(messages)
        self.fair_use_level = level


def chat_profile(messages):
    current = next((m['content'] for m in reversed(messages) if m['role']=='user'), '')
    if isinstance(current, list):
        current = ' '.join(b.get('text','') for b in current if isinstance(b, dict))
    tier = chat_tier(current)
    effort, output = TIERS[tier]
    level = getattr(messages, 'fair_use_level', 'NORMAL')
    if level == 'HEAVY':
        output = min(output, 1200)
    elif level in ('VERY_HEAVY', 'PROTECTION'):
        output = min(output, 1000)
    return {'tier':tier, 'effort':effort, 'output_tokens':output,
            'activity':'Menganalisis…' if tier=='DEEP' else 'Menyiapkan jawaban…'}


def agent_planner(job):
    text = job['instruction'].lower()
    complex_work = bool((job.get('replans',0) and job.get('last_error') in ('worker_failed','invalid_plan')) or re.search(
        r'\b(?:bug|debug|refactor|repo|repository|kode|coding|code|authentication|dependencies|dependensi|multi.?stage|multi.?step|retry|retries)\b', text))
    model = SOL if complex_work else luna_model()
    if complex_work and os.environ.get('KILAS_AI_AGENT_MODEL', SOL).strip() != SOL:
        raise ValueError('invalid_complex_planner_model')
    return model, 'medium', 'complex_execution' if complex_work else 'bounded_task'
