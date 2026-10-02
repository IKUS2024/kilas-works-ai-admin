"""One deterministic customer entry; shared Chat quality and existing Work execution."""
import json
import re
from flask import Response, request, session, redirect, stream_with_context, url_for
from . import agent_chat, agent_store, routing, usage, tools, work_runtime, work_schedule, work_documents, work_artifacts, model_policy


def intent(text, prepared=(), previous=None):
    if work_schedule.REMINDER.search(text) or re.match(r'(?i)^(?:setiap|tiap|every)\b',text):
        return 'SCHEDULE'
    if work_schedule.CAPABILITY.search(text) and not routing.fresh_information(routing._normalize(text)):
        return 'CHAT'
    from .agent_intents import infer
    planned=infer(text)
    if planned and planned['mode'] in ('SCHEDULED','RECURRING','CONTINUOUS','CONDITION_WATCH'):
        return 'WORK'
    images=list(prepared)
    if previous and previous['media_type'].startswith('image/') and routing.may_edit_image(text):
        images.append({'mime_type':previous['media_type']})
    tool=routing.tool_for(text,images,has_previous_content=bool(previous))
    if tool in ('WEB','IMAGE_GENERATE','IMAGE_EDIT'):
        return tool
    if routing.explicit_code(text):return 'CHAT'
    if work_documents.intent(text,bool(previous and not previous['media_type'].startswith('image/'))):return 'DOCUMENT'
    return tool


def dispatch(owner,text,key,conversation):
    prepared=getattr(request,'work_attachments',[])
    previous=next(iter(work_artifacts.listing(owner,conversation_id=conversation)),None)
    selected=intent(text,prepared,previous)
    from . import agent_intents, autonomous_store
    pending=any(session.get(k) for k in ('work_document_pending','work_reminder_pending','work_location_request','agent_work_clarification'))
    waiting=any(j['last_error']=='waiting_input' for j in autonomous_store.list_jobs(owner,conversation_id=conversation,active_only=True))
    from .agent_planner import required_connection
    lifecycle=bool(agent_intents.CONTROL.fullmatch(text.strip()) or agent_intents.FEEDBACK.search(text) or required_connection(text) or re.search(r'(?i)\b(?:jam berapa sekarang|what time is it|waktu sekarang|dekat sini|lokasi saya|near me|nearby|tempat terdekat)\b|^(?:ulang (?:tiap|setiap)|jangan tiap hari|ubah .*jadi (?:jam|pukul))',text))
    if lifecycle or ((pending or waiting) and selected=='CHAT' and not work_schedule.CAPABILITY.search(text)):
        return work_runtime.handle(owner,text,key,conversation)
    if selected=='WEB':return search(owner,key,conversation)
    if selected=='CHAT':
        transformation=re.search(r'(?i)\b(?:benerin typo|perbaiki typo|ubah kalimat|tulis ulang|rewrite|translate|terjemahkan)\b',text)
        if not transformation and not routing.explicit_code(text) and not work_schedule.CAPABILITY.search(text) and agent_intents.infer(text):
            return work_runtime.handle(owner,text,key,conversation)
        return agent_chat.ordinary(owner,conversation,key) or redirect(url_for('kilas_ai.agent_home'),code=303)
    if selected=='IMAGE_EDIT' and previous and previous['media_type'].startswith('image/') and not any(p['mime_type'].startswith('image/') for p in prepared):
        text=('Edit gambar sebelumnya: '+text)[:1200]
    if selected=='SCHEDULE' and not work_schedule.REMINDER.search(text) and re.match(r'(?i)^(?:setiap|tiap|every)\b',text) and not re.search(r'(?i)\b(?:buat|riset|research|pantau|monitor|kerjakan)\b',text):
        text='ingatkan '+text
    return work_runtime.handle(owner,text,key,conversation)


def search(owner,key,conversation):
    context=agent_chat.context(owner,conversation)
    meter='agent-web-'+key
    mode=routing.mode_for(model_policy.request_text(context[-1]['content']))
    try:plan,operations=usage.reserve(owner,None,meter,mode,'WEB')
    except usage.UsageLimit as error:return work_runtime.reply(owner,str(error),conversation)
    if not operations:return work_runtime.reply(owner,'Permintaan ini sudah diterima.',conversation)
    def generate():
        success=False;used={};model=None
        try:
            yield {'type':'activity','label':'Mencari informasi terbaru…'}
            result=None
            for update in tools.web_search_steps(context,mode=mode,plan=plan,max_calls=usage.web_call_budget(owner,plan) if tools.research_requested(context) else 1):
                if 'activity' in update:yield {'type':'activity','label':update['activity']}
                else:result=update['result']
            if not result or not result.get('citations'):raise tools.ToolUnavailable('sources_missing')
            model=result['model'];used=result['usage']
            from .agent_results import compact_sources
            sources=compact_sources(result['citations'])[:8]
            if not sources:raise tools.ToolUnavailable('sources_missing')
            text=result['text']
            links=['['+s['title'].replace('[','').replace(']','')+']('+s['url']+')' for s in sources if s['url'] not in text]
            if links:text+='\n\nSumber: '+', '.join(links)
            agent_store.append(owner,'assistant',text[:12000],conversation)
            success=True
            yield {'type':'delta','text':text[:12000]}
            yield {'type':'done'}
        except Exception:
            agent_store.append(owner,'assistant','Informasi terbaru belum dapat diperiksa. Coba lagi sebentar.',conversation)
            yield {'type':'error','message':'Informasi terbaru belum dapat diperiksa. Coba lagi sebentar.'}
        finally:usage.finish(owner,meter,operations,success=success,provider='openai' if model else None,model=model,usage=used)
    if request.headers.get('X-Agent-Chat')=='1':
        return Response(stream_with_context(('data: '+json.dumps(event,ensure_ascii=False)+'\n\n' for event in generate())),mimetype='text/event-stream',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
    for _ in generate():pass
    return redirect(url_for('kilas_ai.agent_home',conversation=conversation),code=303)
