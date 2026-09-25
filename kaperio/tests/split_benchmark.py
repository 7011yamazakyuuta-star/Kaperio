"""Measure startup tradeoffs before choosing the mixed-list split threshold."""
import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from formats import get_hash, inspect_file
from recovery import run_hashcat, run_stage, validate_plan
from test_core import make_pdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hashcat', type=Path, required=True)
    args = parser.parse_args()
    root = Path('.test-data/split-threshold-' + str(time.time_ns())).resolve()
    root.mkdir(parents=True)
    source = root / 'synthetic.pdf'
    make_pdf(source, 'OutsideCandidateSet', 'AES-256')
    value, mode = get_hash(source, inspect_file(source, '.pdf'), args.hashcat.resolve())
    report = {'runs': [], 'medians': {}, 'experimental_split_min_words': 32768}
    for count in (32768, 65536):
        words = '\n'.join('word' + str(i).zfill(6) for i in range(count)) + '\nMixedLongPassword!'
        plan = validate_plan({'strategy': 'dictionary', 'words': words, 'devices': '1', 'minutes': 2})
        for repeat in range(2):
            for policy in (('previous', 'split') if repeat == 0 else ('split', 'previous')):
                folder = root / f'{count}-{policy}-{repeat}'; folder.mkdir()
                (folder / 'source.hash').write_text(value + '\n', encoding='ascii')
                warnings = set()
                def update(**fields):
                    if fields.get('warning'):
                        warnings.add(fields['warning'])
                started = time.monotonic()
                runner = run_stage if policy == 'previous' else run_hashcat
                with patch('recovery.SPLIT_MIN_WORDS', 32768):
                    result = runner(args.hashcat.resolve(), folder, mode, plan, threading.Event(), update)
                assert result['state'] == 'exhausted'
                row = {'short_words': count, 'long_words': 1, 'policy': policy, 'repeat': repeat + 1,
                       'seconds': time.monotonic() - started, 'warnings': sorted(warnings)}
                report['runs'].append(row)
                print(json.dumps(row, ensure_ascii=True), flush=True)
                time.sleep(2)
        medians = {p: statistics.median(r['seconds'] for r in report['runs'] if r['short_words'] == count and r['policy'] == p)
                   for p in ('previous', 'split')}
        report['medians'][str(count)] = medians
        print(json.dumps({'short_words': count, 'medians': medians}), flush=True)
        (root / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Report: ' + str(root / 'results.json'), flush=True)


if __name__ == '__main__':
    main()
