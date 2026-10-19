"""PREPARATION ONLY. Builds a local definition; never calls Template.build/API."""
from pathlib import Path
import json
import re

ROOT=Path(__file__).resolve().parent
PREFLIGHT="/usr/local/bin/python3.12 -I -c \"import sys,platform; assert sys.version_info[:3]==(3,12,14); assert platform.machine()=='x86_64'; assert platform.libc_ver()[0]=='glibc'; assert tuple(map(int,platform.libc_ver()[1].split('.')[:2]))>=(2,28)\""
INSTALL=('set -eu; umask 022; '+PREFLIGHT+'; '
    'test ! -e /opt/kilas-document-python; '
    '/usr/local/bin/python3.12 -I -m venv /opt/kilas-document-python; '
    '/opt/kilas-document-python/bin/python3 -I -m pip install --no-cache-dir --only-binary=:all: --require-hashes --index-url https://pypi.org/simple -r /opt/kilas-document-build/requirements.lock; '
    '/opt/kilas-document-python/bin/python3 -I -m pip check; '
    'chown -R 0:0 /opt/kilas-document-python /opt/kilas-document-build; '
    'chmod -R go-w /opt/kilas-document-python /opt/kilas-document-build')


def definition(base_image):
    if not isinstance(base_image,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._/:\-]*@sha256:[0-9a-f]{64}',base_image):raise ValueError('immutable_base_image_required')
    if base_image!=json.loads((ROOT/'plan.json').read_text())['base_image']:raise ValueError('unreviewed_base_image')
    from e2b import Template
    template=Template(file_context_path=str(ROOT),file_ignore_patterns=['__pycache__','*.pyc','.env','*.key']).from_image(base_image)
    template=template.run_cmd('mkdir -p /opt/kilas-document-build; chmod 0755 /opt/kilas-document-build',user='root')
    for name in ('requirements.lock','plan.json','verify_runtime.py','smoke_documents.py'):
        template=template.copy(name,'/opt/kilas-document-build/'+name,user='root',mode=0o644)
    return template.run_cmd(INSTALL,user='root').run_cmd('/opt/kilas-document-python/bin/python3 -I -B /opt/kilas-document-build/verify_runtime.py --smoke --representative',user='nobody')
