"""Native provider options. Never resize a generated image to satisfy a request."""
import math
import re

MODERN = ('gpt-image-2', 'gpt-image-2.5-sunburst', 'gpt-image-2.5-flare')
RATIOS = ('1:1','3:2','2:3','3:4','4:3','4:5','5:4','9:16','16:9','21:9')
# Official Gemini Pro native dimensions, in the same order as RATIOS.
GOOGLE_1K = ((1024,1024),(1264,848),(848,1264),(896,1200),(1200,896),(928,1152),(1152,928),(768,1376),(1376,768),(1584,672))
GOOGLE_2K = ((2048,2048),(2528,1696),(1696,2528),(1792,2400),(2400,1792),(1856,2304),(2304,1856),(1536,2752),(2752,1536),(3168,1344))
GOOGLE_4K = ((4096,4096),(5056,3392),(3392,5056),(3584,4800),(4800,3584),(3712,4608),(4608,3712),(3072,5504),(5504,3072),(6336,2688))


def resolve(model, prompt):
    from . import image_models, tools
    provider=image_models.spec(model)['provider']
    def unavailable(message):raise tools.ToolUnavailable(message,model=model)
    ratio=next(iter(re.findall(r'\b(?:'+ '|'.join(RATIOS) + r')\b',prompt)),'1:1')
    explicit=re.search(r'\b(\d{3,5})\s*[x×]\s*(\d{3,5})\b',prompt)
    resolution=next(iter(re.findall(r'\b(\d+)K\b',prompt,re.I)),None)
    if resolution and resolution not in ('1','2','4'):unavailable('Resolusi ini tidak didukung. Gunakan 1K, 2K atau 4K sesuai model pilihan.')
    quality_match=re.search(r'(?i)\b(?:quality|kualitas|calidad)\s*[:=]?\s*(low|medium|high|xhigh|max|auto|tinggi|sedang|rendah)\b',prompt)
    quality={'tinggi':'high','sedang':'medium','rendah':'low'}.get(quality_match[1].lower(),quality_match[1].lower()) if quality_match else 'high'
    transparent=bool(re.search(r'(?i)\b(?:transparent|transparan|transparente)\b|透明',prompt))
    if transparent and not image_models.transparency(model):unavailable('Model pilihan belum mendukung transparansi. Pilih model gambar yang mendukung PNG transparan.')
    if provider=='google':
        tier=(resolution+'K') if resolution else ('2K' if model=='gemini-3-pro-image' else '1K')
        if model!='gemini-3-pro-image' and tier!='1K':unavailable('Model pilihan hanya mendukung 1K. Pilih Gemini 3 Pro Image untuk 2K/4K.')
        tables={'1K':GOOGLE_1K,'2K':GOOGLE_2K,'4K':GOOGLE_4K}
        dimensions=tables[tier][RATIOS.index(ratio)]
        if explicit:
            requested=(int(explicit[1]),int(explicit[2]))
            matches=[(t,RATIOS[i]) for t,values in tables.items() for i,d in enumerate(values) if d==requested and (model=='gemini-3-pro-image' or t=='1K')]
            if not matches:unavailable('Ukuran piksel ini tidak didukung model pilihan. Gunakan rasio dan 1K/2K/4K yang didukung.')
            tier,actual_ratio=matches[0]
            if resolution and tier!=resolution+'K':unavailable('Ukuran piksel dan resolusi tidak cocok.')
            if re.search(r'\b'+re.escape(ratio)+r'\b',prompt) and actual_ratio!=ratio:unavailable('Ukuran piksel dan rasio gambar tidak cocok.')
            ratio=actual_ratio;dimensions=requested
        return {'size':f'{dimensions[0]}x{dimensions[1]}','aspect_ratio':ratio,'quality':tier,'transparent':transparent}
    allowed=('low','medium','high','auto')+(('xhigh','max') if model.startswith('gpt-image-2.5-') else ())
    if quality not in allowed:unavailable('Pengaturan kualitas ini tidak didukung model pilihan.')
    if model in MODERN:
        tier=resolution or '2'
        w,h=map(int,ratio.split(':'))
        # 4K uses the provider maximum pixel area, with valid multiples of 16.
        scale=min(math.sqrt((8294400 if tier=='4' else 4194304 if tier=='2' else 1048576)/(w*h)),3840/max(w,h))
        dimensions=(int(w*scale)//16*16,int(h*scale)//16*16)
        if ratio=='1:1':dimensions=(2048,2048) if tier=='2' else (2864,2864) if tier=='4' else (1024,1024)
        if explicit:dimensions=(int(explicit[1]),int(explicit[2]))
        w,h=dimensions
        if min(w,h)<=0 or max(w,h)>3840 or w%16 or h%16 or max(w,h)>3*min(w,h) or not 655360<=w*h<=8294400:unavailable('Ukuran model pilihan harus kelipatan 16, maksimal 3840 piksel per sisi dan 8.294.400 piksel, rasio maksimal 3:1.')
    else:
        if resolution and resolution!='1':unavailable('Model pilihan mendukung maksimal 1536 piksel. Pilih GPT Image 2/2.5 untuk 2K/4K.')
        size=image_models.sizes(model).get(ratio)
        if not size:unavailable('Rasio ini tidak didukung model pilihan.')
        dimensions=tuple(map(int,size.split('x')))
        if explicit:
            dimensions=(int(explicit[1]),int(explicit[2]))
            if f'{dimensions[0]}x{dimensions[1]}' not in image_models.sizes(model).values():unavailable('Ukuran ini tidak didukung model pilihan.')
    if explicit and re.search(r'\b(?:'+ '|'.join(RATIOS) +r')\b',prompt):
        rw,rh=map(int,ratio.split(':'))
        if dimensions[0]*rh!=dimensions[1]*rw:unavailable('Ukuran piksel dan rasio gambar tidak cocok.')
    if explicit and not re.search(r'\b(?:'+ '|'.join(RATIOS) +r')\b',prompt):
        divisor=math.gcd(*dimensions);ratio=f'{dimensions[0]//divisor}:{dimensions[1]//divisor}'
    return {'size':f'{dimensions[0]}x{dimensions[1]}','aspect_ratio':ratio,'quality':quality,'transparent':transparent}
