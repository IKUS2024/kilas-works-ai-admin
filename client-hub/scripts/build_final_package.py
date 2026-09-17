#!/usr/bin/env python3
"""Build a complete source release from a clean local commit. No push/deploy/network."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[2]
PARENT='b8b22046d02d150c84c059250aaaf56170f4f280'
BASE='6886dccdc86e2cd4d9aec3c96b0672b031e0e664'


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)


def excluded(name):
    path=Path(name)
    if any(x in ('node_modules','__pycache__','.git','.venv','venv','generated') for x in path.parts):return 'dependency/cache/generated data'
    if path.suffix.lower() in ('.zip','.tar','.gz','.db','.sqlite','.sqlite3','.pyc','.pem','.key','.patch'):return 'archive, database, key, cache, or historical patch'
    if path.name.startswith('.env') and path.name not in ('.env.example',):return 'real environment configuration'
    if path.name.startswith('shot_') and path.suffix=='.png':return 'historical screenshot; not release visual evidence'
    if name=='rencana-konten-hari-ini.pdf':return 'historical generated content document, not application asset'
    return None


def build(output,verification):
    if output.is_relative_to(ROOT):raise SystemExit('ZIP must be outside repository')
    status=git('status','--porcelain').decode()
    if status:raise SystemExit('Working tree must be clean before packaging')
    head=git('rev-parse','HEAD').decode().strip();parent=git('rev-parse','HEAD^').decode().strip()
    if parent!=PARENT:raise SystemExit('Unexpected parent; preserve Phase 6C history')
    changed=git('diff','--name-only',PARENT,head).decode().splitlines()
    if any(not x.startswith('client-hub/') for x in changed):raise SystemExit('Changes outside authorized scope')
    payload={};omitted=[]
    for name in git('ls-tree','-r','--name-only',head).decode().splitlines():
        reason=excluded(name)
        if reason:omitted.append({'path':name,'reason':reason});continue
        # Read committed bytes, never an accidental environment/cache file.
        payload['source/'+name]=git('show',head+':'+name)
    manual=ROOT/'client-hub/release-manual'
    for file in sorted(manual.iterdir()):
        if file.is_file():payload['manual/'+file.name]=file.read_bytes()
    for file in sorted(verification.iterdir()):
        if file.is_file():payload['review-metadata/'+file.name]=file.read_bytes()
    metadata={'commit':head,'parent':parent,'base':BASE,'history':git('log','-5','--format=%H %P %s').decode().splitlines(),
              'working_tree':'clean','root_source_changed':False,'push':False,'deployment':False,'production_migrations':False}
    payload['review-metadata/commit.json']=(json.dumps(metadata,indent=2)+'\n').encode()
    payload['review-metadata/changed-files.txt']=git('diff','--name-status',PARENT,head)
    # Human-readable review bundle requested by the release owner.
    payload['FINAL_REVIEW_METADATA/current-commit.txt']=('Commit: '+head+'\nParent: '+parent+'\n').encode()
    payload['FINAL_REVIEW_METADATA/git-log.txt']=git('log','-5','--format=%H %P %s')
    payload['FINAL_REVIEW_METADATA/git-status.txt']=b'git status --porcelain: empty (clean)\n'
    payload['FINAL_REVIEW_METADATA/changed-files.txt']=payload['review-metadata/changed-files.txt']
    for name in ('test-summary.txt','migration-summary.txt','manual-configuration-required.txt'):
        payload['FINAL_REVIEW_METADATA/'+name]=(verification/name).read_bytes()
    deleted=git('diff','--diff-filter=D','--name-only',PARENT,head)
    payload['review-metadata/deleted-files.txt']=deleted or b'(none)\n'
    payload['review-metadata/release.diff']=git('diff','--binary',PARENT,head,'--','client-hub')
    payload['review-metadata/cumulative.diff']=git('diff','--binary',BASE,head,'--','client-hub')
    payload['review-metadata/exclusions.json']=(json.dumps({'tracked_files_excluded':omitted,'untracked_files':'not packaged; dependencies, secrets, databases, caches and unrelated artifacts excluded','checksum_manifest_excludes_itself':True},indent=2)+'\n').encode()
    manifest=[]
    for name,data in sorted(payload.items()):manifest.append({'path':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    payload['review-metadata/file-manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    sums=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in sorted(payload.items()))
    payload['review-metadata/SHA256SUMS.txt']=sums.encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(payload.items()):archive.writestr(name,data)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:raise SystemExit('ZIP CRC validation failed')
        for name,data in payload.items():
            if archive.read(name)!=data:raise SystemExit('ZIP content validation failed')
    print(json.dumps({'file':str(output),'size_bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                      'files':len(payload),'source_files':sum(x.startswith('source/') for x in payload),'excluded_tracked_files':len(omitted),'commit':head,'parent':parent},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--verification-dir',type=Path,required=True)
    args=parser.parse_args()
    build(args.output.resolve(),args.verification_dir.resolve())
