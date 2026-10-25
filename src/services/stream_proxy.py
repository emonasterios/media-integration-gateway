"""Proxy de streaming directo y remux HLS → MPEG-TS."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from fastapi.responses import StreamingResponse

CHUNK_SIZE = 256 * 1024
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
_HLS_CONTENT_TYPES = {
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
}


async def proxy_stream(url: str, request_headers: dict, referer: str = "") -> StreamingResponse:
    if ".m3u8" in url.lower():
        return await remux_hls_to_ts(url, referer=referer)

    headers: dict[str, str] = {}
    range_header = request_headers.get("Range") or request_headers.get("range")
    if range_header:
        headers["Range"] = range_header
    if referer:
        headers["Referer"] = referer

    retries = 2
    for attempt in range(retries + 1):
        session = aiohttp.ClientSession()
        response = None
        try:
            response = await session.get(url, headers=headers)
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type in _HLS_CONTENT_TYPES:
                await response.release()
                await session.close()
                return await remux_hls_to_ts(url, referer=referer)

            if response.status in {429, 502, 503} and attempt < retries:
                await response.release()
                await session.close()
                await asyncio.sleep(2**attempt)
                continue

            response_headers: dict[str, str] = {}
            for key in ("Content-Type", "Accept-Ranges", "Content-Range", "Content-Length"):
                value = response.headers.get(key)
                if value:
                    response_headers[key] = value

            async def content_streamer(session: aiohttp.ClientSession, response: aiohttp.ClientResponse):
                try:
                    async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                        yield chunk
                finally:
                    response.close()
                    await session.close()

            return StreamingResponse(content_streamer(session, response), status_code=response.status, headers=response_headers)
        except Exception:
            if response is not None and not response.closed:
                response.close()
            await session.close()
            if attempt >= retries:
                raise
            await asyncio.sleep(2**attempt)
    raise RuntimeError("proxy_stream failed")


async def remux_hls_to_ts(hls_url: str, referer: str = "") -> StreamingResponse:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_delay_max",
        "2",
        "-rw_timeout",
        "15000000",
        "-analyzeduration",
        "3000000",
        "-probesize",
        "3000000",
    ]
    if referer:
        cmd.extend(["-headers", f"Referer: {referer}\r\n"])
    cmd.extend([
        "-i",
        hls_url,
        "-map",
        "0:v?",
        "-map",
        "0:a?",
        "-map",
        "0:s?",
        "-c",
        "copy",
        "-max_interleave_delta",
        "0",
        "-muxdelay",
        "0",
        "-muxpreload",
        "0",
        "-f",
        "mpegts",
        "pipe:1",
    ])

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    async def ffmpeg_streamer():
        try:
            assert process.stdout is not None
            while True:
                chunk = await process.stdout.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    process.kill()

    return StreamingResponse(ffmpeg_streamer(), media_type="video/mp2t")
