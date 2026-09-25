"""Opt-in synthetic GPU checks and same-candidate mixed-length timing."""
import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path

import msoffcrypto
import pyzipper
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Library
from formats import get_hash, inspect_file
from recovery import execution_stages, run_hashcat, run_stage, validate_plan
from test_core import make_pdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hashcat', type=Path, required=True)
    parser.add_argument('--zip2john', type=Path, required=True)
    parser.add_argument('--benchmark', action='store_true')
    parser.add_argument('--tune', action='store_true')
    args = parser.parse_args()
    root = Path('.test-data/planning-' + str(time.time_ns())).resolve()
    root.mkdir(parents=True)
    executable = args.hashcat.resolve()
    library = Library(root / 'library')
    library.hashcat, library.zip2john = executable, args.zip2john.resolve()
    report = {'checks': [], 'runs': []}
    def record(row):
        print(json.dumps(row, ensure_ascii=True), flush=True)
        (root / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    try:
        for kind in ('RC4-40', 'AES-256', 'docx', 'zip'):
            password = 'Test2024!'
            source = root / ('sample.' + (kind if kind in ('docx', 'zip') else 'pdf'))
            if kind == 'docx':
                plain = root / 'plain.docx'
                document = Document(); document.add_paragraph('Synthetic Kaperio fixture'); document.save(plain)
                with plain.open('rb') as stream, source.open('wb') as dest:
                    msoffcrypto.OfficeFile(stream).encrypt(password, dest)
            elif kind == 'zip':
                with pyzipper.AESZipFile(str(source), 'w', encryption=pyzipper.WZ_AES) as archive:
                    archive.setpassword(password.encode()); archive.writestr('file.txt', b'Kaperio')
            else:
                make_pdf(source, password, kind)
            jid = library.import_pdf(source.name, source.read_bytes())
            library.start_recovery(jid, {'strategy': 'guided', 'words': 'test', 'numbers': '2024',
                                        'separators': '!', 'devices': '1', 'minutes': 2})
            deadline = time.monotonic() + 120
            while library.jobs[jid]['state'] in ('queued', 'recovering'):
                if time.monotonic() >= deadline:
                    raise TimeoutError(kind)
                time.sleep(.2)
            assert library.jobs[jid]['state'] == 'ready', library.jobs[jid]['message']
            assert not list(library.folder(jid).glob('stage-*/candidates.hex'))
            report['checks'].append({'kind': kind, 'guided': True, 'verified_decryption': True})
            record(report['checks'][-1])
        source = root / 'boundary.pdf'
        make_pdf(source, 'Test2024!', 'AES-256')
        value, mode = get_hash(source, inspect_file(source, '.pdf'), executable)
        folder = root / 'resume'; folder.mkdir()
        (folder / 'source.hash').write_text(value + '\n', encoding='ascii')
        plan = validate_plan({'strategy': 'guided', 'words': 'test', 'numbers': '2024', 'devices': '1'})
        stop = threading.Event()
        def stop_between(**fields):
            if fields.get('metrics', {}).get('tested') == 1:
                stop.set()
        result = run_hashcat(executable, folder, mode, plan, stop, stop_between)
        assert result['state'] == 'paused' and result['checkpoint'], result
        stop.clear()
        result = run_hashcat(executable, folder, mode, plan, stop, lambda **kw: None, True)
        assert result['password'] == b'Test2024!'
        report['checks'].append({'guided_stage_resume': True})
        record(report['checks'][-1])
        words = '\n'.join('word' + str(i).zfill(6) for i in range(99999)) + '\nMixedLongPassword!'
        plan = validate_plan({'strategy': 'dictionary', 'words': words, 'devices': '1', 'minutes': 3})
        assert len(execution_stages(10700, plan)) == 2
        make_pdf(source, 'MixedLongPassword!', 'AES-256')
        value, mode = get_hash(source, inspect_file(source, '.pdf'), executable)
        folder = root / 'long-found'; folder.mkdir()
        (folder / 'source.hash').write_text(value + '\n', encoding='ascii')
        result = run_hashcat(executable, folder, mode, plan, threading.Event(), lambda **kw: None)
        assert result['password'] == b'MixedLongPassword!'
        report['checks'].append({'split_long_password_found': True})
        record(report['checks'][-1])
        if args.benchmark:
            make_pdf(source, 'OutsideCandidateSet', 'AES-256')
            value, mode = get_hash(source, inspect_file(source, '.pdf'), executable)
            for repeat in range(3):
                for policy in (('previous', 'split') if repeat % 2 == 0 else ('split', 'previous')):
                    folder = root / f'{policy}-{repeat}'; folder.mkdir()
                    (folder / 'source.hash').write_text(value + '\n', encoding='ascii')
                    warnings = set()
                    def update(**fields):
                        if fields.get('warning'):
                            warnings.add(fields['warning'])
                    started = time.monotonic()
                    runner = run_stage if policy == 'previous' else run_hashcat
                    result = runner(executable, folder, mode, plan, threading.Event(), update)
                    row = {'policy': policy, 'repeat': repeat + 1, 'seconds': time.monotonic() - started,
                           'candidates': 100000, 'warnings': sorted(warnings)}
                    assert result['state'] == 'exhausted', result
                    report['runs'].append(row); record(row)
                    time.sleep(2)
            medians = {p: statistics.median(r['seconds'] for r in report['runs'] if r['policy'] == p)
                       for p in ('previous', 'split')}
            report['medians'] = medians
            report['speedup'] = medians['previous'] / medians['split']
            record({'medians': medians, 'speedup': report['speedup']})
        if args.tune:
            make_pdf(source, 'OutsideCandidateSet', 'AES-256')
            value, mode = get_hash(source, inspect_file(source, '.pdf'), executable)
            folder = root / 'tune'; folder.mkdir()
            (folder / 'source.hash').write_text(value + '\n', encoding='ascii')
            plan = validate_plan({'strategy': 'mask', 'min': 8, 'max': 8, 'charsets': ['lower'],
                                  'workload': 'auto', 'minutes': 3, 'devices': '1'})
            stop = threading.Event()
            def stop_after_calibration(**fields):
                if fields.get('message', '').startswith('段階'):
                    stop.set()
            result = run_hashcat(executable, folder, mode, plan, stop, stop_after_calibration)
            assert result['state'] == 'paused', result
            record_data = json.loads((folder / 'execution.json').read_text())['tuning']['0']
            assert record_data['complete'] and len(record_data['rows']) == 6
            report['tuning'] = record_data
            record({'tuning': record_data})
    finally:
        library.close()
    print('Report: ' + str(root / 'results.json'), flush=True)


if __name__ == '__main__':
    main()
