"""Connected clip contract within existing Video JSON; no persistence or provider calls."""
import json
import math
MAX_PARTS=8  # Keep detailed plans within the existing synchronous/provider budget.

BIBLE_FIELDS=('subject','talent','age_gender','hair','wardrobe','product','packaging_label',
              'location','time_of_day','lighting','color_grade','mood','camera','aspect_ratio',
              'movement','props','environment','cta_style')
PART_TEXT=('title','purpose','scene','start_state','end_state','shot_direction','on_screen_text',
           'voice_over','audio','master_prompt')
PART_LIST=('shot_list','avoid')

STANDARD='''
MULTI-PART MODE overrides only when canonical_brief.plan_mode is multi.
Return two additional fields: continuity_bible and parts. Do not add these in single mode.
continuity_bible is an object with exactly these English string keys: '''+', '.join(BIBLE_FIELDS)+'''.
All nonempty Bible values MUST be professional English. Capture one stable creative identity,
not a sequence of actions. Leave irrelevant or unknown details empty; do not invent age,
gender, hairstyle, brand or label facts. Proposed staging may be creative; product claims may not.
The Bible is the authority for EVERY clip. Preserve exact identity, packaging, wardrobe,
location, light, grade, camera language and props throughout. aspect_ratio matches the plan.
parts is an array matching clip_timeline in canonical_brief exactly, in order.
Each part has number, start, end, duration (numbers), these string fields: '''+', '.join(PART_TEXT)+''',
and shot_list and avoid (arrays of short strings).
Part title, purpose, scene and shot_list are natural Indonesian. start_state, end_state,
shot_direction, audio, avoid and master_prompt MUST be professional ENGLISH.
For each adjacent pair, the next start_state MUST be exactly the same string as the prior
end_state: a concrete visible subject pose, product orientation, camera framing and environment.
Build a visual progression, never independent repeated hero shots: hook, meaningful action,
payoff/CTA appropriate to the genre. First part establishes the scene; final part closes it.
master_prompt describes THIS clip only: local 0-duration second beats, exact opening state,
subject action, one coherent camera direction, light, audio, final state and avoid constraints.
The server appends the shared Bible and exact handoff; do not duplicate the Bible in the prompt.
On-screen text and voice_over are actual intended script, optional; empty voice_over when disabled.
For UGC/review: conversational real actions, restrained camera, practical light, no invented
testimonials, benefit claims or robotic sales delivery. Tutorial/demo shots show causal steps.
Overall scenes and master_prompt must agree with parts, duration, latest subject and Bible.
Keep the complete JSON compact: one overall scene per clip, concise overall directions,
2-3 practical shot_list entries per clip, and 80-120 words per clip master_prompt.
Do not repeat the Bible in overall or clip prompts. Specific action and handoff remain mandatory.
For STYLE_CHANGE with the same timeline, retain each opening/ending state VERBATIM
and the supplied stable Bible identity fields. Improve only requested style/audio/script;
do not restage the action, replace the product, wardrobe, packaging or location.
No proprietary flags, unsupported tool limits, or promises of exact generated labels/text.
COMPACT TRANSPORT OVERRIDE: Do not return the redundant overall fields scenes, master_prompt,
shot_list, b_roll, continuity, must_preserve, avoid, camera, movement, lighting, audio,
voice_over, on_screen_text, duration or aspect_ratio. The server derives these from the
canonical timeline, Bible and parts. Return the remaining overall creative fields, Bible,
and parts. Omit master_prompt inside each part: shot_direction is the authoritative complete
ENGLISH clip direction (50-80 words), including timed action, framing/camera, light and motion.
Keep Bible values concise, other part strings one sentence, and lists 2-3 short entries.
Do not omit or shorten concrete start/end handoffs. Do not add explanation or reasoning.
'''


def _derived_prompt(part):
    return ('Opening frame: '+str(part.get('start_state',''))+'\n'+str(part.get('shot_direction',''))+
            '\nFinal frame: '+str(part.get('end_state',''))+'\nAudio: '+str(part.get('audio','')))


def expand_draft(raw,brief):
    """Build redundant legacy presentation from model-owned clips, without new facts.

    Full existing responses/review fields remain accepted and validated unchanged.
    Only absent derived fields are filled; incorrect supplied values are never repaired.
    """
    if not isinstance(raw,dict) or brief.get('plan_mode')!='multi':return raw
    value=json.loads(json.dumps(raw))
    bible=value.get('continuity_bible');parts=value.get('parts')
    if not isinstance(bible,dict) or not isinstance(parts,list) or not parts:return value
    if any(not isinstance(p,dict) for p in parts):return value
    for p in parts:
        p.setdefault('master_prompt',_derived_prompt(p))
    value.setdefault('duration',brief['duration'])
    value.setdefault('aspect_ratio',bible.get('aspect_ratio',''))
    for field,source in [('camera','camera'),('movement','movement'),('lighting','lighting')]:
        value.setdefault(field,bible.get(source,''))
    for field in ('audio','voice_over','on_screen_text'):
        value.setdefault(field,'\n'.join(str(p.get(field,'')) for p in parts if p.get(field)))
    value.setdefault('shot_list',[s for p in parts for s in p.get('shot_list',[])][:20])
    value.setdefault('b_roll',[])
    value.setdefault('continuity',[str(p.get('start_state','')) for p in parts])
    value.setdefault('must_preserve',[str(v) for k,v in bible.items() if v and k in ('subject','product','wardrobe','location')])
    value.setdefault('avoid',list(dict.fromkeys(s for p in parts for s in p.get('avoid',[])))[:20])
    value.setdefault('master_prompt',f"Create a {value['duration']}-second {value['aspect_ratio']} video.\n\n"+'\n\n'.join(p['master_prompt'] for p in parts))
    value.setdefault('scenes',[dict(start=p.get('start'),end=p.get('end'),visual=p.get('scene',''),
        action=p.get('purpose',''),camera=bible.get('camera',''),lighting=bible.get('lighting',''),
        audio=p.get('audio',''),on_screen_text=p.get('on_screen_text',''),environment=bible.get('location',''),
        continuity=p.get('start_state',''),production_prompt=p['master_prompt']) for p in parts])
    return value


def timeline(total,strategy='auto'):
    """Auto balances clips around 10 seconds; fixed sizes retain a shorter final clip."""
    if type(total) not in (int,float) or not math.isfinite(total) or total!=int(total) or not 5<=total<=180:
        raise ValueError('invalid_total_duration')
    total=int(total)
    if strategy not in ('auto','5','10','15'):raise ValueError('invalid_clip_strategy')
    if strategy=='auto':
        count=max(2,math.ceil(total/10))
        base,remainder=divmod(total,count)
        lengths=[base+(i<remainder) for i in range(count)]
    else:
        size=int(strategy)
        lengths=[min(size,total-start) for start in range(0,total,size)]
    if len(lengths)<2 or min(lengths)<1:raise ValueError('multi_needs_two_parts')
    if len(lengths)>MAX_PARTS:raise ValueError('too_many_video_parts')
    end=0;result=[]
    for number,length in enumerate(lengths,1):
        result.append(dict(number=number,start=end,end=end+length,duration=length));end+=length
    return result


def validate(spec,brief,english_check,previous=None):
    bible=spec.get('continuity_bible');parts=spec.get('parts')
    if not isinstance(bible,dict) or set(bible)!=set(BIBLE_FIELDS):raise ValueError('invalid_continuity_bible')
    if any(not isinstance(v,str) or len(v)>600 for v in bible.values()):raise ValueError('invalid_continuity_bible')
    if not all(bible[k].strip() for k in ('subject','location','lighting','camera','aspect_ratio')):
        raise ValueError('incomplete_continuity_bible')
    english_check('Create the same subject with this continuity. '+ ' '.join(bible.values()))
    if bible['aspect_ratio']!=spec['aspect_ratio']:raise ValueError('continuity_aspect_mismatch')
    expected=brief.get('clip_timeline') or timeline(brief['duration'],brief.get('clip_strategy','auto'))
    if not isinstance(parts,list) or len(parts)!=len(expected):raise ValueError('invalid_parts_count')
    prior=None
    for part,timing in zip(parts,expected):
        if not isinstance(part,dict) or set(part)!=set(PART_TEXT+PART_LIST+('number','start','end','duration')):
            raise ValueError('invalid_video_part')
        if any(type(part[k]) not in (int,float) or part[k]!=v for k,v in timing.items()):raise ValueError('invalid_part_timing')
        if any(not isinstance(part[k],str) or len(part[k])>(3200 if k=='master_prompt' else 900) for k in PART_TEXT):
            raise ValueError('invalid_part_text')
        if not all(part[k].strip() for k in ('title','purpose','scene','start_state','end_state','shot_direction','master_prompt')):
            raise ValueError('incomplete_video_part')
        for key in PART_LIST:
            if not isinstance(part[key],list) or not 1<=len(part[key])<=8 or any(not isinstance(v,str) or not v.strip() or len(v)>400 for v in part[key]):
                raise ValueError('invalid_part_list')
        english_check(part['master_prompt'])
        english_check('Keep the same subject with these constraints. '+' '.join(part['avoid']))
        if any(len(part[k].split())<6 or len(part[k])<35 for k in ('start_state','end_state')):
            raise ValueError('vague_part_handoff')
        for key in ('start_state','end_state','shot_direction','audio'):
            english_check('Use the same subject with this shot. '+part[key])
        if prior is not None and part['start_state']!=prior:raise ValueError('disconnected_part_handoff')
        if brief.get('voice_over')=='disabled' and part['voice_over']:raise ValueError('voice_over_conflict')
        prior=part['end_state']
    if len(set(p['master_prompt'].strip().casefold() for p in parts))!=len(parts):raise ValueError('duplicate_part_prompts')
    if (previous and previous.get('parts') and brief['revision_kind']=='STYLE_CHANGE'
            and [(p['start'],p['end']) for p in previous['parts']]==[(p['start'],p['end']) for p in parts]):
        for old,new in zip(previous['parts'],parts):
            if any(old[k]!=new[k] for k in ('start_state','end_state')):raise ValueError('patch_changed_handoff')
        for key in ('subject','talent','age_gender','hair','wardrobe','product','packaging_label','location','props','environment','aspect_ratio'):
            if previous['continuity_bible'][key]!=bible[key]:raise ValueError('patch_changed_identity:'+key)
    return spec


def bible_text(spec):
    return '\n'.join(k.replace('_',' ').title()+': '+v for k,v in spec['continuity_bible'].items() if v)


def prompt(spec,part):
    # Derived master text repeats exactly the already exported states/direction/audio.
    # Recognize that exact server format, including previously saved compact plans.
    extra='' if part['master_prompt']==_derived_prompt(part) else part['master_prompt']
    scripts='\n'.join(label+': '+json.dumps(part[key],ensure_ascii=False) for key,label in
        [('on_screen_text','Intended on-screen text'),('voice_over','Intended voice-over')] if part[key])
    return (f"Part {part['number']} | {part['duration']:g} seconds | {spec['aspect_ratio']}\n\n"
            'Continuity Bible — retain throughout this clip:\n'+bible_text(spec)+'\n\n'
            'Exact opening state: '+part['start_state']+'\n'
            'Exact final state: '+part['end_state']+'\n'
            'Shot direction: '+part['shot_direction']+'\n'
            'Audio: '+(part['audio'] or 'No additional music or sound is specified.')+'\n'
            +('Voice-over: none.\n' if not part['voice_over'] else '')+scripts+'\n\n'+(extra+'\n\n' if extra else '')
            +'Avoid: '+'; '.join(part['avoid']))
