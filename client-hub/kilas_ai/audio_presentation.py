"""Reversible offering visibility only; existing audio operations stay available."""
import os


def upload_translation_visible():
    return os.environ.get('KILAS_AUDIO_UPLOAD_TRANSLATION_VISIBLE','false').strip().lower() in ('1','true','yes','on')
