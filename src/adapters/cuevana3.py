"""Adapter para Cuevana3 (cuevana3i.cc).

Extrae películas y series del sitio mediante scraping HTTP + BeautifulSoup.
"""

from __future__ import annotations

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

BASE_URL = "https://cuevana3i.cc"


class Cuevana3Adapter(MediaProvider):
    """Adapter de lectura para cuevana3i.cc."""

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

    @property
    def name(self) -> str:
        return "cuevana3"

    # ------------------------------------------------------------------
    # Búsqueda
    # ------------------------------------------------------------------
    async def search(self, query: str) -> SearchResult:
        """Busca en /buscar/?q=... y devuelve resultados normalizados."""
        resp = await self._client.get("/buscar/", params={"q": query})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        items: list[MediaItem] = []
        for card in soup.select(".item, .poster, article"):
            link = card.find("a", href=True)
            if not link:
                continue
            href = link["href"]
            title_el = card.find("h2") or card.find("h3") or card.find("a")
            title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)

            # Determinar tipo por URL
            media_type = MediaType.SERIES if "/serie/" in href else MediaType.MOVIE
            provider_id = self._slug_from_url(href)

            # Año y rating opcionales
            year = self._extract_year(card)
            overview_el = card.find("p") or card.find("div", class_="description")
            overview = overview_el.get_text(strip=True) if overview_el else None
            poster_el = card.find("img")
            poster_url = poster_el.get("src") if poster_el else None

            items.append(
                MediaItem(
                    media_id=f"cuevana3:{provider_id}",
                    title=title,
                    media_type=media_type,
                    year=year,
                    poster_url=poster_url,
                    overview=overview,
                    provider=self.name,
                    provider_id=provider_id,
                )
            )

        return SearchResult(items=items, total=len(items), query=query)

    # ------------------------------------------------------------------
    # Detalles
    # ------------------------------------------------------------------
    async def get_details(self, media_id: str) -> MediaItem:
        slug = media_id.replace("cuevana3:", "")
        is_series = "/serie/" in media_id or self._is_series_slug(slug)
        path = f"/serie/{slug}/" if is_series else f"/pelicula/{slug}/"

        resp = await self._client.get(path)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        title = self._extract_title(soup)
        year = self._extract_year(soup)
        overview = self._extract_overview(soup)
        poster = self._extract_poster(soup)

        return MediaItem(
            media_id=f"cuevana3:{slug}",
            title=title or slug,
            media_type=MediaType.SERIES if is_series else MediaType.MOVIE,
            year=year,
            poster_url=poster,
            overview=overview,
            provider=self.name,
            provider_id=slug,
        )

    # ------------------------------------------------------------------
    # Temporadas y episodios
    # ------------------------------------------------------------------
    async def get_seasons(self, media_id: str) -> list[Season]:
        """Cuevana3 no expone temporadas de forma estructurada; se parsean de la página."""
        slug = media_id.replace("cuevana3:", "")
        resp = await self._client.get(f"/serie/{slug}/")
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Buscar selectores de temporada o listas de capítulos
        seasons: list[Season] = []
        season_select = soup.find("select", id="season") or soup.find("select")
        if season_select:
            for opt in season_select.find_all("option"):
                num = int(opt.get("value", 1))
                seasons.append(Season(season_number=num, title=opt.get_text(strip=True)))
        else:
            # Si no hay selector, asumir temporada única
            episodes = self._count_episodes(soup)
            seasons.append(Season(season_number=1, episode_count=episodes))

        return seasons

    async def get_episodes(
        self, media_id: str, season_number: int
    ) -> list[Episode]:
        slug = media_id.replace("cuevana3:", "")
        resp = await self._client.get(f"/serie/{slug}/")
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        episodes: list[Episode] = []
        # Buscar enlaces de episodios
        for i, ep_link in enumerate(
            soup.select(".episodes a, .capitulos a, .item a"), 1
        ):
            ep_slug = self._slug_from_url(ep_link.get("href", ""))
            episodes.append(
                Episode(
                    episode_number=i,
                    season_number=season_number,
                    title=ep_link.get_text(strip=True) or f"Episodio {i}",
                    provider_id=ep_slug or f"ep-{i}",
                    provider=self.name,
                )
            )

        return episodes

    # ------------------------------------------------------------------
    # Resolución de reproducción
    # ------------------------------------------------------------------
    async def resolve_playback(self, media_id: str) -> PlaybackDescriptor:
        """Navega a la página del título y extrae el iframe/embed del reproductor."""
        slug = media_id.replace("cuevana3:", "")
        is_series = "/serie/" in media_id or self._is_series_slug(slug)
        path = f"/serie/{slug}/" if is_series else f"/pelicula/{slug}/"

        resp = await self._client.get(path)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Buscar iframe de video
        iframe = soup.find("iframe", src=True)
        if not iframe:
            iframe = soup.find("source", src=True)

        if iframe and iframe.get("src"):
            embed_url = iframe["src"]
            if not embed_url.startswith("http"):
                embed_url = urljoin(self._base, embed_url)
            return PlaybackDescriptor(
                protocol="hls" if ".m3u8" in embed_url else "mp4",
                url=embed_url,
                headers={"Referer": self._base},
            )

        # Fallback: buscar enlaces de servidores (filemoon, doodstream, etc.)
        server_links = soup.select(".server a, .options a, .btn-play")
        if server_links:
            return PlaybackDescriptor(
                protocol="embed",
                url=urljoin(self._base, server_links[0].get("href", path)),
                headers={"Referer": self._base},
            )

        raise ValueError(f"No se encontró fuente de reproducción para {media_id}")

    # ------------------------------------------------------------------
    # Catálogo
    # ------------------------------------------------------------------
    async def get_catalog(self, category: Optional[str] = None) -> list[MediaItem]:
        """Lista películas o series recientes."""
        path = "/peliculas/" if not category else f"/genero/{category}/"
        resp = await self._client.get(path)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        items: list[MediaItem] = []
        for card in soup.select(".item, .poster, article"):
            link = card.find("a", href=True)
            if not link:
                continue
            title_el = card.find("h2") or card.find("h3") or card.find("a")
            title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)
            provider_id = self._slug_from_url(link["href"])
            poster_el = card.find("img")

            items.append(
                MediaItem(
                    media_id=f"cuevana3:{provider_id}",
                    title=title,
                    media_type=MediaType.MOVIE,
                    poster_url=poster_el.get("src") if poster_el else None,
                    provider=self.name,
                    provider_id=provider_id,
                )
            )

        return items

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _slug_from_url(url: str) -> str:
        parts = url.rstrip("/").split("/")
        return parts[-1] if parts else ""

    @staticmethod
    def _is_series_slug(slug: str) -> bool:
        return False  # se determina por contexto de URL

    @staticmethod
    def _extract_year(soup) -> Optional[int]:
        text = soup.get_text()
        match = re.search(r"\b(19|20)\d{2}\b", text)
        return int(match.group()) if match else None

    @staticmethod
    def _extract_title(soup) -> Optional[str]:
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        title_tag = soup.find("title")
        return title_tag.get_text(strip=True) if title_tag else None

    @staticmethod
    def _extract_overview(soup) -> Optional[str]:
        for sel in [".description", ".synopsis", ".info", "meta[name='description']"]:
            el = soup.select_one(sel)
            if el:
                text = el.get("content") or el.get_text(strip=True)
                if text:
                    return text
        return None

    @staticmethod
    def _extract_poster(soup) -> Optional[str]:
        img = soup.find("img", class_="poster") or soup.find("img", class_="thumbnail")
        if img and img.get("src"):
            return img["src"]
        og = soup.find("meta", property="og:image")
        return og.get("content") if og and og.get("content") else None

    @staticmethod
    def _count_episodes(soup) -> int:
        return len(soup.select(".episodes a, .capitulos a, .item a"))

    async def close(self) -> None:
        await self._client.aclose()
