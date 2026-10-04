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


def file_limit():
    return min(50, max(1, int(os.environ.get('KILAS_AUDIO_MAX_MB', '25')))) * 1024 * 1024


def decode(raw, suffix, *, mp3=False):
    """Decode a bounded audio track to PCM to measure actual seconds. Temp is private."""
    with tempfile.TemporaryDirectory(prefix='kilas-audio-') as directory:
        source = Path(directory) / ('source.' + suffix)
        target = Path(directory) / 'audio.wav'
        source.write_bytes(raw)
        command = [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error',
                   '-protocol_whitelist', 'file,pipe', '-threads', '1', '-i', str(source),
                   '-map', '0:a:0', '-vn', '-t', str(duration_limit()+1), '-ac', '1',
                   '-ar', '16000', '-c:a', 'pcm_s16le', '-y', str(target)]
        try:
            result = subprocess.run(command, capture_output=True, timeout=15)
            if result.returncode or not target.exists():
                raise MediaError('Audio tidak dapat dibaca. Gunakan file MP4, MP3, WAV, atau M4A yang valid.')
            pcm = target.read_bytes()
            with wave.open(io.BytesIO(pcm)) as audio:
                seconds = audio.getnframes() / audio.getframerate()
            if not 0 < seconds <= duration_limit():
                raise MediaError(f'Durasi audio maksimal {duration_limit()} detik.')
            return math.ceil(seconds * 1000), pcm
        except (subprocess.TimeoutExpired, wave.Error, EOFError):
            raise MediaError('Audio tidak dapat dibaca dalam batas waktu. Coba file yang lebih kecil.') from None


def upload(item):
    if not item or not item.filename:
        raise MediaError('Pilih audio atau video terlebih dahulu.')
    name = secure_filename(item.filename)[:160] or 'audio'
    suffix = name.rsplit('.', 1)[-1].lower()
    raw = item.stream.read(file_limit()+1)
    if not raw or len(raw) > file_limit():
        raise MediaError(f'File maksimal {file_limit()//1024//1024} MB.')
    signatures = {
        'wav': raw[:4] == b'RIFF' and raw[8:12] == b'WAVE',
        'mp3': raw[:3] == b'ID3' or (len(raw)>1 and raw[0]==255 and raw[1]&224==224),
        'm4a': raw[4:8] == b'ftyp', 'mp4': raw[4:8] == b'ftyp',
    }
    mimes = {'wav': ('audio/wav','audio/x-wav','audio/vnd.wave'), 'mp3': ('audio/mpeg','audio/mp3'),
             'mp4': ('video/mp4',), 'm4a': ('audio/mp4','audio/x-m4a','video/mp4')}
    if suffix not in signatures or not signatures[suffix] or item.mimetype not in (*mimes[suffix], 'application/octet-stream'):
        raise MediaError('Format tidak didukung. Pilih MP4, MP3, WAV, atau M4A yang valid.')
    ms, pcm = decode(raw, suffix)
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
