"""Native, exact-model tool turns. Only registered read/package tools are callable."""
import json
import os
import re
import requests
from . import chat_models,providers,selected_provider

TOOLS=[
 {'name':'list_files','description':'List uploaded source files available to this job. Read-only; never host files.','parameters':{'type':'object','properties':{},'required':[],'additionalProperties':False}},
 {'name':'read_file','description':'Read one uploaded source file; returns an explicit bounded excerpt and coverage.','parameters':{'type':'object','properties':{'name':{'type':'string'}},'required':['name'],'additionalProperties':False}},
 {'name':'publish_project','description':'Submit complete source files to deterministic path/syntax/ZIP validation. Requested execution is handled separately by the gated isolated executor. Include README, configuration and useful implementation.','parameters':{'type':'object','properties':{'files':{'type':'array','minItems':1,'maxItems':40,'items':{'type':'object','properties':{'name':{'type':'string'},'content':{'type':'string'}},'required':['name','content'],'additionalProperties':False}}},'required':['files'],'additionalProperties':False}},
]


class NativeFailure(providers.ProviderError):
    """Fixed diagnostics only. Never retain response text, tool arguments or keys."""
    def __init__(self,code,used=None,**diagnostic):
        super().__init__(code)
        self.code=code;self.usage=used or {};self.diagnostic={'code':code,**diagnostic}


def _usage(provider,data):
    value=data.get('usageMetadata' if provider=='google' else 'usage') or {}
    if not isinstance(value,dict):return {}
    def count(v):return v if type(v) is int and 0<=v<=10000000 else 0
    if provider=='openai':
        details=value.get('input_tokens_details') or {}
        if not isinstance(details,dict):details={}
        return {'input_tokens':count(value.get('input_tokens')),'output_tokens':count(value.get('output_tokens')),
                'cached_input_tokens':count(details.get('cached_tokens')),'cache_write_input_tokens':count(details.get('cache_write_tokens'))}
    if provider=='anthropic':return {'input_tokens':sum(count(value.get(k)) for k in ('input_tokens','cache_creation_input_tokens','cache_read_input_tokens')),'output_tokens':count(value.get('output_tokens')),'cached_input_tokens':count(value.get('cache_read_input_tokens')),'cache_write_input_tokens':count(value.get('cache_creation_input_tokens'))}
    return {'input_tokens':count(value.get('promptTokenCount')),'output_tokens':count(value.get('candidatesTokenCount'))+count(value.get('thoughtsTokenCount')),'cached_input_tokens':count(value.get('cachedContentTokenCount'))}


def _http_diagnostic(response):
    result={'phase':'http','http_status':getattr(response,'status_code',None)}
    try:
        error=response.json().get('error') or {}
        for key,allowed in {'code':{'invalid_function_parameters','unsupported_parameter','invalid_value','model_not_found','rate_limit_exceeded','insufficient_quota','server_error'},'type':{'invalid_request_error','server_error','rate_limit_error','insufficient_quota','authentication_error'}}.items():
            if error.get(key):result['provider_error_'+key]=error[key] if error[key] in allowed else 'other'
        param=error.get('param')
        if isinstance(param,str):result['provider_error_param']=param if len(param)<=160 and re.fullmatch(r'(?:model|max_output_tokens|reasoning\.effort|include|input|tools(?:\[\d{1,2}\])?(?:\.(?:parameters|properties|files|items|name|content|required|strict|type|additionalProperties))*)',param) else 'other'
    except (ValueError,AttributeError,TypeError):pass
    return result


def turn(model,history,instruction,output_tokens=8192,effort='medium'):
    """One paid request, never retried or silently sent to another model."""
    item=chat_models.check(model)
    if not item['available']:raise providers.ProviderError('selected_model_unavailable')
    provider=item['provider'];headers={'Content-Type':'application/json'}
    key=os.environ.get(chat_models.KEYS[provider],'').strip()
    if provider=='openai':
        url='https://api.openai.com/v1/responses';headers['Authorization']='Bearer '+key
        if os.environ.get('OPENAI_PROJECT_ID'):headers['OpenAI-Project']=os.environ['OPENAI_PROJECT_ID']
        payload={'model':model,'store':False,'instructions':instruction,'input':history,'max_output_tokens':output_tokens,
                 'tools':[{'type':'function',**tool,'strict':True} for tool in TOOLS],
                 'parallel_tool_calls':False,'tool_choice':'required','reasoning':{'effort':effort},'include':['reasoning.encrypted_content']}
    elif provider=='anthropic':
        url='https://api.anthropic.com/v1/messages';headers.update({'x-api-key':key,'anthropic-version':'2023-06-01'})
        payload={'model':model,'system':instruction,'messages':history,'max_tokens':output_tokens,
                 'tools':[{'name':t['name'],'description':t['description'],'input_schema':t['parameters']} for t in TOOLS]}
    else:
        url='https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent';headers['x-goog-api-key']=key
        payload={'systemInstruction':{'parts':[{'text':instruction}]},'contents':history,
                 'tools':[{'functionDeclarations':TOOLS}],
                 'generationConfig':{'maxOutputTokens':output_tokens}}
    used={};phase='transport';response=None
    try:
        response=requests.post(url,headers=headers,json=payload,timeout=(5,55));response.raise_for_status();phase='response_json';data=response.json()
        if not isinstance(data,dict):raise ValueError('invalid_response_root')
        used=_usage(provider,data);phase='model_identity'
        actual=data.get('model') if provider=='openai' else data.get('model') if provider=='anthropic' else data.get('modelVersion')
        if actual:selected_provider._returned(model,actual)
        calls=[];text=[]
        if provider=='openai':
            if data.get('status')!='completed':
                reason=(data.get('incomplete_details') or {}).get('reason')
                raise NativeFailure('native_incomplete',used,phase='response_status',status=data.get('status') if data.get('status') in ('incomplete','failed','cancelled','queued','in_progress') else 'other',incomplete_reason=reason if reason in ('max_output_tokens','content_filter') else 'other')
            raw=data.get('output',[]);phase='tool_parse'
            for block in raw:
                if block.get('type')=='function_call':calls.append({'id':block['call_id'],'name':block['name'],'arguments':json.loads(block['arguments'])})
                if block.get('type')=='message':text.extend(p.get('text','') for p in block.get('content',[]) if p.get('type')=='output_text')
        elif provider=='anthropic':
            if data.get('stop_reason') not in ('tool_use','end_turn'):raise NativeFailure('native_incomplete',used,phase='response_status')
            raw=data.get('content',[]);phase='tool_parse'
            for block in raw:
                if block.get('type')=='tool_use':calls.append({'id':block['id'],'name':block['name'],'arguments':block['input']})
                if block.get('type')=='text':text.append(block['text'])
        else:
            candidate=data['candidates'][0]
            if candidate.get('finishReason')!='STOP':raise NativeFailure('native_incomplete',used,phase='response_status')
            raw=candidate['content'];phase='tool_parse'
            for block in raw.get('parts',[]):
                if 'functionCall' in block:calls.append({'id':block['functionCall'].get('id',block['functionCall']['name']),'name':block['functionCall']['name'],'arguments':block['functionCall'].get('args',{})})
                if 'text' in block and not block.get('thought'):text.append(block['text'])
        if len(calls)>4 or any(call['name'] not in {t['name'] for t in TOOLS} or not isinstance(call['arguments'],dict) for call in calls):raise ValueError('invalid_tool_call')
        if not calls:raise NativeFailure('native_missing_tool',used,phase='tool_parse')
        if provider=='openai':history.extend(raw)
        elif provider=='anthropic':history.append({'role':'assistant','content':raw})
        else:history.append(raw)
        return {'calls':calls,'text':'\n'.join(text),'usage':used,'model_provenance':{'requested_model':model,'returned_model':actual or 'unreported','provider':provider}}
    except NativeFailure:raise
    except requests.HTTPError:
        raise NativeFailure('native_http_error',used,**_http_diagnostic(response)) from None
    except requests.RequestException:
        raise NativeFailure('native_transport_error',used,phase=phase) from None
    except (ValueError,TypeError,KeyError,IndexError,AttributeError,providers.ProviderError):
        raise NativeFailure('native_invalid_response',used,phase=phase) from None


def initial(provider,prompt):
    return [{'role':'user','parts':[{'text':prompt}]}] if provider=='google' else [{'role':'user','content':prompt}]


def tool_results(provider,history,results):
    if provider=='openai':history.extend({'type':'function_call_output','call_id':call['id'],'output':json.dumps(result)} for call,result in results)
    elif provider=='anthropic':history.append({'role':'user','content':[{'type':'tool_result','tool_use_id':call['id'],'content':json.dumps(result)} for call,result in results]})
    else:history.append({'role':'user','parts':[{'functionResponse':{'name':call['name'],'response':result,**({'id':call['id']} if call['id']!=call['name'] else {})}} for call,result in results]})
