import sys
import tempfile
import time
import unittest
from pathlib import Path
from converter import run_converter


class ConverterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_success(self):
        run_converter([sys.executable,'-c','print("converted")'],self.root)
        self.assertIn('converted',(self.root/'conversion.log').read_text())

    def test_timeout_and_cancel_release_worker(self):
        cmd=[sys.executable,'-c','import time; print("HIRAKU_STAGE=test",flush=True); time.sleep(60)']
        start=time.monotonic()
        with self.assertRaisesRegex(ValueError,'test'):
            run_converter(cmd,self.root,timeout=.5)
        self.assertLess(time.monotonic()-start,5)
        with self.assertRaises(InterruptedError):
            run_converter(cmd,self.root,cancelled=lambda:True)
