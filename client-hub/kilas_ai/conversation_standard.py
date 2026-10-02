"""Stable runtime standard plus an offline evaluation contract (no fixture injection)."""
from .response_style import CHAT_SYSTEM

SYSTEM = CHAT_SYSTEM
EVALUATION_DIMENSIONS = ('language_and_tone','answers_question','context_continuity',
    'correction_priority','useful_depth','honest_uncertainty','no_invented_action',
    'no_internal_terminology','no_canned_filler')
