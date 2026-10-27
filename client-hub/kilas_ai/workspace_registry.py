"""Documented API facts versus implemented workspace features; never infer parity."""
CHECKED_ON='2026-10-27'


def chat(model):
    from . import chat_models
    item=chat_models.spec(model);provider=item['provider']
    source=('https://developers.openai.com/api/docs/models/'+model if provider=='openai' else
            'https://platform.claude.com/docs/en/models/overview' if provider=='anthropic' else
            'https://ai.google.dev/gemini-api/docs/models/'+model)
    context=1050000 if provider=='openai' else 1000000 if provider=='anthropic' else 1048576
    output=128000 if provider in ('openai','anthropic') else 65536
    endpoint={'openai':'/v1/chat/completions','anthropic':'/v1/messages','google':'/v1beta/models/'+model+':streamGenerateContent'}[provider]
    return {**item,'source':source,'documentation_checked_on':CHECKED_ON,'ordinary_chat_endpoint':endpoint,
            'workspace_tool_endpoint':'/v1/responses' if provider=='openai' else '/v1/messages' if provider=='anthropic' else '/v1beta/models/'+model+':generateContent',
            'documented_context_tokens':context,'documented_output_tokens':output,
            'documented_long_decode_tokens':1048576 if model=='gemini-4-argon' else None,
            'app_context_characters':64000,'app_max_output_tokens':24576,
            'vision':True,'streaming':True,'native_function_calling':True,'structured_output_documented':True,
            'reasoning':'adaptive' if provider=='anthropic' else ['low','medium','high'],
            'native_pdf_input_used':False,'file_input_mode':'bounded extracted text and selected PDF page images; Office/ZIP never executed',
            'tool_scope':['list_files','read_file','publish_project'],'provider_code_execution_enabled':False,
            'reasoning_summary_exposed':False,'inference_acceptance':'deferred; Models GET confirms access only'}


def image(model):
    from . import image_models
    item=image_models.spec(model);openai=item['provider']=='openai'
    return {**item,'source':'https://developers.openai.com/api/docs/guides/image-generation' if openai else 'https://ai.google.dev/gemini-api/docs/image-generation',
            'documentation_checked_on':CHECKED_ON,'generation_endpoint':'/v1/images/generations' if openai else '/v1beta/models/'+model+':generateContent',
            'edit_endpoint':'/v1/images/edits' if openai else '/v1beta/models/'+model+':generateContent',
            'app_reference_limit':5,'documented_reference_limit':None if openai else 14,
            'app_quality':item['quality'],'app_quality_options':(['low','medium','high','auto']+(['xhigh','max'] if model.startswith('gpt-image-2.5-') else [])) if openai else (['1K','2K','4K'] if model=='gemini-3-pro-image' else ['1K']),'app_sizes':list(image_models.sizes(model).values()) if openai else (['1K','2K','4K'] if model=='gemini-3-pro-image' else ['1K']),'custom_dimensions':model in ('gpt-image-2','gpt-image-2.5-sunburst','gpt-image-2.5-flare'),
            'app_aspect_ratios':list(image_models.sizes(model)) if openai else ['1:1','3:2','2:3','3:4','4:3','4:5','5:4','9:16','16:9','21:9'],
            'app_transparency':image_models.transparency(model),'outputs':['image/png','image/jpeg','image/webp'],
            'editing_input':'original uploaded bytes; incompatible normalized sources rejected',
            'inference_acceptance':'deferred; Models GET confirms access only'}


def registry():
    from . import chat_models,image_models,workspace_execution,work_artifacts
    return {'checked_on':CHECKED_ON,'chat':[chat(model) for model in chat_models.CATALOG],
            'images':[image(model) for model in image_models.CATALOG],
            'execution':workspace_execution.capability(),'artifact_retention':work_artifacts.RETENTION_POLICY,
            'features':{'documents':['pdf','docx','xlsx','pptx','csv','txt','md','json'],
                        'source_projects':'native tool authoring; validated source ZIP; remote Python execution only when separately configured',
                        'spreadsheet_formulas':'restricted local arithmetic/functions; recalculated by spreadsheet app, not this server',
                        'spreadsheet_charts':['bar','line','pie'],'html_preview':'opaque browser sandbox; network blocked',
                        'stream_reconnect':'persisted event replay, never inference retry'}}
