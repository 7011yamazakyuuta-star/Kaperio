"""PDF parsing, hash extraction, decryption, and faithful image exports."""
from __future__ import annotations

import io
import threading
import zipfile
from pathlib import Path

import pypdfium2 as pdfium
from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.shared import Pt
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

PDFIUM_LOCK = threading.Lock()
MODES = {2: 10400, 3: 10500, 4: 10500, 5: 10600, 6: 10700}


def raw_bytes(value):
    if isinstance(value, bytes):
        return value
    return value.original_bytes


def extract_hash(reader):
    enc = reader.trailer['/Encrypt'].get_object()
    if enc.get('/Filter') != '/Standard':
        raise ValueError('証明書・DRM方式には対応していません。')
    revision = int(enc['/R'])
    if revision not in MODES:
        raise ValueError('このPDFの暗号方式には対応していません。')
    version = int(enc.get('/V', 1))
    length = int(enc.get('/Length', 40 if revision == 2 else 128))
    permissions = int(enc['/P'])
    if permissions >= 2**31:
        permissions -= 2**32
    identifier = raw_bytes(reader.trailer['/ID'][0]) if '/ID' in reader.trailer else b''
    user = raw_bytes(enc['/U'])[:48 if revision >= 5 else 32]
    owner = raw_bytes(enc['/O'])[:48 if revision >= 5 else 32]
    metadata = enc.get('/EncryptMetadata', True)
    metadata = bool(getattr(metadata, 'value', metadata))
    parts = [version, revision, length, permissions, int(metadata), len(identifier),
             identifier.hex(), len(user), user.hex(), len(owner), owner.hex()]
    if revision >= 5:
        # Hashcat's AES-256 parser requires both encrypted-key fields as well.
        for key in ('/UE', '/OE'):
            value = raw_bytes(enc[key])
            if len(value) != 32:
                raise ValueError('PDFの暗号鍵データが不正です。')
            parts.extend((len(value), value.hex()))
    return '$pdf$' + '*'.join(map(str, parts)), MODES[revision]


def inspect_pdf(path):
    with path.open('rb') as stream:
        return inspect_reader(PdfReader(stream, strict=False))


def inspect_reader(reader):
    info = {'encrypted': reader.is_encrypted, 'pages': None, 'mode': None,
            'revision': None, 'recoverable': False, 'encryption': '暗号化なし'}
    if reader.is_encrypted:
        enc = reader.trailer['/Encrypt'].get_object()
        revision = int(enc.get('/R', 0))
        bits = int(enc.get('/Length', 40 if revision == 2 else 128))
        info.update(revision=revision, encryption=f'PDF R{revision} / {bits} bit')
        try:
            _, info['mode'] = extract_hash(reader)
            info['recoverable'] = True
        except (ValueError, KeyError, AttributeError):
            pass
        try:
            info['empty_password'] = bool(reader.decrypt(''))
        except Exception:
            info['empty_password'] = False
    else:
        info['empty_password'] = True
    if info['empty_password']:
        info['pages'] = len(reader.pages)
    return info


def unlock_pdf(source, password, target):
    temporary = target.with_suffix('.partial')
    try:
        with source.open('rb') as stream:
            reader = PdfReader(stream, strict=False)
            if reader.is_encrypted and not reader.decrypt(password):
                raise ValueError('パスワードが一致しません。')
            writer = PdfWriter()
            writer.clone_document_from_reader(reader)
            count = len(reader.pages)
            writer.write(temporary)
            writer.close()
        with temporary.open('rb') as stream:
            result = PdfReader(stream)
            if result.is_encrypted or len(result.pages) != count:
                raise ValueError('保存後のPDF検証に失敗しました。')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return count


def render_page(source, number, dpi=110, grayscale=False):
    with PDFIUM_LOCK:
        with pdfium.PdfDocument(str(source)) as pdf:
            if not 0 <= number < len(pdf):
                raise ValueError('ページ番号が範囲外です。')
            page = pdf[number]
            try:
                width, height = page.get_size()
                scale = dpi / 72
                if width * height * scale * scale > 32_000_000:
                    raise ValueError('ページが大きすぎます。解像度を下げてください。')
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil().convert('L' if grayscale else 'RGB')
                finally:
                    bitmap.close()
            finally:
                page.close()
    return image, (width, height)


def preview_png(source, number):
    image, _ = render_page(source, number)
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    image.close()
    return stream.getvalue()


def export_pdf(source, target, kind, dpi, grayscale, progress, cancelled):
    if kind not in {'image_pdf', 'word', 'images', 'text'}:
        raise ValueError('未対応の出力形式です。')
    with source.open('rb') as stream:
        _export_pdf(PdfReader(stream), source, target, kind, dpi, grayscale, progress, cancelled)


def _export_pdf(reader, source, target, kind, dpi, grayscale, progress, cancelled):
    count = len(reader.pages)
    temporary = target.with_suffix('.partial')
    doc = Document() if kind == 'word' else None
    output_canvas = canvas.Canvas(str(temporary)) if kind == 'image_pdf' else None
    archive = zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) if kind == 'images' else None
    text_output = temporary.open('w', encoding='utf-8') if kind == 'text' else None
    try:
        for index in range(count):
            if cancelled():
                raise InterruptedError('書き出しを中止しました。')
            if kind == 'text':
                text = reader.pages[index].extract_text() or ''
                text_output.write(f'## Page {index + 1}\n\n{text}\n\n')
            else:
                image, (width, height) = render_page(source, index, dpi, grayscale)
                stream = io.BytesIO()
                image.save(stream, format='PNG')
                image.close()
                stream.seek(0)
                if kind == 'image_pdf':
                    output_canvas.setPageSize((width, height))
                    output_canvas.drawImage(ImageReader(stream), 0, 0, width, height)
                    output_canvas.showPage()
                elif kind == 'images':
                    archive.writestr(f'page-{index + 1:04d}.png', stream.getvalue())
                else:
                    section = doc.sections[0] if index == 0 else doc.add_section(WD_SECTION_START.NEW_PAGE)
                    section.page_width, section.page_height = Pt(width), Pt(height)
                    section.left_margin = section.right_margin = Pt(0)
                    section.top_margin = section.bottom_margin = Pt(0)
                    section.header_distance = section.footer_distance = Pt(0)
                    paragraph = doc.add_paragraph() if index else doc.paragraphs[0] if doc.paragraphs else doc.add_paragraph()
                    paragraph.paragraph_format.space_before = Pt(0)
                    paragraph.paragraph_format.space_after = Pt(0)
                    paragraph.paragraph_format.line_spacing = 1
                    paragraph.add_run().add_picture(stream, width=Pt(width - 2), height=Pt(height - 3))
                    paragraph.runs[0].font.size = Pt(1)
                stream.close()
            progress(index + 1, count)
        if output_canvas:
            output_canvas.save()
            with temporary.open('rb') as stream:
                check = PdfReader(stream)
                if check.is_encrypted or len(check.pages) != count:
                    raise ValueError('画像PDFの検証に失敗しました。')
        if archive:
            archive.close()
            archive = None
        if doc:
            doc.save(temporary)
        if text_output:
            text_output.close()
        if cancelled():
            raise InterruptedError('書き出しを中止しました。')
        temporary.replace(target)
    finally:
        if text_output:
            text_output.close()
        if archive:
            archive.close()
        temporary.unlink(missing_ok=True)
