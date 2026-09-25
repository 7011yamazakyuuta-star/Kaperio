"""Explicit opt-in Hashcat download test in an isolated library; no CUDA install."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import Library
from environment_setup import CATALOG_REVISION, run_readonly


def main():
    if sys.argv[1:] != ['--download-hashcat']:
        raise SystemExit('Pass --download-hashcat to explicitly run this network integration test.')
    library = Library(ROOT / '.test-data' / ('setup-native-' + str(os.getpid())))
    library.hashcat = library.zip2john = None
    try:
        library.setup.start({'component': 'hashcat', 'consent': True, 'catalog_revision': CATALOG_REVISION})
        library.setup.thread.join(660)
        if library.setup.thread.is_alive():
            library.setup.cancel()
            raise RuntimeError('Setup timed out')
        assert library.setup.status['phase'] == 'complete', library.setup.status
        code, text = run_readonly([str(library.hashcat), '--version'], cwd=library.hashcat.parent)
        assert code == 0 and text.strip() == 'v7.1.2', (code, text)
        report = library.setup.diagnose()['report']
        assert report['backend']['status'] == 'recognized', report['backend']['status']
        assert not report['backend']['compute_tested']
        assert not library.setup.installed('nvrtc')
        assert not list(library.setup.root.glob('.install-*'))
        assert library.snapshot() == []
        print(json.dumps({'passed': True, 'hashcat_version': text.strip(),
                          'download_checksum_extract_configure': True,
                          'hardware_status': report['hardware']['status'],
                          'backend_status': report['backend']['status'],
                          'devices': [d['name'] for d in report['backend']['devices']],
                          'nvrtc_missing': report['backend']['nvrtc_missing'],
                          'nvrtc_installed': False, 'drivers_changed': False,
                          'data': str(library.root)}))
    finally:
        library.close()


if __name__ == '__main__':
    main()
