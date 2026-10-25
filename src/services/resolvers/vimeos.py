"""Resolver para embeds de vimeos.net."""

from __future__ import annotations

import re

from curl_cffi import requests

from src.services.resolvers.unpacker import unpack_js

_M3U8_RE = re.compile(r"https?://[^\s'\"]+?\.m3u8[^\s'\"]*", re.IGNORECASE)
_SOURCES_RE = re.compile(
    r"sources\s*:\s*\[\s*\{\s*file\s*:\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE | re.DOTALL,
)


class VimeosResolver:
    def __init__(self, url: str = "", request_headers: dict | None = None):
        self.url = url

    async def extract(self, url: str | None = None) -> dict:
        target_url = url or self.url
        if not target_url:
            raise ValueError("Se requiere una URL para resolver vimeos.net")

        session = requests.AsyncSession(impersonate="chrome")
        response = await session.get(
            target_url,
            headers={"Referer": "https://vimeos.net/"},
        )
        html = response.text

        unpacked = unpack_js(html)

        source_match = _SOURCES_RE.search(unpacked)
        if source_match:
            destination_url = source_match.group(1)
        else:
            m3u8_match = _M3U8_RE.search(unpacked)
            if not m3u8_match:
                raise ValueError(f"No se encontró video m3u8 en vimeos.net para {target_url}")
            destination_url = m3u8_match.group(0)

        return {
            "destination_url": destination_url,
            "request_headers": {"Referer": "https://vimeos.net/"},
        }
