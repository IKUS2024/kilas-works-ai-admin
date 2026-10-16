"""SELECT-only restoration evidence; never creates a session or provider call."""
import os
import db
from . import audio_branded_voices as voices, audio_transcription_budget as budget
from . import free_test, live_translator as live, live_translator_realtime as realtime
from . import live_translator_store as sessions


def report():
    config = budget.policy()
    owner = (config or {}).get('allowed_owner')
    other = db.query_one('SELECT id FROM users WHERE id<>? ORDER BY id LIMIT 1', (owner or 0,))

    def account(user):
        if type(user) is not int:
            return {'configured_ready':False}
        return {'user_id':user, 'configured_ready':live.ready(user),
                'input_mode':'realtime-v1' if realtime.ready(user) else 'batch',
                'sponsored':free_test.eligible(user), 'session_busy':bool(sessions.active(user))}

    return {'selected_provider':os.environ.get('KILAS_TRANSLATOR_PROVIDER','elevenlabs'),
            'audience':'authenticated' if free_test.active() else 'existing_entitlements',
            'owner':account(owner), 'nonowner':account(other['id'] if other else None),
            'voices':voices.public_choices(), 'silence_endpoint_ms':2000,
            'stt_global_budget_micro_usd':(config or {}).get('global_micro'),
            'stt_account_budget_micro_usd':(config or {}).get('account_micro'),
            'whole_utterance':True, 'paid_qa':False}
