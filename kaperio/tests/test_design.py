import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import runtime
from app import Library, public_plan
from test_core import make_pdf


class DesignTests(unittest.TestCase):
    def test_summary_does_not_expose_password_fragments(self):
        plan = {'strategy': 'mask', 'min': 4, 'max': 6, 'charsets': ['digits'],
                'words': ['secret'], 'prefix': 'secret', 'suffix': 'secret',
                'numbers': 'secret', 'separators': 'secret', 'candidates': '1000'}
        summary = public_plan(plan)
        self.assertEqual(summary['candidates'], '1000')
        self.assertNotIn('secret', json.dumps(summary))
        self.assertNotIn('words', summary)

    def test_events_elapsed_and_restart_are_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'test.pdf'
            make_pdf(source, 'secret')
            library = Library(root / 'library')
            try:
                jid = library.import_pdf(source.name, source.read_bytes())
                self.assertIsNone(library.snapshot()[0]['plan_summary'])
                with patch('app.time.time', return_value=100):
                    library.update(jid, state='recovering', plan={'strategy': 'mask', 'prefix': 'private'})
                with patch('app.time.time', return_value=110):
                    library.update(jid, metrics={'tested': 10, 'total': 100})
                    current = library.snapshot()[0]
                self.assertEqual(current['elapsed'], 10)
                self.assertEqual(current['metrics_at'], 110)
                self.assertNotIn('activity_started', current)
                self.assertNotIn('private', json.dumps(current))
                with patch('app.time.time', return_value=120):
                    library.update(jid, state='paused')
                with patch('app.time.time', return_value=180):
                    self.assertEqual(library.snapshot()[0]['elapsed'], 20)
                    library.update(jid, state='recovering')
                with patch('app.time.time', return_value=195):
                    library.update(jid, metrics={'tested': 20, 'total': 100})
                restored = Library(root / 'library')
                try:
                    saved = restored.snapshot()[0]
                    self.assertEqual(saved['state'], 'paused')
                    self.assertEqual(saved['elapsed'], 35)
                finally:
                    restored.close()
                library.update(jid, message='private candidate must not enter event history')
                self.assertNotIn('private', json.dumps(library.jobs[jid]['events']))
                for index in range(90):
                    library.update(jid, state='paused' if index % 2 else 'recovering')
                self.assertEqual(len(library.jobs[jid]['events']), 80)
                self.assertTrue(all({'time', 'text'} == set(e) for e in library.jobs[jid]['events']))
            finally:
                library.close()

    def test_existing_libraries_win_over_new_name_on_all_platforms(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            with patch.object(runtime.sys, 'frozen', True, create=True), patch.object(Path, 'home', return_value=base):
                for platform, relative, old, new in [('win32', 'windows', 'Kaperio', 'Loxmit'),
                                                     ('linux', 'linux', 'kaperio', 'loxmit'),
                                                     ('darwin', 'Library/Application Support', 'Kaperio', 'Loxmit')]:
                    target = base / relative
                    with patch.object(runtime.sys, 'platform', platform), patch.dict(runtime.os.environ, {'LOCALAPPDATA': str(target), 'XDG_DATA_HOME': str(target)}):
                        self.assertEqual(runtime.data_directory(), target / new)
                        (target / old).mkdir(parents=True)
                        self.assertEqual(runtime.data_directory(), target / old)
                        (target / new).mkdir()
                        self.assertEqual(runtime.data_directory(), target / new)

    def test_icon_formats_and_transparency(self):
        static = Path(__file__).resolve().parents[1] / 'static'
        for size in (64, 192, 512):
            with Image.open(static / f'icon-{size}.png') as im:
                self.assertEqual(im.size, (size, size))
                self.assertEqual(im.mode, 'RGBA')
                self.assertEqual(im.getchannel('A').getextrema(), (0, 255))
        with Image.open(static / 'favicon.ico') as im:
            self.assertEqual(im.ico.sizes(), {(n, n) for n in (16, 24, 32, 48, 64, 128, 256)})
        with Image.open(static / 'icon.icns') as im:
            self.assertEqual(im.format, 'ICNS')


if __name__ == '__main__':
    unittest.main()
