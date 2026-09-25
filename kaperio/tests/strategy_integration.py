"""Opt-in recovery tests for rules and both hybrid directions."""
import argparse
import json
import sys
import time
from pathlib import Path

import msoffcrypto
import pyzipper
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Library
from test_core import make_pdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--hashcat', required=True, type=Path)
    parser.add_argument('--zip2john', required=True, type=Path)
    args = parser.parse_args()
    root = Path('.test-data/strategies').resolve()
    root.mkdir(parents=True, exist_ok=True)
    library = Library(root / ('library-' + str(time.time_ns())))
    library.hashcat, library.zip2john = args.hashcat.resolve(), args.zip2john.resolve()
    rows = []
    try:
        for kind in ('RC4-40', 'AES-256', 'docx', 'zip'):
            for strategy, password in [('dictionary_rules', 'Test9'), ('hybrid_suffix', 'test42'),
                                       ('hybrid_prefix', '42test')]:
                source = root / ('sample.' + (kind if kind in ('docx', 'zip') else 'pdf'))
                if kind == 'docx':
                    plain = root / 'plain.docx'
                    doc = Document(); doc.add_paragraph('Kaperio'); doc.save(plain)
                    with plain.open('rb') as stream, source.open('wb') as dest:
                        msoffcrypto.OfficeFile(stream).encrypt(password, dest)
                elif kind == 'zip':
                    with pyzipper.AESZipFile(str(source), 'w', encryption=pyzipper.WZ_AES) as archive:
                        archive.setpassword(password.encode()); archive.writestr('file.txt', b'Kaperio')
                else:
                    make_pdf(source, password, kind)
                jid = library.import_pdf(source.name, source.read_bytes())
                library.start_recovery(jid, {'strategy': strategy, 'words': 'wrong\ntest',
                                            'min': 2, 'max': 2, 'charsets': ['digits'],
                                            'devices': '1', 'minutes': 2})
                deadline = time.monotonic() + 120
                while library.jobs[jid]['state'] in ('queued', 'recovering'):
                    if time.monotonic() > deadline:
                        raise TimeoutError(strategy)
                    time.sleep(.2)
                assert library.jobs[jid]['state'] == 'ready', library.jobs[jid]['message']
                row = {'format': kind, 'strategy': strategy, 'passed': True}
                rows.append(row)
                print(json.dumps(row), flush=True)
        (root / 'results.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    finally:
        library.close()


if __name__ == '__main__':
    main()
