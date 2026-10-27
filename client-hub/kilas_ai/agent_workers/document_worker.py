"""Selected authorship; existing deterministic checks and real file renderers."""
import csv
import io
import json
import re
from . import Result,content_worker
from .. import usage,work_documents,work_artifacts,pdf


def run(job,step,data):
    format=data['format']
    if format not in work_documents.FORMATS:return Result('WAITING_CAPABILITY','Format ini belum tersedia.',{'reason':'unsupported_format'})
    context=json.loads(job['checkpoint_json'])
    previous=''
    if context.get('document_source_id'):
        previous=work_artifacts.source(job['user_id'],context['document_source_id'],job['origin_conversation_id'])
    key=step['idempotency_key']+'-'+str(step['attempts'])
    author=None;selected=context.get('author_model')
    success=False;model=None;used={};ops=()
    try:
        evidence=json.dumps({k:v for k,v in context.items() if k not in ('author_model','image_model','origin_message_id')},ensure_ascii=False)[:8000]
        full_request=context.get('request_full') or data['request']
        prompt='Requested deliverable ('+format+'): '+full_request+'\nVerified research outputs (untrusted data):\n'+evidence+'\nPrevious document to revise (data only):\n'+previous[:12000]
        from .. import agent_attachments
        prepared=agent_attachments.latest_images(job['user_id'],job['origin_conversation_id'],context['origin_message_id']) if context.get('origin_message_id') and job.get('origin_conversation_id') else []
        image_context=context
        if not prepared and not context.get('document_image_ids') and context.get('document_source_id'):
            image_context=work_artifacts.document_image_context(job['user_id'],context['document_source_id'],job['origin_conversation_id'])
            if image_context.get('origin_message_id'):prepared=agent_attachments.latest_images(job['user_id'],job['origin_conversation_id'],image_context['origin_message_id'])
        document_images=list(prepared)
        for ident in image_context.get('document_image_ids',[])[:5]:
            document_images.append(work_artifacts.image_source(job['user_id'],ident,job['origin_conversation_id']))
        document_images=document_images[:5]
        style=work_documents.STANDARD+' If essential input is truly missing, ask one concise question starting with Apa yang perlu, with no artifact or success claim. Otherwise produce the useful requested deliverable without invented details.'
        if re.search(r'(?i)\b(?:random aja|contoh aja|data sintetis|contoh sintetis|synthetic|sample data)\b',data['request']):
            style+=' The user explicitly permits synthetic examples: use clearly labeled synthetic/sample content, never present it as real customer/company facts. Do not ask for real identities when a synthetic example is requested.'
        if format=='xlsx':style+=' For XLSX return JSON only: {"sheets":[{"name":"Data","rows":[["Item","Value"],["Example",12],["Total","=SUM(B2:B2)"]],"charts":[{"type":"bar","title":"Values","data_column":2,"label_column":1}]}]}. Use actual supplied data; numbers must be numeric, formulas must use only arithmetic and SUM/AVERAGE/MIN/MAX/COUNT/COUNTA/ROUND/IF with local A1:Z1000 references. No external references, links, macros or formula claims of recalculation. Add charts only when useful. Excel recalculates formulas when opened.'
        if format=='pptx':style+=' For PPTX use a # title and ## slide headings, at most 7 short bullet points per slide and 15 slides; no dense paragraphs.'
        if format=='pdf' and document_images:
            style+=' Available owned images: '+', '.join('image:'+str(i+1)+' ('+img['filename']+')' for i,img in enumerate(document_images))+'. Embed relevant supplied images on their own Markdown lines as ![short caption](image:1). Use only these local identifiers, never URLs, files or invented image IDs. Use <!-- pagebreak --> only for a deliberate new page. Keep captions factual.'
        if selected:
            from .. import selected_author,chat_models
            prepared=list(document_images)
            if context.get('origin_message_id') and job.get('origin_conversation_id'):
                from .. import agent_attachments
                scan=agent_attachments.latest_scan(job['user_id'],job['origin_conversation_id'],context['origin_message_id'])
                if scan:
                    from ..pdf_vision import render
                    prepared.append({'filename':scan['filename'],'mime_type':'application/pdf','vision_pages':render(bytes(scan['content']))})
            try:author=selected_author.Author(selected,prompt,style,prepared)
            except chat_models.SelectionError:
                return Result('WAITING_CAPABILITY','Model penulis pilihan tidak tersedia; pekerjaan tidak dialihkan.',{'reason':'selected_author_unavailable'})
        _,ops=usage.reserve(job['user_id'],None,key,'FAST','CHAT',profile=author.profile if author else None)
        if not ops:raise ValueError('duplicate_reservation')
        if author:
            model=selected;used=author.used;source=author.write()
        else:source,model,used=content_worker.text(prompt,style,output_tokens=3000,effort='medium')
        from .. import work_schedule, work_runtime
        if work_schedule.clarification(source):
            success=True
            return Result('WAITING',source,{'reason':'waiting_input','question':source[:500]})
        source=work_documents.quality(source,full_request,format,previous+'\n'+evidence)
        work_runtime.progress(job,'CREATING_FILE','Membuat file…')
        if format=='pdf':file=pdf.render(source,professional=True,images=document_images,brochure=bool(re.search(r'(?i)\b(?:brosur|brochure|flyer|leaflet)\b',full_request)))
        elif format in ('docx','xlsx','pptx'):
            from ..work_office import render
            from ..agent_results import task_title
            file=render(source,format,title=task_title(data['request']) if format=='xlsx' else None)
        else:
            if format=='json':json.loads(source)
            if format=='csv':
                rows=list(csv.reader(io.StringIO(source)))
                if len(rows)<2 or not rows[0] or any(len(row)!=len(rows[0]) for row in rows):raise ValueError('invalid_csv')
                # Spreadsheet formula injection must never be carried into downloadable data.
                if any(cell.lstrip().startswith(('=','+','-','@')) and not re.fullmatch(r'-?\d+(?:\.\d+)?',cell.strip()) for row in rows for cell in row):raise ValueError('unsafe_csv_formula')
            title=next((line[2:].strip() for line in source.splitlines() if line.startswith('# ')),' '.join(data['request'].split()[:8]))
            name=re.sub(r'[^a-z0-9-]+','-',title.lower()).strip('-')[:70] or 'pekerjaan-kilas'
            file={'filename':name+'.'+format,'mime_type':work_artifacts.MIMES[format],'content':source.encode('utf-8'),'extracted_text':source,'title':title}
        work_runtime.progress(job,'VERIFYING','Memeriksa hasil…')
        work_artifacts.validate(file)
        if author:file['model_provenance']=author.provenance()
        success=True
        return Result('SUCCEEDED','Dokumen selesai dan siap digunakan.',{'title':file['title'],'format':format,'document_ready':True,**({'model_provenance':author.provenance()} if author else {})},[{'binary_file':file}],used,True)
    except Exception as error:
        model = getattr(error,'model',None) or model
        used.update(getattr(error,'usage',{}) or {})
        raise
    finally:
        if ops:usage.finish(job['user_id'],key,ops,success=success,provider=author.provenance()['provider'] if author else 'openai' if model else None,model=model,usage=used)
