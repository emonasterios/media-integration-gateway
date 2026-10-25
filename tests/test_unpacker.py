import re
from pathlib import Path

from src.services.resolvers.unpacker import unpack_js

FIXTURES = Path(__file__).parent / "fixtures"


def test_unpacks_payload_with_parentheses_inside_p_string():
    # Página real de vimeos.net (2026-10-25): el payload p contiene "(" y ")",
    # y k viene como '...'.split('|').
    packed = (FIXTURES / "vimeos_packed.js").read_text()

    unpacked = unpack_js(packed)

    assert unpacked != packed
    assert re.search(r"https?://[^\s'\"]+\.m3u8", unpacked)


def test_unpacks_minimal_split_form():
    packed = "eval(function(p,a,c,k,e,d){return p}('0(\"1\")',2,2,'alert|hola'.split('|'),0,{}))"

    assert unpack_js(packed) == 'alert("hola")'


def test_returns_input_when_not_packed():
    assert unpack_js("var x = 1;") == "var x = 1;"
