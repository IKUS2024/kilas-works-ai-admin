"""MANUAL ONLY. Never called by CI/deploy; structural acceptance, not truth proof."""
import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    if os.environ.get('KILAS_CHAT_LIVE_EVAL') != 'I_ACCEPT_LUNA_API_COST':
        parser.error('Manual evaluation requires KILAS_CHAT_LIVE_EVAL=I_ACCEPT_LUNA_API_COST')
    if os.environ.get('CI') or os.environ.get('RENDER'):
        parser.error('Manual evaluation is disabled in CI/deploy environments')
    if not os.environ.get('OPENAI_API_KEY'):
        parser.error('Explicit OPENAI_API_KEY configuration required')
    if not 1 <= args.limit <= 20:
        parser.error('--limit must be between 1 and 20')
    sys.path.insert(0, str(Path(__file__).parents[1]))
    from kilas_ai import providers, model_policy, chat_quality
    if model_policy.luna_model() != model_policy.LUNA:
        parser.error('Luna only')
    cases = json.loads((Path(__file__).parents[1]/'tests/fixtures/kilas_conversation_standard.json').read_text())
    # One representative per category, never real customer messages or identifiers.
    selected, seen = [], set()
    for case in cases:
        if case['category'] not in seen:
            selected.append(case)
            seen.add(case['category'])
        if len(selected) == args.limit:
            break
    report = []
    for case in selected:
        messages = model_policy.ChatContext(case.get('turns') or [
            {'role':'user','content':case['first_user']},
            {'role':'assistant','content':case['prior_assistant']},
            {'role':'user','content':case['follow_up']}])
        text, finish, tokens = [], None, {}
        try:
            for event in providers.stream('SMART',messages):
                if event['type']=='delta':text.append(event['text'])
                elif event['type']=='finish':finish=event['reason']
                elif event['type']=='usage':tokens={k:v for k,v in event.items() if k.endswith('_tokens')}
            errors=chat_quality.violations(case['follow_up'],''.join(text),tier=model_policy.chat_profile(messages)['tier'],finish=finish)
        except providers.ProviderError:
            errors=['provider_unavailable']
        report.append({'id':case['id'],'structural_flags':errors,'usage':tokens})
    print(json.dumps({'label':'Manual model acceptance; structural checks only, not deterministic proof of answer quality',
                      'model':model_policy.LUNA,'cases':report},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
