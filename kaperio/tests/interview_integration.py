"""Opt-in GPU acceptance: generated PDFs only, never user documents."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Library
from test_core import make_pdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hashcat', type=Path, required=True)
    args = parser.parse_args()
    root = Path('.test-data/interview-' + str(time.time_ns())).resolve()
    root.mkdir(parents=True)
    library = Library(root / 'library')
    library.hashcat = args.hashcat.resolve()
    cases = [
        ('RC4-40', 'LongMemoryPhrase2024!', {'words': 'LongMemoryPhrase', 'numbers': '2024'}),
        ('AES-256', 'LongMemory?Prefix!7', {'prefix': 'LongMemory?Prefix!', 'characters': 'digits',
                                           'length': 'range', 'min': 19, 'max': 19}),
        ('AES-256', 'L' + 'o' * 124 + 'x7', {'words': 'L' + 'o' * 124 + 'x7'}),
    ]
    results = []
    try:
        for index, (algorithm, password, answers) in enumerate(cases):
            if answers.get('length') == 'range':
                assert answers['min'] <= len(password) <= answers['max']
            source = root / f'synthetic-{index}.pdf'
            make_pdf(source, password, algorithm)
            jid = library.import_pdf(source.name, source.read_bytes())
            library.start_recovery(jid, dict(answers, strategy='automatic', devices='1', minutes=2))
            deadline = time.monotonic() + 150
            while library.jobs[jid]['state'] in ('queued', 'recovering', 'unlocking'):
                if time.monotonic() > deadline:
                    library.stop(jid)
                    raise TimeoutError('Synthetic interview acceptance exceeded its deadline')
                time.sleep(.2)
            job = library.jobs[jid]
            assert job['state'] == 'ready', job['message']
            assert (library.folder(jid) / job['unlocked']).is_file()
            assert not (library.folder(jid) / 'candidates.hex').exists()
            assert not list(library.folder(jid).glob('stage-*/candidates.hex'))
            results.append({'algorithm': algorithm, 'password_bytes': len(password),
                            'verified_decryption': True, 'private_candidates_removed': True})
            print(json.dumps(results[-1]), flush=True)
        (root / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    finally:
        library.close()
    print('Report: ' + str(root / 'results.json'), flush=True)


if __name__ == '__main__':
    main()
