"""Servicio de resolución de video directo para servidores Doodstream/Playmogo."""

from __future__ import annotations

import logging
import random
import re
import string
import time
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from src.models.catalog import PlaybackDescriptor

DOODSTREAM_DOMAINS = (
    "doodstream.com",
    "dood.la",
    "dood.ws",
    "playmogo.com",
    "d000d.com",
    "dood.yt",
    "dooood.com",
)

VOE_DOMAINS = (
    "voe.sx",
    "voe-unblock.com",
    "voeunblock.com",
    "voeunbl0ck.com",
    "voeunblocker.com",
)

logger = logging.getLogger(__name__)


class VideoResolver:
    """Resuelve URLs de reproducción directa para servidores Doodstream/Playmogo."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=20.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                )
            },
        )

    @staticmethod
    def is_doodstream(url: str) -> bool:
        """Verifica si la URL pertenece a un dominio Doodstream/Playmogo."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in DOODSTREAM_DOMAINS)

    async def resolve_doodstream(self, embed_url: str) -> Optional[PlaybackDescriptor]:
        """
        Resuelve la URL de embed de Doodstream/Playmogo a una URL de video directo MP4.
        
        Args:
            embed_url: URL de la página de embed (ej: https://doodstream.com/e/abc123)
            
        Returns:
            PlaybackDescriptor con protocol="mp4" y la URL directa, o None si falla.
        """
        # 1. Obtener la página de embed
        try:
            resp = await self._client.get(embed_url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Error obteniendo página de embed %s: %s", embed_url, e)
            return None

        page_url = str(resp.url)
        html = resp.text

        # 2. Extraer token
        token_match = re.search(r"token=([a-zA-Z0-9]+)", html)
        if not token_match:
            logger.debug("No se encontró token en la página: %s", embed_url)
            return None
        token = token_match.group(1)

        # 3. Extraer pass_path
        pass_match = re.search(r"pass_md5/([^'\"]+)", html)
        if not pass_match:
            logger.debug("No se encontró pass_path en la página: %s", embed_url)
            return None
        pass_path = pass_match.group(1)

        # 4. Obtener URL base del CDN
        base_url = page_url.rsplit("/", 1)[0]
        pass_url = f"{base_url}/pass_md5/{pass_path}"

        # 5. Hacer GET a pass_url con Referer
        try:
            pass_resp = await self._client.get(pass_url, headers={"Referer": page_url})
            pass_resp.raise_for_status()
            cdn_base = pass_resp.text.strip()
        except httpx.HTTPError as e:
            logger.warning("Error obteniendo pass_md5 %s: %s", pass_url, e)
            return None

        if not cdn_base.startswith("http"):
            logger.debug("CDN base no es una URL válida: %s", cdn_base)
            return None

        # 6. Generar sufijo aleatorio y expiry
        random_suffix = "".join(
            random.choices(string.ascii_letters + string.digits, k=10)
        )
        expiry = int(time.time() * 1000)

        # 7. Construir URL final del video
        video_url = f"{cdn_base}{random_suffix}?token={token}&expiry={expiry}"

        # 8. Retornar descriptor de reproducción
        return PlaybackDescriptor(
            protocol="mp4",
            url=video_url,
            headers={"Referer": base_url},
        )

    @staticmethod
    def is_voe(url: str) -> bool:
        """Verifica si la URL pertenece a un dominio Voe."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in VOE_DOMAINS)

    async def resolve_voe(self, embed_url: str) -> Optional[PlaybackDescriptor]:
        """
        Resuelve la URL de embed de Voe.sx a una URL de video directo (m3u8/mp4).
        Usa FlareSolverr para bypass del anti-bot.
        """
        from src.services.flaresolverr import FlareSolverrClient

        flaresolverr = FlareSolverrClient()
        solution = flaresolverr.get_solution(embed_url, max_timeout=60000)
        if not solution or not solution.get("response"):
            logger.warning("FlareSolverr no pudo resolver %s", embed_url)
            return None

        html = solution["response"]
        soup = BeautifulSoup(html, "lxml")

        # Patrón 1: Buscar tag <source> o <video>
        for source in soup.find_all("source"):
            src = source.get("src", "")
            if src and (src.endswith(".m3u8") or src.endswith(".mp4")):
                protocol = "hls" if ".m3u8" in src else "mp4"
                return PlaybackDescriptor(
                    protocol=protocol,
                    url=src,
                    headers={"Referer": embed_url},
                )

        # Patrón 2: Buscar URLs en scripts (player config)
        scripts = soup.find_all("script")
        for script in scripts:
            txt = script.get_text()
            # Buscar m3u8
            m3u8_match = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', txt)
            if m3u8_match:
                return PlaybackDescriptor(
                    protocol="hls",
                    url=m3u8_match.group(1),
                    headers={"Referer": embed_url},
                )
            # Buscar mp4 directo
            mp4_match = re.search(r'(https?://[^\s"\']+\.mp4[^\s"\']*)', txt)
            if mp4_match:
                return PlaybackDescriptor(
                    protocol="mp4",
                    url=mp4_match.group(1),
                    headers={"Referer": embed_url},
                )
            # Buscar pattern file: 'url' o src: 'url'
            file_match = re.search(r'''(?:file|src)\s*:\s*['"]([^'"]+)['"]''', txt)
            if file_match:
                url = file_match.group(1)
                if url.startswith("http"):
                    protocol = "hls" if ".m3u8" in url else "mp4"
                    return PlaybackDescriptor(
                        protocol=protocol,
                        url=url,
                        headers={"Referer": embed_url},
                    )

        # Patrón 3: Buscar variables de video ofuscadas
        # Voe a veces usa variables como 'hls', 'videoSrc', etc.
        for script in scripts:
            txt = script.get_text()
            # Buscar cualquier URL larga que parezca un CDN de video
            cdn_matches = re.findall(
                r'(https?://[a-zA-Z0-9.-]+\.[a-z]{2,}/[a-zA-Z0-9/_-]+\.(m3u8|mp4|m3u)[^\s"\']*)',
                txt,
            )
            for url, ext in cdn_matches:
                protocol = "hls" if ext in ("m3u8", "m3u") else "mp4"
                return PlaybackDescriptor(
                    protocol=protocol,
                    url=url,
                    headers={"Referer": embed_url},
                )

        logger.debug("No se encontró video directo en %s", embed_url)
        return None

    async def close(self) -> None:
        """Cierra el cliente HTTP asíncrono."""
        await self._client.aclose()