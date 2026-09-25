import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from candidates import guided_candidates
from recovery import (SPLIT_MIN_WORDS, calibrate, choose_workload, execution_stages,
                      has_checkpoint, parse_status, run_hashcat, validate_plan)


class PlanningTests(unittest.TestCase):
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
