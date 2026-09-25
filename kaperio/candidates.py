"""Bounded, deterministic local hints. No external dictionaries or services."""
from __future__ import annotations

MAX_CANDIDATES = 100000
ASCII_LOWER = str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')
ASCII_UPPER = str.maketrans('abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ')
LEET = (('a', '@'), ('e', '3'), ('i', '1'), ('o', '0'), ('s', '$'))


def lines(value, maximum, width):
    if not isinstance(value, str):
        raise ValueError('候補はテキストで指定してください。')
    result = list(dict.fromkeys(w for w in value.splitlines() if w))
    if len(result) > maximum or any(len(w.encode('utf-8')) > width for w in result):
        raise ValueError(f'入力は{maximum}行、各行{width} UTF-8バイト以内にしてください。')
    return result


def guided_candidates(data):
    bases = lines(data.get('words', ''), 64, 48)
    tokens = lines(data.get('numbers', ''), 32, 16)
    symbols = data.get('separators', '!_')
    if not bases:
        raise ValueError('覚えている単語を1件以上指定してください。')
    if not isinstance(symbols, str) or len(symbols) > 8 or any(c not in '!@#$%&*+-_.?' for c in symbols):
        raise ValueError('記号は !@#$%&*+-_.? から8文字以内で指定してください。')
    for field in ('combine', 'typos'):
        if not isinstance(data.get(field, False), bool):
            raise ValueError('候補生成の設定が不正です。')
    symbols = list(dict.fromkeys(symbols))
    words, seen, groups = [], set(), []

    def add(word):
        if word and word not in seen:
            if len(word.encode('utf-8')) > 127 or len(words) >= MAX_CANDIDATES:
                raise ValueError('生成候補が上限を超えます。単語・数字・記号を減らしてください。')
            seen.add(word)
            words.append(word)

    def group(name, start):
        if len(words) > start:
            groups.append({'name': name, 'count': len(words) - start})

    for word in bases:
        add(word)
    group('入力候補', 0)
    start = len(words)
    variants = []
    for word in bases:
        lower = word.translate(ASCII_LOWER)
        for variant in (lower, word.translate(ASCII_UPPER), lower[:1].translate(ASCII_UPPER) + lower[1:]):
            add(variant)
            variants.append(variant)
        for old, new in LEET:
            if old in lower:
                variant = lower.replace(old, new)
                add(variant)
                variants.append(variant)
    variants = list(dict.fromkeys(bases + variants))
    group('表記違い', start)
    start = len(words)
    for word in variants:
        for token in tokens:
            add(word + token)
            add(token + word)
            for symbol in symbols:
                add(word + token + symbol)
                add(word + symbol + token)
        for symbol in symbols:
            add(word + symbol)
    group('数字・記号', start)
    start = len(words)
    if data.get('combine', False):
        for left in bases:
            for right in bases:
                for separator in ['', *symbols]:
                    add(left + separator + right)
    if data.get('typos', False):
        for word in bases:
            for i in range(len(word)):
                add(word[:i] + word[i + 1:])
                if i + 1 < len(word):
                    add(word[:i] + word[i + 1] + word[i] + word[i + 2:])
    group('単語結合・誤入力', start)
    return words, groups


def interview_candidates(data, low, high, allowed, prefix, suffix, max_bytes=127):
    """Prioritize literal memories before bounded local variations."""
    bases = lines(data.get('words', ''), 64, 127)
    tokens = lines(data.get('numbers', ''), 32, 16)
    words, seen, groups = [], set(), []
    omitted = {'bytes': False, 'capacity': False}

    def add(value):
        if not value:
            return
        if prefix and not value.startswith(prefix):
            value = prefix + value
        if suffix and not value.endswith(suffix):
            value += suffix
        if not low <= len(value) <= high:
            return
        middle = value[len(prefix):len(value) - len(suffix) if suffix else None]
        if allowed is not None and any(c not in allowed for c in middle):
            return
        if len(value.encode('utf-8')) > max_bytes:
            omitted['bytes'] = True
            return
        if value in seen:
            return
        if len(words) >= MAX_CANDIDATES:
            omitted['capacity'] = True
            return
        seen.add(value)
        words.append(value)

    def group(name, start):
        if len(words) > start:
            groups.append({'name': name, 'count': len(words) - start})

    for word in [*bases, *tokens]:
        add(word)
    group('覚えている語句・数字', 0)
    start = len(words)
    variants = list(bases)
    for word in bases:
        lower = word.translate(ASCII_LOWER)
        variants.extend([lower, word.translate(ASCII_UPPER), lower[:1].translate(ASCII_UPPER) + lower[1:]])
        variants.extend(lower.replace(old, new) for old, new in LEET if old in lower)
    variants = list(dict.fromkeys(variants))
    for word in variants:
        add(word)
    group('英字の大小・置き換え', start)
    start = len(words)
    for left in bases:
        for right in bases:
            for separator in ('', ' ', '_', '-'):
                add(left + separator + right)
    group('2つの単語の組み合わせ', start)
    start = len(words)
    for word in variants:
        for token in dict.fromkeys([*tokens, *(str(n) for n in range(100)), *(f'{n:02d}' for n in range(10))]):
            add(word + token)
            for symbol in ('!', '_', '-'):
                add(word + symbol + token)
                add(word + token + symbol)
        for token in dict.fromkeys([*tokens, *(str(n) for n in range(10))]):
            add(token + word)
        for symbol in ('!', '_', '-'):
            add(word + symbol)
    group('数字・記号の付け足し', start)
    return words, groups, omitted
