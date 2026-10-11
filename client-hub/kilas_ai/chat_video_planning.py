"""Reuse the existing director's creative rules in ordinary metered AI Chat."""
import re

VIDEO = re.compile(r'(?i)\b(?:storyboard|video plan|konsep video|ide video|rencana video|video concept|video prompt|prompt video|naskah video|video script|shot list)\b')


def requested(text):
    return bool(VIDEO.search(str(text)))


def instruction(messages):
    from .model_policy import request_text
    users=[request_text(m['content']) for m in messages if m['role']=='user']
    if not users:return ''
    latest=users[-1]
    followup=len(latest)<200 and re.search(r'(?i)\b(?:ubah|ganti|lanjut|yang tadi|change|revise|continue|scene|shot|adegan|prompt)\b',latest)
    if not (requested(latest) or (followup and any(requested(t) for t in users[-4:-1]))):return ''
    from .video_director import STANDARD
    creative=STANDARD.split('Return all string fields:',1)[0]
    creative=creative.replace('Produce a UNIVERSAL VIDEO SPEC as JSON, not a rendered video, image, tool call or proprietary model instructions.',
                             'Prepare a usable concept, storyboard and production prompts in this conversation. Do not claim a rendered video or an external action.')
    return creative+'\nChat presentation: use readable Markdown, with concept/hook, a timed scene table, continuity constraints and complete English production prompts when requested. Scripts follow the requested audience language. Preserve latest corrections and supplied product facts. This conversation stores the plan; do not redirect to a separate Video Plan tab or start video generation.'
