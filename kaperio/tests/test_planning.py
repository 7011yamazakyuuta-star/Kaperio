import json
import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from candidates import guided_candidates
from recovery import (SPLIT_MIN_WORDS, calibrate, choose_workload, execution_stages,
                      has_checkpoint, parse_status, run_hashcat, run_stage, validate_plan,
                      candidate_max_bytes, optimized_kernel, write_inputs)


class PlanningTests(unittest.TestCase):
    def test_automatic_unknown_answers_are_bounded_and_honest(self):
        plan = validate_plan({'strategy': 'automatic'})
        self.assertEqual(plan['words'], [])
        self.assertGreater(int(plan['candidates']), 0)
        self.assertLessEqual(int(plan['candidates']), 10000000)
        stages = execution_stages(10700, plan)
        self.assertEqual(sum(int(s['candidates']) for s in stages), int(plan['candidates']))
        self.assertEqual(stages[0]['charsets'], ['digits'])
        self.assertGreaterEqual(stages[0]['max'], 6)
        self.assertTrue(any('網羅' in note for note in plan['notes']))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            write_inputs(folder, plan)
            self.assertEqual((folder / 'candidates.hex').read_text(), '')
            self.assertEqual(write_inputs(folder, stages[0])[:2], ['-a', '3'])

    def test_automatic_long_hints_exact_priority_and_utf8(self):
        password = 'LongRememberedPhrase42'
        plan = validate_plan({'strategy': 'automatic', 'words': password + '\n日本語の長いフレーズ', 'numbers': '2024'})
        self.assertEqual(plan['words'][:2], [password, '日本語の長いフレーズ'])
        self.assertIn(password + '2024!', plan['words'])
        self.assertIn(password + '00', plan['words'])
        self.assertEqual(len(plan['words']), len(set(plan['words'])))
        first = execution_stages(10700, plan)[0]
        self.assertFalse(optimized_kernel(10700, first))
        self.assertGreater(candidate_max_bytes(first), 16)
        bounded = validate_plan({'strategy': 'automatic', 'words': 'x' * 127})
        self.assertIn('x' * 127, bounded['words'])
        self.assertTrue(any('127' in note for note in bounded['notes']))
        self.assertTrue(all(len(word.encode('utf-8')) <= 127 for word in bounded['words']))

    def test_automatic_known_length_charset_and_long_fixed_part(self):
        prefix = 'RememberedLongPart??'
        plan = validate_plan({'strategy': 'automatic', 'length': 'range', 'min': len(prefix) + 1,
                              'max': len(prefix) + 1, 'prefix': prefix, 'characters': 'digits'})
        self.assertEqual(plan['candidates'], '10')
        stage = execution_stages(10700, plan)[0]
        self.assertFalse(optimized_kernel(10700, stage))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            write_inputs(folder, stage)
            self.assertIn('?????1', (folder / 'search.hcmask').read_text())
        plan = validate_plan({'strategy': 'automatic', 'words': 'abc\n1234', 'characters': 'digits',
                              'length': 'range', 'min': 4, 'max': 4})
        self.assertEqual(plan['words'], ['1234'])

    def test_automatic_format_limit_does_not_block_later_valid_stages(self):
        plan = validate_plan({'strategy': 'automatic', 'words': 'LongRememberedPhrase'}, 10400)
        self.assertIn('LongRememberedPhrase42', plan['words'])
        self.assertTrue(all(candidate_max_bytes(s) <= 32 for s in execution_stages(10400, plan)))
        self.assertTrue(any('32バイト' in note for note in plan['notes']))
        with self.assertRaisesRegex(ValueError, '32バイト'):
            validate_plan({'strategy': 'automatic', 'length': 'range', 'min': 40, 'max': 45}, 10400)

    def test_automatic_invalid_answers_and_infeasible_range(self):
        for data in ({'length': 'maybe'}, {'characters': 'maybe'}, {'prefix': ['x']},
                     {'words': 'x' * 128}, {'words': '\n'.join(str(n) for n in range(65))},
                     {'length': 'range', 'min': 0, 'max': 20}, {'length': 'range', 'min': 17, 'max': 127}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_plan(dict(data, strategy='automatic'))

    def test_automatic_public_summary_redacts_private_stage_fragments(self):
        from app import public_plan
        plan = validate_plan({'strategy': 'automatic', 'words': 'SecretMemory', 'prefix': 'PrivateStart'})
        summary = public_plan(plan)
        serialized = json.dumps(summary)
        self.assertNotIn('SecretMemory', serialized)
        self.assertNotIn('PrivateStart', serialized)
        self.assertNotIn('stages', summary)
        self.assertEqual(sum(int(g['count']) for g in summary['groups']), int(plan['candidates']))

    def test_automatic_mask_stages_resume_at_next_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            exe = folder / 'hashcat'
            exe.touch()
            (folder / 'source.hash').write_text('synthetic')
            plan = validate_plan({'strategy': 'automatic'})
            stop, calls = threading.Event(), []
            def stage(executable, target, mode, current, event, update, resume, seconds):
                calls.append(target.name)
                if target.name == 'stage-000':
                    stop.set()
                return {'state': 'exhausted'}
            with patch('recovery.run_stage', side_effect=stage):
                result = run_hashcat(exe, folder, 10700, plan, stop, lambda **kw: None)
                self.assertEqual(result['state'], 'paused')
                stop.clear()
                calls.clear()
                result = run_hashcat(exe, folder, 10700, plan, stop, lambda **kw: None, True)
            self.assertEqual(result['state'], 'exhausted')
            self.assertNotIn('stage-000', calls)

    def test_automatic_capacity_notice_and_length_constraints(self):
        with patch('candidates.MAX_CANDIDATES', 2):
            plan = validate_plan({'strategy': 'automatic', 'words': 'word'})
        self.assertEqual(len(plan['words']), 2)
        self.assertTrue(any('先頭10万件' in note for note in plan['notes']))
        plan = validate_plan({'strategy': 'automatic', 'words': 'LongMemory', 'length': 'range', 'min': 20, 'max': 20})
        self.assertEqual(plan['words'], ['LongMemoryLongMemory'])

    def test_manual_long_mask_requires_bounded_keyspace(self):
        plan = validate_plan({'strategy': 'mask', 'min': 127, 'max': 127, 'prefix': 'a' * 126, 'charsets': ['digits']})
        self.assertEqual(plan['candidates'], '10')
        self.assertFalse(optimized_kernel(10700, plan))
        with self.assertRaisesRegex(ValueError, '候補範囲'):
            validate_plan({'strategy': 'mask', 'min': 20, 'max': 20})

    def test_engine_length_limit_is_not_reported_as_exhaustive_search(self):
        process = Mock(stdout=io.BytesIO(b'Maximum password length supported by kernel: 16\n'))
        process.poll.return_value = 1
        process.wait.return_value = 1
        plan = validate_plan({'strategy': 'dictionary', 'words': 'LongRememberedPhrase'})
        with tempfile.TemporaryDirectory() as temporary, patch('recovery.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(ValueError, '16バイト'):
                run_stage(Path(temporary) / 'hashcat', Path(temporary), 10700, plan, threading.Event(), lambda **kw: None)

    def test_guided_exact_priority_dedup_and_unicode(self):
        single, _ = guided_candidates({'words': 'test', 'numbers': '2024', 'separators': '!'})
        self.assertIn('Test2024!', single)
        self.assertNotIn('Ttest2024!', single)
        words, groups = guided_candidates({'words': 'test\nTest\n日本\n$HEX[4142]', 'numbers': '2024',
                                           'separators': '!', 'combine': True, 'typos': True})
        self.assertEqual(words[:4], ['test', 'Test', '日本', '$HEX[4142]'])
        for word in ('Test2024!', 'test!2024', '2024test', '日本2024!', 'test!日本', 'tset', 'tst'):
            self.assertIn(word, words)
        self.assertEqual(len(words), len(set(words)))
        self.assertEqual(sum(g['count'] for g in groups), len(words))
        self.assertEqual(groups[0]['name'], '入力候補')

    def test_guided_limits_fail_instead_of_silent_truncation(self):
        for data in ({'words': ''}, {'words': 'x' * 49}, {'words': '\n'.join(str(x) for x in range(65))},
                     {'words': 'word', 'separators': '\n'}, {'words': 'word', 'combine': 'false'},
                     {'words': 'word', 'numbers': '\n'.join(str(x) for x in range(33))}):
            with self.assertRaises(ValueError):
                guided_candidates(data)
        with patch('candidates.MAX_CANDIDATES', 2), self.assertRaises(ValueError):
            guided_candidates({'words': 'test'})

    def test_split_preserves_every_word_and_transformed_bounds(self):
        short = ['w' + str(i).zfill(6) for i in range(SPLIT_MIN_WORDS)]
        for strategy, boundary in [('dictionary', 16), ('dictionary_rules', 15), ('hybrid_suffix', 14), ('hybrid_prefix', 14)]:
            words = short + ['x' * boundary, 'y' * (boundary + 1), '日本語日本語']
            plan = validate_plan({'strategy': strategy, 'words': '\n'.join(words), 'min': 1, 'max': 2})
            stages = execution_stages(10700, plan)
            self.assertEqual(len(stages), 2)
            self.assertEqual(stages[1]['words'], words[-2:])
            self.assertEqual([w for s in stages for w in s['words']], words)
            self.assertEqual(sum(int(s['candidates']) for s in stages), int(plan['candidates']))
            self.assertEqual(len(execution_stages(10400, plan)), 1)
            self.assertEqual(len(execution_stages(10700, dict(plan, kernel='pure'))), 1)

    def test_small_lists_do_not_add_launch_overhead(self):
        plan = validate_plan({'strategy': 'dictionary', 'words': 'short\n' + 'x' * 17})
        self.assertEqual(len(execution_stages(10700, plan)), 1)

    def test_completed_stages_resume_without_retesting(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            exe = folder / 'hashcat'; exe.touch()
            (folder / 'source.hash').write_text('synthetic')
            plan = validate_plan({'strategy': 'guided', 'words': 'test', 'numbers': '42'})
            stop = threading.Event()
            calls = []
            def stage(executable, target, mode, current, event, update, resume, seconds):
                calls.append((target.name, current['words']))
                if target.name == 'stage-000':
                    stop.set()
                return {'state': 'exhausted'}
            with patch('recovery.run_stage', side_effect=stage):
                result = run_hashcat(exe, folder, 10700, plan, stop, lambda **kw: None)
            self.assertEqual(result['state'], 'paused')
            self.assertTrue(has_checkpoint(folder))
            self.assertEqual(json.loads((folder / 'execution.json').read_text())['index'], 1)
            stop.clear(); calls.clear()
            with patch('recovery.run_stage', side_effect=stage):
                result = run_hashcat(exe, folder, 10700, plan, stop, lambda **kw: None, True)
            self.assertEqual(result['state'], 'exhausted')
            self.assertNotIn('stage-000', [c[0] for c in calls])
            changed = dict(plan, words=['different'] + plan['words'][1:])
            with self.assertRaises(ValueError):
                run_hashcat(exe, folder, 10700, changed, stop, lambda **kw: None, True)

    def test_found_long_candidate_and_legacy_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            exe = folder / 'hashcat'; exe.touch()
            (folder / 'source.hash').write_text('synthetic')
            plan = validate_plan({'strategy': 'dictionary', 'words': 'word'})
            (folder / 'session.restore').touch()
            with patch('recovery.run_stage', return_value={'state': 'found', 'password': b'word'}) as run:
                result = run_hashcat(exe, folder, 10700, plan, threading.Event(), lambda **kw: None, True)
            self.assertEqual(result['password'], b'word')
            self.assertEqual(run.call_args.args[1], folder)

    def test_time_budget_is_shared_across_stages(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            exe = folder / 'hashcat'; exe.touch()
            (folder / 'source.hash').write_text('synthetic')
            plan = validate_plan({'strategy': 'guided', 'words': 'test', 'numbers': '42', 'minutes': 1})
            clock, budgets = [0], []
            def stage(executable, target, mode, current, stop, update, resume, seconds):
                budgets.append(seconds)
                clock[0] += min(40, seconds)
                return {'state': 'exhausted'} if seconds >= 40 else {'state': 'paused', 'reason': 'time_limit'}
            with patch('recovery.time.monotonic', side_effect=lambda: clock[0]), patch('recovery.run_stage', side_effect=stage):
                result = run_hashcat(exe, folder, 10700, plan, threading.Event(), lambda **kw: None)
            self.assertEqual(budgets, [60, 20])
            self.assertEqual(result['reason'], 'time_limit')
            self.assertTrue(result['checkpoint'])

    def test_tuning_needs_repeatable_improvement_and_safe_samples(self):
        status = parse_status(json.dumps({'status': 3, 'devices': [{'speed': 100, 'temp': 50}, {'speed': 10}]}))
        self.assertFalse(status['thermal_complete'])
        def rows(speeds):
            return [{'workload': w, 'speed': speed, 'usable': True} for w, pair in enumerate(speeds, 1) for speed in pair]
        self.assertEqual(choose_workload(rows([(100, 102), (130, 132), (131, 133)])), 2)
        self.assertEqual(choose_workload(rows([(100, 102), (104, 105), (106, 106)])), 1)
        self.assertEqual(choose_workload(rows([(100, 102), (100, 170), (110, 170)])), 1)
        hot = rows([(100, 102), (130, 132), (150, 160)])
        for row in hot:
            row['usable'] = row['workload'] == 1
        self.assertEqual(choose_workload(hot), 1)
        self.assertTrue(validate_plan({'workload': 'auto'})['tune'])

    def test_tuning_found_password_is_not_discarded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'source.hash').write_text('synthetic')
            with patch('recovery.run_stage', return_value={'state': 'found', 'password': b'found'}):
                result, workload = calibrate(root / 'hashcat', root, 10700, validate_plan({}),
                                              threading.Event(), lambda **kw: None, 0, {}, float('inf'))
            self.assertEqual(result['password'], b'found')


if __name__ == '__main__':
    unittest.main()
