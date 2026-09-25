import hashlib
import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import Library
from environment_setup import (CATALOG, CATALOG_REVISION, NVRTC_DLLS, Cancelled,
                               PinnedRedirect, download_component, hardware_inventory,
                               parse_backend, safe_member, unpack_nvrtc)
from runtime import engine_environment


DEVICE_TEXT = '''Failed to initialize NVIDIA RTC library.
OpenCL Info:
OpenCL Platform ID #1
  Name....: NVIDIA CUDA
  Backend Device ID #01
    Type...........: GPU
    Name...........: Synthetic NVIDIA GPU
OpenCL Platform ID #2
  Name....: CPU platform
  Backend Device ID #02
    Type...........: CPU
    Name...........: Synthetic CPU
'''


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = Library(self.root / 'data')
        self.library.hashcat = self.library.zip2john = None
        self.setup = self.library.setup
        self.win = patch('environment_setup.windows_x64', return_value=True)
        self.tar = patch('environment_setup.system_tar', return_value=Path('trusted-system-tar.exe'))
        self.win.start(); self.tar.start()

    def tearDown(self):
        self.library.close(); self.win.stop(); self.tar.stop(); self.temp.cleanup()

    def consent(self, key='hashcat'):
        return {'component': key, 'consent': True, 'catalog_revision': CATALOG_REVISION}

    def finish(self):
        self.setup.thread.join(5)
        self.assertFalse(self.setup.thread.is_alive())

    def test_snapshot_and_guide_never_download_or_execute(self):
        with patch('environment_setup.urllib.request.build_opener') as network, patch('environment_setup.subprocess.run') as run:
            data = self.setup.snapshot()
            self.assertFalse(data['guide_seen'])
            self.assertEqual(set(CATALOG), {'hashcat', 'nvrtc'})
            self.assertTrue(data['components'][0]['eligible'])
            self.assertFalse(data['components'][1]['eligible'])
            self.setup.dismiss()
            self.assertTrue(self.setup.snapshot()['guide_seen'])
            network.assert_not_called(); run.assert_not_called()
        self.assertEqual(self.library.snapshot(), [])

    def test_exact_consent_platform_and_arbitrary_download_rejected(self):
        invalid = [self.consent() | {'consent': False}, self.consent() | {'consent': 'true'},
                   self.consent() | {'url': 'https://attacker.test/tool'},
                   self.consent() | {'catalog_revision': 'old'}, self.consent('driver')]
        with patch('environment_setup.download_component') as download:
            for data in invalid:
                with self.assertRaises(ValueError): self.setup.start(data)
            with patch('environment_setup.windows_x64', return_value=False):
                with self.assertRaises(ValueError): self.setup.start(self.consent())
            download.assert_not_called()

    def test_diagnostics_separate_inventory_enumeration_and_compute(self):
        engine = self.root / 'hashcat.exe'; engine.touch(); self.library.hashcat = engine
        inventory = {'status': 'detected', 'devices': [{'name': 'Synthetic NVIDIA', 'vendor': 'NVIDIA', 'driver': ''}]}
        with patch('environment_setup.hardware_inventory', return_value=inventory), patch('environment_setup.run_readonly', return_value=(0, DEVICE_TEXT)) as run:
            result = self.setup.diagnose()
        self.assertEqual(run.call_args.args[0], [str(engine), '-I'])
        self.assertEqual(run.call_args.kwargs['cwd'], engine.parent)
        self.assertEqual(result['report']['backend']['status'], 'recognized')
        self.assertFalse(result['report']['backend']['compute_tested'])
        self.assertTrue(result['components'][1]['eligible'])
        self.library.hashcat = self.root / 'different.exe'
        self.assertFalse(self.setup.snapshot()['components'][1]['eligible'])

    def test_inventory_failure_and_gpu_types(self):
        with patch('environment_setup.platform.system', return_value='Windows'), patch('environment_setup.run_readonly', side_effect=OSError()):
            self.assertEqual(hardware_inventory()['status'], 'unknown')
        with patch('environment_setup.platform.system', return_value='Windows'), patch('environment_setup.run_readonly', return_value=(0, '[]')):
            self.assertEqual(hardware_inventory()['status'], 'not_reported')
        cpu = parse_backend(DEVICE_TEXT.replace('Type...........: GPU', 'Type...........: CPU'), 0)
        self.assertEqual(cpu['status'], 'cpu_only')
        self.assertEqual(parse_backend(DEVICE_TEXT, 1)['status'], 'unavailable')
        cuda = parse_backend('CUDA Info:\n  Backend Device ID #1\n    Name...........: NVIDIA\n', 0)
        self.assertEqual(cuda['devices'][0]['type'], 'GPU')

    def test_existing_engine_and_unneeded_nvrtc_not_downloaded(self):
        engine = self.root / 'hashcat.exe'; engine.touch(); self.library.hashcat = engine
        with self.assertRaises(ValueError): self.setup.start(self.consent())
        with self.assertRaises(ValueError): self.setup.start(self.consent('nvrtc'))
        self.setup.report = {'hardware': {'devices': [{'name': 'Intel', 'vendor': 'Intel'}]}, 'backend': {'nvrtc_missing': True}}
        self.setup.diagnosed_engine = str(engine)
        with self.assertRaises(ValueError): self.setup.start(self.consent('nvrtc'))

    def fake_unpack(self, archive, stage, stop):
        target = stage / CATALOG['hashcat']['folder']; target.mkdir()
        (target / 'hashcat.exe').write_bytes(b'fixture, never executed')
        return target

    def test_install_activation_receipt_and_reuse_preserve_settings(self):
        extra = self.root / 'zip2john.exe'; extra.touch(); self.library.zip2john = extra
        with patch('environment_setup.download_component') as download, patch('environment_setup.unpack_hashcat', side_effect=self.fake_unpack):
            self.setup.start(self.consent()); self.finish()
            self.assertEqual(self.setup.status['phase'], 'complete')
            self.assertEqual(self.library.zip2john, extra.resolve())
            self.assertTrue(self.setup.installed('hashcat'))
            receipt = json.loads(self.setup.receipt_path('hashcat').read_text())
            self.assertEqual(receipt['sha256'], CATALOG['hashcat']['sha256'])
            self.library.save_settings({'hashcat': ''})
            self.setup.start(self.consent()); self.finish()
            self.assertEqual(download.call_count, 1)
        self.assertFalse(list(self.setup.root.glob('.install-*')))

    def test_corrupt_download_never_activates_and_can_retry(self):
        with patch('environment_setup.download_component', side_effect=ValueError('checksum failure')), patch('environment_setup.unpack_hashcat') as unpack:
            self.setup.start(self.consent()); self.finish()
            self.assertEqual(self.setup.status['phase'], 'error')
            self.assertIsNone(self.library.hashcat); unpack.assert_not_called()
        self.assertFalse(list(self.setup.root.glob('.install-*')))
        self.assertFalse(self.setup.installed('hashcat'))

    def test_cancel_and_concurrent_settings_are_guarded(self):
        begun = threading.Event()
        def download(item, path, stop, progress):
            begun.set(); stop.wait(3); raise Cancelled()
        with patch('environment_setup.download_component', side_effect=download):
            self.setup.start(self.consent()); self.assertTrue(begun.wait(2))
            with self.assertRaises(ValueError): self.setup.start(self.consent())
            with self.assertRaises(ValueError): self.library.save_settings({'hashcat': ''})
            with self.assertRaises(ValueError): self.library.start_recovery('not-needed', {})
            with self.assertRaises(ValueError): self.setup.diagnose()
            self.setup.cancel(); self.finish()
        self.assertEqual(self.setup.status['phase'], 'cancelled')
        self.assertIsNone(self.library.hashcat)

    def test_existing_directory_and_low_disk_never_overwritten(self):
        target = self.setup.root / CATALOG['hashcat']['folder']; target.mkdir(parents=True)
        marker = target / 'keep.txt'; marker.write_text('keep')
        with patch('environment_setup.download_component') as download:
            self.setup.start(self.consent()); self.finish(); download.assert_not_called()
            self.assertEqual(marker.read_text(), 'keep')
        marker.unlink(); target.rmdir()
        with patch('environment_setup.shutil.disk_usage') as disk, patch('environment_setup.download_component') as download:
            disk.return_value.free = 0
            self.setup.start(self.consent()); self.finish(); download.assert_not_called()
            self.assertEqual(self.setup.status['phase'], 'error')

    def test_stream_checksum_size_cancel_and_redirect(self):
        data = b'synthetic archive'
        item = {'url': 'https://hashcat.net/fixed', 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        class Response(io.BytesIO):
            headers = {}
        def attempt(content, spec=item, stop=None):
            target = self.root / 'archive'; target.unlink(missing_ok=True)
            with patch('environment_setup.urllib.request.build_opener') as opener:
                opener.return_value.open.return_value = Response(content)
                download_component(spec, target, stop or threading.Event(), lambda *_: None)
        attempt(data)
        for content in (data[:-1], data + b'x', b'X' * len(data)):
            with self.assertRaises(ValueError): attempt(content)
        stopped = threading.Event(); stopped.set()
        with self.assertRaises(Cancelled): attempt(data, stop=stopped)
        import urllib.request
        request = urllib.request.Request(item['url'])
        for url in ('http://hashcat.net/a', 'https://other.test/a', 'https://user@hashcat.net/a'):
            with self.assertRaises(ValueError): PinnedRedirect().redirect_request(request, None, 302, '', {}, url)

    def test_nvrtc_extracts_only_runtime_pair_and_notices(self):
        archive = self.root / 'runtime.zip'; stage = self.root / 'stage'; stage.mkdir()
        with zipfile.ZipFile(archive, 'w') as out:
            for name in NVRTC_DLLS: out.writestr('nvidia/cuda_nvrtc/bin/' + name, b'fixture DLL')
            out.writestr('package.dist-info/License.txt', 'Fixture license')
            out.writestr('bin/driver-installer.exe', 'must not extract')
            out.writestr('include/nvrtc.h', 'must not extract')
        target = unpack_nvrtc(archive, stage, threading.Event())
        self.assertEqual({p.name for p in (target / 'bin').iterdir()}, NVRTC_DLLS)
        self.assertEqual(len(list(target.rglob('*.*'))), 3)
        self.assertFalse((target / 'driver-installer.exe').exists())
        for name in ('../x', '/root/file', 'C:/file', 'x\\file', 'x/CON.txt', 'x/file.'):
            self.assertFalse(safe_member(name), name)
        self.assertTrue(safe_member('hashcat-7.1.2/docs/license.txt', 'hashcat-7.1.2'))

    def test_child_runtime_environment_does_not_change_system_path(self):
        target = self.setup.root / CATALOG['nvrtc']['folder']; (target / 'bin').mkdir(parents=True)
        (target / 'loxmit-receipt.json').write_text('{}')
        for name in NVRTC_DLLS: (target / 'bin' / name).touch()
        before = os.environ.get('PATH', '')
        with patch('runtime.sys.platform', 'win32'):
            env = engine_environment(self.library.root)
        self.assertTrue(env['PATH'].startswith(str(target / 'bin')))
        self.assertEqual(os.environ.get('PATH', ''), before)


if __name__ == '__main__':
    unittest.main()
