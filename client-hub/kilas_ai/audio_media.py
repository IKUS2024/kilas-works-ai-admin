"""Bounded local media decoding; no user URLs, paths, or paid transport."""
import io
import math
import os
import subprocess
import tempfile
import wave
from pathlib import Path

import imageio_ffmpeg
from werkzeug.utils import secure_filename


class MediaError(ValueError):
    pass


def duration_limit():
    return min(600, max(1, int(os.environ.get('KILAS_AUDIO_MAX_SECONDS', '600'))))


def file_limit(suffix='mp4'):
    """Product caps in MiB; video size never determines Audio balance."""
    return (250 if suffix == 'mp4' else 100) * 1024 * 1024


def _decode_source(source, directory):
    # Both paths are generated privately by this module, never accepted from a form.
    target = Path(directory) / 'audio.wav'
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error',
               '-protocol_whitelist', 'file,pipe', '-threads', '1', '-i', str(source),
               '-map', '0:a:0', '-vn', '-t', str(duration_limit()+1), '-ac', '1',
               '-ar', '16000', '-c:a', 'pcm_s16le', '-y', str(target)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=15)
        if result.returncode or not target.exists():
            raise MediaError('Audio pada file ini tidak dapat dibaca.')
        # At most 601 seconds of mono 16 kHz PCM; never read source video into RAM.
        with target.open('rb') as output:
            pcm = output.read(20*1024*1024+1)
        if len(pcm) > 20*1024*1024:
            raise MediaError('Audio pada file ini tidak dapat dibaca.')
        with wave.open(io.BytesIO(pcm)) as audio:
            seconds = audio.getnframes() / audio.getframerate()
        if not 0 < seconds <= duration_limit():
            raise MediaError(f'Durasi audio maksimal {duration_limit()} detik.')
        return math.ceil(seconds * 1000), pcm
    except (subprocess.TimeoutExpired, wave.Error, EOFError):
        raise MediaError('Audio pada file ini tidak dapat dibaca dalam batas waktu.') from None


def decode(raw, suffix, *, mp3=False):
    """Only bounded provider audio uses this convenience decoder."""
    if suffix not in ('wav', 'mp3', 'm4a', 'mp4') or len(raw)>20*1024*1024:
        raise MediaError('Audio pada file ini tidak dapat dibaca.')
    with tempfile.TemporaryDirectory(prefix='kilas-audio-') as directory:
        source = Path(directory) / ('source.' + suffix)
        source.write_bytes(raw)
        return _decode_source(source, directory)


def upload(item):
    if not item or not item.filename:
        raise MediaError('Pilih audio atau video terlebih dahulu.')
    name = secure_filename(item.filename)[:160] or 'audio'
    suffix = name.rsplit('.', 1)[-1].lower()
    mimes = {'wav': ('audio/wav','audio/x-wav','audio/vnd.wave'), 'mp3': ('audio/mpeg','audio/mp3'),
             'mp4': ('video/mp4',), 'm4a': ('audio/mp4','audio/x-m4a','video/mp4')}
    if suffix not in mimes or item.mimetype not in (*mimes[suffix], 'application/octet-stream'):
        raise MediaError('Format tidak didukung. Pilih MP4, MP3, WAV, atau M4A yang valid.')
    total = 0
    with tempfile.TemporaryDirectory(prefix='kilas-audio-upload-') as directory:
        source = Path(directory) / ('source.' + suffix)
        with source.open('wb') as output:
            while True:
                chunk = item.stream.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > file_limit(suffix):
                    raise MediaError(f'File maksimal {file_limit(suffix)//1024//1024} MB.')
                output.write(chunk)
        with source.open('rb') as incoming:
            head = incoming.read(12)
        valid = {'wav': head[:4]==b'RIFF' and head[8:12]==b'WAVE',
                 'mp3': head[:3]==b'ID3' or (len(head)>1 and head[0]==255 and head[1]&224==224),
                 'mp4': head[4:8]==b'ftyp', 'm4a': head[4:8]==b'ftyp'}
        if not total or not valid[suffix]:
            raise MediaError('Audio pada file ini tidak dapat dibaca.')
        ms, pcm = _decode_source(source, directory)
    # Context cleanup has deleted both the large source and extracted temp audio.
    print(f'KILAS_AUDIO_MEDIA bytes={total} duration_ms={ms} source_cleanup=true', flush=True)
    return name, ms, pcm


def mp3_duration(raw):
    if not raw or len(raw)>20*1024*1024 or not (raw[:3]==b'ID3' or (raw[0]==255 and len(raw)>1 and raw[1]&224==224)):
        raise MediaError('Provider belum menghasilkan MP3 yang valid.')
    return decode(raw, 'mp3')[0]


def ensure_mp3(raw):
    """Dubbing can return source-format audio; normalize WAV to an actual MP3."""
    if raw[:4]!=b'RIFF':
        return raw,mp3_duration(raw)
    if len(raw)>20*1024*1024 or raw[8:12]!=b'WAVE':raise MediaError('Hasil audio tidak valid.')
    with tempfile.TemporaryDirectory(prefix='kilas-audio-result-') as folder:
        source=Path(folder)/'input.wav';target=Path(folder)/'result.mp3';source.write_bytes(raw)
        try:
            r=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-protocol_whitelist','file,pipe',
                '-threads','1','-i',str(source),'-map','0:a:0','-vn','-t',str(duration_limit()+1),'-c:a','libmp3lame','-b:a','128k','-y',str(target)],capture_output=True,timeout=15)
            if r.returncode:raise MediaError('Hasil audio belum dapat dikonversi ke MP3.')
            result=target.read_bytes();return result,mp3_duration(result)
        except subprocess.TimeoutExpired:
            raise MediaError('Hasil audio belum dapat dikonversi dalam batas waktu.') from None
