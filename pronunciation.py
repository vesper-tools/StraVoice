"""Literal pronunciation replacements; never send phonemes to unsupported models."""
import json
import re
from pathlib import Path

from pauses import PAUSE


def validate(entries):
    if not isinstance(entries, dict) or len(entries) > 500:
        raise ValueError("词典最多保存 500 条读法。")
    clean = {}
    for source, spoken in entries.items():
        if not isinstance(source, str) or not isinstance(spoken, str):
            raise ValueError("原文和读法必须是文字。")
        source, spoken = source.strip(), spoken.strip()
        if not source or not spoken or max(len(source), len(spoken)) > 100:
            raise ValueError("原文和读法均须为 1–100 个字符。")
        if any(mark in source + spoken for mark in ("【停顿", "\n", "\r", "\t")):
            raise ValueError("词条不能包含停顿标记、换行或制表符。")
        clean[source] = spoken
    return clean


def load(path):
    path = Path(path)
    if not path.exists():
        return {}
    return validate(json.loads(path.read_text(encoding="utf-8")))


def save(path, entries):
    entries = validate(entries)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".tmp")
    partial.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    partial.replace(path)


def apply(text, entries):
    """One pass, longest first, case-sensitive; protect ASCII word boundaries."""
    if not entries:
        return text
    patterns = []
    for key in sorted(entries, key=len, reverse=True):
        left = r"(?<![A-Za-z0-9_])" if key[0].isascii() and key[0].isalnum() else ""
        right = r"(?![A-Za-z0-9_])" if key[-1].isascii() and key[-1].isalnum() else ""
        patterns.append(left + re.escape(key) + right)
    matcher = re.compile("|".join(patterns))
    # Pause markers remain parseable, even if a dictionary includes digits.
    parts, cursor = [], 0
    for pause in PAUSE.finditer(text):
        parts.extend((matcher.sub(lambda m: entries[m[0]], text[cursor:pause.start()]), pause[0]))
        cursor = pause.end()
    parts.append(matcher.sub(lambda m: entries[m[0]], text[cursor:]))
    return "".join(parts)
