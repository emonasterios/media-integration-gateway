"""Utilities for unpacking Dean Edwards packed JavaScript."""

from __future__ import annotations

import re

_PACKED_RE = re.compile(
    r"eval\(function\(p,a,c,k,e,(?:r|d)\)\{.*?\}\((?P<prefix>.+?)\)",
    re.DOTALL,
)

_ARGS_RE = re.compile(
    r"^(?P<p>.*?),(?P<a>\d+),(?P<c>\d+),(?P<k>'(?:[^'\\]|\\.)*'|\[(?:.|\n)*?\]),(?P<rest>.*)$",
    re.DOTALL,
)

_TOKEN_RE = re.compile(r"\b\w+\b")


def _decode_word(word: str, base: int) -> str:
    try:
        return str(int(word, base))
    except ValueError:
        return word


def unpack_js(packed: str) -> str:
    match = _PACKED_RE.search(packed)
    if not match:
        return packed

    prefix = match.group("prefix")
    args_match = _ARGS_RE.match(prefix)
    if not args_match:
        return packed

    p = args_match.group("p").strip()
    a = int(args_match.group("a"))
    c = int(args_match.group("c"))
    k_raw = args_match.group("k").strip()

    if k_raw.startswith("'") and k_raw.endswith("'"):
        k_raw = k_raw[1:-1]
    elif k_raw.startswith("[") and k_raw.endswith("]"):
        k_raw = k_raw[1:-1]
    k = k_raw.split("|") if k_raw else []

    if c and len(k) < c:
        k.extend([""] * (c - len(k)))

    def repl(token: re.Match[str]) -> str:
        key = token.group(0)
        idx = _decode_word(key, a)
        if idx == key:
            return key
        pos = int(idx)
        if 0 <= pos < len(k) and k[pos]:
            return k[pos]
        return key

    return _TOKEN_RE.sub(repl, p)
