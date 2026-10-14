"""Committed sentence output, one job, cumulative settlement; no input STT change."""
import io
import json
import math
import os
import re
import struct
import tempfile
import subprocess
import wave
from pathlib import Path
from time import monotonic
import requests
import db
from . import audio_store as store, audio_media as media, audio_provider as provider, usage
from . import live_translator_store as sessions, live_translator_transport as transport

MAX_SEGMENTS=8
MAX_BYTES=20*1024*1024
MAGIC=b'KWSEG1'
PREFIX='live-stream:'


def sentences(text):
    """Group committed sentences, including non-Latin punctuation, without losing text."""
    if not isinstance(text,str) or not 1<=len(text)<=4000:raise store.AudioError('Terjemahan tidak valid.','translation_failed',503)
    boundaries=[]
    abbreviations={'dr','mr','mrs','ms','prof','jr','sr','st','vs','etc','e.g','i.e','no'}
    for match in re.finditer(r'[.!?。！？؟]+[\"\'”’»)]*(?:\s+|$|(?<=[。！？؟]))',text):
        stop=match.end();prefix=text[:match.start()]
        if text[match.start()]=='.':
            last=re.search(r'([\w.]+)$',prefix)
            if last and (last[1].lower() in abbreviations or len(last[1])==1):continue
            if match.start()>0 and text[match.start()-1].isdigit() and stop<len(text) and text[stop:stop+1].isdigit():continue
        boundaries.append(stop)
    parts=[];at=0
    for stop in boundaries:
        if stop>at:parts.append(text[at:stop]);at=stop
    if at<len(text):parts.append(text[at:])
    grouped=parts[:1] if len(parts)>1 else [];pending=''
    if grouped:parts=parts[1:]
    for index,part in enumerate(parts):
        pending+=part
        if len(pending)>=80 or index==len(parts)-1:grouped.append(pending);pending=''
    if pending:grouped.append(pending)
    if len(grouped)>MAX_SEGMENTS:grouped=grouped[:MAX_SEGMENTS-1]+[''.join(grouped[MAX_SEGMENTS-1:])]
    assert ''.join(grouped)==text
    return grouped


def manifest(value):
    if not isinstance(value,str) or not value.startswith(PREFIX):return None
    try:
        data=json.loads(value[len(PREFIX):])
        if type(data['version']) is not int or data['version']!=1 or type(data['ceiling_ms']) is not int or not 1000<=data['ceiling_ms']<=600000 or type(data['total']) is not int or type(data['dispatched']) is not int or not 1<=data['total']<=MAX_SEGMENTS or not 0<=data['dispatched']<=data['total'] or not isinstance(data['clips'],list) or len(data['clips'])>data['total']:raise ValueError()
        if not len(data['clips'])<=data['dispatched']<=len(data['clips'])+1:raise ValueError()
        end=len(MAGIC);duration=0
        for c in data['clips']:
            if set(c)!= {'offset','bytes','ms'} or any(type(c[n]) is not int for n in c) or c['offset']!=end+8 or not 0<c['bytes']<=MAX_BYTES or not 0<c['ms']<=600000:raise ValueError()
            end=c['offset']+c['bytes'];duration+=c['ms']
        if end>MAX_BYTES or duration>data['ceiling_ms']:raise ValueError()
        return data
    except (ValueError,KeyError,TypeError):raise store.AudioError('Status audio tidak valid.','stream_invalid',503) from None


def _encode(data):return PREFIX+json.dumps(data,separators=(',',':'))


def attach(owner,ident,key,job,total,ceiling):
    with store.locked(owner) as conn:
        sessions.locked(owner,ident,conn)
        row=usage._query(conn,"SELECT status FROM kilas_live_translator_turns WHERE session_id=? AND operation_key=?",(ident,key),one=True)
        if not row or row[0]!='PROCESSING':raise store.AudioError('Ucapan dibatalkan.','turn_cancelled',409)
        data={'version':1,'total':total,'ceiling_ms':ceiling*1000,'dispatched':0,'clips':[]};manifest(_encode(data))
        usage._query(conn,"UPDATE kilas_audio_jobs SET status='PROCESSING',provider_id=?,source_content=? WHERE id=? AND user_id=? AND status='QUEUED'",(_encode(data),MAGIC,job,owner))
        usage._query(conn,"UPDATE kilas_live_translator_turns SET audio_job_id=? WHERE session_id=? AND operation_key=? AND status='PROCESSING'",(job,ident,key))


def dispatch(owner,ident,key,job,index):
    # Commit a conservative possible-paid marker BEFORE the sole request for this index.
    with store.locked(owner) as conn:
        sessions.locked(owner,ident,conn)
        row=usage._query(conn,"SELECT t.status,j.status,j.provider_id FROM kilas_live_translator_turns t JOIN kilas_audio_jobs j ON j.id=t.audio_job_id AND j.user_id=? WHERE t.session_id=? AND t.operation_key=?",(owner,ident,key),one=True)
        if not row or row[0]!='PROCESSING' or row[1]!='PROCESSING':raise store.AudioError('Ucapan dibatalkan.','turn_cancelled',409)
        data=manifest(row[2])
        if not data or type(index) is not int or not 0<=index<data['total'] or data['dispatched']!=index or len(data['clips'])!=index:raise store.AudioError('Segmen sudah dikirim.','duplicate_turn',409)
        data['dispatched']+=1
        usage._query(conn,'UPDATE kilas_audio_jobs SET provider_id=?,updated_at=? WHERE id=? AND user_id=?',(_encode(data),usage._now().isoformat(),job,owner))


def _frames(data,framed):
    end=len(MAGIC)
    if not framed.startswith(MAGIC):raise store.AudioError('Audio tidak valid.','stream_invalid',503)
    for c in data['clips']:
        if end+8>len(framed) or struct.unpack('>II',framed[end:end+8])!=(c['bytes'],c['ms']):raise store.AudioError('Audio tidak valid.','stream_invalid',503)
        end=c['offset']+c['bytes']
    if len(framed)!=end or end>MAX_BYTES:raise store.AudioError('Audio tidak valid.','stream_invalid',503)


def commit_clip(owner,job,index,raw,ms=None):
    """Settle validated output even when End raced its response; canceled reads stay fenced."""
    measured=media.mp3_duration(raw)
    if ms is not None and ms!=measured:raise store.AudioError('Durasi audio tidak cocok.','stream_invalid',503)
    ms=measured
    with store.locked(owner) as conn:
        row=usage._query(conn,'SELECT status,provider_id,actual_ms,seconds_charged,reserved_seconds,length(source_content) FROM kilas_audio_jobs WHERE id=? AND user_id=?',(job,owner),one=True)
        if not row or row[0]!='PROCESSING':raise store.AudioError('Audio tidak tersedia.','stream_invalid',409)
        data=manifest(row[1])
        if not data or type(index) is not int or not 0<=index<data['total'] or index!=len(data['clips']) or data['dispatched']!=index+1:raise store.AudioError('Urutan audio berubah.','stream_invalid',409)
        if int(row[2])!=sum(c['ms'] for c in data['clips']):raise store.AudioError('Durasi audio berubah.','stream_invalid',409)
        size=int(row[5] or 0);total_ms=int(row[2])+ms
        if size+8+len(raw)>MAX_BYTES:raise store.AudioError('Audio melebihi batas.','stream_limit',413)
        if total_ms>data['ceiling_ms']:raise store.AudioError('Durasi melebihi cadangan audio.','output_exceeds_reservation',402)
        exempt=usage._qa_quota_exempt(conn,owner,usage._now())
        charge=0 if exempt else math.ceil(total_ms/1000)
        delta=charge-int(row[3])
        if delta<0 or (not exempt and (delta>int(row[4]) or delta>store._balance(conn,owner))):raise store.AudioError('Durasi melebihi cadangan audio.','output_exceeds_reservation',402)
        if delta:usage._query(conn,'UPDATE kilas_audio_balances SET seconds=seconds-? WHERE user_id=? AND seconds>=?',(delta,owner,delta))
        frame=struct.pack('>II',len(raw),ms)+raw
        # BYTEA writes stay small and all bytes + duration + debit commit atomically.
        expression='source_content || ?' if db.BACKEND=='postgres' else 'CAST(source_content || ? AS BLOB)'
        for at in range(0,len(frame),512*1024):
            usage._query(conn,'UPDATE kilas_audio_jobs SET source_content='+expression+' WHERE id=? AND user_id=?',(frame[at:at+512*1024],job,owner))
        data['clips'].append({'offset':size+8,'bytes':len(raw),'ms':ms})
        usage._query(conn,'UPDATE kilas_audio_jobs SET provider_id=?,actual_ms=?,seconds_charged=?,reserved_seconds=reserved_seconds-?,updated_at=? WHERE id=? AND user_id=?',(_encode(data),total_ms,charge,delta,usage._now().isoformat(),job,owner))


def _join(data,framed,check):
    # Byte concatenation can introduce MP3 encoder padding between clips. Decode
    # each private clip, concatenate PCM, then encode one valid downloadable MP3.
    with tempfile.TemporaryDirectory(prefix='kilas-live-output-') as folder:
        source=Path(folder)/'clip.mp3';decoded=Path(folder)/'clip.wav';joined=Path(folder)/'joined.wav';target=Path(folder)/'result.mp3'
        with wave.open(str(joined),'wb') as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(44100)
            for c in data['clips']:
                check()
                source.write_bytes(framed[c['offset']:c['offset']+c['bytes']])
                try:
                    converted=subprocess.run([media.imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-protocol_whitelist','file,pipe','-threads','1','-i',str(source),'-map','0:a:0','-vn','-t','600','-ac','1','-ar','44100','-c:a','pcm_s16le','-y',str(decoded)],capture_output=True,timeout=15)
                    if converted.returncode or not decoded.exists() or decoded.stat().st_size>54*1024*1024:raise media.MediaError('Audio gabungan belum dapat disiapkan.')
                    with wave.open(str(decoded)) as clip:
                        if clip.getframerate()!=44100 or clip.getnchannels()!=1 or clip.getsampwidth()!=2:raise media.MediaError('Audio gabungan tidak valid.')
                        while True:
                            check();frames=clip.readframes(65536)
                            if not frames:break
                            output.writeframes(frames)
                    if joined.stat().st_size>54*1024*1024:raise media.MediaError('Audio gabungan melebihi batas.')
                except (subprocess.TimeoutExpired,wave.Error,EOFError):raise media.MediaError('Audio gabungan belum dapat disiapkan.') from None
        try:
            check()
            result=subprocess.run([media.imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-protocol_whitelist','file,pipe','-threads','1','-i',str(joined),'-c:a','libmp3lame','-b:a','128k','-y',str(target)],capture_output=True,timeout=15)
            if result.returncode or not target.exists() or target.stat().st_size>MAX_BYTES:raise media.MediaError('Audio gabungan belum dapat disiapkan.')
            return target.read_bytes()
        except subprocess.TimeoutExpired:raise media.MediaError('Audio gabungan belum dapat disiapkan.') from None


def complete(owner,job,check=lambda:None):
    output=db.query_one('SELECT source_content,provider_id FROM kilas_audio_jobs WHERE id=? AND user_id=?',(job,owner))
    data=manifest(output['provider_id']) if output else None
    if not data or len(data['clips'])!=data['total']:raise store.AudioError('Audio belum lengkap.','stream_invalid',409)
    framed=bytes(output['source_content']);_frames(data,framed);raw=_join(data,framed,check)
    final_ms=max(sum(c['ms'] for c in data['clips']),media.mp3_duration(raw))
    if final_ms>data['ceiling_ms']:raise store.AudioError('Durasi melebihi cadangan audio.','output_exceeds_reservation',402)
    check()
    with store.locked(owner) as conn:
        row=usage._query(conn,'SELECT status,provider_id FROM kilas_audio_jobs WHERE id=? AND user_id=?',(job,owner),one=True)
        data=manifest(row[1]) if row else None
        if not row or row[0]!='PROCESSING' or not data or len(data['clips'])!=data['total']:raise store.AudioError('Audio belum lengkap.','stream_invalid',409)
        if row[1]!=output['provider_id']:raise store.AudioError('Audio berubah.','stream_invalid',409)
        ledger=usage._query(conn,'SELECT seconds_charged,reserved_seconds FROM kilas_audio_jobs WHERE id=? AND user_id=?',(job,owner),one=True)
        exempt=usage._qa_quota_exempt(conn,owner,usage._now());charge=0 if exempt else math.ceil(final_ms/1000);delta=charge-int(ledger[0])
        if delta<0 or (not exempt and (delta>int(ledger[1]) or delta>store._balance(conn,owner))):raise store.AudioError('Durasi melebihi cadangan audio.','output_exceeds_reservation',402)
        if delta:usage._query(conn,'UPDATE kilas_audio_balances SET seconds=seconds-? WHERE user_id=? AND seconds>=?',(delta,owner,delta))
        # Reuse completed duration/charges; never debit the full job a second time.
        for at in range(0,len(raw),512*1024):
            expression='?' if at==0 else 'result_content || ?' if db.BACKEND=='postgres' else 'CAST(result_content || ? AS BLOB)'
            usage._query(conn,'UPDATE kilas_audio_jobs SET result_content='+expression+' WHERE id=? AND user_id=?',(raw[at:at+512*1024],job,owner))
        usage._query(conn,"UPDATE kilas_audio_jobs SET status='COMPLETED',actual_ms=?,seconds_charged=?,reserved_seconds=0,script=NULL,updated_at=? WHERE id=? AND user_id=?",(final_ms,charge,usage._now().isoformat(),job,owner))


def speech(text,voice,check,on_first_byte,*,previous='',following=''):
    """One documented HTTP stream; never retry or switch endpoints after dispatch."""
    # Translator-only request overrides: moderate expressive variation while
    # retaining the approved voice and normal speaking speed. Optional speaker
    # boost adds provider computation/latency for a subtle similarity effect;
    # keep similarity .75 and omit that extra processing for live conversation.
    # Do not edit saved voice defaults, add tags or rewrite the text.
    payload={'text':text,'model_id':'eleven_multilingual_v2',
             'voice_settings':{'stability':0.4,'similarity_boost':0.75,'style':0.0,
                               'use_speaker_boost':False,'speed':1.0},
             'apply_text_normalization':'auto'}
    if previous:payload['previous_text']=previous[-1000:]
    if following:payload['next_text']=following[:1000]
    check();deadline=monotonic()+60;raw=bytearray();first=True
    try:
        with transport.request('POST',provider.BASE+'/text-to-speech/'+voice+'/stream',headers={'xi-api-key':os.environ['ELEVENLABS_API_KEY'].strip()},params={'output_format':'mp3_44100_128'},json=payload,stream=True,timeout=(5,15),allow_redirects=False) as response:
            if response.status_code!=200:
                code='stream_unavailable' if response.status_code in (404,405) else 'provider_credit_exhausted' if response.status_code==402 else 'provider_billing_unverified' if response.status_code in (401,403) else 'speech_failed'
                raise store.AudioError('Audio streaming belum tersedia. Permintaan ini tidak dikirim ulang.','stream_unavailable' if code=='stream_unavailable' else code,503)
            for part in response.iter_content(16384):
                if not part:continue
                if first:on_first_byte();first=False
                if monotonic()>deadline:raise provider.ProviderError('provider_timeout')
                raw.extend(part)
                if len(raw)>MAX_BYTES:raise provider.ProviderError('provider_output_limit')
                # An accepted response is closed promptly on the next read after End.
                check()
        if not raw:raise provider.ProviderError('invalid_audio')
        return bytes(raw)
    except requests.RequestException:raise provider.ProviderError('provider_transport') from None


def progress(owner,ident,key,state):
    if state['status'] not in ('PROCESSING','COMPLETED') or not state.get('audio_job_id'):return None
    row=db.query_one('SELECT provider_id,original_script,source_language,target_language FROM kilas_audio_jobs WHERE id=? AND user_id=?',(state['audio_job_id'],owner))
    data=manifest(row['provider_id']) if row else None
    if not data:return None
    parts=sentences(row['original_script'])
    if sessions.result(owner,ident,key)['status'] not in ('PROCESSING','COMPLETED'):return None
    return {'total_segments':data['total'],'segments':[{'index':i,'duration_ms':clip['ms'],'translated_text':''.join(parts[:i+1]).strip()} for i,clip in enumerate(data['clips'])],
            'translated_text':row['original_script'],'source_language':row['source_language'],'target_language':row['target_language']}


def clip(owner,ident,key,index):
    state=sessions.result(owner,ident,key)
    if state['status'] not in ('PROCESSING','COMPLETED') or not state.get('audio_job_id'):raise store.AudioError('Audio tidak tersedia.','turn_unavailable',404)
    row=db.query_one('SELECT provider_id,source_content FROM kilas_audio_jobs WHERE id=? AND user_id=?',(state['audio_job_id'],owner))
    data=manifest(row['provider_id']) if row else None
    if not data or not 0<=index<len(data['clips']):raise store.AudioError('Audio tidak tersedia.','turn_unavailable',404)
    record=data['clips'][index];framed=bytes(row['source_content'])
    _frames(data,framed)
    # Recheck after the blob read so End/cancel cannot expose a stale chunk.
    latest=sessions.result(owner,ident,key)
    if latest['status'] not in ('PROCESSING','COMPLETED'):raise store.AudioError('Audio tidak tersedia.','turn_unavailable',404)
    return framed[record['offset']:record['offset']+record['bytes']]
