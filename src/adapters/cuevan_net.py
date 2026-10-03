"""Adapter para Cuevan.net (cuevan.net).

Extrae películas y series del sitio mediante scraping HTTP + BeautifulSoup.
Usa embeds firmados con expiración que redirigen a servidores externos (Streamtape, etc.).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from src.adapters.base import MediaProvider
from src.models.catalog import (
    Episode,
    MediaItem,
    MediaType,
    PlaybackDescriptor,
    Season,
    SearchResult,
)
from src.services.video_resolver import VideoResolver

BASE_URL = "https://cuevan.net"

logger = logging.getLogger(__name__)


class CuevanNetAdapter(MediaProvider):
    """Adapter de lectura para cuevan.net."""

    def __init__(self, base_url: str = BASE_URL) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base,
            follow_redirects=True,
            timeout=15.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "es-ES,es;q=0.9",
            },
        )
        self._video_resolver = VideoResolver()

    @property
    def name(self) -> str:
        return "cuevan_net"

    # ------------------------------------------------------------------
    # Búsqueda
    # ------------------------------------------------------------------
    async def search(self, query: str) -> SearchResult:
        """Busca en /buscar?q=... y devuelve resultados normalizados."""
        try:
            resp = await self._client.get("/buscar", params={"q": query})
            resp.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("Timeout buscando %s en cuevan_net", query)
            return SearchResult(items=[], total=0, query=query)
        except httpx.HTTPError as e:
            logger.warning("Error HTTP buscando %s: %s", query, e)
            return SearchResult(items=[], total=0, query=query)

        soup = BeautifulSoup(resp.text, "lxml")
        items = self._parse_grid_items(soup)
        return SearchResult(items=items, total=len(items), query=query)

    # ------------------------------------------------------------------
    # Catálogo
    # ------------------------------------------------------------------
    async def get_catalog(self, category: Optional[str] = None) -> list[MediaItem]:
        """Lista películas o series recientes con paginación completa."""
        if category == "movies":
            path = "/peliculas"
        elif category == "series":
            path = "/series"
        elif category:
            path = f"/genero/{category}"
        else:
            path = "/peliculas"  # default
        all_items: list[MediaItem] = []
        page = 1
        max_pages = 10  # límite inicial razonable (se puede aumentar después)

        while page <= max_pages:
            params = {"page": page} if page > 1 else {}
            try:
                resp = await self._client.get(path, params=params if params else None)
                resp.raise_for_status()
            except httpx.TimeoutException:
                logger.warning("Timeout en catálogo página %d: %s", page, path)
                break
            except httpx.HTTPError as e:
                logger.warning("Error HTTP en catálogo página %d: %s", page, e)
                break

            soup = BeautifulSoup(resp.text, "lxml")
            items = self._parse_grid_items(soup)
            if not items:
                logger.debug("No hay más items en página %d, fin de paginación", page)
                break

            all_items.extend(items)
            logger.info("Página %d: %d items (total acumulado: %d)", page, len(items), len(all_items))

            await asyncio.sleep(0.5)
            page += 1

        logger.info("Catálogo completo: %d items en %d páginas", len(all_items), page - 1)
        return all_items

    # ------------------------------------------------------------------
    # Detalles
    # ------------------------------------------------------------------
    async def get_details(self, media_id: str) -> MediaItem:
        slug = media_id.removeprefix("cuevan_net:")
        html = None
        media_type = MediaType.MOVIE

        for prefix, mtype in (("peliculas", MediaType.MOVIE), ("series", MediaType.SERIES)):
            try:
                resp = await self._client.get(f"/{prefix}/{slug}/")
                if resp.status_code == 200:
                    html = resp.text
                    media_type = mtype
                    break
            except httpx.HTTPError:
                continue

        if html is None:
            raise ValueError(f"No se pudo acceder a {media_id}")

        soup = BeautifulSoup(html, "lxml")
        title = self._extract_title(soup)
        overview = self._extract_overview(soup)
        year = self._extract_year(soup)
        poster = self._extract_poster(soup)
        genres = self._extract_genres(soup)
        duration = self._extract_duration(soup)

        return MediaItem(
            media_id=f"cuevan_net:{slug}",
            title=title or slug,
            media_type=media_type,
            year=year,
            poster_url=poster,
            overview=overview,
            provider=self.name,
            provider_id=slug,
            available_languages=["es"],
        )

    # ------------------------------------------------------------------
    # Temporadas y episodios
    # ------------------------------------------------------------------
    async def get_seasons(self, media_id: str) -> list[Season]:
        slug = media_id.removeprefix("cuevan_net:")
        try:
            resp = await self._client.get(f"/series/{slug}/")
            if resp.status_code != 200:
                return []
        except httpx.HTTPError:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        seasons: list[Season] = []

        # Buscar selector de temporada
        season_select = soup.find("select", id="season") or soup.find("select", class_=re.compile(r"season"))
        if season_select:
            for opt in season_select.find_all("option"):
                try:
                    num = int(opt.get("value", 1))
                except ValueError:
                    num = 1
                seasons.append(Season(season_number=num, title=opt.get_text(strip=True)))
        else:
            season_links = soup.select("a[href*='temporada-']")
            if season_links:
                seen = set()
                for link in season_links:
                    m = re.search(r"temporada-(\d+)", link.get("href", ""))
                    if m:
                        num = int(m.group(1))
                        if num not in seen:
                            seen.add(num)
                            seasons.append(Season(season_number=num, title=f"Temporada {num}"))
                seasons.sort(key=lambda s: s.season_number)

        if not seasons:
            seasons.append(Season(season_number=1, episode_count=0))

        return seasons

    async def get_episodes(self, media_id: str, season_number: int) -> list[Episode]:
        slug = media_id.removeprefix("cuevan_net:")
        try:
            resp = await self._client.get(f"/series/{slug}/")
            if resp.status_code != 200:
                return []
        except httpx.HTTPError:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        episodes: list[Episode] = []
        ep_links = soup.select(f"a[href*='temporada-{season_number}-capitulo-']")
        for i, ep_link in enumerate(ep_links, 1):
            ep_slug = self._slug_from_url(ep_link.get("href", ""))
            ep_title = ep_link.get_text(strip=True) or f"Episodio {i}"
            episodes.append(
                Episode(
                    episode_number=i,
                    season_number=season_number,
                    title=ep_title,
                    provider_id=ep_slug or f"ep-{i}",
                    provider=self.name,
                )
            )

        return episodes

    # ------------------------------------------------------------------
    # Resolución de reproducción
    # ------------------------------------------------------------------
    async def resolve_playback(self, media_id: str) -> PlaybackDescriptor:
        """Navega a la página del título y extrae el embed firmado."""
        slug = media_id.removeprefix("cuevan_net:")
        html = None

        for prefix in ("peliculas", "series"):
            try:
                resp = await self._client.get(f"/{prefix}/{slug}/")
                if resp.status_code == 200:
                    html = resp.text
                    break
            except httpx.HTTPError:
                continue

        if html is None:
            raise ValueError(f"Timeout resolviendo reproducción para {media_id}")

        soup = BeautifulSoup(html, "lxml")

        # 1. Buscar data-initial-url en el player-mount
        mount = soup.select_one("#player-mount[data-initial-url]")
        if mount and mount.get("data-initial-url"):
            embed_url = mount["data-initial-url"]
            return await self._resolve_embed(embed_url)

        # 2. Buscar en video-server-tab
        tab = soup.select_one(".video-server-tab[data-url]")
        if tab and tab.get("data-url"):
            embed_url = tab["data-url"]
            return await self._resolve_embed(embed_url)

        # 3. Buscar iframes directos
        iframe = soup.find("iframe", src=True)
        if iframe:
            return await self._build_playback_descriptor(iframe["src"])

        logger.debug("No se encontró fuente de reproducción para %s", media_id)
        raise ValueError(f"No se encontró fuente de reproducción para {media_id}")

    async def _resolve_embed(self, embed_url: str) -> PlaybackDescriptor:
        """Resuelve un embed firmado de cuevan.net → extrae iframe del servidor externo."""
        try:
            resp = await self._client.get(
                embed_url,
                headers={"Referer": self._base},
                timeout=10.0,
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                iframe = soup.find("iframe", src=True)
                if iframe:
                    server_url = iframe["src"]
                    logger.info("Embed resuelto a servidor externo: %s", server_url[:80])
                    return await self._build_playback_descriptor(server_url)
        except httpx.HTTPError as e:
            logger.warning("Error resolviendo embed %s: %s", embed_url[:80], e)

        # Si no se puede resolver el embed, devolver el embed mismo
        return PlaybackDescriptor(protocol="embed", url=embed_url, headers={"Referer": self._base})

    async def _build_playback_descriptor(self, server_url: str) -> PlaybackDescriptor:
        """Intenta resolver servidores conocidos a URL directa."""
        if VideoResolver.is_morencius(server_url):
            try:
                direct = await self._video_resolver.resolve_morencius(server_url)
                if direct:
                    return direct
            except Exception as e:
                logger.warning("Fallo resolviendo Morencius %s: %s", server_url, e)

        if VideoResolver.is_streamtape(server_url):
            try:
                direct = await self._video_resolver.resolve_streamtape(server_url)
                if direct:
                    return direct
            except Exception as e:
                logger.warning("Fallo resolviendo Streamtape %s: %s", server_url, e)

        if VideoResolver.is_doodstream(server_url):
            try:
                direct = await self._video_resolver.resolve_doodstream(server_url)
                if direct:
                    return direct
            except Exception as e:
                logger.warning("Fallo resolviendo Doodstream %s: %s", server_url, e)

        if VideoResolver.is_voe(server_url):
            try:
                direct = await self._video_resolver.resolve_voe(server_url)
                if direct:
                    return direct
            except Exception as e:
                logger.warning("Fallo resolviendo Voe %s: %s", server_url, e)

        return PlaybackDescriptor(protocol="embed", url=server_url, headers={"Referer": self._base})

    # ------------------------------------------------------------------
    # Helpers de parsing
    # ------------------------------------------------------------------
    def _parse_grid_items(self, soup: BeautifulSoup) -> list[MediaItem]:
        """Parsea los items de la grid de películas/series."""
        items: list[MediaItem] = []
        # cuevan.net usa links con estructura: /peliculas/{slug}/ o /series/{slug}/
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not (href.startswith("/peliculas/") or href.startswith("/series/")):
                continue
            # Evitar enlaces de paginación y navegación
            if "/page/" in href or "page=" in href:
                continue

            # Extraer título del texto del link
            text = link.get_text(strip=True)
            if not text or len(text) < 3:
                continue

            title, year = self._parse_title_and_year(text)
            if not title:
                continue

            # Determinar tipo
            media_type = MediaType.SERIES if "/series/" in href else MediaType.MOVIE
            provider_id = self._slug_from_url(href)

            # Poster: buscar imagen dentro del link
            img = link.find("img")
            poster_url = None
            if img:
                src = img.get("src") or img.get("data-src")
                if src and not src.startswith("data:"):
                    poster_url = urljoin(self._base, src) if not src.startswith("http") else src

            items.append(
                MediaItem(
                    media_id=f"cuevan_net:{provider_id}",
                    title=title,
                    media_type=media_type,
                    year=year,
                    poster_url=poster_url,
                    overview=None,
                    provider=self.name,
                    provider_id=provider_id,
                    available_languages=["es"],
                )
            )

        return items

    @staticmethod
    def _slug_from_url(url: str) -> str:
        parts = url.rstrip("/").split("/")
        return parts[-1] if parts else ""

    @staticmethod
    def _parse_title_and_year(text: str) -> tuple[str, Optional[int]]:
        """Extrae título y año del texto."""
        year_match = re.search(r"\b(19|20)\d{2}\b", text)
        year = int(year_match.group()) if year_match else None
        title = re.sub(r"\b(19|20)\d{2}\b", "", text).strip().strip("()")
        # Limpiar etiquetas tipo PELÍCULA, SERIE
        title = re.sub(r"\bPELÍCULA\b|\bSERIE\b|\bSERIES\b", "", title, flags=re.IGNORECASE).strip()
        return title, year

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> Optional[str]:
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        title_tag = soup.find("title")
        if title_tag:
            text = title_tag.get_text(strip=True)
            # Limpiar: "Verity (2026) Online en Español Latino | Cuevana 3" → "Verity"
            text = re.sub(r"\s*\(?\d{4}\)?.*", "", text)
            text = re.sub(r"\s*\|.*", "", text)
            return text.strip()
        return None

    @staticmethod
    def _extract_overview(soup: BeautifulSoup) -> Optional[str]:
        # Buscar en párrafos dentro de la sección de sinopsis
        for heading in soup.find_all(["h2", "h3"]):
            if "sinopsis" in heading.get_text(strip=True).lower():
                parent = heading.find_parent()
                if parent:
                    p = parent.find_next_sibling("p") or parent.find("p")
                    if p:
                        return p.get_text(strip=True)
        # Fallback: meta description
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        if meta and meta.get("content"):
            return meta["content"].strip()
        return None

    @staticmethod
    def _extract_year(soup: BeautifulSoup) -> Optional[int]:
        # Buscar año en el texto cerca del título
        h1 = soup.find("h1")
        if h1:
            text = h1.get_text()
            match = re.search(r"\b(19|20)\d{2}\b", text)
            if match:
                return int(match.group())
        # Buscar en el texto general
        text = soup.get_text()
        match = re.search(r"\b(19|20)\d{2}\b", text)
        return int(match.group()) if match else None

    @staticmethod
    def _extract_duration(soup: BeautifulSoup) -> Optional[str]:
        # Buscar patrones como "114M", "1h 52m", "100 min"
        text = soup.get_text()
        match = re.search(r"(\d+M)\b", text)
        if match:
            mins = match.group(1).rstrip("M")
            return f"{mins} min"
        match = re.search(r"(\d+h\s*\d*m|\d+h|\d+\s*min)", text, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def _extract_poster(soup: BeautifulSoup) -> Optional[str]:
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"]
        # Buscar imagen principal
        img = soup.select_one("main img") or soup.find("img")
        if img:
            src = img.get("src") or img.get("data-src")
            if src and not src.startswith("data:"):
                return src
        return None

    @staticmethod
    def _extract_genres(soup: BeautifulSoup) -> list[str]:
        genres = []
        for link in soup.find_all("a", href=True):
            if "/genero/" in link["href"] or "/genre/" in link["href"]:
                text = link.get_text(strip=True)
                if text:
                    genres.append(text)
        return genres

    async def close(self) -> None:
        await self._video_resolver.close()
        await self._client.aclose()
