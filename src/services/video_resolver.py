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

STREAMTAPE_DOMAINS = (
    "streamtape.com",
    "streamtape.to",
    "streamtape.site",
)

MORENCIUS_DOMAINS = (
    "morencius.com",
    "pixibay.cc",
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

    async def _validate_video_url(self, video_url: str, headers: dict) -> bool:
        """Verifica que la URL devuelva realmente video (no HTML/403).
        Sigue TODA la cadena de redirects y verifica el destino final."""
        try:
            import ssl
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            async with httpx.AsyncClient(verify=ssl_context) as verify_client:
                # HEAD con redirects para verificar el destino final
                resp = await verify_client.head(
                    video_url,
                    headers=headers,
                    follow_redirects=True,
                    timeout=15.0,
                )
            ct = resp.headers.get("content-type", "").lower()
            # Aceptar tipos de video reales
            valid_types = [
                "video/",
                "application/vnd.apple.mpegurl",  # HLS m3u8
                "application/x-mpegurl",
                "application/octet-stream",  # CDN genérico
                "binary/octet-stream",
            ]
            # Rechazar HTML, texto, o respuestas de error
            if resp.status_code >= 400:
                logger.warning("HEAD %d para %s (final: %s)", resp.status_code, video_url[:80], str(resp.url)[:80])
                return False
            if any(t in ct for t in ["text/html", "text/plain", "application/json"]):
                logger.warning("Content-Type no-video (%s) para %s", ct, video_url[:80])
                return False
            if any(t in ct for t in valid_types):
                return True
            # Si sigue siendo 302 después de follow_redirects=True, el destino final no respondió
            if resp.status_code == 302:
                logger.warning("HEAD 302 sin resolver para %s → %s", video_url[:80], str(resp.url)[:80])
                return False
            # Si no tiene Content-Type claro pero es 200, ser permisivo
            if resp.status_code in (200, 206):
                logger.info("HEAD %d sin CT claro para %s, aceptando", resp.status_code, video_url[:80])
                return True
            return False
        except httpx.HTTPError as e:
            logger.warning("Error validando URL %s: %s", video_url[:80], e)
            return False

    async def resolve_doodstream(self, embed_url: str) -> Optional[PlaybackDescriptor]:
        """
        Resuelve la URL de embed de Doodstream/Playmogo a una URL de video directo MP4.
        
        Flujo:
        1. GET embed → extraer pass_md5 y token
        2. GET /pass_md5/... → obtiene URL base del CDN
        3. Construir: {cdn_base}{token}?t={timestamp}
        """
        headers = {
            "User-Agent": self._client.headers.get("User-Agent", ""),
            "Referer": "https://doodstream.com/",
        }

        # 1. Obtener la página de embed (seguir redirects a playmogo, etc.)
        try:
            resp = await self._client.get(embed_url, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Error obteniendo página de embed %s: %s", embed_url, e)
            return None

        page_url = str(resp.url)
        html = resp.text

        # 2. Extraer pass_md5 (formato: /pass_md5/265711424-181-.../token)
        pass_match = re.search(r"(/pass_md5/[^\"']+)", html)
        if not pass_match:
            logger.debug("No se encontró pass_md5 en la página: %s", embed_url)
            return None
        pass_path = pass_match.group(1)

        # 3. Extraer token
        token_match = re.search(r"token=([a-zA-Z0-9]+)", html)
        if not token_match:
            logger.debug("No se encontró token en la página: %s", embed_url)
            return None
        token = token_match.group(1)

        # 4. Determinar dominio base (puede ser doodstream.com o playmogo.com)
        from urllib.parse import urlparse
        parsed = urlparse(page_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        # 5. Llamar al pass_md5 endpoint
        pass_url = f"{base_url}{pass_path}"
        pass_headers = {
            "User-Agent": headers["User-Agent"],
            "Referer": page_url,
        }
        try:
            pass_resp = await self._client.get(pass_url, headers=pass_headers)
            pass_resp.raise_for_status()
            cdn_base = pass_resp.text.strip()
        except httpx.HTTPError as e:
            logger.warning("Error obteniendo pass_md5 %s: %s", pass_url, e)
            return None

        if not cdn_base.startswith("http"):
            logger.debug("CDN base no es una URL válida: %s", cdn_base)
            return None

        # 6. Construir URL final del video
        video_url = f"{cdn_base}{token}?t={int(time.time())}"

        logger.info("Doodstream resuelto: %s → %s", embed_url, video_url[:80])
        
        # Validar que la URL realmente sirva video
        valid = await self._validate_video_url(video_url, {"Referer": base_url})
        if not valid:
            logger.warning("URL de Doodstream no válida (caída o 403): %s", video_url[:80])
            return None
        
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
                # Validar URL
                valid = await self._validate_video_url(src, {"Referer": embed_url})
                if valid:
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
                url = m3u8_match.group(1)
                valid = await self._validate_video_url(url, {"Referer": embed_url})
                if valid:
                    return PlaybackDescriptor(
                        protocol="hls",
                        url=url,
                        headers={"Referer": embed_url},
                    )
            # Buscar mp4 directo
            mp4_match = re.search(r'(https?://[^\s"\']+\.mp4[^\s"\']*)', txt)
            if mp4_match:
                url = mp4_match.group(1)
                valid = await self._validate_video_url(url, {"Referer": embed_url})
                if valid:
                    return PlaybackDescriptor(
                        protocol="mp4",
                        url=url,
                        headers={"Referer": embed_url},
                    )
            # Buscar pattern file: 'url' o src: 'url'
            file_match = re.search(r'''(?:file|src)\s*:\s*['"]([^'"]+)['"]''', txt)
            if file_match:
                url = file_match.group(1)
                if url.startswith("http"):
                    protocol = "hls" if ".m3u8" in url else "mp4"
                    valid = await self._validate_video_url(url, {"Referer": embed_url})
                    if valid:
                        return PlaybackDescriptor(
                            protocol=protocol,
                            url=url,
                            headers={"Referer": embed_url},
                        )

        # Patrón 3: Buscar variables de video ofuscadas
        for script in scripts:
            txt = script.get_text()
            cdn_matches = re.findall(
                r'(https?://[a-zA-Z0-9.-]+\.[a-z]{2,}/[a-zA-Z0-9/_-]+\.(m3u8|mp4|m3u)[^\s"\']*)',
                txt,
            )
            for url, ext in cdn_matches:
                protocol = "hls" if ext in ("m3u8", "m3u") else "mp4"
                valid = await self._validate_video_url(url, {"Referer": embed_url})
                if valid:
                    return PlaybackDescriptor(
                        protocol=protocol,
                        url=url,
                        headers={"Referer": embed_url},
                    )

        logger.debug("No se encontró video directo en %s", embed_url)
        return None

    @staticmethod
    def is_streamtape(url: str) -> bool:
        """Verifica si la URL pertenece a un dominio Streamtape."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in STREAMTAPE_DOMAINS)

    async def resolve_streamtape(self, embed_url: str) -> Optional[PlaybackDescriptor]:
        """
        Resuelve la URL de embed de Streamtape a una URL de video directo.
        Streamtape usa un sistema de 'videoplayback' con tokens.
        """
        try:
            resp = await self._client.get(embed_url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Error obteniendo página de Streamtape %s: %s", embed_url, e)
            return None

        html = resp.text

        # Streamtape tiene un div con id='videolink' que contiene la URL directa
        # o un script con la URL del video
        soup = BeautifulSoup(html, "lxml")

        # Patrón 1: buscar div#videolink
        video_link = soup.find("div", id="videolink")
        if video_link:
            direct_url = video_link.get_text(strip=True)
            if direct_url and direct_url.startswith("http"):
                # Validar URL
                valid = await self._validate_video_url(direct_url, {"Referer": "https://streamtape.com/"})
                if valid:
                    logger.info("Streamtape resuelto (videolink): %s", direct_url[:80])
                    return PlaybackDescriptor(
                        protocol="mp4",
                        url=direct_url,
                        headers={"Referer": "https://streamtape.com/"},
                    )

        # Patrón 2: buscar en scripts la URL del video
        scripts = soup.find_all("script")
        for script in scripts:
            txt = script.get_text()
            url_match = re.search(r"['\"](https?://[^'\"]*videoplayback[^'\"]*)['\"]", txt)
            if url_match:
                url = url_match.group(1)
                valid = await self._validate_video_url(url, {"Referer": "https://streamtape.com/"})
                if valid:
                    return PlaybackDescriptor(
                        protocol="mp4",
                        url=url,
                        headers={"Referer": "https://streamtape.com/"},
                    )

        # Patrón 3: buscar URLs con .mp4 en el HTML
        for script in scripts:
            txt = script.get_text()
            mp4_match = re.search(r'(https?://[^"\']+\.mp4[^"\']*)', txt)
            if mp4_match:
                url = mp4_match.group(1)
                valid = await self._validate_video_url(url, {"Referer": "https://streamtape.com/"})
                if valid:
                    return PlaybackDescriptor(
                        protocol="mp4",
                        url=url,
                        headers={"Referer": "https://streamtape.com/"},
                    )

        logger.debug("No se encontró video directo en Streamtape %s", embed_url)
        return None

    @staticmethod
    def is_morencius(url: str) -> bool:
        """Verifica si la URL pertenece a un dominio Morencius."""
        url_lower = url.lower()
        return any(domain in url_lower for domain in MORENCIUS_DOMAINS)

    async def resolve_morencius(self, embed_url: str) -> Optional[PlaybackDescriptor]:
        """
        Resuelve la URL de embed de Morencius a una URL de video directo (HLS m3u8).

        Morencius usa un script ofuscado con Dean Edwards Packer (eval function(p,a,c,k,e,d)).
        El objeto `links` contiene las URLs de video:
          - hls2: CDN directo (dramiyos-cdn.com) con token
          - hls3: CDN alternativo (realestateinvests.cfd)
          - hls4: URL relativa en morencius.com/stream/.../master.m3u8

        Estrategia:
        1. FlareSolverr para bypass anti-bot
        2. Extraer el bloque eval(...)
        3. Deobfuscar el Packer (base36, keyword dictionary)
        4. Extraer objeto `links` → preferir hls2 (CDN con token), fallback hls4
        """
        from src.services.flaresolverr import FlareSolverrClient

        flaresolverr = FlareSolverrClient()
        solution = flaresolverr.get_solution(embed_url, max_timeout=60000)
        if not solution or not solution.get("response"):
            logger.warning("FlareSolverr no pudo resolver %s", embed_url)
            return None

        html = solution["response"]

        # Extraer el bloque eval(function(p,a,c,k,e,d)
        eval_match = re.search(
            r"eval\(function\(p,a,c,k,e,d\)\{.*?return p\}\s*\(\s*'(.+?)',\s*(\d+),\s*(\d+),\s*'(.+?)'\.split\('\|'\)\s*\)\)",
            html, re.DOTALL,
        )
        if not eval_match:
            logger.debug("No se encontró eval packer en %s", embed_url)
            return None

        p_str = eval_match.group(1)
        base = int(eval_match.group(2))
        count = int(eval_match.group(3))
        k_str = eval_match.group(4)
        keywords = k_str.split("|")

        # Deobfuscar: reemplazar números en base-N por keywords
        decoded = self._unpack_packer(p_str, base, count, keywords)

        # Extraer objeto links: {"hls2": "...", "hls3": "...", "hls4": "..."}
        links_match = re.search(r'links=\{([^}]+)\}', decoded)
        if not links_match:
            logger.debug("No se encontró objeto links en %s", embed_url)
            return None

        links_str = links_match.group(1)
        # Parsear manualmente las URLs del objeto
        hls_urls = {}
        for m in re.finditer(r'"(hls\d+)":"([^"]+)"', links_str):
            hls_urls[m.group(1)] = m.group(2)

        if not hls_urls:
            logger.debug("No se encontraron URLs HLS en links: %s", embed_url)
            return None

        # Preferir hls4 (relativa en morencius.com, más estable),
        # luego hls2 (CDN con token, a veces cae), luego hls3
        from urllib.parse import urljoin

        video_url = None
        if "hls4" in hls_urls:
            video_url = urljoin(embed_url, hls_urls["hls4"])
        elif "hls2" in hls_urls:
            video_url = hls_urls["hls2"]
        elif "hls3" in hls_urls:
            video_url = hls_urls["hls3"]

        if not video_url:
            return None

        # Validar URL antes de devolver
        valid = await self._validate_video_url(video_url, {"Referer": "https://morencius.com/"})
        if not valid:
            logger.warning("URL de Morencius no válida: %s", video_url[:100])
            return None

        logger.info("Morencius resuelto: %s → %s", embed_url, video_url[:100])
        return PlaybackDescriptor(
            protocol="hls",
            url=video_url,
            headers={"Referer": "https://morencius.com/"},
        )

    @staticmethod
    def _unpack_packer(p_str: str, base: int, count: int, keywords: list) -> str:
        """
        Deobfusca un script empaquetado con Dean Edwards Packer.

        Args:
            p_str: El string codificado (p)
            base: La base numérica (a)
            count: Número de keywords (c)
            keywords: Lista de palabras clave (k)

        Returns:
            El script deobfuscado
        """
        def to_base(n: int, b: int) -> str:
            if n == 0:
                return "0"
            digits = []
            alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
            while n > 0:
                digits.append(alphabet[n % b])
                n //= b
            return "".join(reversed(digits))

        decoded = p_str
        # Reemplazar de mayor a menor índice (como el algoritmo original)
        for i in range(count - 1, -1, -1):
            if i < len(keywords) and keywords[i]:
                base_repr = to_base(i, base)
                decoded = re.sub(r"\b" + re.escape(base_repr) + r"\b", keywords[i], decoded)

        return decoded

    async def close(self) -> None:
        """Cierra el cliente HTTP asíncrono."""
        await self._client.aclose()