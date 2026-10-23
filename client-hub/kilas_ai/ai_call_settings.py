"""Strict, call-local preferences. No account or cross-call learning state."""
LANGUAGES = {'id':'Indonesian','en':'English','es':'Spanish','fr':'French','de':'German',
             'ja':'Japanese','ko':'Korean','zh':'Mandarin Chinese','ar':'Arabic','pt':'Portuguese'}
DEFAULTS = dict(mode='normal',character='friendly',target_language='en',level='beginner',
                explanation_language='id',scenario='interview',roast_opt_in=False)
CHOICES = dict(mode={'normal','learning','roleplay','roast'},character={'friendly','casual','firm','roast'},
               target_language=set(LANGUAGES),explanation_language=set(LANGUAGES),
               level={'beginner','intermediate','advanced'},scenario={'interview','airport','customer'})


def validate(value=None):
    if value is None:value={}
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):raise ValueError('call_settings_invalid')
    result={**DEFAULTS,**value}
    for key,choices in CHOICES.items():
        if not isinstance(result[key],str) or result[key] not in choices:raise ValueError('call_settings_invalid')
    if type(result['roast_opt_in']) is not bool:raise ValueError('call_settings_invalid')
    if result['mode']=='roast':
        if not result['roast_opt_in'] or result['character']!='roast':raise ValueError('call_settings_invalid')
    elif result['character']=='roast' or result['roast_opt_in']:raise ValueError('call_settings_invalid')
    return result


def instructions(settings):
    s=validate(settings)
    style={'friendly':'Warm, friendly and encouraging.', 'casual':'Relaxed, conversational and informal.',
           'firm':'Direct, candid and firm without humiliation.', 'roast':'Playfully sharp and irreverent.'}[s['character']]
    text=' Selected character: '+style+' '
    if s['mode']=='learning':
        text+=f"Language practice: use {LANGUAGES[s['target_language']]} for conversation at {s['level']} level. Explain corrections in {LANGUAGES[s['explanation_language']]}. The selected target overrides the initial-language rule. Give a brief natural correction with an improved example when useful, then continue conversational practice with one question. Adapt to requests for deeper grammar explanations. "
    elif s['mode']=='roleplay':
        scene={'interview':'a job interview; you are the interviewer','airport':'an airport check-in; you are the airport agent','customer':'a customer conversation; you are the customer'}[s['scenario']]
        text+=f'Practice a fictional roleplay of {scene}. Start with a short scene cue when the person speaks, then take natural turns. Offer feedback when requested; never claim real bookings or transactions. '
    elif s['mode']=='roast':
        text+='The person explicitly opted into coarse playful roasting of themselves. Maintain a consistently casual, slang-heavy and coarse persona across turns; do not drift back to formal politeness. Use natural profanity such as Indonesian anjing, bangsat, English fuck, or analogous slang in the conversation language. Be spontaneous and responsive to what the person actually says, not stiff or scripted; do not mechanically attach a swear word to every sentence. Stay helpful and substantive. For sensitive distress, grief or safety concerns, suspend roasting and respond supportively without mockery. Consent covers this person only, never nonconsenting third parties. No threats, protected-group hate, dangerous encouragement, or coercion. Respect provider safeguards; no word or angry vocal delivery is guaranteed. If the person asks to stop, becomes uncomfortable, or requests normal conversation, immediately drop the roast and profanity for the rest of this call. '
    if s['mode']!='roast':text+='No coarse roasting or insulting profanity in this mode, even as a character trait. '
    return text+'Use listenable turns, with pauses for participation rather than an unsolicited monologue. Explain in depth when asked. '
