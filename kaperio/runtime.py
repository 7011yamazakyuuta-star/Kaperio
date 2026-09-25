"""Paths shared by the source launcher and the frozen desktop application."""
import os
import sys
from pathlib import Path

VERSION = '0.3.0-alpha.1'
APP_DIR = Path(__file__).resolve().parent


def data_directory():
    if not getattr(sys, 'frozen', False):
        return APP_DIR.parent / 'outputs' / 'kaperio'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'Kaperio'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/Kaperio'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'kaperio'
