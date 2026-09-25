import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime
from recovery import RULES, candidate_max_bytes, hashcat_arguments, optimized_kernel, validate_plan, write_inputs


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

    def test_hybrids_and_rules_preserve_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for strategy, attack in [('hybrid_suffix', '6'), ('hybrid_prefix', '7')]:
                plan = validate_plan({'strategy': strategy, 'words': 'one\ntwo', 'min': 1, 'max': 2,
                                      'charsets': ['digits'], 'prefix': 'ignored'})
                self.assertEqual(plan['candidates'], '220')
                self.assertEqual(candidate_max_bytes(plan), 5)
                args = write_inputs(folder, plan)
                self.assertEqual(args[:3], ['-a', attack, '--hex-wordlist'])
                self.assertEqual((folder / 'search.hcmask').read_text(), '?d,?1\n?d,?1?1\n')
                expected_first = folder / ('candidates.hex' if attack == '6' else 'search.hcmask')
                self.assertEqual(args[3], str(expected_first))
                plan['words'] = ['x' * 15]
                self.assertFalse(optimized_kernel(10700, plan))
            plan = validate_plan({'strategy': 'dictionary_rules', 'words': 'word'})
            self.assertEqual(plan['candidates'], str(len(RULES)))
            self.assertEqual(candidate_max_bytes(plan), 5)
            self.assertIn('-r', write_inputs(folder, plan))
            self.assertIn('c$9', (folder / 'variants.rule').read_text().splitlines())
            for strategy in ('dictionary_rules', 'hybrid_prefix', 'hybrid_suffix'):
                with self.assertRaises(ValueError):
                    validate_plan({'strategy': strategy, 'words': 'x' * 127})

    def test_compound_resume_restores_private_wordlist(self):
        from app import Library
        from test_core import make_pdf
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'test.pdf'
            make_pdf(source, 'secret')
            library = Library(root / 'library')
            library.hashcat = root / 'hashcat'
            try:
                jid = library.import_pdf(source.name, source.read_bytes())
                with patch.object(library.recovery_pool, 'submit') as submit:
                    for strategy in ('dictionary_rules', 'hybrid_prefix', 'hybrid_suffix'):
                        library.start_recovery(jid, {'strategy': strategy, 'words': 'private-word'})
                        self.assertNotIn('words', library.jobs[jid]['plan'])
                        library.update(jid, state='paused')
                        library.start_recovery(jid, {}, resume=True)
                        self.assertEqual(submit.call_args.args[3]['words'], ['private-word'])
                        library.update(jid, state='paused')
            finally:
                library.close()
