"""Canonical Video state; explicit replacement discards old derived context."""
import copy
import re

FIELDS=('subject','product','brand','objective','video_type','audience','platform','duration','aspect_ratio',
        'tone','style','location','talent','product_requirements','reference_requirements','audio','voice_over',
        'cta','must_preserve','must_avoid')
REPLACE=re.compile(r'(?i)\b(?:ganti(?:kan)?(?:\s+(?:topik|subjek|produk|idenya|ide|jadi|menjadi|ke|dengan|to))*|ubah(?:\s+(?:produk|topik|subjek))?\s+(?:jadi|menjadi|ke)|sekarang\s+produk(?:nya)?|change\s+(?:the\s+)?(?:subject|product|topic)(?:\s+to)?|switch\s+to|replace\s+.+?\s+with)\s+(.+?)(?:[.!\n]|$)')


def build(instruction,controls,previous=None,version=0,project_id=None):
    previous=previous or {}
    old=copy.deepcopy(controls.get('_brief') or {})
    if not old and previous:
        mapping={'audience':'audience','location':'setting','style':'visual_style'}
        old={k:copy.deepcopy(previous.get(mapping.get(k,k),'')) for k in FIELDS}
        old['seed_instruction']=previous.get('story','')
    attribute=re.search(r'(?i)\b(?:ganti|ubah|change)\s+(?:the\s+)?(lokasi|location|setting|orang|talent|person|model)(?:nya)?\s+(?:jadi|menjadi|ke|to)\s+([^,.!\n]+)',instruction) if version else None
    match=REPLACE.search(instruction) if version and not attribute else None
    preserve=bool(re.search(r'(?i)\b(?:tetap|pertahankan|preserve|keep|same)\b',instruction))
    if attribute:
        field='location' if attribute.group(1).lower() in ('lokasi','location','setting') else 'talent'
        brief=old
        retired=brief.pop(field,'')
        brief.pop('seed_instruction',None);brief.pop('working_title',None);brief.pop('amendments',None)
        brief[field]=attribute.group(2).strip()
        brief['retired_subjects']=[*brief.get('retired_subjects',[]),retired][-12:]
        kind='PRESERVE_AND_REPLACE'
    elif match:
        kind='PRESERVE_AND_REPLACE' if preserve else 'REPLACE_CORE'
        # Preserve neutral delivery constraints only. No old title/story/CTA/brand.
        brief={k:copy.deepcopy(old[k]) for k in ('platform','duration','aspect_ratio','video_type') if old.get(k)}
        explicit=[]
        if preserve:
            for pattern,field in [(r'orang(?:nya)?|talent|person|model','talent'),(r'lokasi|location|ruangan|room','location'),
                                  (r'produk|product','product'),(r'warna|color|kemasan|packaging|logo','product_requirements')]:
                if re.search(r'(?i)\b(?:'+pattern+r')\b.{0,35}\b(?:tetap|sama|same)|\b(?:keep|preserve|pertahankan)\b.{0,35}\b(?:'+pattern+r')\b',instruction):
                    if old.get(field):brief[field]=copy.deepcopy(old[field]);explicit.append(field)
        brief.update(subject=re.split(r'[,;]|\s+(?:tapi|but)\s+',match.group(1),maxsplit=1)[0].strip(),seed_instruction=instruction,preserved_fields=explicit,
                     retired_subjects=list(dict.fromkeys([*old.get('retired_subjects',[]),old.get('subject',''),old.get('subject_en',''),old.get('product','')]))[-12:],
                     use_references=bool(preserve and explicit))
    else:
        brief=old if version else {'seed_instruction':instruction,'use_references':True}
        kind=('SCENE_CHANGE' if re.search(r'(?i)\b(?:scene|adegan|shot)\s*\d+',instruction) else
              'FORMAT_CHANGE' if re.search(r'(?i)\b(?:detik|seconds?|9:16|16:9|reels|tiktok|runway|seedance|flow|higgsfield)\b',instruction) else
              'STYLE_CHANGE' if re.search(r'(?i)\b(?:premium|ugc|gaya|style|natural|cinematic)\b',instruction) else 'PATCH') if version else 'NEW'
        if version:brief['amendments']=[*brief.get('amendments',[]),instruction][-8:]
    brief.update(project_id=project_id,revision_number=version+1,revision_kind=kind,latest_user_instruction=instruction)
    for field,value in controls.items():
        if field!='_brief' and value and field!='tool':brief[field]=value
    seconds=re.search(r'(?i)\b(\d{1,3})\s*(?:detik|seconds?|secs?)\b',instruction)
    if seconds and 5<=int(seconds[1])<=180:brief['duration']=int(seconds[1])
    if re.search(r'(?i)\b(?:tanpa|no|without|jangan ada)\s+(?:voice[ -]?over|vo|narasi)\b',instruction):brief['voice_over']='disabled'
    elif re.search(r'(?i)\b(?:pakai|gunakan|add|with)\s+(?:voice[ -]?over|vo|narasi)\b',instruction):brief['voice_over']='requested'
    if re.search(r'(?i)\b(?:ugc)\b',instruction):brief['video_type']='UGC'
    return brief


def commit(brief,spec):
    """Extract active semantic fields without copying generated prose/history."""
    result=copy.deepcopy(brief)
    mapping={'location':'setting','style':'visual_style','platform':'target_platform','must_avoid':'avoid','product_requirements':'product_direction'}
    for field in FIELDS:
        if field=='voice_over' and brief.get(field)=='disabled':continue
        value=spec.get(mapping.get(field,field))
        if value is not None:result[field]=copy.deepcopy(value)
    result['working_title']=spec['title']
    result['subject_en']=spec.get('subject_en','')
    return result


def generation_context(brief,previous):
    # Subject replacement never supplies old generated fragments to the provider.
    return None if brief['revision_kind'] in ('NEW','REPLACE_CORE','PRESERVE_AND_REPLACE') else previous
