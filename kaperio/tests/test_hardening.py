import datetime
import http.client
import json
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import msoffcrypto
import psutil
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from openpyxl import Workbook

from app import Handler, Library
from document_worker import DocumentWorker, write_json
from formats import inspect_file, unlock_file, contents
from local_server import LocalHTTPServer
from test_core import make_pdf


class HardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_progress_update_retries_windows_reader_sharing_violation(self):
        path = self.root / 'progress.json'
        original = Path.replace
        calls = []
        def replace(source, target):
            calls.append(source)
            if len(calls) == 1:
                raise PermissionError('synthetic sharing violation')
            return original(source, target)
        with patch.object(Path, 'replace', replace):
            write_json(path, [1, 2])
        self.assertEqual(json.loads(path.read_text()), [1, 2])
        self.assertEqual(len(calls), 2)
        self.assertFalse(path.with_suffix('.tmp').exists())

    def test_office_expansion_guard_before_and_after_decryption(self):
        plain = self.root / 'plain.xlsx'
        Workbook().save(plain)
        with zipfile.ZipFile(plain, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('padding.bin', b'0' * (2 * 1024 * 1024))
        encrypted = self.root / 'encrypted.xlsx'
        with plain.open('rb') as source, encrypted.open('wb') as output:
            msoffcrypto.OfficeFile(source).encrypt('synthetic', output)
        target = self.root / 'unlocked.xlsx'
        target.write_bytes(b'preserve previous output')
        with patch('formats.MAX_EXPANDED', 1024 * 1024):
            with self.assertRaises(ValueError):
                inspect_file(plain, '.xlsx')
            for source in (plain, encrypted):
                with self.assertRaises(ValueError):
                    unlock_file(source, 'synthetic', target, {'format': 'office'})
                self.assertEqual(target.read_bytes(), b'preserve previous output')
                self.assertFalse(target.with_suffix('.partial').exists())
            with self.assertRaises(ValueError):
                contents(plain, {'format': 'office'})

    def test_office_entry_and_metadata_limits(self):
        source = self.root / 'plain.xlsx'
        Workbook().save(source)
        for name, limit in [('MAX_ENTRIES', 1), ('MAX_METADATA', 16)]:
            with patch('formats.' + name, limit), self.assertRaises(ValueError):
                inspect_file(source, '.xlsx')

    def test_prepare_releases_lock_and_can_cancel_without_engine_start(self):
        source = self.root / 'source.pdf'
        make_pdf(source, 'synthetic')
        library = Library(self.root / 'library')
        entered = threading.Event()
        errors = []
        def helper(*args):
            entered.set()
            deadline = time.monotonic() + 3
            while not args[-1]():
                if time.monotonic() > deadline:
                    raise AssertionError('cancel did not reach preparation')
                time.sleep(.01)
            raise InterruptedError()
        try:
            jid = library.import_pdf('source.pdf', source.read_bytes())
            library.hashcat = self.root / 'hashcat'
            def prepare():
                try:
                    library.start_recovery(jid, {'min': 4, 'max': 4})
                except Exception as exc:
                    errors.append(exc)
            with patch.object(library.documents, 'get_hash', side_effect=helper), patch.object(library.recovery_pool, 'submit') as submit:
                thread = threading.Thread(target=prepare)
                thread.start()
                self.assertTrue(entered.wait(3))
                start = time.monotonic()
                self.assertEqual(library.snapshot()[0]['state'], 'preparing')
                self.assertTrue(library.settings_snapshot()['settings_locked'])
                with self.assertRaises(ValueError):
                    library.remove(jid)
                library.stop(jid, cancel=True)
                self.assertLess(time.monotonic() - start, 1)
                thread.join(4)
                self.assertFalse(thread.is_alive())
                self.assertFalse(errors)
                self.assertEqual(library.jobs[jid]['state'], 'cancelled')
                submit.assert_not_called()
        finally:
            library.close()

    def test_document_worker_roundtrip_preview_exports_and_no_request_files(self):
        source = self.root / 'source.pdf'
        make_pdf(source, 'synthetic-secret')
        worker = DocumentWorker(self.root)
        try:
            info = worker.inspect_file(source, '.pdf')
            target = self.root / 'unlocked.pdf'
            result = worker.unlock_file(source, 'synthetic-secret', target, info)
            self.assertEqual(result['pages'], 2)
            self.assertTrue(worker.preview_png(target, 0).startswith(b'\x89PNG'))
            for kind, suffix in [('image_pdf', '.pdf'), ('word', '.docx'), ('images', '.zip'), ('text', '.md')]:
                updates = []
                exported = self.root / ('export' + suffix)
                worker.export_pdf(target, exported, kind, 100, False,
                                  lambda n, total: updates.append((n, total)), lambda: False)
                self.assertGreater(exported.stat().st_size, 0)
                self.assertEqual(updates[-1], (2, 2))
            self.assertFalse(list(self.root.glob('.document-*')))
        finally:
            worker.close()

    def test_worker_timeout_memory_crash_and_cancel_preserve_previous_output(self):
        fixture = Path(__file__).with_name('worker_fixture.py')
        for mode in ('timeout', 'blocked_stdin', 'memory', 'crash', 'cancel'):
            with self.subTest(mode=mode):
                worker = DocumentWorker(self.root, memory=16 * 1024**2 if mode == 'memory' else 2 * 1024**3,
                                        timeout=.7 if mode in ('timeout', 'blocked_stdin') else 5)
                target = self.root / 'previous.pdf'
                target.write_bytes(b'original')
                started = time.monotonic()
                cancelled = lambda: mode == 'cancel' and time.monotonic() - started > .5
                command = ([sys.executable, '-c', 'import time; time.sleep(20)'] if mode == 'blocked_stdin'
                           else [sys.executable, str(fixture), mode])
                with patch('document_worker.worker_command', return_value=command):
                    with self.assertRaises((ValueError, InterruptedError)) as failure:
                        worker.run('unlock', {'source': str(self.root / 'unused'), 'suffix': '.pdf',
                                              'padding': 'x' * 60000 if mode == 'blocked_stdin' else ''},
                                   target=target, cancelled=cancelled)
                if mode == 'memory':
                    self.assertIn('メモリー', str(failure.exception))
                self.assertLess(time.monotonic() - started, 8)
                self.assertEqual(target.read_bytes(), b'original')
                self.assertFalse(list(self.root.glob('.document-*')))
                worker.close()

    @unittest.skipUnless(sys.platform == 'win32' or sys.platform.startswith('linux'), 'macOS uses RSS monitoring')
    def test_os_memory_limit_blocks_large_allocation(self):
        worker = DocumentWorker(self.root)
        fixture = Path(__file__).with_name('worker_fixture.py')
        with patch('document_worker.worker_command', return_value=[sys.executable, str(fixture), 'os_limit']):
            with self.assertRaisesRegex(ValueError, 'OS memory limit enforced'):
                worker.run('inspect', {'source': 'unused'})
        worker.close()

    def test_worker_cancellation_kills_descendants(self):
        worker = DocumentWorker(self.root, timeout=5)
        record = self.root / 'pids.json'
        fixture = Path(__file__).with_name('worker_fixture.py')
        with patch('document_worker.worker_command', return_value=[sys.executable, str(fixture), 'tree']):
            with self.assertRaises(InterruptedError):
                worker.run('inspect', {'source': str(record)}, cancelled=record.exists)
        for pid in json.loads(record.read_text()):
            self.assertFalse(psutil.pid_exists(pid), str(pid))
        worker.close()

    def test_closed_worker_never_starts_another_process(self):
        worker = DocumentWorker(self.root)
        worker.close()
        with patch('document_worker.subprocess.Popen') as start, self.assertRaises(InterruptedError):
            worker.inspect_file(self.root / 'unused.pdf', '.pdf')
        start.assert_not_called()


class NetworkHardeningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.library = Library(self.root / 'library')
        self.server = LocalHTTPServer(('127.0.0.1', 0), Handler, max_connections=3)
        self.server.library, self.server.token, self.server.tls = self.library, 'synthetic', True
        self.server.authority = f'127.0.0.1:{self.server.server_port}'
        self.server.origin = 'https://' + self.server.authority
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(hours=1)).sign(key, hashes.SHA256()))
        cert_path, key_path = self.root / 'cert.pem', self.root / 'key.pem'
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        self.server.tls_context = context
        self.server.handshake_timeout = .4
        self.server.request_timeout = .4
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.library.close()
        self.tmp.cleanup()

    def client(self):
        return http.client.HTTPSConnection('127.0.0.1', self.server.server_port,
                                            timeout=2, context=ssl._create_unverified_context())

    def test_incomplete_tls_does_not_block_other_connections_and_expires(self):
        idle = socket.create_connection(('127.0.0.1', self.server.server_port), timeout=2)
        try:
            client = self.client()
            client.request('GET', '/api/jobs', headers={'Cookie': 'loxmit_session=synthetic'})
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            response.read()
            client.close()
            self.assertEqual(idle.recv(1), b'')
        finally:
            idle.close()

    def test_json_body_timeout_releases_connection(self):
        client = self.client()
        try:
            with patch('app.UPLOAD_TIMEOUT', .2):
                client.request('POST', '/api/settings', b'{', headers={
                    'Cookie': 'loxmit_session=synthetic', 'X-Loxmit': '1', 'Content-Length': '100'})
                response = client.getresponse()
                self.assertEqual(response.status, 408)
                response.read()
        finally:
            client.close()

    def test_connection_limit_rejects_excess_and_restores_slots(self):
        self.server.handshake_timeout = 1
        connections = [socket.create_connection(('127.0.0.1', self.server.server_port), timeout=2)
                       for _ in range(3)]
        try:
            time.sleep(.1)
            with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=2) as extra:
                self.assertEqual(extra.recv(1), b'')
        finally:
            for connection in connections:
                connection.close()
        deadline = time.monotonic() + 2
        while self.server.connections and time.monotonic() < deadline:
            time.sleep(.02)
        client = self.client()
        client.request('GET', '/api/jobs', headers={'Cookie': 'loxmit_session=synthetic'})
        response = client.getresponse()
        self.assertEqual(response.status, 200)
        response.read()
        client.close()
