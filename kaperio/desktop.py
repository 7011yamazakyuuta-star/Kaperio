"""Frozen entry point; the UI stays in the user's default browser."""
import contextlib
import json
import os
import runpy
import sys
import traceback
from pathlib import Path

from runtime import APP_DIR, data_directory


def main():
    if len(sys.argv) == 2 and sys.argv[1] == '--document-worker':
        from document_worker import worker_main
        worker_main()
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == '--self-check':
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.backends.openssl.backend import backend
            from pypdf._crypt_providers._cryptography import CryptAES
            cipher = Cipher(algorithms.AES(bytes(16)), modes.CBC(bytes(16)))
            assert len(cipher.encryptor().update(bytes(16))) == 16
            assert CryptAES
            result = {'ok': True, 'openssl': backend.openssl_version_text()}
        except Exception:
            result = {'ok': False, 'error': traceback.format_exc()}
        Path(sys.argv[2]).write_text(json.dumps(result), encoding='utf-8')
        return 0 if result['ok'] else 1
    # A separate bounded helper keeps the original upstream extractor unchanged.
    if len(sys.argv) == 4 and sys.argv[1] == '--office-hash':
        source, destination = sys.argv[2:]
        sys.argv = [str(APP_DIR / 'vendor/office2john.py'), source]
        with open(destination, 'w', encoding='utf-8') as output, open(os.devnull, 'w') as errors:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                runpy.run_path(str(APP_DIR / 'vendor/office2john.py'), run_name='__main__')
        return
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    try:
        from app import main as serve
        serve()
    except Exception:
        root = data_directory()
        root.mkdir(parents=True, exist_ok=True)
        log = root / 'startup-error.log'
        log.write_text(traceback.format_exc(), encoding='utf-8')
        if sys.platform == 'win32' and '--no-browser' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, 'Startup failed. See: ' + str(log), 'Loxmit', 16)
        raise


if __name__ == '__main__':
    raise SystemExit(main())
