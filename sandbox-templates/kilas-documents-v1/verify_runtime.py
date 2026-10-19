"""Build-time interpreter/import/ownership verification. Never an acceptance bypass."""
import argparse,hashlib,importlib,importlib.metadata,importlib.util,json,os,platform,stat,sys
from pathlib import Path

MODULES={'reportlab':'reportlab','python-docx':'docx','openpyxl':'openpyxl','python-pptx':'pptx','pillow':'PIL','lxml':'lxml','typing-extensions':'typing_extensions','et-xmlfile':'et_xmlfile','xlsxwriter':'xlsxwriter','charset-normalizer':'charset_normalizer'}


def verify(prefix,owner=0):
    here=Path(__file__).resolve().parent;plan=json.loads((here/'plan.json').read_text());prefix=Path(prefix).resolve()
    assert platform.python_implementation()=='CPython' and platform.python_version()==plan['python_version']
    assert platform.machine()=='x86_64' and tuple(map(int,platform.libc_ver()[1].split('.')[:2]))>=(2,28)
    assert Path(sys.prefix).resolve()==prefix and sys.prefix!=sys.base_prefix
    assert sys.flags.ignore_environment and sys.flags.no_user_site
    binary=Path(sys._base_executable).resolve().stat();assert binary.st_uid in (0,owner) and not binary.st_mode&0o022
    cfg=(prefix/'pyvenv.cfg').read_text().lower();assert 'include-system-site-packages = false' in cfg
    for path in prefix.rglob('*'):
        info=path.lstat()
        if stat.S_ISLNK(info.st_mode):
            assert info.st_uid==owner
            continue
        assert info.st_uid==owner and not info.st_mode&0o022
    versions={};imports={}
    for wheel in plan['wheels']:
        name=wheel['name'].lower().replace('_','-');module=importlib.import_module(MODULES[name])
        location=Path(module.__file__).resolve();assert location.is_relative_to(prefix)
        if os.getuid()!=owner:assert not os.access(location.parent,os.W_OK)
        assert importlib.metadata.version(wheel['name'])==wheel['version']
        versions[wheel['name']]=wheel['version'];imports[MODULES[name]]=str(location)
    for value in sys.path:
        assert value and Path(value).is_absolute()
        assert not Path(value).is_relative_to(Path.cwd()) or Path.cwd()==prefix
        assert not str(value).startswith('/tmp/kilas-run')
        location=Path(value).resolve();location=location if location.exists() else location.parent
        info=location.stat();assert info.st_uid in (0,owner) and not info.st_mode&0o022
    return {'python':platform.python_version(),'executable':sys.executable,'prefix':str(prefix),'architecture':platform.machine(),'versions':versions,'imports':imports,'owner_checked':owner,'verification_uid':os.getuid(),'ignore_environment':bool(sys.flags.ignore_environment),'no_user_site':bool(sys.flags.no_user_site)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prefix',default='/opt/kilas-document-python');parser.add_argument('--owner',type=int,default=0);parser.add_argument('--smoke',action='store_true');parser.add_argument('--representative',action='store_true');args=parser.parse_args()
    result=verify(args.prefix,args.owner)
    if args.smoke or args.representative:
        import resource
        for name,value in (('RLIMIT_CPU',10),('RLIMIT_AS',268435456),('RLIMIT_FSIZE',8388608)):
            resource.setrlimit(getattr(resource,name),(value,value))
        path=Path(__file__).with_name('smoke_documents.py');spec=importlib.util.spec_from_file_location('fixed_document_smoke',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        files=module.representative() if args.representative else module.smoke()
        result['documents']={n:{'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in files.items()}
        result['generation_limits']={'cpu_seconds':10,'address_space_bytes':268435456,'file_bytes':8388608}
        result['verification_scope']='package_generation_only; not E2B confinement or end-to-end acceptance'
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':main()
