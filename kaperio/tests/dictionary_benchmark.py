"""Compare the previous pure-dictionary default with bounded auto optimization."""
import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from formats import inspect_file, get_hash
from recovery import run_hashcat, validate_plan
from test_core import make_pdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hashcat', type=Path, required=True)
    args = parser.parse_args()
    executable = args.hashcat.resolve()
    root = Path('.test-data/dictionary-benchmark').resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'synthetic.pdf'
    make_pdf(source, 'OutsideThisCandidateSet', 'AES-256')
    value, mode = get_hash(source, inspect_file(source, '.pdf'), executable)
    words = '\n'.join('word' + str(i).zfill(6) for i in range(100000))
    rows = []
    for repeat in range(3):
        for kernel in (('pure', 'auto') if repeat % 2 == 0 else ('auto', 'pure')):
            folder = root / (str(time.time_ns()) + '-' + kernel)
            folder.mkdir()
            (folder / 'source.hash').write_text(value + '\n', encoding='ascii')
            plan = validate_plan({'strategy': 'dictionary', 'words': words, 'devices': '1',
                                  'workload': 1, 'minutes': 2, 'kernel': kernel})
            warnings = set()
            def update(**fields):
                if fields.get('warning'):
                    warnings.add(fields['warning'])
            started = time.monotonic()
            result = run_hashcat(executable, folder, mode, plan, threading.Event(), update)
            elapsed = time.monotonic() - started
            assert result['state'] == 'exhausted', result['state']
            row = {'mode': mode, 'kernel': kernel, 'repeat': repeat + 1, 'wall_seconds': elapsed,
                   'candidates': 100000, 'outcome': 'exhausted', 'warnings': sorted(warnings)}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=True), flush=True)
            time.sleep(2)
    medians = {k: statistics.median(r['wall_seconds'] for r in rows if r['kernel'] == k) for k in ('pure', 'auto')}
    report = {'runs': rows, 'median_seconds': medians, 'pure_over_auto': medians['pure'] / medians['auto'],
              'scope': 'Kaperio old/new dictionary policy; total wall time including initialization and input write; same 100000 candidates, PDF R6, device 1, workload 1, 80 C abort.'}
    (root / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(medians), flush=True)


if __name__ == '__main__':
    main()
