"""Bounded public opening question; no model call or learner content required."""
TARGETS={'id':{'en':'Inggris','zh':'Mandarin','es':'Spanyol'},
         'en':{'en':'English','zh':'Mandarin','es':'Spanish'},
         'zh':{'en':'英语','zh':'普通话','es':'西班牙语'},
         'es':{'en':'inglés','zh':'chino mandarín','es':'español'}}


def text(settings):
    native=settings['native'];target=TARGETS[native][settings['target']]
    if native=='id':return f'Halo, aku tutor bahasa {target}. Penjelasannya mau bahasa Indonesia atau {target}?'
    if native=='en':
        return "Hi, I'm your English tutor. Shall we use English for explanations too?" if settings['target']=='en' else f"Hi, I'm your {target} tutor. Explanations in English or {target}?"
    if native=='zh':
        return '你好，我是你的普通话老师。解释也用中文，可以吗？' if settings['target']=='zh' else f'你好，我是你的{target}老师。解释用中文还是{target}？'
    teacher='tutora' if settings.get('voice')=='kilas-female' else 'tutor'
    return f'Hola, soy tu {teacher} de español. ¿Explicaciones en español también?' if settings['target']=='es' else f'Hola, soy tu {teacher} de {target}. ¿Explicaciones en español o {target}?'
