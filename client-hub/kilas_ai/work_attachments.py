"""Work-only Office inputs; reuse existing attachment limits and image validation."""
import io
import os
import re
from . import attachments, work_artifacts


def prepare_many(files, plan):
    if len(files)>attachments.limits(plan)['max_files']:
        raise attachments.AttachmentError('Terlalu banyak lampiran untuk paket ini.')
    result=[]
    for upload in files:
        extension=(upload.filename or '').rsplit('.',1)[-1].lower()
        if extension not in ('xlsx','pptx'):
            item=attachments.prepare(upload)
            if extension=='docx':
                try:work_artifacts.validate(item)
                except Exception:raise attachments.AttachmentError('DOCX tidak dapat dibaca dengan aman.') from None
            result.append(item);continue
        name=re.sub(r'[^A-Za-z0-9._-]+','_',os.path.basename(upload.filename))[:100]
        raw=upload.stream.read(attachments.MAX_FILE_BYTES+1)
        file={'filename':name,'mime_type':work_artifacts.MIMES[extension],'content':raw}
        try:
            if len(raw)>attachments.MAX_FILE_BYTES:raise ValueError('input_limit')
            if upload.mimetype not in (file['mime_type'],'application/octet-stream'):raise ValueError('mime')
            work_artifacts.validate(file)
            if extension=='xlsx':
                from openpyxl import load_workbook
                book=load_workbook(io.BytesIO(raw),read_only=True,data_only=False,keep_links=False)
                try:
                    parts=[]
                    for sheet in book.worksheets[:5]:
                        for row in sheet.iter_rows(max_row=200,max_col=20):
                            if any(c.data_type=='f' for c in row):raise ValueError('formula_input')
                            parts.append(', '.join(str(c.value or '')[:200] for c in row))
                    text='\n'.join(parts)
                finally:book.close()
            else:
                from pptx import Presentation
                deck=Presentation(io.BytesIO(raw))
                text='\n'.join(shape.text for slide in list(deck.slides)[:30] for shape in slide.shapes if shape.has_text_frame)
            file.update(byte_size=len(raw),extracted_text=text[:12000])
            result.append(file)
        except Exception:
            raise attachments.AttachmentError('File Office tidak dapat dibaca dengan aman. Gunakan file tanpa macro, formula atau tautan eksternal.') from None
    return result
