"""Exact-model Chat transport. Native APIs, one attempt, no model substitution."""
import json
import os
import re
import requests
from . import providers, chat_models, model_policy, capabilities


def _returned(requested, value):
    if value is None: return None
    if not isinstance(value,str) or not (value == requested or re.fullmatch(re.escape(requested)+r'-(?:20\d\d-\d\d-\d\d|\d{3})',value)):
        raise providers.ProviderError('selected_model_mismatch')
    return value


def _parts(content, google=False):
    if isinstance(content,str): return [{'text':content}] if google else content
    result=[]
    for block in content:
        if block['type']=='text': result.append({'text':block['text']} if google else block)
        elif block['type']=='image_url':
            data=block['image_url']['url']
            match=re.fullmatch(r'data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)',data)
            if not match: raise providers.ProviderError('selected_attachment_unsupported')
            result.append({'inlineData':{'mimeType':match[1],'data':match[2]}} if google else
                {'type':'image','source':{'type':'base64','media_type':match[1],'data':match[2]}})
        else: raise providers.ProviderError('selected_attachment_unsupported')
    return result


def stream(mode, messages, system=None):
    model=messages.selected_model
    item=chat_models.spec(model)
    provider=item['provider']
    try:chat_models.validate_messages(model,messages)
    except chat_models.SelectionError:
        raise providers.ProviderError('selected_model_unavailable') from None
    key=os.environ.get(chat_models.KEYS[provider],'').strip()
    profile=model_policy.chat_profile(messages)
    facts=capabilities.current()
    facts.update(conversation=True, uploaded_image_understanding=chat_models.check(model)['images'])
    system=(providers.SYSTEM if system is None else system)+'\nCurrent runtime capabilities: '+json.dumps(facts)+'. '
    system+='The selected Chat model is '+item['name']+'. Use only actual tool evidence; never claim to execute code or actions in Chat. '
    system+=model_policy.intelligence.playbook(profile)
    headers={'Content-Type':'application/json'}
    if provider=='openai':
        url='https://api.openai.com/v1/chat/completions'
        headers['Authorization']='Bearer '+key
        if os.environ.get('OPENAI_PROJECT_ID'):headers['OpenAI-Project']=os.environ['OPENAI_PROJECT_ID']
        payload={'model':model,'messages':[{'role':'system','content':system}]+list(messages),
                 'max_completion_tokens':profile['output_tokens'],'reasoning_effort':profile['effort'],
                 'stream':True,'stream_options':{'include_usage':True},'store':False}
    elif provider=='anthropic':
        url='https://api.anthropic.com/v1/messages'
        headers.update({'x-api-key':key,'anthropic-version':'2023-06-01'})
        payload={'model':model,'system':system,'messages':[{'role':m['role'],'content':_parts(m['content'])} for m in messages],
                 'max_tokens':profile['output_tokens'],'thinking':{'type':'adaptive'},
                 'output_config':{'effort':profile['effort']},'stream':True}
    else:
        url='https://generativelanguage.googleapis.com/v1beta/models/'+model+':streamGenerateContent?alt=sse'
        headers['x-goog-api-key']=key
        contents=[]
        for m in messages:
            role='model' if m['role']=='assistant' else 'user'
            parts=_parts(m['content'],True)
            if contents and contents[-1]['role']==role:contents[-1]['parts'].extend(parts)
            else:contents.append({'role':role,'parts':parts})
        payload={'systemInstruction':{'parts':[{'text':system}]},'contents':contents,
                 'generationConfig':{'maxOutputTokens':profile['output_tokens'], 'thinkingConfig':{'thinkingLevel':profile['effort'].upper()}}}
    yield {'type':'provider','provider':provider,'model':model}
    try:
        with requests.post(url,headers=headers,json=payload,stream=True,timeout=(10,90)) as response:
            response.raise_for_status()
            reported=None
            for event in providers._events(response):
                raw_model=event.get('model') if provider=='openai' else (event.get('message') or {}).get('model') if provider=='anthropic' else event.get('modelVersion')
                if raw_model:
                    actual=_returned(model,raw_model)
                    if actual!=reported:
                        reported=actual
                        yield {'type':'model_metadata','requested_model':model,'returned_model':actual,'provider':provider}
                if provider=='openai':
                    used=event.get('usage') or {}
                    if used:yield {'type':'usage','input_tokens':used.get('prompt_tokens',0),'output_tokens':used.get('completion_tokens',0),
                        'cached_input_tokens':(used.get('prompt_tokens_details') or {}).get('cached_tokens',0),
                        'cache_write_input_tokens':(used.get('prompt_tokens_details') or {}).get('cache_write_tokens',0)}
                    choice=(event.get('choices') or [{}])[0]
                    text=(choice.get('delta') or {}).get('content')
                    finish=choice.get('finish_reason')
                elif provider=='anthropic':
                    if event.get('type')=='error':raise providers.ProviderError('selected_provider_error')
                    used=(event.get('message') or {}).get('usage') or event.get('usage') or {}
                    if used:
                        tokens={'type':'usage'}
                        if 'input_tokens' in used:
                            cached=used.get('cache_read_input_tokens',0);writes=used.get('cache_creation_input_tokens',0)
                            tokens.update(input_tokens=used['input_tokens']+cached+writes,cached_input_tokens=cached,cache_write_input_tokens=writes)
                        if 'output_tokens' in used:tokens['output_tokens']=used['output_tokens']
                        yield tokens
                    delta=event.get('delta') or {}
                    text=delta.get('text') if delta.get('type')=='text_delta' else None
                    finish=delta.get('stop_reason')
                else:
                    used=event.get('usageMetadata') or {}
                    if used:yield {'type':'usage','input_tokens':used.get('promptTokenCount',0),
                        'output_tokens':used.get('candidatesTokenCount',0)+used.get('thoughtsTokenCount',0),
                        'cached_input_tokens':used.get('cachedContentTokenCount',0)}
                    candidate=(event.get('candidates') or [{}])[0]
                    text=''.join(p.get('text','') for p in candidate.get('content',{}).get('parts',[]) if not p.get('thought'))
                    finish=candidate.get('finishReason')
                    if event.get('promptFeedback',{}).get('blockReason'):raise providers.ProviderError('selected_provider_filtered')
                if isinstance(text,str) and text:yield {'type':'delta','text':text}
                if finish:
                    reason={'end_turn':'stop','stop_sequence':'stop','STOP':'stop','MAX_TOKENS':'length',
                            'max_tokens':'length','SAFETY':'refusal','RECITATION':'refusal',
                            'PROHIBITED_CONTENT':'refusal'}.get(finish,finish)
                    if reason not in ('stop','length','refusal','content_filter'):
                        raise providers.ProviderError('selected_provider_incomplete')
                    yield {'type':'finish','reason':reason}
            if reported is None:yield {'type':'model_metadata','requested_model':model,'returned_model':None,'provider':provider}
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        raise providers.ProviderError('selected_provider_unavailable') from None
