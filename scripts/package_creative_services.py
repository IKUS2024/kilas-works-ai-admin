#!/usr/bin/env python3
"""Package the single maintained Creative Services source for Client Hub's Render root.

Run after site edits; --check verifies the committed generated bundle byte for byte.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'creative-services-site'
TARGET = ROOT / 'client-hub' / 'creative-services-site'


def manifest(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob('*')) if p.is_file() and p.name != '.source-manifest.json'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    expected = manifest(SOURCE)
    if args.check:
        if not TARGET.is_dir() or manifest(TARGET) != expected:
            raise SystemExit('Creative Services bundle differs: run python scripts/package_creative_services.py')
        if json.loads((TARGET / '.source-manifest.json').read_text()) != expected:
            raise SystemExit('Creative Services bundle manifest is stale')
        print(f'PASS: {len(expected)} bundled files match the maintained source byte for byte')
        return
    TARGET.mkdir(parents=True, exist_ok=True)
    for path in TARGET.rglob('*'):
        if path.is_file() and path.relative_to(TARGET).as_posix() not in expected:
            path.unlink()
    for name in expected:
        destination = TARGET / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / name, destination)
    (TARGET / '.source-manifest.json').write_text(json.dumps(expected, indent=2) + '\n')
    print(f'Packaged {len(expected)} Creative Services files for the existing Client Hub service')


if __name__ == '__main__':
    main()
