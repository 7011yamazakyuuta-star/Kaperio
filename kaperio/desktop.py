"""Frozen entry point; the UI stays in the user's default browser."""
import contextlib
import os
import runpy
import sys
import traceback
from pathlib import Path

from runtime import APP_DIR, data_directory


def main():
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
            ctypes.windll.user32.MessageBoxW(None, 'Startup failed. See: ' + str(log), 'Kaperio', 16)
        raise


if __name__ == '__main__':
    main()
