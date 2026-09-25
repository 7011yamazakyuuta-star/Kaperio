"""Opt-in GPU regression: byte boundaries must not discard dictionary candidates."""
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
    parser.add_argument('--hashcat', required=True, type=Path)
    args = parser.parse_args()
    root = Path('.test-data/kernel-coverage').resolve()
    root.mkdir(parents=True, exist_ok=True)
    library = Library(root / ('run-' + str(time.time_ns())))
    library.hashcat = args.hashcat.resolve()
    results = []
    try:
        for algorithm in ('RC4-40', 'AES-256'):
            for password in ('A' * 16, 'B' * 17, '日' * 6, '$HEX[4142]'):
                source = root / 'synthetic.pdf'
                make_pdf(source, password, algorithm)
                jid = library.import_pdf('synthetic.pdf', source.read_bytes())
                library.start_recovery(jid, {'strategy': 'dictionary', 'words': 'wrong\n' + password,
                                            'devices': '1', 'minutes': 2})
                deadline = time.monotonic() + 120
                while library.jobs[jid]['state'] in ('queued', 'recovering'):
                    if time.monotonic() > deadline:
                        raise TimeoutError('GPU coverage test timed out')
                    time.sleep(.2)
                assert library.jobs[jid]['state'] == 'ready', library.jobs[jid]['message']
                result = {'algorithm': algorithm, 'utf8_bytes': len(password.encode()),
                          'literal_hex': password.startswith('$HEX'), 'passed': True}
                results.append(result)
                print(json.dumps(result), flush=True)
        (root / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    finally:
        library.close()


if __name__ == '__main__':
    main()
