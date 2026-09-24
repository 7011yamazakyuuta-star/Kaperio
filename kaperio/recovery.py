"""Bounded Hashcat jobs; arguments never pass through a shell."""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path

CHARSETS = {'lower': ('?l', 26), 'upper': ('?u', 26), 'digits': ('?d', 10), 'symbols': ('?s', 33)}
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0


def validate_plan(data):
    strategy = data.get('strategy', 'mask')
    minutes = int(data.get('minutes', 10))
    workload = int(data.get('workload', 1))
    temperature = int(data.get('temperature', 80))
    devices = str(data.get('devices', '')).strip()
    kernel = data.get('kernel', 'auto')
    if kernel not in ('auto', 'pure'):
        raise ValueError('カーネル設定が不正です。')
    if not 1 <= minutes <= 1440 or workload not in (1, 2, 3) or not 60 <= temperature <= 90:
        raise ValueError('探索時間・負荷・温度の設定が範囲外です。')
    if devices and not re.fullmatch(r'[1-9][0-9]*(,[1-9][0-9]*)*', devices):
        raise ValueError('デバイスIDは 1 または 1,2 の形式です。')
    plan = {'strategy': strategy, 'minutes': minutes, 'workload': workload,
            'temperature': temperature, 'devices': devices, 'kernel': kernel}
    if strategy == 'dictionary':
        candidates = data.get('words', '').splitlines()
        candidates = list(dict.fromkeys(x for x in candidates if x))
        if not candidates or len(candidates) > 100000 or any(len(x.encode('utf-8')) > 127 for x in candidates):
            raise ValueError('候補は1〜100,000行、各行はUTF-8で127バイト以内にしてください。')
        plan.update(words=candidates, candidates=str(len(candidates)))
    elif strategy == 'mask':
        low, high = int(data.get('min', 4)), int(data.get('max', 6))
        prefix, suffix = str(data.get('prefix', '')), str(data.get('suffix', ''))
        chosen = list(dict.fromkeys(data.get('charsets', ['lower', 'upper', 'digits'])))
        if not chosen or any(x not in CHARSETS for x in chosen):
            raise ValueError('探索する文字種を選んでください。')
        if any(ord(x) < 32 or ord(x) > 126 or x == ',' for x in prefix + suffix):
            raise ValueError('前後の固定文字はカンマを除く半角英数字・記号にしてください。')
        fixed = len(prefix) + len(suffix)
        if not 1 <= low <= high <= 16 or low < fixed or len(prefix + suffix) > 16:
            raise ValueError('全体の文字数は1〜16、固定部分の長さ以上にしてください。')
        size = sum(CHARSETS[x][1] for x in chosen)
        plan.update(min=low, max=high, prefix=prefix, suffix=suffix, charsets=chosen,
                    candidates=str(sum(size**(n - fixed) for n in range(low, high + 1))))
    else:
        raise ValueError('探索方法が不正です。')
    return plan


def write_inputs(folder, plan):
    if plan['strategy'] == 'dictionary':
        # Hex wordlists preserve literal $HEX[...] and exact UTF-8 bytes.
        path = folder / 'candidates.hex'
        path.write_text('\n'.join(w.encode('utf-8').hex() for w in plan['words']) + '\n', encoding='ascii')
        return ['-a', '0', '--hex-wordlist', str(path)]
    charset = ''.join(CHARSETS[x][0] for x in plan['charsets'])
    prefix = plan['prefix'].replace('?', '??')
    suffix = plan['suffix'].replace('?', '??')
    fixed = len(plan['prefix']) + len(plan['suffix'])
    path = folder / 'search.hcmask'
    masks = [charset + ',' + prefix + '?1' * (length - fixed) + suffix for length in range(plan['min'], plan['max'] + 1)]
    path.write_text('\n'.join(masks) + '\n', encoding='ascii')
    return ['-a', '3', str(path)]


def parse_status(line):
    try:
        item = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(item, dict) or 'status' not in item:
        return None
    devices = item.get('devices', [])
    progress = item.get('progress', [0, 0])
    return {'speed': sum(d.get('speed', 0) for d in devices),
            'temperature': max((d.get('temp', 0) for d in devices), default=0),
            'tested': progress[0], 'total': progress[1],
            'eta': item.get('estimated_stop'), 'hashcat_status': item.get('status'),
            'guess': {k: v for k, v in item.get('guess', {}).items() if k in ('guess_base_offset', 'guess_base_count')}}


def warning_for(line):
    lower = line.lower()
    if 'rtc' in lower or 'cuda sdk' in lower:
        return 'CUDA補助ライブラリなし。OpenCLへの切り替えを確認中。'
    if 'falling back to opencl' in lower:
        return 'OpenCLで実行します。CUDAの警告は致命的エラーではありません。'
    if 'temperature threshold' in lower:
        return 'GPUの温度制御により速度が低下しています。'
    if 'too small' in lower:
        return '候補数が少ないためGPUを使い切れません。処理は続行します。'
    if 'fanspeed' in lower:
        return 'ファン回転数の取得に非対応です。'
    return None


def optimized_kernel(mode, plan):
    if plan.get('kernel', 'auto') == 'pure' or mode not in (10400, 10500, 10600, 10700):
        return False
    maximum = (plan['max'] if plan['strategy'] == 'mask' else
               max(len(word.encode('utf-8')) for word in plan['words']))
    # Conservative common bound: never drop longer dictionary candidates for speed.
    return maximum <= 16


def hashcat_arguments(executable, folder, mode, plan, resume=False):
    restore = folder / 'session.restore'
    base = [str(executable), '--session', 'kaperio_' + folder.name, '--restore-file-path', str(restore)]
    if resume and restore.exists():
        return base + ['--restore']
    args = base + ['-m', str(mode), str(folder / 'source.hash')] + write_inputs(folder, plan)
    args += ['--status', '--status-json', '--status-timer', '1', '--potfile-disable',
             '--logfile-disable', '--outfile', str(folder / 'found.hex'), '--outfile-format', '3',
             '-w', str(plan['workload']), '--hwmon-temp-abort', str(plan['temperature'])]
    if plan['devices']:
        args += ['-d', plan['devices']]
    if optimized_kernel(mode, plan):
        args += ['-O']
    return args


def run_hashcat(executable, folder, mode, plan, stop, update, resume=False):
    restore = folder / 'session.restore'
    found = folder / 'found.hex'
    found.unlink(missing_ok=True)
    args = hashcat_arguments(executable, folder, mode, plan, resume)
    started = time.monotonic()
    process = subprocess.Popen(args, cwd=executable.parent, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               creationflags=CREATE_FLAGS)
    errors = []
    def consume():
        for raw in iter(process.stdout.readline, b''):
            line = raw.decode('utf-8', errors='replace').strip()
            status = parse_status(line)
            if status:
                update(metrics=status)
            warning = warning_for(line)
            if warning:
                update(warning=warning)
            if any(s in line.lower() for s in ('error', 'no devices', 'no hashes loaded', 'no such file', 'aborting')):
                # Hash/candidate lines never enter the persisted event log.
                if '$pdf$' not in line and len(errors) < 8:
                    errors.append(line[:300])
    reader = threading.Thread(target=consume, daemon=True)
    reader.start()
    reason = None
    try:
        while process.poll() is None:
            if stop.is_set() or time.monotonic() - started >= plan['minutes'] * 60:
                reason = 'pause' if stop.is_set() else 'time_limit'
                process.terminate()
                break
            time.sleep(0.15)
        code = process.wait(timeout=15)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        reader.join(timeout=5)
        process.stdout.close()
    password = None
    if found.exists():
        lines = found.read_text(encoding='ascii').splitlines()
        if lines:
            password = bytes.fromhex(lines[0])
        found.unlink(missing_ok=True)
    if password is not None:
        return {'state': 'found', 'password': password}
    if reason:
        return {'state': 'paused', 'checkpoint': restore.exists(), 'reason': reason}
    if code == 1:
        return {'state': 'exhausted'}
    if code in (2, 3, 4):
        return {'state': 'paused', 'checkpoint': restore.exists(), 'reason': 'hashcat_abort'}
    raise RuntimeError('Hashcatが終了しました (code ' + str(code) + ')。' + ' / '.join(errors))
