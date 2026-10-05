"""Deterministic, isolated prompt formatting. No proprietary claims or network calls."""
from . import video_parts
GUIDANCE={
 'Universal':('Arahan produksi','Pilih text-to-video atau image-to-video. Gunakan satu scene per klip bila perlu, lalu susun sesuai storyboard.'),
 'Google Flow':('Arahan scene untuk Google Flow','Buka Flow, pilih alur pembuatan klip yang tersedia. Gunakan referensi jika tersedia, buat setiap scene, lalu susun urutannya.'),
 'Seedance':('Arahan klip untuk Seedance','Pilih layanan resmi yang menyediakan Seedance. Cek mode dan durasi yang tersedia di layanan itu. Pasangkan referensi dengan scene yang sesuai.'),
 'Higgsfield':('Arahan shot untuk Higgsfield','Pilih workflow video yang sesuai. Gunakan referensi dan kontrol kamera yang tersedia; hindari gerakan berlebihan untuk UGC.'),
 'Runway':('Arahan visual untuk Runway','Pilih mode video yang tersedia. Jika memakai gambar, gunakan sebagai frame referensi dan jelaskan gerakan serta perubahan dalam scene.'),
}


def storyboard(spec):
    return '\n\n'.join(f"Scene {i} — {s['start']:g}–{s['end']:g} detik\n"+'\n'.join(label+': '+s[key] for key,label in [('visual','Visual'),('camera','Kamera'),('action','Aksi'),('lighting','Cahaya'),('audio','Audio'),('on_screen_text','Teks layar')] if s[key]) for i,s in enumerate(spec['scenes'],1))


def master(spec):
    if spec.get('master_prompt'):return spec['master_prompt']
    parts=[spec['story'],f"Format {spec['aspect_ratio']}; rencana {spec['duration']:g} detik."]
    for key,label in [('objective','Tujuan'),('hook','Pembuka'),('subject','Subjek'),('product','Produk'),('setting','Lokasi'),('visual_style','Gaya visual'),('tone','Nuansa'),('audio','Audio'),('voice_over','Voice-over'),('on_screen_text','Teks layar'),('cta','CTA')]:
        if spec[key]:parts.append(label+': '+spec[key])
    parts.append(storyboard(spec))
    for key,label in [('shot_list','Shot list'),('b_roll','B-roll'),('continuity','Kontinuitas'),('must_preserve','Pertahankan'),('avoid','Hindari')]:
        if spec[key]:parts.append(label+': '+'; '.join(spec[key]))
    return '\n\n'.join(parts)


def universal(spec):return master(spec)
def scene_prompt(scene):
    frame=('Animate the supplied reference image, preserving its subject, product, wardrobe, environment and lighting.\n\n') if scene.get('image_prompt') else ''
    return frame+scene.get('production_prompt',scene['visual'])

def shots(spec):
    return '\n\n'.join(f"Scene {i} | {s['start']:g}-{s['end']:g} seconds\n"+scene_prompt(s) for i,s in enumerate(spec['scenes'],1))
def google_flow(spec):return 'Plan separate clips, then assemble them in this order. Reuse the same approved reference frame for visual continuity.\n\n'+shots(spec)+'\n\nOverall direction:\n'+master(spec)
def seedance(spec):return 'Follow this chronological sequence. Match clip lengths to the available generation mode; assemble the clips to the planned total duration.\n\n'+master(spec)+'\n\nTimed shot instructions:\n'+shots(spec)
def higgsfield(spec):return 'Choose available camera controls that support these shots. Use one primary camera movement per shot and keep restrained movement for natural UGC.\n\n'+shots(spec)+'\n\nVisual and continuity direction:\n'+master(spec)
def runway(spec):return 'For image-to-video, preserve the approved source frame and describe the subject motion, camera motion and intended changes. Do not assume proprietary syntax.\n\n'+master(spec)+'\n\nGenerate shots individually when needed:\n'+shots(spec)
ADAPTERS={'Universal':universal,'Google Flow':google_flow,'Seedance':seedance,'Higgsfield':higgsfield,'Runway':runway}
PART_GUIDANCE={
    'Universal':'Use this as a standalone clip prompt. Reuse the approved reference and assemble clips in timeline order.',
    'Google Flow':'Use the available clip creation mode in Flow. Reuse the approved reference and match the opening and closing frames.',
    'Seedance':'Use an official service offering Seedance. Check available modes and durations, then create this clip with the approved reference.',
    'Higgsfield':'Choose available camera controls that support this clip. Keep one coherent movement and reuse the approved reference.',
    'Runway':'For image-to-video, use the approved opening frame and preserve its identity while following the planned subject and camera motion.',
}


def package(spec,tool='Universal'):
    if tool not in ADAPTERS:raise ValueError('invalid_video_tool')
    result={'master':master(spec),'platform':ADAPTERS[tool](spec),'script':spec['voice_over'],
            'storyboard':storyboard(spec),'how_to':GUIDANCE[tool][1]+' Tambahkan teks/logo dan audio saat editing jika hasil generasi belum akurat. Tinjau setiap klip sebelum ekspor.'}
    result['everything']=spec['title']+'\n\n'+result['platform']+'\n\nCara menggunakan:\n'+result['how_to']
    if spec.get('parts'):
        result['bible']=video_parts.bible_text(spec)
        for part in spec['parts']:
            key='part_'+str(part['number'])
            result[key]=video_parts.prompt(spec,part)
            # One complete prompt per clip; do not duplicate it as both shot and master.
            result[key+'_platform']=PART_GUIDANCE[tool]+'\n\n'+result[key]
        result['all_parts']='\n\n'.join(result['part_'+str(p['number'])] for p in spec['parts'])
        result['master']=result['all_parts']
        result['platform']='\n\n'.join(result['part_'+str(p['number'])+'_platform'] for p in spec['parts'])
        outlines=[]
        for part in spec['parts']:
            lines=[f"Part {part['number']} — {part['title']} | {part['start']:g}-{part['end']:g} seconds"]
            for key in video_parts.PART_TEXT:
                if key not in ('title','master_prompt') and part[key]:lines.append(key.replace('_',' ').title()+': '+part[key])
            lines.append('Shot list: '+'; '.join(part['shot_list']))
            outlines.append('\n'.join(lines))
        overview='\n'.join(k.replace('_',' ').title()+': '+v for k,v in spec.items()
            if isinstance(v,str) and v and k not in ('title','master_prompt'))
        details='\n'.join(k.replace('_',' ').title()+': '+'; '.join(spec[k])
            for k in ('shot_list','b_roll','continuity','must_preserve','avoid') if spec[k])
        result['everything']=(spec['title']+'\n\n'+overview+'\n\n'+details+'\n\n'+storyboard(spec)+
            '\n\nContinuity Bible:\n'+result['bible']+
            '\n\n'+'\n\n'.join(outlines)+'\n\n'+result['platform']+'\n\nCara menggunakan:\n'+result['how_to'])
    images=[];videos=[]
    for number,scene in enumerate(spec['scenes'],1):
        if scene.get('image_prompt'):
            result[f'image_{number}']=scene['image_prompt']
            images.append(f'Scene {number}\n'+scene['image_prompt'])
        prompt=scene_prompt(scene)
        if spec.get('parts'):
            part=spec['parts'][number-1]
            prompt=('Animate the supplied reference image. Preserve the same identity, wardrobe, product, location and lighting. '
                    +f"Create a {part['duration']:g}-second clip. Begin from {part['start_state']}\n\n"
                    +part['shot_direction']+'\n\nEnd at '+part['end_state']
                    +('\n\n'+part['audio'] if part['audio'] else '')
                    +('\n\nVoice-over: '+part['voice_over'] if part['voice_over'] else '\n\nNo voice-over.'))
        if tool!='Universal':prompt=PART_GUIDANCE[tool]+'\n\n'+prompt
        result[f'video_{number}']=prompt
        videos.append(f'Scene {number}\n'+prompt)
    result['all_images']='\n\n'.join(images)
    result['all_videos']='\n\n'.join(videos)
    if images:
        result['everything']=(spec['title']+'\n\nConcept:\n'+spec['story']+'\n\nStoryboard:\n'+storyboard(spec)+
                              '\n\nStoryboard image prompts:\n'+result['all_images']+'\n\n'+result['everything'])
        result['how_to']='Buat gambar storyboard dari prompt gambar terlebih dahulu. Tinjau konsistensi, lalu gunakan gambar scene sebagai frame referensi untuk prompt video yang sesuai. '+result['how_to']
    return result
