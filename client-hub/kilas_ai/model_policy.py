"""Server-owned model and reasoning decisions; no classifier API call."""
import os
import re

LUNA = 'gpt-6-luna'
SOL = 'gpt-6.1-sol'
TIERS = {'QUICK': ('low', 600), 'NORMAL': ('low', 1000), 'DEEP': ('medium', 1500)}


def luna_model():
    model = os.environ.get('KILAS_AI_CHAT_MODEL', LUNA).strip()
    if model != LUNA:
        raise ValueError('invalid_chat_model')
    return model


def chat_tier(text):
    text = " ".join(str(text).lower().split())
    # A direct text transformation does not become analysis because its quoted source says SQL/strategy.
    if len(text) <= 3500 and re.match(r'^(?:tolong )?(?:translate|terjemah(?:kan)?|benerin typo|perbaiki typo)\b', text):
        return 'QUICK' if len(text) < 250 else 'NORMAL'
    # Reasoning decisions only: PR #113 tool/action routing remains separate.
    analytical = (
        r"\b(?:analisis|analisa|analyze|analyse|analysis|strategi|strategy|debug|debugging|"
        r"refactor|sql|arsitektur|architecture|risiko|trade.?offs?|business plan|"
        r"bandingin|bandingkan|perbandingan|compare|comparison|troubleshoot|troubleshooting|"
        r"planning|rencanakan|rencana|plan|strateginya|recommend|recommendation|rekomendasi|saran)\b",
        r"\b(?:menurut (?:lu|lo|elo|kamu|anda|mu)|mending|lebih baik|lebih bagus|sebaiknya)\b",
        r"\b(?:kemungkinan|penyebab|cause)\b.{0,80}\b(?:salah(?:nya)?|error|gagal|failed|bug)\b",
        r"\b(?:kenapa|knp|why)\b.{0,100}\b(?:kode|code|query|error|gagal|crash|bug)\b",
        r"\b(?:bisnis|usaha|business|pricing|monetisasi|monetization|saas|umkm)\b.{0,100}"
        r"\b(?:modal|budget|harga|biaya|untung|rugi|pilih|marketing|operasional|positioning)\b",
    )
    constraints = re.findall(r'\b(?:budget|modal|bujet|jangan|tanpa|harus|hanya|maksimal|sendiri|without|must|only|maximum)\b', text)
    if len(text) > 3500 or (len(text) > 80 and len(constraints) >= 3) or any(re.search(pattern, text) for pattern in analytical):
        return 'DEEP'
    if len(text) < 250 and re.search(r'^(?:halo|hai|hi|hello|thanks|makasih|terima kasih|translate|terjemah|ubah format|formatkan|apa itu|what is|benerin typo|buat caption pendek)\b', text):
        return 'QUICK'
    return 'NORMAL'


class ChatContext(list):
    """Private request profile, not part of the JSON messages or user parameters."""
    def __init__(self, messages, level='NORMAL'):
        super().__init__(messages)
        self.fair_use_level = level


def request_text(content):
    if isinstance(content, list):
        content = ' '.join(b.get('text','') for b in content if isinstance(b, dict))
    # Extracted document text is evidence, not the user's reasoning/action intent.
    return str(content).split("\n\nTeks berikut berhasil diekstrak dari lampiran '", 1)[0]


def chat_profile(messages):
    current = request_text(next((m['content'] for m in reversed(messages) if m['role']=='user'), ''))
    tier = chat_tier(current)
    # An obvious short reference inherits recent analytical context without another API call.
    if len(current) < 160 and re.search(r'^(?:lanjut|terus|kenapa|knp|yang|yg|kalau|lebih murah|buat versi|yang simpel)\b', current.lower()):
        prior = [m['content'] for m in messages[:-1] if m['role'] == 'user' and isinstance(m['content'], str)]
        if any(chat_tier(text) == 'DEEP' for text in prior[-3:]):
            tier = 'DEEP'
    if getattr(messages, 'quality_retry', False):
        tier = 'DEEP'
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
