"""Audit the installed runtime inventory without installing tools into that runtime."""
from __future__ import annotations

import argparse
import datetime
import importlib.metadata as metadata
import json
import os
import subprocess
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_desktop import RUNTIME

AUDIT_VERSION = '2.10.1'


def runtime_inventory():
    inventory = {canonicalize_name(name): str(Version(metadata.version(name))) for name in RUNTIME}
    for name in inventory:
        for text in metadata.requires(name) or []:
            requirement = Requirement(text)
            if requirement.marker and not requirement.marker.evaluate({'extra': ''}):
                continue
            dependency = canonicalize_name(requirement.name)
            if dependency not in inventory:
                raise ValueError('Runtime inventory is missing dependency: ' + dependency)
            if inventory[dependency] not in requirement.specifier:
                raise ValueError('Runtime dependency version does not satisfy: ' + dependency)
    return dict(sorted(inventory.items()))


def validate_report(report, inventory):
    rows = report.get('dependencies')
    if not isinstance(rows, list) or len(rows) != len(inventory):
        raise ValueError('Audit coverage is incomplete.')
    seen = set()
    for row in rows:
        name = canonicalize_name(row.get('name', ''))
        if (name not in inventory or name in seen or row.get('version') != inventory[name]
                or 'skip_reason' in row or row.get('vulns') != []):
            raise ValueError('Audit is incomplete or reports vulnerabilities: ' + name)
        seen.add(name)
    if seen != set(inventory):
        raise ValueError('Audit coverage is incomplete.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--audit-python', type=Path)
    parser.add_argument('--install-tool', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/dependency-audit')
    args = parser.parse_args()
    inventory = runtime_inventory()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary = output / 'summary.json'
    summary.unlink(missing_ok=True)
    requirements = output / 'runtime.txt'
    requirements.write_text(''.join(name + '==' + version + '\n' for name, version in inventory.items()), encoding='ascii')
    if args.install_tool:
        environment = ROOT / '.audit-venv'
        subprocess.run([sys.executable, '-m', 'venv', str(environment)], check=True, timeout=120)
        executable = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        subprocess.run([str(executable), '-m', 'pip', 'install', 'pip-audit==' + AUDIT_VERSION],
                       check=True, timeout=180)
    elif args.audit_python:
        executable = args.audit_python.resolve(strict=True)
    else:
        parser.error('Use --install-tool or --audit-python with a separate audit environment.')
    version = subprocess.run([str(executable), '-m', 'pip_audit', '--version'],
                             check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    if version != 'pip-audit ' + AUDIT_VERSION:
        raise ValueError('Unexpected dependency audit tool version.')
    report = output / 'audit.json'
    report.unlink(missing_ok=True)
    subprocess.run([str(executable), '-m', 'pip_audit', '-r', str(requirements), '--disable-pip',
                    '--no-deps', '--strict', '--progress-spinner', 'off', '--timeout', '20',
                    '--format', 'json', '--output', str(report)], check=True, timeout=180)
    validate_report(json.loads(report.read_text(encoding='utf-8')), inventory)
    result = {'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'service': 'PyPI', 'tool': version, 'packages': inventory, 'known_vulnerabilities': 0,
              'scope': 'Declared installed Python runtime packages, not native binaries or OS components.'}
    summary.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('Known-vulnerability audit passed for ' + str(len(inventory)) + ' runtime packages.')


if __name__ == '__main__':
    main()
