"""Utilities for unpacking Dean Edwards packed JavaScript."""

from __future__ import annotations

import re

_PACKED_START_RE = re.compile(r"eval\(function\(p,a,c,k,e,(?:r|d)\)\{")
_ARGS_START_RE = re.compile(r"\}\(\s*(?=['\"])")
_NUMS_RE = re.compile(r"\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*")

_TOKEN_RE = re.compile(r"\b\w+\b")
_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _read_js_string(src: str, pos: int) -> tuple[str, int] | None:
    """Lee el literal de cadena JS que empieza en pos; devuelve (contenido, fin)."""
    quote = src[pos]
    out: list[str] = []
    i = pos + 1
    while i < len(src):
        ch = src[i]
        if ch == "\\" and i + 1 < len(src):
            nxt = src[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
            i += 2
            continue
        if ch == quote:
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    return None


def _decode_word(word: str, base: int) -> int | None:
    if base > len(_DIGITS):
        return None
    value = 0
    for ch in word:
        digit = _DIGITS.find(ch)
        if digit < 0 or digit >= base:
            return None
        value = value * base + digit
    return value


def unpack_js(packed: str) -> str:
    start = _PACKED_START_RE.search(packed)
    if not start:
        return packed
    args_start = _ARGS_START_RE.search(packed, start.end())
    if not args_start:
        return packed

    p_lit = _read_js_string(packed, args_start.end())
    if not p_lit:
        return packed
    p, pos = p_lit

    nums = _NUMS_RE.match(packed, pos)
    if not nums or nums.end() >= len(packed) or packed[nums.end()] not in "'\"":
        return packed
    a, c = int(nums.group(1)), int(nums.group(2))

    k_lit = _read_js_string(packed, nums.end())
    if not k_lit:
        return packed
    k = k_lit[0].split("|")

    if c and len(k) < c:
        k.extend([""] * (c - len(k)))

    def repl(token: re.Match[str]) -> str:
        key = token.group(0)
        pos = _decode_word(key, a)
        if pos is not None and pos < len(k) and k[pos]:
            return k[pos]
        return key

    return _TOKEN_RE.sub(repl, p)
