"""Bounded Hashcat jobs; arguments never pass through a shell."""
from __future__ import annotations

import hashlib
import json
import re
import statistics
import subprocess
import threading
import time
from pathlib import Path

from candidates import guided_candidates, interview_candidates

CHARSETS = {'lower': ('?l', 26), 'upper': ('?u', 26), 'digits': ('?d', 10), 'symbols': ('?s', 33)}
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
HYBRIDS = {'hybrid_suffix', 'hybrid_prefix'}
WORD_STRATEGIES = {'dictionary', 'dictionary_rules', 'guided'} | HYBRIDS
MAX_LENGTH = 127
AUTO_ATTEMPTS = 10000000
MAX_KEYSPACE = 2**63 - 1
SPLIT_MIN_WORDS = 65536
RULES = [case + ending for case in (':', 'l', 'u', 'c', 't')
         for ending in ('', *(f'${n}' for n in range(10)))]


def validate_plan(data, mode=None):
    strategy = data.get('strategy', 'mask')
    minutes = int(data.get('minutes', 10))
    tune = data.get('workload') == 'auto'
    workload = 1 if tune else int(data.get('workload', 1))
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
            'temperature': temperature, 'devices': devices, 'kernel': kernel, 'tune': tune}
    if strategy not in WORD_STRATEGIES | {'mask', 'automatic'}:
        raise ValueError('探索方法が不正です。')
    if strategy == 'automatic':
        return automatic_plan(data, plan, mode)
    if strategy == 'guided':
        words, groups = guided_candidates(data)
        plan.update(words=words, groups=groups, candidates=str(len(words)))
    elif strategy in WORD_STRATEGIES:
        candidates = data.get('words', '').splitlines()
        candidates = list(dict.fromkeys(x for x in candidates if x))
        if not candidates or len(candidates) > 100000 or any(len(x.encode('utf-8')) > 127 for x in candidates):
            raise ValueError('候補は1〜100,000行、各行はUTF-8で127バイト以内にしてください。')
        multiplier = len(RULES) if strategy == 'dictionary_rules' else 1
        plan.update(words=candidates, candidates=str(len(candidates) * multiplier))
    if strategy == 'mask' or strategy in HYBRIDS:
        low, high = int(data.get('min', 4)), int(data.get('max', 6))
        prefix, suffix = str(data.get('prefix', '')), str(data.get('suffix', ''))
        if strategy in HYBRIDS:
            prefix, suffix = '', ''
        chosen = list(dict.fromkeys(data.get('charsets', ['lower', 'upper', 'digits'])))
        if not chosen or any(x not in CHARSETS for x in chosen):
            raise ValueError('探索する文字種を選んでください。')
        if any(ord(x) < 32 or ord(x) > 126 or x == ',' for x in prefix + suffix):
            raise ValueError('前後の固定文字はカンマを除く半角英数字・記号にしてください。')
        fixed = len(prefix) + len(suffix)
        if not 1 <= low <= high <= MAX_LENGTH or low < fixed or fixed > MAX_LENGTH:
            raise ValueError('全体の文字数は1〜127、固定部分の長さ以上にしてください。')
        size = sum(CHARSETS[x][1] for x in chosen)
        multiplier = len(plan['words']) if strategy in HYBRIDS else 1
        plan.update(min=low, max=high, prefix=prefix, suffix=suffix, charsets=chosen,
                    candidates=str(multiplier * sum(size**(n - fixed) for n in range(low, high + 1))))
    if strategy in WORD_STRATEGIES and candidate_max_bytes(plan) > 127:
        raise ValueError('変形・追加後の候補はUTF-8で127バイト以内にしてください。')
    if int(plan['candidates']) > MAX_KEYSPACE:
        raise ValueError('候補範囲が大きすぎます。先頭・末尾の手掛かりや文字数で絞ってください。')
    if mode in (10400, 10500) and candidate_max_bytes(plan) > 32:
        raise ValueError('このPDFの探索上限は32バイトです。候補の長さを絞ってください。')
    return plan


def automatic_plan(data, plan, mode=None):
    length = data.get('length', 'unknown')
    charset = data.get('characters', 'unknown')
    choices = {'digits': ['digits'], 'lower': ['lower'],
               'alnum': ['lower', 'upper', 'digits'], 'all': list(CHARSETS)}
    if length not in ('unknown', 'range') or charset not in ('unknown', *choices):
        raise ValueError('長さ・文字種の回答が不正です。')
    low, high = (1, MAX_LENGTH) if length == 'unknown' else (int(data.get('min', 1)), int(data.get('max', MAX_LENGTH)))
    if not 1 <= low <= high <= MAX_LENGTH:
        raise ValueError('文字数は1〜127の範囲で指定してください。')
    max_bytes = 32 if mode in (10400, 10500) else MAX_LENGTH
    if low > max_bytes:
        raise ValueError(f'この形式の探索上限は{max_bytes}バイトです。文字数を見直してください。')
    prefix, suffix = data.get('prefix', ''), data.get('suffix', '')
    if not isinstance(prefix, str) or not isinstance(suffix, str) or any(ord(c) < 32 or ord(c) > 126 or c == ',' for c in prefix + suffix):
        raise ValueError('先頭・末尾はカンマを除く半角文字で指定してください。日本語の手掛かりは語句の欄へ入力してください。')
    fixed = len(prefix) + len(suffix)
    if fixed > min(high, max_bytes):
        raise ValueError('先頭・末尾の文字数が、全体の文字数を超えています。')
    alphabets = {'lower': 'abcdefghijklmnopqrstuvwxyz', 'upper': 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
                 'digits': '0123456789', 'symbols': ''.join(chr(n) for n in range(32, 127) if not chr(n).isalnum())}
    selected = choices.get(charset)
    allowed = None if selected is None else set(''.join(alphabets[key] for key in selected))
    words, groups, omitted = interview_candidates(data, low, high, allowed, prefix, suffix, max_bytes)
    stages, total = [], len(words)
    # Unknown means prioritized subsets, never a claim to cover all passwords.
    sets = [selected] if selected else [choices['digits'], choices['lower'], choices['alnum'], choices['all']]
    notes = ['おまかせは1回1,000万試行以内の優先探索です。すべてのパスワードを網羅するものではありません。']
    for chosen in sets:
        size = sum(CHARSETS[key][1] for key in chosen)
        start, end, count = max(low, fixed, 1), None, 0
        for n in range(start, min(high, max_bytes) + 1):
            attempts = size ** (n - fixed)
            if total + count + attempts > AUTO_ATTEMPTS:
                break
            count += attempts
            end = n
        if end is not None:
            names = {'digits': '数字', 'lower': '英小文字', 'alnum': '英字・数字', 'all': '英字・数字・記号'}
            name = next(names[key] for key, value in choices.items() if value == chosen)
            span = str(start) if start == end else f'{start}〜{end}'
            stages.append({'strategy': 'mask', 'min': start, 'max': end, 'prefix': prefix, 'suffix': suffix,
                           'charsets': chosen, 'candidates': str(count), 'stage_name': f'{name} / 全体{span}文字'})
            total += count
    if omitted['bytes']:
        notes.append(f'この形式ではUTF-8で{max_bytes}バイトを超える候補は対象外です。')
    if omitted['capacity']:
        notes.append('語句から作る候補は先頭10万件までです。語句を絞ると後の組み合わせも対象になります。')
    if not total:
        raise ValueError('この条件では1,000万試行以内に絞れません。覚えている語句、または確かな先頭・末尾を追加してください。')
    notes.append('語句は指定した長さで絞り込みます。半角の組み合わせ探索は表示範囲のみ。暗号方式により長さの上限は異なります。')
    if length == 'unknown':
        notes.append(f'長さ不明でも、入力した長い語句は候補に含まれます（この形式は最大{max_bytes} UTF-8バイト）。')
    plan.update(words=words, groups=groups, stages=stages, candidates=str(total), notes=notes,
                length=length, characters=charset, min=low, max=high)
    return plan


def candidate_max_bytes(plan):
    if plan['strategy'] == 'automatic':
        return max([len(word.encode('utf-8')) for word in plan['words']] + [s['max'] for s in plan['stages']])
    if plan['strategy'] == 'mask':
        return plan['max']
    maximum = max(len(word.encode('utf-8')) for word in plan['words'])
    if plan['strategy'] in HYBRIDS:
        maximum += plan['max']
    elif plan['strategy'] == 'dictionary_rules':
        maximum += 1
    return maximum


def write_inputs(folder, plan):
    strategy = plan['strategy']
    if strategy in WORD_STRATEGIES | {'automatic'}:
        # Hex wordlists preserve literal $HEX[...] and exact UTF-8 bytes.
        path = folder / 'candidates.hex'
        path.write_text(''.join(w.encode('utf-8').hex() + '\n' for w in plan['words']), encoding='ascii')
        if strategy == 'automatic':
            return []
        if strategy in ('dictionary', 'guided'):
            return ['-a', '0', '--hex-wordlist', str(path)]
        if strategy == 'dictionary_rules':
            rules = folder / 'variants.rule'
            rules.write_text('\n'.join(RULES) + '\n', encoding='ascii')
            return ['-a', '0', '--hex-wordlist', str(path), '-r', str(rules)]
    charset = ''.join(CHARSETS[x][0] for x in plan['charsets'])
    prefix = plan['prefix'].replace('?', '??')
    suffix = plan['suffix'].replace('?', '??')
    fixed = len(plan['prefix']) + len(plan['suffix'])
    path = folder / 'search.hcmask'
    masks = [charset + ',' + prefix + '?1' * (length - fixed) + suffix for length in range(plan['min'], plan['max'] + 1)]
    path.write_text('\n'.join(masks) + '\n', encoding='ascii')
    if strategy == 'hybrid_suffix':
        return ['-a', '6', '--hex-wordlist', str(folder / 'candidates.hex'), str(path)]
    if strategy == 'hybrid_prefix':
        return ['-a', '7', '--hex-wordlist', str(path), str(folder / 'candidates.hex')]
    return ['-a', '3', str(path)]


def parse_status(line):
    try:
        item = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(item, dict) or 'status' not in item:
        return None
    devices = item.get('devices', [])
    active = [device for device in devices if device.get('speed', 0) > 0]
    progress = item.get('progress', [0, 0])
    return {'speed': sum(d.get('speed', 0) for d in devices),
            'thermal_complete': bool(active) and all(d.get('temp', 0) > 0 for d in active),
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
    maximum = candidate_max_bytes(plan)
    # Conservative common bound: never drop longer dictionary candidates for speed.
    return maximum <= 16


def hashcat_arguments(executable, folder, mode, plan, resume=False):
    restore = folder / 'session.restore'
    session = 'kaperio_' + hashlib.sha256(str(folder.resolve()).encode('utf-8')).hexdigest()[:24]
    base = [str(executable), '--session', session, '--restore-file-path', str(restore)]
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


def run_stage(executable, folder, mode, plan, stop, update, resume=False, seconds=None):
    restore = folder / 'session.restore'
    if stop.is_set() or (seconds is not None and seconds <= 0):
        return {'state': 'paused', 'reason': 'pause' if stop.is_set() else 'time_limit',
                'checkpoint': restore.exists()}
    found = folder / 'found.hex'
    found.unlink(missing_ok=True)
    args = hashcat_arguments(executable, folder, mode, plan, resume)
    started = time.monotonic()
    process = subprocess.Popen(args, cwd=executable.parent, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                               creationflags=CREATE_FLAGS)
    errors, length_limits = [], []
    maximum = candidate_max_bytes(plan)
    def consume():
        for raw in iter(process.stdout.readline, b''):
            line = raw.decode('utf-8', errors='replace').strip()
            limit = re.fullmatch(r'Maximum password length supported by kernel: (\d+)', line)
            if limit and maximum > int(limit[1]):
                length_limits.append(int(limit[1]))
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
            if length_limits:
                process.terminate()
                break
            if stop.is_set() or time.monotonic() - started >= (plan['minutes'] * 60 if seconds is None else seconds):
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
    if length_limits:
        raise ValueError(f'この暗号方式の探索上限は{min(length_limits)}バイトです。候補に上限を超える長さがあるため停止しました。長さ・語句を絞ってください。')
    if reason:
        return {'state': 'paused', 'checkpoint': restore.exists(), 'reason': reason}
    if code == 1:
        return {'state': 'exhausted'}
    if code in (2, 3, 4):
        return {'state': 'paused', 'checkpoint': restore.exists(), 'reason': 'hashcat_abort'}
    raise RuntimeError('Hashcatが終了しました (code ' + str(code) + ')。' + ' / '.join(errors))


def execution_stages(mode, plan):
    groups = plan.get('groups', []) if plan['strategy'] in ('guided', 'automatic') else []
    if groups and sum(g['count'] for g in groups) != len(plan['words']):
        raise ValueError('保存された候補数が一致しません。新しく探索を開始してください。')
    chunks, offset = [], 0
    for group in groups:
        chunk = dict(plan, strategy='dictionary', words=plan['words'][offset:offset + group['count']],
                     candidates=str(group['count']), stage_name=group['name'])
        chunks.append(chunk)
        offset += group['count']
    if plan['strategy'] == 'automatic':
        chunks.extend(dict(plan, **stage) for stage in plan['stages'])
    if not chunks:
        chunks = [dict(plan, stage_name='候補探索')]
    stages = []
    for chunk in chunks:
        # Splitting tiny/fast jobs costs more launches than it saves. R6 is measured.
        if mode == 10700 and chunk['strategy'] in WORD_STRATEGIES and chunk['kernel'] == 'auto':
            extra = chunk['max'] if chunk['strategy'] in HYBRIDS else int(chunk['strategy'] == 'dictionary_rules')
            short = [w for w in chunk['words'] if len(w.encode('utf-8')) + extra <= 16]
            long = [w for w in chunk['words'] if len(w.encode('utf-8')) + extra > 16]
            if len(short) >= SPLIT_MIN_WORDS and long:
                multiplier = int(chunk['candidates']) // len(chunk['words'])
                for words, name in ((short, '短い候補'), (long, '長い候補')):
                    stages.append(dict(chunk, words=words, candidates=str(len(words) * multiplier),
                                       stage_name=chunk['stage_name'] + ' / ' + name))
                continue
        stages.append(chunk)
    return stages


def save_execution(folder, value):
    temporary = folder / 'execution.tmp'
    temporary.write_text(json.dumps(value), encoding='utf-8')
    temporary.replace(folder / 'execution.json')


def has_checkpoint(folder):
    if (folder / 'session.restore').exists():
        return True
    try:
        value = json.loads((folder / 'execution.json').read_text(encoding='utf-8'))
        return value['index'] > 0 or (folder / f"stage-{value['index']:03d}" / 'session.restore').exists()
    except (OSError, ValueError, KeyError, TypeError):
        return False


def clear_execution(folder):
    # Keep candidate data local, but invalidate every old restore before a new plan.
    for path in [folder / 'session.restore', folder / 'execution.json', *folder.glob('stage-*/session.restore'),
                 *folder.glob('stage-*/found.hex')]:
        path.unlink(missing_ok=True)


def choose_workload(rows):
    scores = {}
    for workload in (1, 2, 3):
        samples = [r['speed'] for r in rows if r['workload'] == workload and r['usable']]
        if len(samples) == 2 and min(samples) > 0 and max(samples) / min(samples) <= 1.2:
            scores[workload] = statistics.median(samples)
    if 1 not in scores:
        return 1
    faster = [w for w in scores if scores[w] >= scores[1] * 1.10]
    if not faster:
        return 1
    best = max(scores[w] for w in faster)
    return min(w for w in faster if scores[w] >= best * .95)


def calibrate(executable, folder, mode, plan, stop, update, index, execution, deadline):
    key = str(index)
    record = execution.setdefault('tuning', {}).setdefault(key, {'rows': [], 'complete': False})
    if record['complete']:
        return None, record['workload']
    order = (1, 2, 3, 3, 2, 1)
    for trial in range(len(record['rows']), len(order)):
        if stop.is_set() or deadline - time.monotonic() < 15:
            return {'state': 'paused', 'reason': 'pause' if stop.is_set() else 'time_limit'}, 1
        update(message=f'GPU負荷を測定中 {trial + 1}/{len(order)}',
               metrics={'phase': 'tuning', 'tested': 0, 'total': 0})
        target = folder / f'tune-{index:03d}-{trial:02d}'
        target.mkdir(mode=0o700, exist_ok=True)
        (target / 'source.hash').write_bytes((folder / 'source.hash').read_bytes())
        speeds, temperatures, warnings, telemetry = [], [], [], []
        first_sample = None
        def measure(**fields):
            nonlocal first_sample
            metrics = fields.get('metrics', {})
            if metrics.get('speed', 0) > 0:
                first_sample = first_sample or time.monotonic()
                if time.monotonic() - first_sample >= 3:
                    speeds.append(metrics['speed'])
                temperatures.append(metrics.get('temperature', 0))
                telemetry.append(metrics.get('thermal_complete', False))
            if fields.get('warning'):
                warnings.append(fields['warning'])
                update(warning=fields['warning'])
        result = run_stage(executable, target, mode, dict(plan, workload=order[trial]),
                           stop, measure, seconds=12)
        # Trial checkpoints never replace the canonical stage checkpoint.
        (target / 'session.restore').unlink(missing_ok=True)
        (target / 'candidates.hex').unlink(missing_ok=True)
        if result['state'] != 'paused' or result.get('reason') != 'time_limit':
            return result, 1
        usable = (len(speeds) >= 4 and temperatures and all(telemetry) and
                  0 < max(temperatures) < min(plan['temperature'] - 5, 75) and
                  not any('温度制御' in w for w in warnings))
        record['rows'].append({'workload': order[trial], 'speed': statistics.median(speeds) if speeds else 0,
                               'temperature': max(temperatures, default=0), 'usable': bool(usable),
                               'samples': len(speeds)})
        save_execution(folder, execution)
    record.update(complete=True, workload=choose_workload(record['rows']))
    save_execution(folder, execution)
    return None, record['workload']


def run_hashcat(executable, folder, mode, plan, stop, update, resume=False):
    if resume and not (folder / 'execution.json').exists() and (folder / 'session.restore').exists():
        return run_stage(executable, folder, mode, plan, stop, update, True)
    started = time.monotonic()
    deadline = started + plan['minutes'] * 60
    stages = execution_stages(mode, plan)
    stat = executable.stat()
    identity = [str(executable.resolve()), stat.st_size, stat.st_mtime_ns]
    fingerprint = hashlib.sha256((folder / 'source.hash').read_bytes() +
                                json.dumps([mode, plan, identity], sort_keys=True).encode('utf-8')).hexdigest()
    execution = {'version': 1, 'fingerprint': fingerprint, 'index': 0, 'workload': plan['workload']}
    if resume and (folder / 'execution.json').exists():
        execution = json.loads((folder / 'execution.json').read_text(encoding='utf-8'))
        if (execution.get('version') != 1 or execution.get('fingerprint') != fingerprint or
                type(execution.get('index')) is not int or not 0 <= execution['index'] <= len(stages)):
            raise ValueError('探索条件と保存地点が一致しません。新しく探索を開始してください。')
    else:
        clear_execution(folder)
        save_execution(folder, execution)
    total = sum(int(stage['candidates']) for stage in stages)
    completed = sum(int(stage['candidates']) for stage in stages[:execution['index']])
    for index in range(execution['index'], len(stages)):
        if stop.is_set() or time.monotonic() >= deadline:
            return {'state': 'paused', 'reason': 'pause' if stop.is_set() else 'time_limit',
                    'checkpoint': has_checkpoint(folder)}
        stage = dict(stages[index], workload=execution['workload'])
        result = None
        if (plan.get('tune') and int(stage['candidates']) >= 1000000 and
                not (folder / f'stage-{index:03d}' / 'session.restore').exists() and
                (str(index) in execution.get('tuning', {}) or deadline - time.monotonic() >= 120)):
            result, workload = calibrate(executable, folder, mode, stage, stop, update, index, execution, deadline)
            stage['workload'] = workload
            if result and result['state'] not in ('exhausted',):
                result['checkpoint'] = has_checkpoint(folder)
                return result
            update(warning=f'負荷測定の選択: {workload}。この候補・実行環境での測定結果です。')
        stage_folder = folder / f'stage-{index:03d}'
        stage_folder.mkdir(mode=0o700, exist_ok=True)
        (stage_folder / 'source.hash').write_bytes((folder / 'source.hash').read_bytes())
        update(message=f"段階 {index + 1}/{len(stages)}: {stage['stage_name']}",
               metrics={'tested': completed, 'total': total, 'stage': index + 1, 'stages': len(stages)})
        def progress(**fields):
            if 'metrics' in fields:
                metrics = fields['metrics']
                fraction = min(1, metrics['tested'] / metrics['total']) if metrics['total'] else 0
                fields['metrics'] = dict(metrics, tested=completed + int(int(stage['candidates']) * fraction),
                                         total=total, stage=index + 1, stages=len(stages))
            update(**fields)
        if result is None:
            result = run_stage(executable, stage_folder, mode, stage, stop, progress,
                               resume and index == execution['index'], max(0, deadline - time.monotonic()))
        if result['state'] != 'exhausted':
            result['checkpoint'] = has_checkpoint(folder)
            return result
        completed += int(stage['candidates'])
        execution['index'] = index + 1
        save_execution(folder, execution)
        update(metrics={'tested': completed, 'total': total, 'stage': index + 1, 'stages': len(stages)})
    return {'state': 'exhausted'}
