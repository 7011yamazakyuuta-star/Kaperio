#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12+ required"'
.venv/bin/python -m pip install -r requirements.txt
printf '%s\n' 'Set HIRAKU_HASHCAT to the hashcat executable, then run: sh launch.sh'
