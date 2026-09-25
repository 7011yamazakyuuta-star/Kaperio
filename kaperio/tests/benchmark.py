"""Opt-in matched-candidate GPU comparison. Outputs contain synthetic data only."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from formats import get_hash, inspect_file
from recovery import CREATE_FLAGS, hashcat_arguments, parse_status, run_hashcat, validate_plan, write_inputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hashcat', required=True, type=Path)
    parser.add_argument('--zip2john', type=Path)
    parser.add_argument('--fixtures', type=Path, default=Path('.test-data/integration'))
    parser.add_argument('--output', type=Path, default=Path('.test-data/benchmark'))
    parser.add_argument('--seconds', type=int, default=12)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--devices', default='1')
    args = parser.parse_args()
    executable = args.hashcat.resolve()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    version = subprocess.check_output([str(executable), '--version'], cwd=executable.parent).decode().strip()
    results = []
    report = {'engine': version, 'engine_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
              'platform': platform.platform(), 'devices': args.devices, 'sample_seconds': args.seconds,
              'warmup_seconds_discarded': 3, 'workload': 1, 'temperature_abort': 80,
              'mask': '?l x 8', 'candidates': 26 ** 8, 'runs': results,
              'limitations': ['One machine; OpenCL/CUDA and thermal conditions are machine-dependent.',
                              'Same upstream kernels; this does not establish superiority over Hashcat.',
                              'CLI and wrapper throughput, not success rate on real-world passwords.']}
    fixtures = ['RC4-40.pdf', 'AES-256.pdf', 'encrypted.docx', 'encrypted.zip']
    for fixture in fixtures:
        source = (args.fixtures / fixture).resolve()
        info = inspect_file(source, source.suffix, args.zip2john)
        value, mode = get_hash(source, info, executable, args.zip2john)
        for repeat in range(args.repeats):
            profiles = ['cli-pure', 'cli-auto', 'kaperio-auto']
            profiles = profiles[repeat % 3:] + profiles[:repeat % 3]
            for profile in profiles:
                folder = root / (str(mode) + '-' + str(repeat) + '-' + profile)
                folder.mkdir(exist_ok=False)
                (folder / 'source.hash').write_text(value + '\n', encoding='ascii')
                plan = validate_plan({'min': 8, 'max': 8, 'charsets': ['lower'], 'devices': args.devices,
                                      'minutes': 2, 'workload': 1, 'kernel': 'pure' if profile == 'cli-pure' else 'auto'})
                stop = threading.Event()
                samples = []
                warnings = set()
                first = [None]
                started = time.monotonic()

                def update(**fields):
                    now = time.monotonic()
                    if fields.get('warning'):
                        warnings.add(fields['warning'])
                    metric = fields.get('metrics')
                    if metric and metric['speed'] > 0:
                        if first[0] is None:
                            first[0] = now
                        if now - first[0] >= 3:
                            samples.append(metric)

                def deadline():
                    while not stop.wait(.1):
                        now = time.monotonic()
                        if now - started > 120 or (first[0] and now - first[0] >= args.seconds):
                            stop.set()

                watcher = threading.Thread(target=deadline)
                watcher.start()
                try:
                    if profile.startswith('cli'):
                        attack = write_inputs(folder, plan)
                        command = [str(executable), '--session', 'kaperio_' + folder.name,
                                   '--restore-file-path', str(folder / 'session.restore'), '-m', str(mode),
                                   str(folder / 'source.hash')] + attack + [
                                   '--status', '--status-json', '--status-timer', '1', '--potfile-disable',
                                   '--logfile-disable', '--outfile', str(folder / 'found.hex'), '--outfile-format', '3',
                                   '-w', '1', '--hwmon-temp-abort', '80', '-d', args.devices]
                        if profile == 'cli-auto' and mode in (10400, 10500, 10600, 10700):
                            command += ['-O']
                        assert command == hashcat_arguments(executable, folder, mode, plan)
                        process = subprocess.Popen(command, cwd=executable.parent, stdout=subprocess.PIPE,
                                                   stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                                   creationflags=CREATE_FLAGS)

                        def read_output():
                            from recovery import warning_for
                            for raw in iter(process.stdout.readline, b''):
                                line = raw.decode('utf-8', errors='replace')
                                update(metrics=parse_status(line), warning=warning_for(line))

                        reader = threading.Thread(target=read_output)
                        reader.start()
                        try:
                            while process.poll() is None and not stop.wait(.1):
                                pass
                            if process.poll() is None:
                                process.terminate()
                            process.wait(timeout=15)
                        finally:
                            if process.poll() is None:
                                process.kill(); process.wait()
                            reader.join(timeout=5)
                            process.stdout.close()
                    else:
                        outcome = run_hashcat(executable, folder, mode, plan, stop, update)
                        assert outcome['state'] == 'paused', outcome['state']
                finally:
                    stop.set()
                    watcher.join()
                if not samples:
                    raise RuntimeError('No valid timed samples: ' + profile + ' / ' + str(mode))
                row = {'mode': mode, 'profile': profile, 'repeat': repeat + 1,
                       'median_hps': statistics.median(s['speed'] for s in samples),
                       'max_temperature': max(s['temperature'] for s in samples),
                       'samples': len(samples), 'wall_seconds': round(time.monotonic() - started, 3),
                       'warnings': sorted(warnings)}
                results.append(row)
                (root / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(row, ensure_ascii=True), flush=True)
                time.sleep(2)
    report['summary'] = []
    for mode in sorted({r['mode'] for r in results}):
        medians = {p: statistics.median(r['median_hps'] for r in results if r['mode'] == mode and r['profile'] == p)
                   for p in ('cli-pure', 'cli-auto', 'kaperio-auto')}
        report['summary'].append({'mode': mode, **medians,
                                  'optimized_vs_pure': medians['cli-auto'] / medians['cli-pure'],
                                  'wrapper_vs_cli': medians['kaperio-auto'] / medians['cli-auto']})
    (root / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary']), flush=True)


if __name__ == '__main__':
    main()
