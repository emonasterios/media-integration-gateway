"""Resolver para embeds de waaw.to."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from curl_cffi import requests

_IFRAME_RE = re.compile(r"<iframe[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
_FILE_RE = re.compile(r"file:\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_SOURCE_RE = re.compile(r"source:\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_MEDIA_RE = re.compile(r"https?://[^\s'\"]+\.(?:m3u8|mp4)(?:\?[^\s'\"]*)?", re.IGNORECASE)


class WaawResolver:
    def __init__(self, url: str = ""):
        self.url = url

    async def extract(self, url: str | None = None) -> dict:
        target_url = url or self.url
        if not target_url:
            raise ValueError("Se requiere una URL para resolver waaw.to")

        session = requests.AsyncSession(impersonate="chrome")
        headers = {"Referer": "https://waaw.to/"}

        response = await session.get(target_url, headers=headers)
        html = response.text

        iframe_match = _IFRAME_RE.search(html)
        if iframe_match and "/f/" in target_url:
            iframe_url = urljoin(target_url, iframe_match.group(1))
            response = await session.get(iframe_url, headers={"Referer": target_url})
            html = response.text

        candidates = []
        for regex in (_FILE_RE, _SOURCE_RE, _MEDIA_RE):
            match = regex.search(html)
            if match:
                candidates.append(match.group(1) if match.lastindex else match.group(0))

        if not candidates:
            raise ValueError(f"No se encontró video en waaw.to para {target_url}")

        return {
            "destination_url": candidates[0],
            "request_headers": {"Referer": "https://waaw.to/"},
        }
