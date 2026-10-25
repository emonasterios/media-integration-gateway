"""Utilities for unpacking Dean Edwards packed JavaScript."""

from __future__ import annotations

import re

# Full Dean Edwards IIFE pattern:
# eval(function(p,a,c,k,e,d){...return p}('p_string', a, c, 'k_string'.split('|')))
# Note: the function is CALLED immediately after the closing brace: }('p_string'...)
# The string has THREE closing parens: .split('|')))  -- split(), IIFE call, eval()
# The function body may contain 'return p' internally, so match up to }('
_PACKED_RE = re.compile(
    r"eval\(function\(p,a,c,k,e,(?:r|d)\)\{"
    r"(?P<body>.*?)"           # function body (non-greedy)
    r"return p\}\)\("            # final 'return p}' followed by '('
    r"(?P<p>.+?)"              # p_string (non-greedy)
    r"',\s*(?P<a>\d+)"
    r",\s*(?P<c>\d+)"
    r",\s*(?P<k>.+?)"          # k_string (non-greedy)
    r"\.split\('\|'\)\)\)",    # .split('|'))) - THREE closing parens: split(), IIFE call, eval()
    re.DOTALL,
)

_TOKEN_RE = re.compile(r"\b\w+\b")


def _decode_word(word: str, base: int) -> str:
    try:
        return str(int(word, base))
    except ValueError:
        return word


def _unescape_js_string(s: str) -> str:
    """Unescape a JavaScript single-quoted string."""
    result = []
    i = 0
    while i < len(s):
        if s[i] == "\\":
            if i + 1 < len(s):
                next_char = s[i + 1]
                if next_char == "'":
                    result.append("'")
                elif next_char == "\\":
                    result.append("\\")
                else:
                    result.append("\\" + next_char)
                i += 2
            else:
                i += 1
        else:
            result.append(s[i])
            i += 1
    return "".join(result)


def _strip_quotes(s: str) -> str:
    """Remove surrounding single or double quotes and unescape."""
    s = s.strip()
    if len(s) >= 2 and ((s[0] == "'" and s[-1] == "'") or (s[0] == '"' and s[-1] == '"')):
        return _unescape_js_string(s[1:-1])
    return s


def unpack_js(packed: str) -> str:
    """Unpack Dean Edwards packed JavaScript. Handles nested packing recursively."""
    result = packed
    
    for _ in range(10):  # Max 10 levels of nesting
        # Find ALL matches, use the LAST one (outermost IIFE)
        matches = list(_PACKED_RE.finditer(result))
        if not matches:
            break
        
        match = matches[-1]  # Last match = outermost IIFE
        
        p_raw = match.group("p")
        a = int(match.group("a"))
        c = int(match.group("c"))
        k_raw = match.group("k")

        # Strip quotes and unescape
        p = _strip_quotes(p_raw)
        k_raw = _strip_quotes(k_raw)

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

        # Replace the entire IIFE (from eval( to the closing )))
        unpacked_part = _TOKEN_RE.sub(repl, p)
        result = result[:match.start()] + unpacked_part + result[match.end():]
    
    return result