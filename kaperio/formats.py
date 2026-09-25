"""Format adapters. Preserve document bytes after authenticated decryption."""
from __future__ import annotations

import re
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

import msoffcrypto
import pyzipper
from pypdf import PdfReader

from pdf_tools import extract_hash, inspect_pdf, unlock_pdf
from recovery import CREATE_FLAGS
from converter import run_converter

ROOT = Path(__file__).resolve().parent
OFFICE_EXT = {'.xlsx', '.pptx', '.docx', '.xlsm', '.pptm', '.docm'}
SUPPORTED = OFFICE_EXT | {'.pdf', '.zip'}
MAX_EXPANDED = 512 * 1024 * 1024
MAX_ENTRIES = 10000


def office_renderer(extension):
    if shutil.which('soffice') or shutil.which('libreoffice') or Path('/Applications/LibreOffice.app/Contents/MacOS/soffice').exists():
        return True
    if os.name != 'nt':
        return False
    import winreg
    progid = 'Excel.Application' if extension.startswith('.xls') else 'PowerPoint.Application' if extension.startswith('.ppt') else 'Word.Application'
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + '\\CLSID'):
            return True
    except OSError:
        return False


def render_office(source, target, cancelled=lambda: False):
    if not office_renderer(source.suffix):
        raise ValueError('PDF変換には対応するMicrosoft Officeのインストールが必要です。')
    temporary = target.with_name('office-rendering.pdf')
    try:
        soffice = shutil.which('soffice') or shutil.which('libreoffice')
        if not soffice and Path('/Applications/LibreOffice.app/Contents/MacOS/soffice').exists():
            soffice = '/Applications/LibreOffice.app/Contents/MacOS/soffice'
        if soffice:
            output_dir = target.parent / 'office-render'
            output_dir.mkdir(exist_ok=True)
            profile = target.parent / 'libreoffice-profile'
            # A dedicated profile never attaches to the user's open LibreOffice instance.
            run_converter([soffice, '-env:UserInstallation=' + profile.as_uri(), '--headless',
                           '--convert-to', 'pdf', '--outdir', str(output_dir), str(source)], target.parent, cancelled)
            rendered = output_dir / (source.stem + '.pdf')
            if rendered.exists():
                rendered.replace(temporary)
        else:
            run_converter(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                           '-File', str(ROOT / 'office_render.ps1'), '-Source', str(source), '-Target', str(temporary)],
                          target.parent, cancelled)
        if not temporary.exists():
            raise ValueError('OfficeのPDF変換に失敗しました。Officeのライセンスとファイル内容を確認してください。')
        reader = PdfReader(temporary)
        if reader.is_encrypted or not len(reader.pages):
            raise ValueError('Office出力のPDFを検証できませんでした。')
        if cancelled():
            raise InterruptedError('書き出しを中止しました。')
        temporary.replace(target)
        return len(reader.pages)
    finally:
        temporary.unlink(missing_ok=True)


def validate_entries(entries):
    if len(entries) > MAX_ENTRIES or sum(i.file_size for i in entries) > MAX_EXPANDED:
        raise ValueError('ZIPの展開量上限（512MB・10,000件）を超えています。')
    for item in entries:
        path = PurePosixPath(item.filename.replace('\\', '/'))
        if path.is_absolute() or '..' in path.parts or ':' in item.filename or '\x00' in item.filename:
            raise ValueError('ZIP内に安全に扱えないファイル名があります。')
        if stat.S_ISLNK(item.external_attr >> 16):
            raise ValueError('シンボリックリンクを含むZIPは未対応です。')


def office_hash(source):
    if getattr(sys, 'frozen', False):
        with tempfile.TemporaryDirectory(prefix='kaperio-office-') as temporary:
            output = Path(temporary) / 'hash.txt'
            result = subprocess.run([sys.executable, '--office-hash', str(source), str(output)],
                                    capture_output=True, timeout=30, creationflags=CREATE_FLAGS)
            raw = output.read_bytes() if result.returncode == 0 and output.exists() else b''
    else:
        result = subprocess.run([sys.executable, str(ROOT / 'vendor' / 'office2john.py'), str(source)],
                                capture_output=True, timeout=30, creationflags=CREATE_FLAGS)
        raw = result.stdout
    match = re.search(rb'\$office\$\*(2007|2010|2013)\*[^\r\n:]+', raw)
    if not match:
        raise ValueError('このOffice暗号方式のHashcat復元には対応していません。')
    value = match.group().decode('ascii')
    return value, {b'2007': 9400, b'2010': 9500, b'2013': 9600}[match[1]]


def discover_zip2john(configured=None):
    candidates = [configured, os.environ.get('LOXMIT_ZIP2JOHN'), os.environ.get('KAPERIO_ZIP2JOHN'), shutil.which('zip2john'),
                  ROOT / 'vendor' / 'john' / 'zip2john.exe']
    return next((Path(p).resolve() for p in candidates if p and Path(p).is_file()
                 and (os.name == 'nt' or Path(p).suffix != '.exe')), None)


def zip_hash(source, executable=None):
    executable = discover_zip2john(executable)
    if not executable:
        raise ValueError('ZIP探索には別途zip2johnが必要です。設定で実行ファイルを指定してください。')
    if os.name != 'nt' and executable.suffix == '.exe':
        raise ValueError('このOSのzip2johnをPATHに配置してください。')
    if not executable.exists():
        raise ValueError('zip2johnが見つかりません。')
    result = subprocess.run([str(executable), str(source)], capture_output=True, timeout=60,
                            cwd=executable.parent, creationflags=CREATE_FLAGS)
    if result.returncode:
        raise ValueError('zip2johnを実行できませんでした。配布一式のDLLと実行権限を確認してください。終了コード: ' + str(result.returncode))
    aes = re.search(rb'\$zip2\$[^\r\n]+?\$/zip2\$', result.stdout)
    if aes:
        return aes.group().decode('ascii'), 13600
    pk = re.search(rb'\$pkzip2\$[^\r\n]+?\$/pkzip2\$', result.stdout)
    if pk:
        # Hashcat's PKZIP parser uses the same fields with the pkzip marker.
        value = pk.group().decode('ascii').replace('$pkzip2$', '$pkzip$').replace('$/pkzip2$', '$/pkzip$')
        fields = value[len('$pkzip$'):].split('*')
        count = int(fields[0], 16)
        if count != 1:
            # Let hashcat identify the multi-file variant from its complete hash.
            return value, None
        return value, 17210 if fields[9] == '0' else 17200
    raise ValueError('このZIPの暗号方式・サイズではHashcat用データを取得できません。')


def inspect_file(source, extension, zip2john=None):
    if extension == '.pdf':
        return dict(inspect_pdf(source), format='pdf', extension=extension)
    info = {'format': 'zip' if extension == '.zip' else 'office', 'extension': extension,
            'pages': None, 'mode': None, 'recoverable': False, 'revision': None}
    if extension == '.zip':
        with pyzipper.AESZipFile(str(source)) as archive:
            entries = archive.infolist()
            validate_entries(entries)
            encrypted = any(x.flag_bits & 1 for x in entries)
            info.update(encrypted=encrypted, empty_password=not encrypted,
                        encryption='暗号化ZIP' if encrypted else '暗号化なし', entries=len(entries))
        if encrypted:
            try:
                _, info['mode'] = zip_hash(source, zip2john)
                info['recoverable'] = True
            except ValueError as exc:
                info['recovery_note'] = str(exc)
    elif extension in OFFICE_EXT:
        with open(source, 'rb') as stream:
            office = msoffcrypto.OfficeFile(stream)
            encrypted = office.is_encrypted()
            info.update(encrypted=encrypted, empty_password=not encrypted,
                        encryption='Office / ' + str(getattr(office, 'type', '暗号化')) if encrypted else '暗号化なし')
        if encrypted:
            try:
                _, info['mode'] = office_hash(source)
                info['recoverable'] = True
            except ValueError:
                pass
    else:
        raise ValueError('対応形式はPDF、Excel、PowerPoint、Word、ZIPです。')
    return info


def get_hash(source, info, hashcat, zip2john=None):
    if info['format'] == 'pdf':
        with source.open('rb') as stream:
            return extract_hash(PdfReader(stream))
    if info['format'] == 'office':
        return office_hash(source)
    value, mode = zip_hash(source, zip2john)
    if mode is None:
        path = source.with_suffix('.identify.hash')
        path.write_text(value, encoding='ascii')
        try:
            result = subprocess.run([str(hashcat), '--identify', str(path)], cwd=hashcat.parent,
                                    capture_output=True, timeout=30, creationflags=CREATE_FLAGS)
            modes = re.findall(rb'^\s*(172\d\d)\s*\|', result.stdout, re.M)
            if len(modes) != 1:
                raise ValueError('ZIPのHashcat方式を一意に特定できませんでした。')
            mode = int(modes[0])
        finally:
            path.unlink(missing_ok=True)
    return value, mode


def unlock_file(source, password, target, info):
    if info['format'] == 'pdf':
        return unlock_pdf(source, password, target)
    temporary = target.with_suffix('.partial')
    try:
        if info['format'] == 'office':
            if isinstance(password, bytes):
                password = password.decode('utf-8')
            with open(source, 'rb') as stream:
                office = msoffcrypto.OfficeFile(stream)
                if office.is_encrypted():
                    office.load_key(password=password, verify_password=True)
                    with open(temporary, 'wb') as output:
                        office.decrypt(output, verify_integrity=True)
                else:
                    shutil.copyfile(source, temporary)
            with zipfile.ZipFile(temporary) as archive:
                if '[Content_Types].xml' not in archive.namelist() or archive.testzip():
                    raise ValueError('解除後のOffice文書を検証できませんでした。')
        else:
            pwd = password.encode('utf-8') if isinstance(password, str) else password
            with pyzipper.AESZipFile(str(source)) as archive, zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as output:
                entries = archive.infolist()
                validate_entries(entries)
                total = 0
                for item in entries:
                    clean = zipfile.ZipInfo(item.filename, item.date_time)
                    clean.compress_type = zipfile.ZIP_DEFLATED
                    clean.external_attr = item.external_attr
                    clean.comment = item.comment
                    with archive.open(item, pwd=pwd or None) as src, output.open(clean, 'w', force_zip64=True) as dest:
                        while chunk := src.read(1024 * 1024):
                            total += len(chunk)
                            if total > MAX_EXPANDED:
                                raise ValueError('ZIPの展開量上限を超えました。')
                            dest.write(chunk)
                output.comment = archive.comment
            with zipfile.ZipFile(temporary) as archive:
                if any(i.flag_bits & 1 for i in archive.infolist()) or archive.testzip():
                    raise ValueError('解除後のZIPを検証できませんでした。')
        temporary.replace(target)
        return None
    except (msoffcrypto.exceptions.InvalidKeyError, RuntimeError) as exc:
        raise ValueError('パスワードが一致しないか、対応していない暗号方式です。') from exc
    finally:
        temporary.unlink(missing_ok=True)


def contents(source, info):
    with zipfile.ZipFile(source) as archive:
        if info['format'] == 'zip':
            return [{'name': i.filename, 'size': i.file_size} for i in archive.infolist()][:1000]
        names = archive.namelist()
        if 'xl/workbook.xml' in names:
            root = ElementTree.fromstring(archive.read('xl/workbook.xml'))
            return [{'name': e.attrib['name'], 'size': None} for e in root.iter() if e.tag.endswith('}sheet')]
        if 'ppt/presentation.xml' in names:
            pages = sorted(n for n in names if re.fullmatch(r'ppt/slides/slide\d+\.xml', n))
            return [{'name': 'スライド ' + str(i + 1), 'size': None} for i, _ in enumerate(pages)]
        return [{'name': 'Word文書', 'size': None}]


def office_text(source):
    with zipfile.ZipFile(source) as archive:
        names = [n for n in archive.namelist() if n in ('word/document.xml', 'xl/sharedStrings.xml') or re.fullmatch(r'ppt/slides/slide\d+\.xml', n)]
        result = []
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            result.append('## ' + name + '\n\n' + '\n'.join(e.text for e in root.iter() if e.tag.endswith('}t') and e.text))
        return '\n\n'.join(result)
