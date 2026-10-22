from __future__ import annotations

import re

from curl_cffi import requests

from .unpacker import unpack_js


class VidhideResolver:
    def __init__(self, url: str = ""):
        self.url = url

    async def extract(self, url: str | None = None) -> dict:
        target_url = url or self.url
        if not target_url:
            raise ValueError("No video URL provided for VidhideResolver")

        headers = {"Referer": "https://vidhidepro.com/"}
        async with requests.AsyncSession(impersonate="chrome") as session:
            response = await session.get(target_url, headers=headers)
            html = response.text

        candidates = [html]
        for packed in re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S | re.I):
            if "eval(function(p,a,c,k,e,d)" in packed or "eval(function(" in packed:
                candidates.append(unpack_js(packed))

        patterns = [
            r"https?://[^\"'\s>]+?\.m3u8[^\"'\s>]*",
            r"https?://[^\"'\s>]+?\.mp4[^\"'\s>]*",
            r"['\"](https?://[^'\"\s>]+?\.(?:m3u8|mp4)[^'\"\s>]*)['\"]",
            r"(?:file|url|src)\s*[:=]\s*['\"]([^'\"\s>]+?\.(?:m3u8|mp4)[^'\"\s>]*)['\"]",
        ]

        for candidate in candidates:
            for pattern in patterns:
                match = re.search(pattern, candidate, flags=re.I)
                if match:
                    video_url = match.group(1) if match.lastindex else match.group(0)
                    return {
                        "destination_url": video_url,
                        "request_headers": headers,
                    }

        raise RuntimeError("No video stream URL found in vidhidepro.com response")
