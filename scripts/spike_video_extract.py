#!/usr/bin/env python3
"""Spike: intentar extraer URLs de video directo (.m3u8/.mp4) de los servidores
que usa Cuevana3 (doodstream, voe, vidhide, streamwish, etc.).

Uso:
    cd /home/emon/media-integration-gateway
    . .venv/bin/activate
    python scripts/spike_video_extract.py [URL]

Si no se pasa URL, usa Signal One por defecto.
"""
import asyncio
import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import httpx

sys.path.insert(0, "/home/emon/media-integration-gateway")

from src.adapters.cuevana3 import Cuevana3Adapter

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

VIDEO_PATTERNS = [
    r'https?://[^"\s]+\.m3u8[^"\s]*',
    r'https?://[^"\s]+\.mp4[^"\s]*',
    r'https?://[^"\s]+\.mkv[^"\s]*',
    r'https?://[^"\s]+\.webm[^"\s]*',
    r'sources\s*:\s*\[([^\]]+)\]',       # video.js sources
    r'file\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
    r'file\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
    r'"?file"?\s*:\s*["\']([^"\']+)["\']',
    r'src\s*:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
    r'src\s*:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
    r'<source[^>]+src=["\']([^"\']+)["\']',
    r'contentUrl["\s:]+["\']([^"\']+\.(?:mp4|m3u8|mkv|webm)[^"\']*)["\']',
]


def find_video_urls(html: str, source_url: str) -> list[dict]:
    """Busca URLs de video directo en el HTML."""
    results = []
    for pat in VIDEO_PATTERNS:
        for m in re.finditer(pat, html, re.IGNORECASE | re.DOTALL):
            url = m.group(1) if m.lastindex else m.group(0)
            url = url.strip().strip("'\"")
            if url and not url.startswith("data:"):
                if not url.startswith("http"):
                    url = urljoin(source_url, url)
                ext = urlparse(url).path.rsplit(".", 1)[-1].split("?")[0].lower()
                results.append({"url": url, "type": ext, "pattern": pat[:40]})
    return results


async def try_http_chain(url: str, label: str) -> dict:
    """Sigue la cadena de redirecciones con httpx y busca video."""
    result = {
        "server": label,
        "initial_url": url,
        "final_url": None,
        "status": None,
        "video_urls": [],
        "error": None,
        "cloudflare_blocked": False,
    }

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=20.0,
            headers={"User-Agent": UA, "Referer": "https://cuevana3i.cc/"},
        ) as client:
            resp = await client.get(url)
            result["final_url"] = str(resp.url)
            result["status"] = resp.status_code

            html = resp.text.lower()
            if "just a moment" in html or "cf-challenge" in html:
                result["cloudflare_blocked"] = True

            result["video_urls"] = find_video_urls(resp.text, str(resp.url))

    except httpx.TimeoutException:
        result["error"] = "timeout"
    except httpx.HTTPError as e:
        result["error"] = str(e)

    return result


async def resolve_and_extract(adapter: Cuevana3Adapter, media_id: str) -> dict:
    """Resuelve playback desde el adapter y luego intenta extraer video directo."""
    result = {
        "media_id": media_id,
        "playback_resolved": False,
        "playback_url": None,
        "playback_protocol": None,
        "direct_video": [],
        "server_chain": [],
        "error": None,
    }

    try:
        playback = await adapter.resolve_playback(media_id)
        result["playback_resolved"] = True
        result["playback_url"] = playback.url
        result["playback_protocol"] = playback.protocol
    except (ValueError, Exception) as e:
        result["error"] = str(e)
        return result

    if playback.url:
        # Determinar nombre del servidor
        server_name = "unknown"
        for name in ("dood", "voe", "vidhide", "streamwish", "filemoon", "streamtape"):
            if name in playback.url.lower():
                server_name = name
                break

        chain_result = await try_http_chain(playback.url, server_name)
        result["server_chain"].append(chain_result)
        result["direct_video"] = chain_result["video_urls"]

    return result


async def main():
    target_url = (
        sys.argv[1] if len(sys.argv) > 1
        else "https://cuevana3i.cc/pelicula/signal-one/"
    )

    print("=" * 60)
    print("SPIKE: Extracción de video directo de servidores de streaming")
    print("=" * 60)
    print(f"Target: {target_url}")
    print(f"Fecha: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    adapter = Cuevana3Adapter()

    # Extraer slug de la URL
    slug = target_url.rstrip("/").split("/")[-1]
    media_id = f"cuevana3:{slug}"

    print(f"[1/3] Resolviendo playback para '{slug}'...")
    result = await resolve_and_extract(adapter, media_id)

    if result["playback_resolved"]:
        print(f"  ✅ Playback resuelto")
        print(f"  Protocolo: {result['playback_protocol']}")
        print(f"  URL del servidor: {result['playback_url']}")
    else:
        print(f"  ❌ No se pudo resolver playback: {result['error']}")
        print()
        print("Intentando acceso directo a la página de la película...")
        # Fallback: acceder directamente a la página y buscar servidores
        html, resp = await adapter._fetch_with_flare_fallback(f"/pelicula/{slug}/")
        if html:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            # Buscar data-server
            li = soup.select_one("li[data-server]")
            if li:
                server_url = li.get("data-server")
                print(f"  Servidor encontrado (data-server): {server_url}")
                chain = await try_http_chain(server_url, "data-server")
                result["server_chain"].append(chain)
                result["direct_video"] = chain["video_urls"]
            else:
                server_info = adapter._extract_server_from_list(soup)
                if server_info:
                    server_url = server_info["url"]
                    print(f"  Servidor encontrado (lista): {server_url}")
                    chain = await try_http_chain(server_url, "lista")
                    result["server_chain"].append(chain)
                    result["direct_video"] = chain["video_urls"]
                else:
                    print("  No se encontraron servidores en la página")

    print()
    print("[2/3] Analizando cadena de servidores...")
    for chain in result["server_chain"]:
        print(f"\n  Servidor: {chain['server']}")
        print(f"  URL inicial: {chain['initial_url']}")
        print(f"  URL final: {chain.get('final_url', 'N/A')}")
        print(f"  Status: {chain.get('status', 'N/A')}")
        if chain.get("cloudflare_blocked"):
            print(f"  ⚠️  BLOQUEADO por Cloudflare")
        if chain.get("error"):
            print(f"  ❌ Error: {chain['error']}")
        if chain.get("video_urls"):
            print(f"  ✅ {len(chain['video_urls'])} URL(s) de video encontradas:")
            for v in chain["video_urls"]:
                print(f"     - [{v['type']}] {v['url'][:120]}...")
        else:
            print(f"  ❌ No se encontraron URLs de video directo")

    print()
    print("[3/3] Resumen:")
    all_videos = []
    for chain in result["server_chain"]:
        all_videos.extend(chain.get("video_urls", []))

    if all_videos:
        print(f"  ✅ VIDEO DIRECTO disponible ({len(all_videos)} URL(s))")
        for v in all_videos:
            print(f"     - {v['type'].upper()}: {v['url']}")
    else:
        print(f"  ❌ NO se encontró video directo (.m3u8/.mp4)")
        print("  Posibles causas:")
        print("  - Cloudflare CAPTCHA bloquea el acceso automatizado")
        print("  - El video se carga via JavaScript (requiere navegador real)")
        print("  - El servidor usa decodificación especial (Doodstream, etc.)")
        print("  - Se necesita FlareSolverr u otro bypass")

    # Guardar resultado como JSON
    output = {
        "target": target_url,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "playback": {
            "resolved": result["playback_resolved"],
            "url": result["playback_url"],
            "protocol": result["playback_protocol"],
        },
        "servers": [
            {
                "name": c["server"],
                "initial_url": c["initial_url"],
                "final_url": c.get("final_url"),
                "status": c.get("status"),
                "cloudflare_blocked": c.get("cloudflare_blocked", False),
                "error": c.get("error"),
                "video_urls": c.get("video_urls", []),
            }
            for c in result["server_chain"]
        ],
        "direct_video_found": len(all_videos) > 0,
        "direct_video_urls": all_videos,
    }

    print()
    print("Resultado JSON:")
    print(json.dumps(output, indent=2, ensure_ascii=False))

    await adapter.close()
    return 0 if all_videos else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
