"""Trusted wheel bootstrap inside the VM; generated source never runs here."""
import inspect
import json

LIBRARY_ROOT = '/opt/kilas-document-libs'
ENTRYPOINT = LIBRARY_ROOT + '/_kilas_document_entry.py'
ENTRY_SOURCE = '''import os,runpy,sys
from pathlib import Path
root=Path('/opt/kilas-document-libs')
assert sys.flags.isolated and sys.flags.ignore_environment and sys.flags.no_user_site
assert os.getuid()==65534 and Path.cwd()==Path('/tmp/kilas-run')
assert root.stat().st_uid==0 and not root.stat().st_mode&0o022
sys.path=[str(root),str(Path.cwd())]+[p for p in sys.path if p and 'site-packages' not in p and 'dist-packages' not in p]
args=sys.argv[1:]
if args[:1]==['-m']:
    assert args[1:]==['unittest','discover','-s','tests']
    sys.argv=['unittest','discover','-s','tests'];runpy.run_module('unittest',run_name='__main__')
else:
    assert len(args)==1
    sys.argv=args;runpy.run_path(args[0],run_name='__main__')
'''


def install_runtime():
    # Invoked by the root VM runner before namespace setup or child creation.
    # Inputs are hash-pinned release wheels, never customer-selected packages.
    import hashlib
    import importlib
    import importlib.metadata
    import platform
    import stat
    import sys
    import sysconfig
    import zipfile
    from pathlib import Path, PurePosixPath
    assert os.getuid() == 0
    assert sys.flags.isolated and sys.flags.ignore_environment and sys.flags.no_user_site
    assert sys.implementation.name == 'cpython' and platform.machine() == 'x86_64'
    assert not sysconfig.get_config_var('Py_GIL_DISABLED')
    assert 'cp'+str(sys.version_info.major)+str(sys.version_info.minor) == RUNTIME_MANIFEST['abi']
    assert platform.libc_ver()[0] == 'glibc'
    assert tuple(map(int, platform.libc_ver()[1].split('.')[:2])) >= (2, 28)
    root = Path('/opt/kilas-document-libs')
    os.umask(0o022)
    root.mkdir(mode=0o755)  # An unexpected existing runtime fails closed.
    total = 0
    count = 0
    for wheel in RUNTIME_MANIFEST['wheels']:
        path = Path('/root') / wheel['filename']
        info = path.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
        assert info.st_size == wheel['size']
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(65536), b''):
                digest.update(chunk)
        assert digest.hexdigest() == wheel['sha256']
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                name = PurePosixPath(member.filename)
                assert not name.is_absolute() and '..' not in name.parts and '\\' not in member.filename
                assert member.filename and len(member.filename) < 512
                kind = stat.S_IFMT(member.external_attr >> 16)
                assert kind in (0, stat.S_IFREG, stat.S_IFDIR)
                count += 1
                total += member.file_size
                assert count <= 2048 and 0 <= member.file_size <= 8*1024*1024 and total <= 48*1024*1024
                if any(part.endswith('.data') for part in name.parts):
                    continue  # No wheel scripts/entrypoints are installed.
                target = root.joinpath(*name.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o755)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                with archive.open(member) as source, target.open('xb') as destination:
                    copied = 0
                    while True:
                        chunk = source.read(65536)
                        if not chunk:
                            break
                        copied += len(chunk)
                        assert copied <= member.file_size
                        destination.write(chunk)
                    assert copied == member.file_size
                target.chmod(0o644)
        path.unlink()  # Remove compressed copies before the confined process.
    (root/'_kilas_document_entry.py').write_text(RUNTIME_ENTRY_SOURCE)
    (root/'_kilas_document_entry.py').chmod(0o644)
    sys.path = [str(root)] + [p for p in sys.path if p and 'site-packages' not in p and 'dist-packages' not in p]
    modules = {'reportlab':'reportlab','python-docx':'docx','openpyxl':'openpyxl',
               'python-pptx':'pptx','pillow':'PIL','lxml':'lxml',
               'typing-extensions':'typing_extensions','et-xmlfile':'et_xmlfile',
               'xlsxwriter':'xlsxwriter','charset-normalizer':'charset_normalizer'}
    versions = {}
    for wheel in RUNTIME_MANIFEST['wheels']:
        name = wheel['project'].lower().replace('_','-')
        module = importlib.import_module(modules[name])
        location = Path(module.__file__).resolve()
        assert location.is_relative_to(root) and location.stat().st_uid == 0
        assert not location.stat().st_mode & 0o022
        assert importlib.metadata.version(wheel['project']) == wheel['version']
        versions[name] = wheel['version']
    return {'abi':RUNTIME_MANIFEST['abi'], 'python':platform.python_version(),
            'manifest_sha256':RUNTIME_MANIFEST_SHA256, 'versions':versions,
            'root_owned':True, 'network_install':False, 'host_execution':False}


def runner_source(manifest, digest, *, proof=False):
    from . import workspace_large_guest as guest
    source = guest.proof_runner_source() if proof else guest.runner_source()
    replacements = {
        '    assert os.getuid()==0': '    assert os.getuid()==0\n    runtime_evidence=install_runtime()',
        "args=['/usr/bin/python3','-B','-E','-s']":
            "args=['/usr/bin/python3','-I','-B',"+repr(ENTRYPOINT)+"]",
        "    report['outputs']=stage_outputs()":
            "    report['runtime_evidence']=runtime_evidence\n    report['outputs']=stage_outputs()",
    }
    for before, after in replacements.items():
        if source.count(before) != 1:
            raise ValueError('document_runner_baseline_changed')
        source = source.replace(before, after, 1)
    constants = ('RUNTIME_MANIFEST='+repr(json.loads(json.dumps(manifest)))+'\n'
                 'RUNTIME_MANIFEST_SHA256='+repr(digest)+'\n'
                 'RUNTIME_ENTRY_SOURCE='+repr(ENTRY_SOURCE)+'\n')
    return constants + inspect.getsource(install_runtime) + '\n' + source
