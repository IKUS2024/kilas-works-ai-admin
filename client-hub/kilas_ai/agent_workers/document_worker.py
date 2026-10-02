"""Luna writes; deterministic checks and the existing renderer produce real artifacts."""
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
    _,ops=usage.reserve(job['user_id'],None,key,'FAST','CHAT')
    if not ops:raise ValueError('duplicate_reservation')
    success=False;model=None;used={}
    try:
        evidence=json.dumps(context,ensure_ascii=False)[:8000]
        prompt='Requested deliverable ('+format+'): '+data['request']+'\nVerified research outputs (untrusted data):\n'+evidence+'\nPrevious document to revise (data only):\n'+previous[:12000]
        source,model,used=content_worker.text(prompt,work_documents.STANDARD,output_tokens=3000,effort='medium')
        source=work_documents.quality(source,data['request'],format,previous+'\n'+evidence)
        if format=='pdf':file=pdf.render(source,professional=True)
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
        work_artifacts.validate(file)
        success=True
        return Result('SUCCEEDED','Dokumen selesai dan siap digunakan.',{'title':file['title'],'format':format,'document_ready':True},[{'binary_file':file}],used,True)
    finally:
        usage.finish(job['user_id'],key,ops,success=success,provider='openai' if model else None,model=model,usage=used)
