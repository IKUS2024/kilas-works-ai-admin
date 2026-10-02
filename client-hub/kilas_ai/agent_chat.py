"""Normal Agent Q&A uses the existing metered streaming provider, never task planning."""
import json
from flask import Response, stream_with_context, request
from . import agent_store, providers, usage, agent_response_style


def ordinary(user_id, conversation_id, operation_key):
    context = [{'role': r['role'], 'content': r['content']} for r in agent_store.messages(user_id, 12, conversation_id)]
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
        yield {'type': 'activity', 'label': 'Thinking…'}
        try:
            for event in providers.stream('FAST', context, agent_response_style.CHAT):
                if event['type'] == 'provider':
                    provider, model = event['provider'], event['model']
                elif event['type'] == 'usage':
                    used.update({k: event[k] for k in ('input_tokens', 'output_tokens') if k in event})
                elif event['type'] == 'delta':
                    pieces.append(event['text'])
                    if sum(map(len, pieces)) > 2400:
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
                agent_store.append(user_id, 'assistant', ''.join(pieces)[:2400], conversation_id)
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
