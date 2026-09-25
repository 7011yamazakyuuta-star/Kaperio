"""Build on the target OS, smoke-test separately, then package the exact bundle."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import platform
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime import APP_NAME, VERSION

RUNTIME = ['cffi', 'charset-normalizer', 'cryptography', 'lxml', 'msoffcrypto-tool',
           'olefile', 'pillow', 'pycparser', 'pycryptodomex', 'pypdf', 'pypdfium2',
           'python-docx', 'pyzipper', 'reportlab', 'typing_extensions']


def collect_licenses(destination):
    destination.mkdir(parents=True, exist_ok=True)
    inventory = {}
    for name in RUNTIME:
        dist = metadata.distribution(name)
        notices = [f for f in dist.files or [] if any(key in str(f).lower()
                   for key in ('license', 'copying', 'notice')) and dist.locate_file(f).is_file()]
        if not notices:
            raise RuntimeError('Missing upstream notices for ' + name)
        inventory[name] = dist.version
        for index, file in enumerate(notices):
            target = destination / (name + '-' + str(index) + '-' + file.name + '.txt')
            shutil.copyfile(dist.locate_file(file), target)
    python_license = next((p for p in [Path(sys.base_prefix) / 'LICENSE.txt',
                          Path(sys.base_prefix) / 'LICENSE',
                          Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt'] if p.exists()), None)
    if python_license is None:
        raise RuntimeError('Python license missing from build runtime')
    shutil.copyfile(python_license, destination / 'Python.txt')
    inventory['Python'] = platform.python_version()
    (destination / 'versions.txt').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    return inventory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package-only', action='store_true')
    args = parser.parse_args()
    output = ROOT / 'dist'
    build = ROOT / 'build'
    bundle = output / (APP_NAME + '.app' if sys.platform == 'darwin' else APP_NAME)
    if not args.package_only:
        licenses = build / 'runtime-licenses'
        collect_licenses(licenses)
        command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
                   '--name', APP_NAME, '--distpath', str(output), '--workpath', str(build / 'pyinstaller'),
                   '--specpath', str(build), '--paths', str(ROOT), '--noupx',
                   '--collect-data', 'docx', '--collect-all', 'pypdfium2', '--collect-all', 'pypdfium2_raw',
                   '--collect-submodules', 'Cryptodome', '--hidden-import', 'olefile']
        for source, target in [('static', 'static'), ('licenses', 'licenses'),
                               ('vendor/office2john.py', 'vendor'), ('office_render.ps1', '.'),
                               ('LICENSE', '.'), ('THIRD_PARTY.md', '.')]:
            command += ['--add-data', str(ROOT / source) + ':' + target]
        command += ['--add-data', str(licenses) + ':licenses/runtime']
        if sys.platform in ('darwin', 'linux'):
            from environment_setup import native_pack
            if native_pack() is None:
                raise RuntimeError('Build the pinned native engine pack before packaging this platform')
            command += ['--add-data', str(ROOT / 'component_pack') + ':component_pack']
        if sys.platform in ('win32', 'darwin'):
            icon = 'favicon.ico' if sys.platform == 'win32' else 'icon.icns'
            command += ['--windowed', '--icon', str(ROOT / 'static' / icon)]
        if sys.platform == 'darwin':
            command += ['--osx-bundle-identifier', 'org.loxmit.desktop']
        command += [str(ROOT / 'desktop.py')]
        subprocess.run(command, cwd=ROOT, check=True)
    if not bundle.is_dir():
        raise RuntimeError('Build output not found')
    package_name = APP_NAME + '-' + VERSION + '-' + platform.system().lower() + '-' + platform.machine().lower()
    releases = output / 'releases'
    releases.mkdir(exist_ok=True)
    target = releases / package_name
    if sys.platform == 'darwin':
        archive = Path(str(target) + '.zip')
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(bundle), str(archive)], check=True)
    else:
        archive = Path(shutil.make_archive(str(target), 'zip' if sys.platform == 'win32' else 'gztar',
                                          root_dir=output, base_dir=APP_NAME))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + '.sha256').write_text(digest + '  ' + archive.name + '\n', encoding='ascii')
    print(json.dumps({'archive': str(archive), 'sha256': digest, 'system': platform.platform(),
                      'architecture': platform.machine(), 'developer_signed': False}))


if __name__ == '__main__':
    main()
