import errno
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import Handler, Library, TRANSFER_CHUNK
from test_core import make_pdf


class BoundedReader(io.BytesIO):
    def read(self, size=-1):
        if not 0 < size <= TRANSFER_CHUNK:
            raise AssertionError('Unbounded read')
        return super().read(size)


class StreamingTests(unittest.TestCase):
    def test_streamed_import_identity_duplicate_and_bounded_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Library(Path(tmp) / 'library')
            content = b'x' * (3 * TRANSFER_CHUNK + 7)
            info = {'format': 'pdf', 'extension': '.pdf', 'empty_password': False}
            try:
                with patch('app.inspect_file', return_value=info) as inspect:
                    first = library.import_stream('test.pdf', BoundedReader(content), len(content))
                    second = library.import_stream('again.pdf', BoundedReader(content), len(content))
                    self.assertEqual(first, second)
                    inspect.assert_called_once()
                self.assertEqual(library.jobs[first]['sha256'], hashlib.sha256(content).hexdigest())
                self.assertEqual((library.folder(first) / 'source.pdf').read_bytes(), content)
                self.assertFalse(list(library.root.glob('.upload-*')))
            finally:
                library.close()

    def test_failed_write_parse_and_save_clean_up_and_allow_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = Library(root / 'library')
            source = root / 'valid.pdf'
            make_pdf(source, 'Test42')
            content = source.read_bytes()
            try:
                for target, failure in (('inspect_file', ValueError('parse')), ('disk_usage', OSError(errno.ENOSPC, 'full'))):
                    patch_target = 'app.inspect_file' if target == 'inspect_file' else 'app.shutil.disk_usage'
                    with patch(patch_target, side_effect=failure), self.assertRaises((ValueError, OSError)):
                        library.import_stream('valid.pdf', BoundedReader(content), len(content))
                    self.assertEqual(list(library.root.iterdir()), [])
                with patch.object(library, 'save', side_effect=OSError(errno.ENOSPC, 'full')), self.assertRaises(OSError):
                    library.import_stream('valid.pdf', BoundedReader(content), len(content))
                self.assertEqual(library.snapshot(), [])
                self.assertEqual(list(library.root.iterdir()), [])
                jid = library.import_stream('valid.pdf', BoundedReader(content), len(content))
                self.assertEqual(library.jobs[jid]['state'], 'locked')
            finally:
                library.close()

    def test_disk_full_during_transfer_removes_partial_and_releases_slot(self):
        original_open = Path.open
        class FullDisk:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.stream.close()
            def write(self, chunk):
                if self.stream.tell():
                    raise OSError(errno.ENOSPC, 'full')
                return self.stream.write(chunk)
        def failing_open(path, mode='r', *args, **kwargs):
            stream = original_open(path, mode, *args, **kwargs)
            return FullDisk(stream) if mode == 'wb' and path.parent.name.startswith('.upload-') else stream
        with tempfile.TemporaryDirectory() as tmp:
            library = Library(tmp)
            try:
                with patch.object(Path, 'open', failing_open), self.assertRaises(OSError):
                    library.import_stream('test.pdf', BoundedReader(b'x' * (TRANSFER_CHUNK + 1)), TRANSFER_CHUNK + 1)
                self.assertEqual(list(library.root.iterdir()), [])
                self.assertFalse(library.import_lock.locked())
            finally:
                library.close()

    def test_download_streams_without_read_bytes_and_handles_disconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'output.pdf'
            content = b'z' * (TRANSFER_CHUNK * 2 + 3)
            target.write_bytes(content)
            handler = object.__new__(Handler)
            handler.connection = type('Connection', (), {'settimeout': lambda *args: None})()
            handler.send_headers = lambda status, size, *args: self.assertEqual((status, size), (200, len(content)))
            class Sink(io.BytesIO):
                def write(self, chunk):
                    self.assert_size(chunk)
                    return super().write(chunk)
                def assert_size(self, chunk):
                    if len(chunk) > TRANSFER_CHUNK:
                        raise AssertionError('Unbounded write')
            handler.wfile = Sink()
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('Whole-file read')):
                handler.send_file(target, 'application/pdf')
            self.assertEqual(handler.wfile.getvalue(), content)
            with patch.object(handler.wfile, 'write', side_effect=BrokenPipeError):
                handler.send_file(target, 'application/pdf')
            self.assertTrue(handler.close_connection)
