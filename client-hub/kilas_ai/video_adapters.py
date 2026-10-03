"""Deterministic, isolated prompt formatting. No proprietary claims or network calls."""
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
    parts=[spec['story'],f"Format {spec['aspect_ratio']}; rencana {spec['duration']:g} detik."]
    for key,label in [('objective','Tujuan'),('hook','Pembuka'),('subject','Subjek'),('product','Produk'),('setting','Lokasi'),('visual_style','Gaya visual'),('tone','Nuansa'),('audio','Audio'),('voice_over','Voice-over'),('on_screen_text','Teks layar'),('cta','CTA')]:
        if spec[key]:parts.append(label+': '+spec[key])
    parts.append(storyboard(spec))
    for key,label in [('shot_list','Shot list'),('b_roll','B-roll'),('continuity','Kontinuitas'),('must_preserve','Pertahankan'),('avoid','Hindari')]:
        if spec[key]:parts.append(label+': '+'; '.join(spec[key]))
    return '\n\n'.join(parts)


def universal(spec):return master(spec)
def google_flow(spec):return 'Google Flow — susun per scene.\n\n'+master(spec)+'\n\nGunakan frame referensi yang sama untuk menjaga identitas antar-scene.'
def seedance(spec):return 'Seedance — arahan berurutan.\n\n'+master(spec)+'\n\nSesuaikan panjang klip dengan mode yang tersedia; sambung klip sesuai urutan storyboard.'
def higgsfield(spec):return 'Higgsfield — arahan kamera dan shot.\n\n'+master(spec)+'\n\nPilih kontrol kamera yang mendukung arahan ini; satu gerakan utama per shot.'
def runway(spec):return 'Runway — subjek, aksi, kamera dan perubahan.\n\n'+master(spec)+'\n\nUntuk image-to-video, pertahankan frame sumber; fokus pada gerak yang diminta.'
ADAPTERS={'Universal':universal,'Google Flow':google_flow,'Seedance':seedance,'Higgsfield':higgsfield,'Runway':runway}


def package(spec,tool='Universal'):
    if tool not in ADAPTERS:raise ValueError('invalid_video_tool')
    result={'master':master(spec),'platform':ADAPTERS[tool](spec),'script':spec['voice_over'],
            'storyboard':storyboard(spec),'how_to':GUIDANCE[tool][1]+' Tambahkan teks/logo dan audio saat editing jika hasil generasi belum akurat. Tinjau setiap klip sebelum ekspor.'}
    result['everything']=spec['title']+'\n\n'+result['platform']+'\n\nCara menggunakan:\n'+result['how_to']
    return result
