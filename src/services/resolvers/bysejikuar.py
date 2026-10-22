"""Resolver para embeds de bysejikuar.com."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests

from src.services.resolvers.unpacker import unpack_js

_MEDIA_RE = re.compile(r"https?://[^\s'\"]+?\.(?:m3u8|mp4)(?:\?[^\s'\"]*)?", re.IGNORECASE)
_IFRAME_RE = re.compile(r"<iframe[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
_VIDEO_SRC_RE = re.compile(r"<video[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
_SOURCE_TAG_RE = re.compile(r"<source[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)
_FILE_RE = re.compile(r"(?:file|url|src)\s*[:=]\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_PACKED_RE = re.compile(r"eval\(function\(p,a,c,k,e,d\)", re.IGNORECASE | re.DOTALL)


class BysejikuarResolver:
    def __init__(self, url: str = ""):
        self.url = url

    async def extract(self, url: str | None = None) -> dict:
        target_url = url or self.url
        if not target_url:
            raise ValueError("Se requiere una URL para resolver bysejikuar.com")

        if "/e/" not in target_url:
            target_url = target_url.rstrip("/")

        headers = {"Referer": "https://bysejikuar.com/"}
        async with requests.AsyncSession(impersonate="chrome") as session:
            response = await session.get(target_url, headers=headers)
            html = response.text

        soup = BeautifulSoup(html, "html.parser")
        candidates: list[str] = []

        for video in soup.find_all("video"):
            src = video.get("src")
            if src:
                candidates.append(urljoin(target_url, src))
            for source in video.find_all("source"):
                src = source.get("src")
                if src:
                    candidates.append(urljoin(target_url, src))

        for tag in soup.find_all(["source", "iframe"]):
            src = tag.get("src")
            if src:
                candidates.append(urljoin(target_url, src))

        for regex in (_VIDEO_SRC_RE, _SOURCE_TAG_RE, _IFRAME_RE, _FILE_RE, _MEDIA_RE):
            for match in regex.finditer(html):
                value = match.group(1) if match.lastindex else match.group(0)
                candidates.append(urljoin(target_url, value))

        if _PACKED_RE.search(html):
            unpacked = unpack_js(html)
            for regex in (_MEDIA_RE, _FILE_RE, _VIDEO_SRC_RE, _SOURCE_TAG_RE, _IFRAME_RE):
                for match in regex.finditer(unpacked):
                    value = match.group(1) if match.lastindex else match.group(0)
                    candidates.append(urljoin(target_url, value))

        seen: set[str] = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            if candidate.endswith((".m3u8", ".mp4")) or ".m3u8" in candidate or ".mp4" in candidate:
                return {
                    "destination_url": candidate,
                    "request_headers": headers,
                }

        nested_iframe = soup.find("iframe", src=True)
        if nested_iframe:
            nested_url = urljoin(target_url, nested_iframe["src"])
            async with requests.AsyncSession(impersonate="chrome") as session:
                nested_response = await session.get(nested_url, headers={"Referer": target_url})
                nested_html = nested_response.text
            for regex in (_MEDIA_RE, _FILE_RE, _VIDEO_SRC_RE, _SOURCE_TAG_RE):
                match = regex.search(nested_html)
                if match:
                    candidate = urljoin(nested_url, match.group(1) if match.lastindex else match.group(0))
                    return {
                        "destination_url": candidate,
                        "request_headers": headers,
                    }

        raise ValueError(f"No se encontró video en bysejikuar.com para {target_url}")
