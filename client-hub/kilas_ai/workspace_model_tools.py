"""Native, exact-model tool turns. Only registered read/package tools are callable."""
import json
import os
import requests
from . import chat_models,providers,selected_provider

TOOLS=[
 {'name':'list_files','description':'List uploaded source files available to this job. Read-only; never host files.','parameters':{'type':'object','properties':{},'required':[],'additionalProperties':False}},
 {'name':'read_file','description':'Read one uploaded source file; returns an explicit bounded excerpt and coverage.','parameters':{'type':'object','properties':{'name':{'type':'string'}},'required':['name'],'additionalProperties':False}},
 {'name':'publish_project','description':'Submit complete source files to deterministic path/syntax/ZIP validation. Requested execution is handled separately by the gated isolated executor. Include README, configuration and useful implementation.','parameters':{'type':'object','properties':{'files':{'type':'array','minItems':1,'maxItems':40,'items':{'type':'object','properties':{'name':{'type':'string'},'content':{'type':'string'}},'required':['name','content'],'additionalProperties':False}}},'required':['files'],'additionalProperties':False}},
]


def turn(model,history,instruction,output_tokens=8192):
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
                 'parallel_tool_calls':False,'reasoning':{'effort':'medium'},'include':['reasoning.encrypted_content']}
    elif provider=='anthropic':
        url='https://api.anthropic.com/v1/messages';headers.update({'x-api-key':key,'anthropic-version':'2023-06-01'})
        payload={'model':model,'system':instruction,'messages':history,'max_tokens':output_tokens,
                 'tools':[{'name':t['name'],'description':t['description'],'input_schema':t['parameters']} for t in TOOLS]}
    else:
        url='https://generativelanguage.googleapis.com/v1beta/models/'+model+':generateContent';headers['x-goog-api-key']=key
        payload={'systemInstruction':{'parts':[{'text':instruction}]},'contents':history,
                 'tools':[{'functionDeclarations':TOOLS}],
                 'generationConfig':{'maxOutputTokens':output_tokens}}
    try:
        response=requests.post(url,headers=headers,json=payload,timeout=(5,55));response.raise_for_status();data=response.json()
        actual=data.get('model') if provider=='openai' else data.get('model') if provider=='anthropic' else data.get('modelVersion')
        if actual:selected_provider._returned(model,actual)
        calls=[];text=[]
        if provider=='openai':
            if data.get('status') not in ('completed',):raise ValueError('incomplete_tool_turn')
            raw=data.get('output',[]);history.extend(raw)
            for block in raw:
                if block.get('type')=='function_call':calls.append({'id':block['call_id'],'name':block['name'],'arguments':json.loads(block['arguments'])})
                if block.get('type')=='message':text.extend(p.get('text','') for p in block.get('content',[]) if p.get('type')=='output_text')
            tokens=data.get('usage') or {};used={'input_tokens':tokens.get('input_tokens',0),'output_tokens':tokens.get('output_tokens',0)}
        elif provider=='anthropic':
            if data.get('stop_reason') not in ('tool_use','end_turn'):raise ValueError('incomplete_tool_turn')
            raw=data.get('content',[]);history.append({'role':'assistant','content':raw})
            for block in raw:
                if block.get('type')=='tool_use':calls.append({'id':block['id'],'name':block['name'],'arguments':block['input']})
                if block.get('type')=='text':text.append(block['text'])
            tokens=data.get('usage') or {};used={'input_tokens':tokens.get('input_tokens',0)+tokens.get('cache_creation_input_tokens',0)+tokens.get('cache_read_input_tokens',0),'output_tokens':tokens.get('output_tokens',0)}
        else:
            candidate=data['candidates'][0]
            if candidate.get('finishReason')!='STOP':raise ValueError('incomplete_tool_turn')
            raw=candidate['content'];history.append(raw)
            for block in raw.get('parts',[]):
                if 'functionCall' in block:calls.append({'id':block['functionCall'].get('id',block['functionCall']['name']),'name':block['functionCall']['name'],'arguments':block['functionCall'].get('args',{})})
                if 'text' in block and not block.get('thought'):text.append(block['text'])
            tokens=data.get('usageMetadata') or {};used={'input_tokens':tokens.get('promptTokenCount',0),'output_tokens':tokens.get('candidatesTokenCount',0)+tokens.get('thoughtsTokenCount',0)}
        if len(calls)>4 or any(call['name'] not in {t['name'] for t in TOOLS} or not isinstance(call['arguments'],dict) for call in calls):raise ValueError('invalid_tool_call')
        return {'calls':calls,'text':'\n'.join(text),'usage':used,'model_provenance':{'requested_model':model,'returned_model':actual or 'unreported','provider':provider}}
    except (requests.RequestException,ValueError,TypeError,KeyError,IndexError):
        raise providers.ProviderError('workspace_provider_failed') from None


def initial(provider,prompt):
    return [{'role':'user','parts':[{'text':prompt}]}] if provider=='google' else [{'role':'user','content':prompt}]


def tool_results(provider,history,results):
    if provider=='openai':history.extend({'type':'function_call_output','call_id':call['id'],'output':json.dumps(result)} for call,result in results)
    elif provider=='anthropic':history.append({'role':'user','content':[{'type':'tool_result','tool_use_id':call['id'],'content':json.dumps(result)} for call,result in results]})
    else:history.append({'role':'user','parts':[{'functionResponse':{'name':call['name'],'response':result,**({'id':call['id']} if call['id']!=call['name'] else {})}} for call,result in results]})
