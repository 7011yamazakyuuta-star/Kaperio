import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from scripts.release import build, safe_name, source_bytes, verify


class ReleaseTests(unittest.TestCase):
    def test_private_and_binary_paths_rejected(self):
        for path in ('../secret', 'outputs/result.txt', 'kaperio/.test-data/file.txt',
                     'kaperio/vendor/john/LICENSE.txt', 'hashcat.exe', 'driver.dll', '.git/config'):
            with self.assertRaises(ValueError):
                safe_name(path)

    def test_allowlist_determinism_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'kaperio').mkdir()
            (root / 'kaperio/release-files.json').write_text(json.dumps({'version': 'test', 'files': ['README.md']}))
            (root / 'README.md').write_text('Public source only')
            (root / 'secret.txt').write_text('not allowed in the archive')
            first = build(root, root / 'one')
            second = build(root, root / 'two')
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(verify(first, root)['files'], 1)
            with zipfile.ZipFile(first, 'a') as archive:
                archive.writestr('Kaperio-test/secret.txt', 'forbidden')
            with self.assertRaises(ValueError):
                verify(first, root)

    def test_personal_path_scanner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'example.py').write_text('C:' + '\\' + 'Users' + '\\' + 'private-account\\file.pdf')
            with self.assertRaises(ValueError):
                source_bytes(root, 'example.py')
