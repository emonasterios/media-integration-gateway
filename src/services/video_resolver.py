"""Servicio de resolución de video directo para servidores Doodstream/Playmogo."""

from __future__ import annotations

import logging
import random
import re
import string
import time
from typing import Optional

import httpx

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

    async def close(self) -> None:
        """Cierra el cliente HTTP asíncrono."""
        await self._client.aclose()