"""Known Creative Services interface copy only; no customer text is rewritten."""
import json
from pathlib import Path
from ui_i18n import language, translate as ui_translate
CATALOG = json.loads((Path(__file__).parent / 'locales' / 'creative.json').read_text())

def translate(message):
    text = str(message)
    return CATALOG.get(text, {}).get(language(), ui_translate(text))

def messages():
    keys = ('Nomor rekening disalin.', 'Nomor rekening dipilih. Gunakan menu Salin perangkat Anda.',
            'Ukuran foto maksimal 5 MB.', 'Pilih foto PNG atau JPEG.', 'Menyimpan…')
    return {key: translate(key) for key in keys}
