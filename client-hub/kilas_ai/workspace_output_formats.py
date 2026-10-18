"""Bounded static output validation. Never execute, import or render supplied code."""
import io,json,re,stat,zipfile,posixpath,warnings
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from .workspace_files import SOURCE_TYPES

OFFICE={'docx':('application/vnd.openxmlformats-officedocument.wordprocessingml.document','word/document.xml','wordprocessingml.document.main+xml'),
        'xlsx':('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','xl/workbook.xml','spreadsheetml.sheet.main+xml'),
        'pptx':('application/vnd.openxmlformats-officedocument.presentationml.presentation','ppt/presentation.xml','presentationml.presentation.main+xml')}
MIMES={**{k:v for k,v in SOURCE_TYPES.items() if not v.startswith('image/')},'svg':'text/plain','pdf':'application/pdf','zip':'application/zip',
       'png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','webp':'image/webp','gif':'image/gif','bmp':'image/bmp',**{k:v[0] for k,v in OFFICE.items()}}
MAX_RAW=8*1024*1024


def filename(name):
    if name in ('LICENSE','Dockerfile','Makefile','.gitignore'):return 'txt'
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}',name) or '..' in name:raise ValueError('invalid_work_filename')
    extension=name.rsplit('.',1)[-1].lower()
    if extension not in MIMES:raise ValueError('unsupported_output_format')
    return extension


def strict_json(raw):
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise ValueError('duplicate_json_key')
            value[key]=item
        return value
    def invalid(value):raise ValueError('invalid_json_number')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)


def entries(raw):
    if not raw.startswith(b'PK\x03\x04'):raise ValueError('invalid_archive_magic')
    result={};seen=set();total=0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos=archive.infolist()
        if not 1<=len(infos)<=1000:raise ValueError('archive_count')
        for item in infos:
            name=item.filename.rstrip('/')
            if not name or '\\' in name or ':' in name or name.startswith('/') or any(p in ('','..','.') for p in name.split('/')):raise ValueError('unsafe_archive_path')
            if any(p.startswith('.') and p!='.gitignore' and not (p=='.rels' and name.endswith('_rels/.rels')) for p in name.split('/')):raise ValueError('protected_archive_path')
            if name.casefold() in seen:raise ValueError('duplicate_archive_path')
            seen.add(name.casefold());mode=item.external_attr>>16
            local=raw[item.header_offset:item.header_offset+8]
            if len(local)!=8 or local[:4]!=b'PK\x03\x04' or int.from_bytes(local[6:8],'little')!=item.flag_bits:raise ValueError('archive_header_mismatch')
            if item.flag_bits&1 or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR)) or item.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):raise ValueError('unsafe_archive_entry')
            total+=item.file_size
            if item.file_size>MAX_RAW or total>24*1024*1024 or item.file_size>max(1,item.compress_size)*200:raise ValueError('oversized_archive')
            if item.is_dir():continue
            with archive.open(item) as source:data=source.read(item.file_size+1)
            if len(data)!=item.file_size:raise ValueError('invalid_archive_size')
            result[name]=data
    return result


def xml(raw):
    if b'<!doctype' in raw.lower() or b'<!entity' in raw.lower():raise ValueError('unsafe_office_xml')
    root=ET.fromstring(raw);count=0;stack=[(root,0)]
    while stack:
        node,depth=stack.pop();count+=1
        if depth>80 or count>100000:raise ValueError('oversized_office_xml')
        stack.extend((child,depth+1) for child in node)
    return root


def office(extension,raw):
    files=entries(raw);mime,main,content_type=OFFICE[extension]
    if main not in files or '[Content_Types].xml' not in files or '_rels/.rels' not in files:raise ValueError('invalid_office_file')
    roots={'docx':'{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document','xlsx':'{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbook','pptx':'{http://schemas.openxmlformats.org/presentationml/2006/main}presentation'}
    if xml(files[main]).tag!=roots[extension]:raise ValueError('invalid_office_root')
    types=xml(files['[Content_Types].xml'])
    if not any(n.get('PartName')=='/'+main and n.get('ContentType','').endswith(content_type) for n in types):raise ValueError('office_type_mismatch')
    for name,data in files.items():
        if any(v in name.lower() for v in ('vbaproject','activex','embeddings/')) or name.lower().endswith(('.exe','.dll','.html','.htm','.mht','.mhtml','.js','.vbs','.ps1','.hta','.svg')):raise ValueError('unsafe_office_file')
        if name.lower().endswith('.bin'):
            # Standard Office printer metadata is data, not an embedded OLE/VBA payload.
            prefix={'docx':'word','xlsx':'xl','pptx':'ppt'}[extension]
            printer_type='application/vnd.openxmlformats-officedocument.'+{'docx':'wordprocessingml','xlsx':'spreadsheetml','pptx':'presentationml'}[extension]+'.printerSettings'
            declared=any(n.get('Extension')=='bin' and n.get('ContentType')==printer_type for n in types)
            if not re.fullmatch(prefix+r'/printerSettings/printerSettings[0-9]+\.bin',name) or not declared or len(data)>65536 or data.startswith((b'MZ',b'\x7fELF',b'\xd0\xcf\x11\xe0')):raise ValueError('unsafe_office_binary')
        if name.endswith(('.xml','.rels')):
            root=xml(data)
            if b'macroenabled' in data.lower() or b'oleobject' in data.lower():raise ValueError('unsafe_office_file')
            if name.endswith('.rels'):
                base=name.rsplit('/_rels/',1)[0] if '/_rels/' in name else ''
                for relation in root:
                    target=relation.get('Target','')
                    if relation.get('TargetMode','').lower()=='external' or re.search(r'^[A-Za-z][A-Za-z0-9+.-]*:|^//',target) or '\\' in target:raise ValueError('unsafe_office_link')
                    resolved=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(base,target.split('#',1)[0]))
                    if resolved.startswith('../') or (target and not target.startswith('#') and resolved not in files):raise ValueError('invalid_office_link')
            if extension=='xlsx':
                for node in root.iter():
                    if node.tag.rsplit('}',1)[-1]=='f':
                        formula=node.text or ''
                        if re.search(r'\[|\]|\||https?:|file:|DDE|WEBSERVICE|HYPERLINK|INDIRECT',formula,re.I):raise ValueError('unsafe_formula')
                        functions=re.findall(r'([A-Za-z_][A-Za-z_0-9.]*)\s*\(',formula)
                        if any(f.upper() not in {'SUM','AVERAGE','MIN','MAX','COUNT','COUNTA','IF','IFERROR','ROUND','ABS','SUMIF','COUNTIF','AND','OR'} for f in functions):raise ValueError('unsafe_formula')
    if extension=='xlsx' and not any(n.startswith('xl/worksheets/sheet') and n.endswith('.xml') for n in files):raise ValueError('empty_workbook')
    if extension=='pptx' and not any(n.startswith('ppt/slides/slide') and n.endswith('.xml') for n in files):raise ValueError('empty_presentation')


def pdf(raw):
    from pypdf import PdfReader
    from pypdf.generic import IndirectObject,DictionaryObject,ArrayObject
    if not raw.startswith(b'%PDF-') or b'%%EOF' not in raw[-1024:]:raise ValueError('invalid_work_pdf')
    reader=PdfReader(io.BytesIO(raw),strict=True)
    if reader.is_encrypted or not 1<=len(reader.pages)<=50:raise ValueError('invalid_work_pdf')
    forbidden={'/JS','/JavaScript','/OpenAction','/AA','/Launch','/EmbeddedFiles','/EmbeddedFile','/RichMedia','/XFA','/AcroForm'}
    actions={'/JavaScript','/Launch','/GoToR','/SubmitForm','/ImportData','/Rendition','/Movie','/Sound'}
    visited=set();stack=[(reader.trailer,0)];count=0
    while stack:
        value,depth=stack.pop();count+=1
        if count>10000 or depth>64:raise ValueError('oversized_pdf')
        if isinstance(value,IndirectObject):
            ident=(value.idnum,value.generation)
            if ident in visited:continue
            visited.add(ident);value=value.get_object()
        if isinstance(value,DictionaryObject):
            if forbidden.intersection(map(str,value.keys())) or str(value.get('/S','')) in actions:raise ValueError('active_pdf')
            stack.extend((v,depth+1) for v in value.values())
        elif isinstance(value,ArrayObject):stack.extend((v,depth+1) for v in value)
    if not any(p.get('/Contents') for p in reader.pages):raise ValueError('empty_pdf')


def _validate(name,mime,raw,*,nested=False,large=False):
    extension=filename(name)
    if mime!=MIMES[extension] or not isinstance(raw,bytes) or not 0<len(raw)<=MAX_RAW:raise ValueError('invalid_work_file')
    if raw.startswith((b'MZ',b'\x7fELF')):raise ValueError('executable_output')
    if extension=='zip':
        if nested:raise ValueError('nested_archive')
        files=entries(raw)
        if len(files)>80 or sum(map(len,files.values()))>(8 if large else 2)*1024*1024:raise ValueError('archive_size')
        for path,data in files.items():
            leaf=PurePosixPath(path).name
            if leaf in ('LICENSE','Dockerfile','Makefile','.gitignore'):data.decode('utf-8');continue
            ext=filename(leaf)
            # SVG is source only, never an admitted raster preview.
            validate(leaf,MIMES[ext],data,nested=True)
    elif extension in OFFICE:office(extension,raw)
    elif extension=='pdf':pdf(raw)
    elif mime.startswith('image/'):
        from PIL import Image
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if {'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp','GIF':'image/gif','BMP':'image/bmp'}.get(image.format)!=mime or image.width*image.height>20_000_000 or getattr(image,'n_frames',1)!=1:raise ValueError('invalid_work_image')
                image.verify()
    else:
        text=raw.decode('utf-8')
        if '\0' in text:raise ValueError('invalid_source_text')
        if extension in ('py','json'):
            from .workspace_files import validate_source
            validate_source(name,text)
        if extension=='json':strict_json(text)
        elif extension=='csv':
            import csv
            for row in csv.reader(io.StringIO(text)):
                for cell in row:
                    if cell.lstrip().startswith(('=','+','-','@')) and not re.fullmatch(r'[+-]?\d+(?:\.\d+)?',cell.strip()):raise ValueError('unsafe_csv_output')
    return raw


def validate(name,mime,raw,*,nested=False,large=False):
    try:return _validate(name,mime,raw,nested=nested,large=large)
    except ValueError:raise
    except Exception:raise ValueError('invalid_work_file') from None
