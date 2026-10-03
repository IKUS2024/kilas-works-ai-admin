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
                cached=load_workbook(io.BytesIO(raw),read_only=True,data_only=True,keep_links=False)
                try:
                    parts=[]
                    for sheet in book.worksheets[:5]:
                        parts.append('Sheet: '+sheet.title+' (first 200 rows / 20 columns)')
                        values=cached[sheet.title].iter_rows(max_row=200,max_col=20)
                        for number,(row,calculated) in enumerate(zip(sheet.iter_rows(max_row=200,max_col=20),values),1):
                            cells=[]
                            for cell,value in zip(row,calculated):
                                if cell.value is None:continue
                                content=str(cell.value)[:200]
                                if cell.data_type=='f':
                                    content+=' [cached value: '+str(value.value)[:200]+ '; not recalculated]'
                                cells.append(cell.coordinate+'='+content)
                            if cells:parts.append('Row '+str(number)+': '+' | '.join(cells))
                    text='\n'.join(parts)
                finally:
                    book.close()
                    cached.close()
            else:
                from pptx import Presentation
                deck=Presentation(io.BytesIO(raw))
                parts=[]
                for number,slide in enumerate(list(deck.slides)[:30],1):
                    parts.append('Slide '+str(number))
                    for shape in slide.shapes:
                        if shape.has_text_frame:parts.append(shape.text)
                        if shape.has_table:
                            parts.extend(' | '.join(cell.text[:200] for cell in row.cells[:20]) for row in list(shape.table.rows)[:100])
                    if slide.has_notes_slide:
                        notes=slide.notes_slide.notes_text_frame
                        if notes and notes.text.strip():parts.append('Notes: '+notes.text)
                text='\n'.join(parts)
            file.update(byte_size=len(raw),extracted_text=text[:12000])
            result.append(file)
        except Exception:
            raise attachments.AttachmentError('File Office tidak dapat dibaca dengan aman. Gunakan file tanpa macro atau tautan eksternal.') from None
    return result
