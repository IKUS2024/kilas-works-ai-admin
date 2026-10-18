"""Fixed unprivileged guest-side framing. Never imported/executed on the web host."""
import base64,hashlib,importlib.util,json,os,stat,sys
from pathlib import Path

MAX_FILE=65536
MAX_TOTAL=180000
CHUNK=45000


def export_outputs():
    folder=Path('output');files=[];total=0;parts=0
    for path in sorted(folder.iterdir()):
        if path.name.startswith('kilas-export-') or path.name=='kilas-runtime.json':raise ValueError('reserved_export_name')
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid() or not 0<info.st_size<=MAX_FILE:raise ValueError('invalid_export_file')
            data=os.read(fd,MAX_FILE+1)
            if len(data)!=info.st_size:raise ValueError('export_file_changed')
        finally:os.close(fd)
        total+=len(data);parts+=(len(data)+CHUNK-1)//CHUNK
        if total>MAX_TOTAL or parts>4:raise ValueError('artifact_transport_limit')
        files.append((path,data))
    # No generated code is evaluated here. Actual format validation is host-side.
    for path,data in files:path.unlink()
    sequence=0
    for path,data in files:
        digest=hashlib.sha256(data).hexdigest();count=(len(data)+CHUNK-1)//CHUNK
        for part in range(count):
            frame={'protocol':'kilas.artifact.v1','name':path.name,'part':part,'parts':count,'sha256':digest,'base64':base64.b64encode(data[part*CHUNK:(part+1)*CHUNK]).decode()}
            (folder/f'kilas-export-{sequence:03}.json').write_text(json.dumps(frame));sequence+=1
    packages={name:importlib.util.find_spec(name) is not None for name in ('reportlab','docx','openpyxl','xlsxwriter','pptx','PIL')}
    (folder/'kilas-runtime.json').write_text(json.dumps({'protocol':'kilas.runtime.v1','python':sys.version.split()[0],'packages':packages}))
