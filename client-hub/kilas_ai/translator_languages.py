"""Mode-specific documented language routes, checked 2026-10-18.

Sources: ElevenLabs models, transcription and dubbing capability tables;
Google's dedicated Live Translation table (not the general Live API table).
No dialect duplication contributes to the distinct-language counts.
"""
import json
from pathlib import Path
import logging
import os
from threading import Lock,Thread
from time import monotonic

NAMES=dict(item.split('=',1) for item in (
    'af=Afrikaans;ak=Akan;sq=Albanian;am=Amharic;ar=Arabic;hy=Armenian;as=Assamese;ast=Asturian;az=Azerbaijani;eu=Basque;be=Belarusian;bn=Bengali;bs=Bosnian;bg=Bulgarian;my=Burmese;yue=Cantonese;ca=Catalan;ceb=Cebuano;ny=Chichewa;zh=Mandarin Chinese;hr=Croatian;cs=Czech;da=Danish;dgo=Dogri;nl=Dutch;en=English;et=Estonian;fil=Filipino;fi=Finnish;fr=French;ful=Fulah;gl=Galician;lg=Ganda;ka=Georgian;de=German;el=Greek;gu=Gujarati;ha=Hausa;he=Hebrew;hi=Hindi;hu=Hungarian;is=Icelandic;ig=Igbo;id=Indonesian;ga=Irish;it=Italian;ja=Japanese;jv=Javanese;kea=Kabuverdianu;kn=Kannada;kk=Kazakh;km=Khmer;ki=Kikuyu;rw=Kinyarwanda;rn=Kirundi;ko=Korean;ku=Kurdish;ky=Kyrgyz;lo=Lao;lv=Latvian;ln=Lingala;lt=Lithuanian;luo=Luo;lb=Luxembourgish;mk=Macedonian;ms=Malay;ml=Malayalam;mt=Maltese;mi=Māori;mr=Marathi;mn=Mongolian;ne=Nepali;nso=Northern Sotho;no=Norwegian;oc=Occitan;or=Odia;ps=Pashto;fa=Persian;pl=Polish;pt=Portuguese;pa=Punjabi;ro=Romanian;ru=Russian;sr=Serbian;st=Sesotho;sn=Shona;sd=Sindhi;si=Sinhala;sk=Slovak;sl=Slovenian;so=Somali;es=Spanish;su=Sundanese;sw=Swahili;ss=Swati;sv=Swedish;tg=Tajik;ta=Tamil;te=Telugu;th=Thai;bo=Tibetan;ts=Tsonga;tn=Tswana;tr=Turkish;uk=Ukrainian;ug=Uyghur;umb=Umbundu;ur=Urdu;uz=Uzbek;ve=Venda;vi=Vietnamese;war=Waray;cy=Welsh;wo=Wolof;xh=Xhosa;yo=Yoruba;zu=Zulu'
).split(';'))
V4=set('af ar hy as ast az be bn bs bg my yue ca ceb hr cs da nl en et fil fi fr gl ka de el gu ha he hi hu is id ga it ja jv kn kk ko ky lv ln lt lb mk ms ml mt zh mi mr mn ne no oc or ps fa pl pt pa ro ru sr sd sk sl so es sw sv tg ta te th tr uk ur uz vi cy yo'.split())
STT=set('af am ar hy as ast az be bn bs bg my yue ca ceb ny hr cs da nl en et fil fi fr ful gl lg ka de el gu ha he hi hu is ig id ga it ja jv kea kn kk km ko ku ky lo lv ln lt luo lb mk ms ml mt zh mi mr mn ne nso no oc or ps fa pl pt pa ro ru sr sn sd si sk sl so es sw sv ta tg te th tr uk umb ur uz vi cy wo xh zu'.split())
DUBBING=set('af ak sq am ar hy as az eu be bs bg my yue ca ceb zh hr cs da dgo nl en et fil fi fr gl ka de el gu ha he hi hu is id it ja jv kn kk ki rw rn ko ky lv lt lg mk ms ml mr mn ne no fa pl pt pa ro ru nso st sd sk sl es su sw ss sv tg ta te th bo ts tn tr uk ur ug uz ve vi war cy wo yo zu'.split())
NATIVE=set('af ak sq am ar hy az eu be bn bg my ca zh hr cs da nl en et fil fi fr gl ka de el gu ha he hi hu is id it ja jv kn kk km rw ko lo lv lt mk ms ml mr mn ne no fa pl pt pa ro ru sr sd si sk sl es su sw sv ta te th tr uk ur uz vi zu'.split())
CLASSIC=STT&V4
MODEL='eleven_v4'
_LOCALIZED=json.loads(Path(__file__).with_name('translator_language_names.json').read_text())
# Scribe's documented ISO639-3 response IDs; UI/backend retain canonical IDs.
_STT_CODES=dict(item.split('=') for item in 'afr=af amh=am ara=ar hye=hy asm=as ast=ast aze=az bel=be ben=bn bos=bs bul=bg mya=my yue=yue cat=ca ceb=ceb nya=ny hrv=hr ces=cs dan=da nld=nl eng=en est=et fil=fil fin=fi fra=fr ful=ful glg=gl lug=lg kat=ka deu=de ell=el guj=gu hau=ha heb=he hin=hi hun=hu isl=is ibo=ig ind=id gle=ga ita=it jpn=ja jav=jv kea=kea kan=kn kaz=kk khm=km kor=ko kur=ku kir=ky lao=lo lav=lv lin=ln lit=lt luo=luo ltz=lb mkd=mk msa=ms mal=ml mlt=mt zho=zh mri=mi mar=mr mon=mn nep=ne nso=nso nor=no oci=oc ori=or pus=ps fas=fa pol=pl por=pt pan=pa ron=ro rus=ru srp=sr sna=sn snd=sd sin=si slk=sk slv=sl som=so spa=es swa=sw swe=sv tam=ta tgk=tg tel=te tha=th tur=tr ukr=uk umb=umb urd=ur uzb=uz vie=vi cym=cy wol=wo xho=xh zul=zu'.split())


def localized_names(*,native=False):
    from ui_i18n import language
    result=dict(_LOCALIZED[language()])
    if native:result.update(zh=result['zh-Hans'],pt=result['pt-PT'])
    return result


def detected_source(metadata,target,*,input_ms=None):
    from .audio_store import AudioError
    metadata=metadata if isinstance(metadata,dict) else {}
    source=canonical(metadata.get('language_code'))
    confidence=metadata.get('language_probability')
    valid_probability=type(confidence) in (int,float) and 0<=confidence<=1
    def reject(reason,code,message):
        # Fixed reason + numeric metadata only. Never transcript/audio/provider
        # body, language name, user/session/operation identifiers or credentials.
        probability=f'{confidence:.3f}' if valid_probability else 'missing' if confidence is None else 'invalid'
        duration=str(int(input_ms)) if type(input_ms) in (int,float) and 0<=input_ms<=600000 else 'unknown'
        try:print(f'KILAS_LANGUAGE_DETECTION reason={reason} confidence={probability} input_ms={duration}',flush=True)
        except OSError:pass
        raise AudioError(message,code,422)
    unavailable='Data deteksi bahasa belum tersedia dari layanan suara. Pilih bahasa sumber lalu bicara kembali.'
    if not valid_probability:
        reject('missing_probability' if confidence is None else 'invalid_probability','detection_unavailable',unavailable)
    if source is None:reject('unknown_language','detection_unavailable',unavailable)
    if confidence<0.7:
        reject('low_probability','detection_uncertain','Bahasa ucapan belum terdeteksi dengan yakin. Pilih bahasa sumber lalu bicara kembali.')
    if source not in classic_names():
        reject('unsupported_language','detected_language_unsupported','Bahasa yang terdeteksi belum didukung oleh suara Translator. Pilih bahasa sumber yang didukung.')
    if source==target:
        reject('same_target','detected_language_is_target','Bahasa ucapan sama dengan bahasa tujuan. Pilih bahasa tujuan lain.')
    return source

_cache=None
_until=0
_lock=Lock()


def names(codes):
    return {code:NAMES[code] for code in sorted(codes,key=lambda c:(c not in ('id','en'),NAMES[c]))}


def canonical(code):
    if not isinstance(code,str):return None
    value=code.strip().lower().replace('_','-')
    aliases={**_STT_CODES,'in':'id','cmn':'zh','zho':'zh','zh-hans':'zh','zh-hant':'zh','tl':'fil','nb':'no',
             'ind':'id','eng':'en','jpn':'ja','kor':'ko','spa':'es','fra':'fr','deu':'de','por':'pt','rus':'ru','tur':'tr','tha':'th','vie':'vi','msa':'ms'}
    value=aliases.get(value,value)
    if value in NAMES:return value
    base=value.split('-')[0]
    return aliases.get(base,base) if base in NAMES or base in aliases else None


def native_wire(code):
    # Explicit documented default variants; visible labels carry these qualifiers.
    return {'zh':'zh-Hans','pt':'pt-PT'}.get(code,code)


def native_names():
    result=names(NATIVE)
    result.update(zh='Chinese (Simplified)',pt='Portuguese (Portugal)')
    return result


def classic_names():
    """Read-only account catalogue, cached5min; no inference or model fallback."""
    global _cache,_until
    from . import audio_provider as provider
    if not provider.configured():return {}
    with _lock:
        if _cache is not None and monotonic()<_until:return dict(_cache)
        supported=set();status='unavailable'
        try:
            rows=provider.request('GET','/models')
            model=next((r for r in rows if isinstance(r,dict) and r.get('model_id')==MODEL),{}) if isinstance(rows,list) else {}
            if model.get('can_do_text_to_speech') is True and model.get('requires_alpha_access') is not True:
                available=model.get('languages')
                supported={canonical(item.get('language_id')) for item in available if isinstance(item,dict)}&CLASSIC if isinstance(available,list) else set()
                status='available' if supported else 'no_languages'
        except provider.ProviderError:pass
        _cache=names(supported);_until=monotonic()+(300 if supported else 30)
        logging.getLogger(__name__).warning('KILAS_TRANSLATOR_CAPABILITIES model=eleven_v4 status=%s classic_languages=%s native_languages=%s dubbing_targets=%s',status,len(_cache),len(NATIVE),len(DUBBING))
        return dict(_cache)


def require_classic(a,b):
    from .audio_store import AudioError
    available=classic_names()
    if (a!='auto' and a not in available) or b not in available or a==b:
        raise AudioError('Bahasa ini belum tersedia pada model suara Translator. Pilih bahasa lain.','translator_language_unavailable',503)


def speech_payload(text,language):
    from .audio_store import AudioError
    if language not in classic_names():raise AudioError('Bahasa ini belum tersedia pada model suara Translator. Pilih bahasa lain.','translator_language_unavailable',503)
    # v4 supports these voice-local overrides. No tags/style/speaker-boost,
    # saved settings, voice replacement or artificial slowing of conversation.
    return {'text':text,'model_id':MODEL,'language_code':language,
            'voice_settings':{'stability':0.5,'similarity_boost':0.75},'apply_text_normalization':'auto'}


def warmup():
    if os.environ.get('RENDER_SERVICE_ID'):Thread(target=classic_names,name='translator-model-catalog',daemon=True).start()
