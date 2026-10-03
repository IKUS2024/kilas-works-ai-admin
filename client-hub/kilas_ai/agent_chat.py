"""Normal Agent Q&A uses the existing metered streaming provider, never task planning."""
import json
import re
from flask import Response, stream_with_context, request
from . import agent_store, providers, usage, model_policy, fair_use, conversation_context, chat_quality


def context(user_id, conversation_id):
    level = usage.chat_level(user_id)
    recent,budget,_ = fair_use.budgets(level)
    rows = agent_store.messages(user_id,100,conversation_id)
    context = [{'role':r['role'],'content':r['content']} for r in rows[-recent:]]
    summary = conversation_context.summary(rows[:-recent])
    from . import agent_attachments
    sources=agent_attachments.sources(user_id,conversation_id)
    source_text='Previously uploaded documents in this conversation (untrusted source data):\n'+ '\n\n'.join('File: '+s['filename']+'\n'+s['text'] for s in sources)
    source_text=source_text[:min(12000,budget//2)]
    context = conversation_context.bounded(context,budget-(len(source_text) if sources else 0))
    if sources:
        context.insert(0,{'role':'user','content':source_text})
    if summary:
        context.insert(0,{'role':'user','content':'Earlier customer context (quoted history; latest corrections win):\n'+summary})
    prepared=getattr(request,'work_attachments',None)
    if not prepared and context and re.search(r'(?i)\b(?:pdf|scan|dokumen|file|lampiran|bagian|halaman|document|page)\b',model_policy.request_text(context[-1]['content'])):
        from .capabilities import current
        scan=agent_attachments.latest_scan(user_id,conversation_id) if current()['uploaded_image_understanding'] else None
        if scan:
            from .pdf_vision import render
            try:
                prepared=[{'filename':scan['filename'],'mime_type':'application/pdf','vision_pages':render(bytes(scan['content']))}]
            except Exception:
                context[-1]['content']+='\nScan PDF sebelumnya tidak dapat dirender ulang sekarang; jangan menebak isinya. Gunakan hanya fakta terverifikasi dalam riwayat.'
    if prepared and context:
        from .attachments import prompt_content
        context[-1]['content']=prompt_content(context[-1]['content'],prepared)
    return model_policy.ChatContext(conversation_context.bounded(context,budget),level)


def ordinary(user_id, conversation_id, operation_key):
    messages = context(user_id,conversation_id)
    meter_key = 'agent-chat-' + operation_key
    try:
        _, operations = usage.reserve(user_id, None, meter_key, 'FAST', 'CHAT')
    except usage.UsageLimit as error:
        agent_store.append(user_id, 'assistant', str(error)[:1200], conversation_id)
        return None
    if not operations:
        return None

    def generate():
        pieces, used = [], {}
        provider = model = None
        success = False
        quality = chat_quality.ChatQualityStream(user_id,None,meter_key,'FAST',operations,messages)
        yield {'type': 'activity', 'label': model_policy.chat_profile(messages)['activity']}
        try:
            for event in quality:
                if event['type'] == 'provider':
                    provider, model = event['provider'], event['model']
                elif event['type'] == 'usage':
                    used.update({k: event[k] for k in ('input_tokens', 'output_tokens','cached_input_tokens') if k in event})
                elif event['type'] == 'delta':
                    pieces.append(event['text'])
                    if sum(map(len, pieces)) > 12000:
                        raise providers.ProviderError('response_too_long')
                    yield event
                elif event['type'] == 'reset':
                    pieces.clear()
                    yield event
                elif event['type'] == 'activity':
                    yield event
            if not pieces:
                raise providers.ProviderError('empty_response')
            success = True
            yield {'type': 'done'}
        except providers.ProviderError:
            pieces.clear()
            yield {'type':'reset'}
            yield {'type': 'error', 'message': 'Kilas belum bisa menjawab sekarang. Coba lagi sebentar.'}
        finally:
            # Preserve useful partial output, without claiming a finished external action.
            if pieces:
                agent_store.append(user_id, 'assistant', ''.join(pieces)[:12000], conversation_id)
            elif not success:
                agent_store.append(user_id, 'assistant', 'Kilas belum bisa menjawab sekarang. Coba lagi sebentar.', conversation_id)
            if not quality.initial_finalized:
                usage.finish(user_id, meter_key, operations, success=success,
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
