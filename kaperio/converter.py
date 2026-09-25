"""Supervise Office/LibreOffice conversions without blocking the job controls."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path

from recovery import CREATE_FLAGS


def cleanup_office(state_path):
    if os.name != 'nt' or not state_path.exists():
        return
    try:
        state = json.loads(state_path.read_text(encoding='utf-8-sig'))
        if not state.get('owned'):
            return
        pid, ticks = int(state['pid']), int(state['created_ticks'])
    except (OSError, KeyError, ValueError):
        return
    # Match the creation timestamp as well as the PID to avoid PID reuse.
    command = (f'$p=Get-Process -Id {pid} -ErrorAction SilentlyContinue; '
               f'if ($p -and $p.StartTime.ToUniversalTime().Ticks -eq {ticks}) '
               '{ Stop-Process -InputObject $p -Force }')
    subprocess.run(['powershell.exe', '-NoProfile', '-Command', command],
                   capture_output=True, timeout=15, creationflags=CREATE_FLAGS)


def run_converter(args, folder, cancelled=lambda: False, timeout=120):
    folder = Path(folder)
    log_path = folder / 'conversion.log'
    state_path = folder / 'office-worker.json'
    state_path.unlink(missing_ok=True)
    started = time.monotonic()
    failure = None
    with log_path.open('wb') as log:
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, creationflags=CREATE_FLAGS,
                                   start_new_session=os.name != 'nt')
        try:
            while process.poll() is None:
                if cancelled():
                    failure = 'cancelled'
                    break
                if time.monotonic() - started > timeout:
                    failure = 'timeout'
                    break
                if log_path.stat().st_size > 8 * 1024 * 1024:
                    failure = 'log_limit'
                    break
                time.sleep(.15)
        finally:
            if process.poll() is None:
                if os.name == 'nt':
                    # The Windows venv/Office launcher can leave a child holding the log.
                    try:
                        subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       timeout=5, creationflags=CREATE_FLAGS)
                    except subprocess.TimeoutExpired:
                        pass
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if failure:
                cleanup_office(state_path)
    with log_path.open('rb') as log:
        log.seek(max(0, log_path.stat().st_size - 8000))
        output = log.read(8000).decode('utf-8', errors='replace')
    if failure == 'log_limit':
        raise ValueError('Office変換のログが上限を超えたため停止しました。')
    if failure == 'cancelled':
        raise InterruptedError('書き出しを中止しました。')
    if failure == 'timeout':
        stages = [line.split('=', 1)[1] for line in output.splitlines() if line.startswith('KAPERIO_STAGE=')]
        stage = stages[-1] if stages else '起動'
        raise ValueError(f'Officeの変換が{timeout}秒以内に完了しませんでした（段階: {stage}）。')
    if process.returncode:
        raise ValueError('OfficeのPDF変換に失敗しました。conversion.logに詳細を保存しました。')
    state_path.unlink(missing_ok=True)
