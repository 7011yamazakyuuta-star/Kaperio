"""Paths shared by the source launcher and the frozen desktop application."""
import os
import sys
from pathlib import Path

VERSION = '0.4.0-alpha.4'
APP_NAME = 'Loxmit'
APP_DIR = Path(__file__).resolve().parent


def data_directory():
    if not getattr(sys, 'frozen', False):
        # Keep source checkouts and existing recovery checkpoints in place.
        return APP_DIR.parent / 'outputs' / 'kaperio'
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
        legacy, current = base / 'Kaperio', base / APP_NAME
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
        legacy, current = base / 'Kaperio', base / APP_NAME
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
        legacy, current = base / 'kaperio', base / 'loxmit'
    return legacy if legacy.is_dir() and not current.exists() else current
