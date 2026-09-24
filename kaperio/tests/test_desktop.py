import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime
from recovery import hashcat_arguments, optimized_kernel, validate_plan


class DesktopTests(unittest.TestCase):
    def test_private_data_paths(self):
        with patch.object(runtime.sys, 'frozen', True, create=True):
            with patch.object(runtime.sys, 'platform', 'win32'), patch.dict(runtime.os.environ, {'LOCALAPPDATA': 'local-data'}):
                self.assertEqual(runtime.data_directory(), Path('local-data/Kaperio'))
            with patch.object(runtime.sys, 'platform', 'linux'), patch.dict(runtime.os.environ, {'XDG_DATA_HOME': 'xdg-data'}):
                self.assertEqual(runtime.data_directory(), Path('xdg-data/kaperio'))
            with patch.object(runtime.sys, 'platform', 'darwin'):
                self.assertEqual(runtime.data_directory(), Path.home() / 'Library/Application Support/Kaperio')

    def test_kernel_bounds_and_utf8(self):
        for word, expected in [('a' * 16, True), ('a' * 17, False), ('日' * 5, True), ('日' * 6, False)]:
            plan = validate_plan({'strategy': 'dictionary', 'words': word})
            self.assertEqual(optimized_kernel(10700, plan), expected)
            self.assertFalse(optimized_kernel(9600, plan))
        plan = validate_plan({'strategy': 'dictionary', 'words': 'short\n' + 'x' * 100})
        self.assertFalse(optimized_kernel(10400, plan))
        self.assertFalse(optimized_kernel(10400, validate_plan({'kernel': 'pure'})))
        with self.assertRaises(ValueError):
            validate_plan({'kernel': 'unsafe'})

    def test_argument_parity_and_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            exe = folder / 'hashcat'
            plan = validate_plan({'strategy': 'dictionary', 'words': 'Test42'})
            args = hashcat_arguments(exe, folder, 10400, plan)
            self.assertIn('-O', args)
            self.assertIn('--hex-wordlist', args)
            self.assertIn('--hwmon-temp-abort', args)
            plan['kernel'] = 'pure'
            self.assertNotIn('-O', hashcat_arguments(exe, folder, 10400, plan))
            (folder / 'session.restore').touch()
            self.assertEqual(hashcat_arguments(exe, folder, 10400, plan, True)[-1], '--restore')
