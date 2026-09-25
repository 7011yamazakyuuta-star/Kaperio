"""Build and verify a source-only release from an explicit file allowlist."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = 'RELEASE-MANIFEST.json'
PRIVATE_PARTS = {'outputs', 'work', 'kernels', '.git', '.agents', '.codex', '.venv',
                 '.test-data', '.tmp', '__pycache__', 'node_modules'}
TEXT_SUFFIXES = {'.py', '.ps1', '.sh', '.cmd', '.md', '.txt', '.json', '.js', '.cjs', '.html', '.css', '.webmanifest', '.yml'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
            or any(p.lower() in PRIVATE_PARTS for p in path.parts)
            or path.suffix.lower() in {'.exe', '.dll', '.pdf', '.docx', '.xlsx', '.pptx', '.hash', '.potfile', '.restore', '.hex', '.log'}
            or '/vendor/john/' in '/' + name):
        raise ValueError('Forbidden release path: ' + name)
    return path


def source_bytes(root, name):
    safe_name(name)
    path = root / name
    current = path
    while current != root:
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('Release inputs cannot be links: ' + name)
        current = current.parent
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Release input escaped root: ' + name)
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        content = data.decode('utf-8-sig')
        account_root = r'[\\/](?:Users|home)[\\/]'
        if re.search(account_root + r'[^\s"<>]+', content, re.I):
            raise ValueError('Personal absolute path in release source: ' + name)
        if re.search(r'/launch\?token=[A-Za-z0-9_-]{24,}', content):
            raise ValueError('Launch capability found: ' + name)
    return data


def specification(root):
    spec = json.loads((root / 'kaperio/release-files.json').read_text(encoding='utf-8'))
    if not re.fullmatch(r'[0-9A-Za-z.-]+', spec['version']):
        raise ValueError('Invalid release version')
    if len(spec['files']) != len(set(spec['files'])):
        raise ValueError('Duplicate release paths')
    for name in spec['files']:
        safe_name(name)
    return spec


def write_member(archive, name, data):
    item = zipfile.ZipInfo(name, date_time=(2026, 9, 24, 0, 0, 0))
    item.compress_type = zipfile.ZIP_DEFLATED
    item.create_system = 3
    item.external_attr = (0o100755 if name.endswith('.sh') else 0o100644) << 16
    archive.writestr(item, data)


def build(root=ROOT, output=None):
    root = Path(root).resolve()
    spec = specification(root)
    payload = {name: source_bytes(root, name) for name in sorted(spec['files'])}
    prefix = 'Kaperio-' + spec['version']
    output = Path(output or root / 'outputs/releases')
    output.mkdir(parents=True, exist_ok=True)
    target = output / (prefix + '-source.zip')
    temporary = target.with_suffix('.partial')
    evidence = {'version': spec['version'], 'kind': 'source-only',
                'files': {n: {'sha256': digest(d), 'bytes': len(d)} for n, d in payload.items()}}
    try:
        with zipfile.ZipFile(temporary, 'w') as archive:
            for name, data in payload.items():
                write_member(archive, prefix + '/' + name, data)
            write_member(archive, prefix + '/' + MANIFEST, json.dumps(evidence, indent=2).encode('utf-8'))
        verify(temporary, root)
        temporary.replace(target)
        target.with_suffix('.zip.sha256').write_text(digest(target.read_bytes()) + '  ' + target.name + '\n', encoding='ascii')
    finally:
        temporary.unlink(missing_ok=True)
    return target


def verify(target, root=ROOT):
    spec = specification(Path(root))
    prefix = 'Kaperio-' + spec['version'] + '/'
    expected = {prefix + n for n in spec['files']} | {prefix + MANIFEST}
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError('Archive does not match the release allowlist')
        evidence = json.loads(archive.read(prefix + MANIFEST))
        if evidence['version'] != spec['version'] or set(evidence['files']) != set(spec['files']):
            raise ValueError('Invalid embedded manifest')
        for name in spec['files']:
            safe_name(name)
            data = archive.read(prefix + name)
            if evidence['files'][name] != {'sha256': digest(data), 'bytes': len(data)}:
                raise ValueError('Checksum mismatch: ' + name)
    return {'version': spec['version'], 'files': len(spec['files']), 'sha256': digest(Path(target).read_bytes())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'verify'))
    parser.add_argument('archive', nargs='?')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action == 'build':
        result = build(output=args.output)
        print(result)
        print(json.dumps(verify(result)))
    elif args.archive:
        print(json.dumps(verify(args.archive)))
    else:
        parser.error('verify requires an archive path')
