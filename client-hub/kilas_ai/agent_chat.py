"""Normal Agent Q&A uses the existing metered streaming provider, never task planning."""
import json
from flask import Response, stream_with_context, request
from . import agent_store, providers, usage, agent_response_style, model_policy, fair_use, conversation_context


def ordinary(user_id, conversation_id, operation_key):
    level = usage.chat_level(user_id)
    recent,budget,_ = fair_use.budgets(level)
    rows = agent_store.messages(user_id,100,conversation_id)
    context = [{'role':r['role'],'content':r['content']} for r in rows[-recent:]]
    summary = conversation_context.summary(rows[:-recent])
    context = conversation_context.bounded(context,budget)
    if summary:
        context.insert(0,{'role':'user','content':'Earlier customer context (quoted history; latest corrections win):\n'+summary})
    prepared=getattr(request,'work_attachments',None)
    if prepared and context:
        from .attachments import prompt_content
        context[-1]['content']=prompt_content(context[-1]['content'],prepared)
    context = model_policy.ChatContext(context,level)
    try:
        _, operations = usage.reserve(user_id, None, 'agent-chat-' + operation_key, 'FAST', 'CHAT')
    except usage.UsageLimit as error:
        agent_store.append(user_id, 'assistant', str(error)[:1200], conversation_id)
        return None
    if not operations:
        return None

    def generate():
        pieces, used = [], {}
        provider = model = None
        success = False
        yield {'type': 'activity', 'label': model_policy.chat_profile(context)['activity']}
        try:
            work_style = agent_response_style.CHAT + '\nWork supports public research, files, source analysis, reminders and configured coding. It cannot access connected Google accounts, send messages or interact with arbitrary websites. Do not claim unavailable capabilities or completed work without a real result. Capability questions are conversational, not task execution.'
            for event in providers.stream('FAST', context, work_style):
                if event['type'] == 'provider':
                    provider, model = event['provider'], event['model']
                elif event['type'] == 'usage':
                    used.update({k: event[k] for k in ('input_tokens', 'output_tokens','cached_input_tokens') if k in event})
                elif event['type'] == 'delta':
                    pieces.append(event['text'])
                    if sum(map(len, pieces)) > 12000:
                        raise providers.ProviderError('response_too_long')
                    yield event
            if not pieces:
                raise providers.ProviderError('empty_response')
            success = True
            yield {'type': 'done'}
        except providers.ProviderError:
            yield {'type': 'error', 'message': 'Kilas belum bisa menjawab sekarang. Coba lagi sebentar.'}
        finally:
            # Preserve useful partial output, without claiming a finished external action.
            if pieces:
                agent_store.append(user_id, 'assistant', ''.join(pieces)[:12000], conversation_id)
            elif not success:
                agent_store.append(user_id, 'assistant', 'Kilas belum bisa menjawab sekarang. Coba lagi sebentar.', conversation_id)
            usage.finish(user_id, 'agent-chat-' + operation_key, operations, success=success,
                         provider=provider, model=model, usage=used)

    if request.headers.get('X-Agent-Chat') == '1':
        def events():
            for event in generate():
                yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
        return Response(stream_with_context(events()), mimetype='text/event-stream',
                        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
    for _ in generate():
        pass
    return None
