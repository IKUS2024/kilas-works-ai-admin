"""Reuse the existing validated image provider with bounded Work execution and metering."""
import os
import re
from . import Result
from .. import tools,usage,work_artifacts,routing


def run(job,step,data):
    if not os.environ.get('KILAS_AI_OPENAI_IMAGE_MODEL'):return Result('WAITING_CAPABILITY','Pembuatan gambar belum tersedia.',{'reason':'image_not_configured'})
    key=step['idempotency_key']+'-'+str(step['attempts'])
    _,ops=usage.reserve(job['user_id'],None,key,'FAST','IMAGE_EDIT' if step['action']=='edit' else 'IMAGE_GENERATE')
    if not ops:raise ValueError('duplicate_reservation')
    success=False;result={}
    try:
        source=work_artifacts.image_source(job['user_id'],data['source_id'],job['origin_conversation_id']) if step['action']=='edit' else None
        result=tools.image(routing.enhance_image_prompt(data['prompt']),source=source,request_timeout=60)
        extension={'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[result['mime']]
        title=' '.join(data['prompt'].split()[:8])
        name=re.sub(r'[^a-z0-9-]+','-',title.lower()).strip('-')[:70] or 'gambar-kilas'
        file={'filename':name+'.'+extension,'mime_type':result['mime'],'content':result['raw'],'title':title}
        work_artifacts.validate(file);success=True
        return Result('SUCCEEDED','Gambar selesai dan siap digunakan.',{'title':title,'image_ready':True},[{'binary_file':file}],result.get('usage',{}),True)
    finally:
        usage.finish(job['user_id'],key,ops,success=success,provider='openai' if result else None,model=result.get('model'),usage=result.get('usage',{}))
