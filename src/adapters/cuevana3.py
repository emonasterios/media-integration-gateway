"""Adapter para Cuevana3 (cuevana3i.cc).

Extrae películas y series del sitio mediante scraping HTTP + BeautifulSoup.
"""

from __future__ import annotations

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

BASE_URL = "https://cuevana3i.cc"

logger = logging.getLogger(__name__)


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
        try:
            resp = await self._client.get("/buscar/", params={"q": query})
            resp.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("Timeout buscando %s en cuevana3", query)
            return SearchResult(items=[], total=0, query=query)
        except httpx.HTTPError as e:
            logger.warning("Error HTTP buscando %s: %s", query, e)
            return SearchResult(items=[], total=0, query=query)

        soup = BeautifulSoup(resp.text, "lxml")

        posts = soup.select("div.TPost")
        if not posts:
            logger.debug("No se encontraron elementos div.TPost en la respuesta de búsqueda")
            return SearchResult(items=[], total=0, query=query)

        items: list[MediaItem] = []
        for post in posts:
            link = post.find("a", href=True)
            if not link:
                continue
            href = link["href"]

            # Título y año: texto del link o elemento interno
            title_text = link.get_text(strip=True)
            title, year = self._parse_title_and_year(title_text)

            # Año: buscar en span.Year si no se encontró en el título
            year_el = post.select_one("span.Year")
            if year is None and year_el:
                m = re.search(r"\b(19|20)\d{2}\b", year_el.get_text())
                year = int(m.group(0)) if m else None

            # Imagen: figure.Objf img
            img_el = post.select_one("figure.Objf img") or post.find("img")
            poster_url = None
            if img_el:
                src = img_el.get("src")
                # Si src es placeholder SVG (data:image), intentar data-src
                if src and src.startswith("data:"):
                    src = img_el.get("data-src")
                if src and not src.startswith("data:"):
                    poster_url = urljoin(self._base, src) if not src.startswith("http") else src

            # Determinar tipo por URL
            media_type = MediaType.SERIES if "/serie/" in href else MediaType.MOVIE
            provider_id = self._slug_from_url(href)

            items.append(
                MediaItem(
                    media_id=f"cuevana3:{provider_id}",
                    title=title,
                    media_type=media_type,
                    year=year,
                    poster_url=poster_url,
                    overview=None,
                    provider=self.name,
                    provider_id=provider_id,
                )
            )

        return SearchResult(items=items, total=len(items), query=query)

    # ------------------------------------------------------------------
    # Catálogo
    # ------------------------------------------------------------------
    async def get_catalog(self, category: Optional[str] = None) -> list[MediaItem]:
        """Lista películas o series recientes."""
        path = "/peliculas/" if not category else f"/genero/{category}/"
        try:
            resp = await self._client.get(path)
            resp.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("Timeout en catálogo %s", path)
            return []
        except httpx.HTTPError as e:
            logger.warning("Error HTTP en catálogo %s: %s", path, e)
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        posts = soup.select("div.TPost")
        if not posts:
            logger.debug("No se encontraron elementos div.TPost en la respuesta del catálogo")
            return []

        items: list[MediaItem] = []
        for post in posts:
            link = post.find("a", href=True)
            if not link:
                continue

            title_text = link.get_text(strip=True)
            title, year = self._parse_title_and_year(title_text)

            # Año: buscar en span.Year si no se encontró en el título
            year_el = post.select_one("span.Year")
            if year is None and year_el:
                m = re.search(r"\b(19|20)\d{2}\b", year_el.get_text())
                year = int(m.group(0)) if m else None

            img_el = post.select_one("figure.Objf img") or post.find("img")
            poster_url = None
            if img_el:
                src = img_el.get("src")
                # Si src es placeholder SVG (data:image), intentar data-src
                if src and src.startswith("data:"):
                    src = img_el.get("data-src")
                if src and not src.startswith("data:"):
                    poster_url = urljoin(self._base, src) if not src.startswith("http") else src

            provider_id = self._slug_from_url(link["href"])
            # Determinar tipo por URL
            media_type = MediaType.SERIES if "/serie/" in link["href"] else MediaType.MOVIE

            items.append(
                MediaItem(
                    media_id=f"cuevana3:{provider_id}",
                    title=title,
                    media_type=media_type,
                    year=year,
                    poster_url=poster_url,
                    overview=None,
                    provider=self.name,
                    provider_id=provider_id,
                )
            )

        return items

    # ------------------------------------------------------------------
    # Detalles
    # ------------------------------------------------------------------
    async def get_details(self, media_id: str) -> MediaItem:
        slug = media_id.removeprefix("cuevana3:")
        html = None
        media_type = MediaType.MOVIE

        for prefix, mtype in (("pelicula", MediaType.MOVIE), ("serie", MediaType.SERIES)):
            try:
                resp = await self._client.get(f"/{prefix}/{slug}/")
                if resp.status_code == 200:
                    html = resp.text
                    media_type = mtype
                    break
            except (httpx.RequestError, httpx.HTTPError):
                continue

        if html is None:
            raise ValueError(f"Timeout accediendo a {media_id}")

        soup = BeautifulSoup(html, "lxml")

        # Título: article h1 o h2
        title = self._extract_title(soup)

        # Sinopsis: primer p del article
        overview = self._extract_overview(soup)

        # Año: buscar patrón \b(19|20)\d{2}\b en sectionfooter
        year = self._extract_year(soup)

        # Poster: meta og:image primero, luego article figure img
        poster = self._extract_poster(soup)

        # Géneros y duración
        genres = self._extract_genres(soup)
        duration = self._extract_duration(soup)
        
        return MediaItem(
            media_id=f"cuevana3:{slug}",
            title=title or slug,
            media_type=media_type,
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

        seasons: list[Season] = []
        # Buscar selector de temporada (suelen ser select o lista de temporadas)
        season_select = soup.find("select", id="season") or soup.find("select", class_=re.compile(r"season"))
        if season_select:
            for opt in season_select.find_all("option"):
                try:
                    num = int(opt.get("value", 1))
                except ValueError:
                    num = 1
                seasons.append(Season(season_number=num, title=opt.get_text(strip=True)))
        else:
            # Buscar enlaces de temporadas en la página
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
        # Buscar enlaces de episodios: patrón /serie/{slug}/temporada-{N}-capitulo-{M}/
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
        """Navega a la página del título y extrae URLs de servidores (Doodstream, Voe, Vidhide).
        
        NO asumir que existe un iframe con src en el HTML estático inicial.
        Los servidores se cargan dinámicamente o sus identificadores residen en
        atributos como data-mdl / scripts."""
        slug = media_id.removeprefix("cuevana3:")
        html = None

        for prefix in ("pelicula", "serie"):
            try:
                resp = await self._client.get(f"/{prefix}/{slug}/")
                if resp.status_code == 200:
                    html = resp.text
                    break
            except (httpx.TimeoutException, httpx.HTTPError) as e:
                logger.warning("Error HTTP/Timeout resolviendo %s/%s: %s", prefix, slug, e)
                continue

        if html is None:
            raise ValueError(f"Timeout resolviendo reproducción para {media_id}")

        soup = BeautifulSoup(html, "lxml")

        # 1. Buscar servidores en etiquetas li con data-server (NUEVO: estructura real)
        li = soup.select_one("li[data-server]")
        if li and li.get("data-server"):
            return PlaybackDescriptor(
                protocol="embed",
                url=li["data-server"],
                headers={"Referer": self._base},
            )

        # 2. Buscar servidores en la lista ul/li con data-mdl o data-url (PRIORIDAD ALTA)
        server_info = self._extract_server_from_list(soup)
        if server_info:
            return PlaybackDescriptor(
                protocol="embed",
                url=server_info["url"],
                headers={"Referer": self._base},
            )

        # 2. Buscar en scripts inline (data-url, onclick, etc.)
        server_url = self._extract_server_from_scripts(soup)
        if server_url:
            return PlaybackDescriptor(
                protocol="embed",
                url=server_url,
                headers={"Referer": self._base},
            )

        # 3. Fallback: buscar cualquier enlace a servidor conocido
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if self._is_known_server(href):
                return PlaybackDescriptor(
                    protocol="embed",
                    url=urljoin(self._base, href) if not href.startswith("http") else href,
                    headers={"Referer": self._base},
                )

        logger.debug("No se encontró fuente de reproducción para %s. HTML: %s", media_id, soup.prettify()[:2000])
        raise ValueError(f"No se encontró fuente de reproducción para {media_id}")

    # ------------------------------------------------------------------
    # Helpers de extracción
    # ------------------------------------------------------------------
    @staticmethod
    def _slug_from_url(url: str) -> str:
        parts = url.rstrip("/").split("/")
        return parts[-1] if parts else ""

    @staticmethod
    def _is_series_slug(slug: str) -> bool:
        return False  # se determina por contexto de URL

    @staticmethod
    def _parse_title_and_year(text: str) -> tuple[str, Optional[int]]:
        """Extrae título y año del texto combinado (ej: '2024 The Movie')."""
        year_match = re.search(r"\b(19|20)\d{2}\b", text)
        year = int(year_match.group()) if year_match else None
        # Quitar el año del título si está al principio
        title = re.sub(r"^\s*\b(19|20)\d{2}\b\s*", "", text).strip()
        return title, year

    @staticmethod
    def _extract_title(soup) -> Optional[str]:
        article = soup.find("article")
        if article:
            h1 = article.find("h1")
            if h1:
                return h1.get_text(strip=True)
            h2 = article.find("h2")
            if h2:
                return h2.get_text(strip=True)
        # Fallback: h1 en cualquier parte
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        title_tag = soup.find("title")
        return title_tag.get_text(strip=True) if title_tag else None

    @staticmethod
    def _extract_overview(soup) -> Optional[str]:
        # Buscar sinopsis en div.Description p (NUEVO: estructura real)
        desc = soup.select_one("div.Description p")
        if desc:
            return " ".join(desc.get_text(" ", strip=True).split())

        article = soup.find("article")
        if article:
            p = article.find("p")
            if p:
                return p.get_text(strip=True)
        # Fallback: meta description
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
        if meta and meta.get("content"):
            return meta["content"].strip()
        return None

    @staticmethod
    def _extract_genres(soup) -> list[str]:
        """Extrae géneros desde enlaces dentro del article."""
        article = soup.find("article")
        if not article:
            return []
        genres = []
        for a in article.find_all("a", href=True):
            href = a.get("href", "")
            if "/genero/" in href or "genre/" in href:
                text = a.get_text(strip=True)
                if text:
                    genres.append(text)
        return genres

    @staticmethod
    def _extract_year(soup) -> Optional[int]:
        # Primero buscar en sectionfooter
        footer = soup.select_one("sectionfooter") or soup.find(class_=re.compile(r"sectionfooter"))
        if footer:
            text = footer.get_text()
            match = re.search(r"\b(19|20)\d{2}\b", text)
            if match:
                return int(match.group())
        # Fallback: buscar en todo el article
        article = soup.find("article")
        if article:
            text = article.get_text()
            match = re.search(r"\b(19|20)\d{2}\b", text)
            if match:
                return int(match.group())
        # Fallback global
        text = soup.get_text()
        match = re.search(r"\b(19|20)\d{2}\b", text)
        return int(match.group()) if match else None

    @staticmethod
    def _extract_duration(soup) -> Optional[str]:
        """Extrae duración (ej: '1h 52m') desde sectionfooter."""
        footer = soup.select_one("sectionfooter") or soup.find(class_=re.compile(r"sectionfooter"))
        if footer:
            text = footer.get_text()
            # Buscar patrones como '1h 52m', '100 min', '2h', etc.
            match = re.search(r"(\d+h\s*\d*m|\d+h|\d+\s*min)", text, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _extract_poster(soup) -> Optional[str]:
        # Prioridad 1: meta og:image
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"]
        # Prioridad 2: article figure img o figure img
        fig_img = soup.select_one("article figure img, figure img")
        if fig_img and fig_img.get("src"):
            src = fig_img["src"]
            if not src.startswith("data:"):
                return src
        return None

    @staticmethod
    def _extract_server_language(li) -> Optional[str]:
        """Extrae idioma/bandera del servidor desde imagen (es.svg, en.svg, etc.)."""
        img = li.find("img")
        if img and img.get("src"):
            src = img["src"]
            # Buscar código de idioma en el nombre del archivo
            match = re.search(r'/([a-z]{2})\.svg', src)
            if match:
                return match.group(1)
            # Buscar en alt o title
            alt = img.get("alt", "")
            if alt:
                return alt.lower()[:2]
        return None

    @staticmethod
    def _count_episodes(soup) -> int:
        return len(soup.select("a[href*='capitulo-']"))

    @staticmethod
    def _is_known_server(url: str) -> bool:
        """Verifica si la URL pertenece a un servidor de video conocido."""
        known = ("doodstream", "voe", "vidhide", "filemoon", "streamtape", "upstream")
        url_lower = url.lower()
        return any(k in url_lower for k in known)

    def _extract_server_from_list(self, soup) -> Optional[dict]:
        """Extrae URL de servidor e idioma de la lista ul/li con data-mdl.
        
        Returns:
            dict con 'url' y opcional 'language', o None si no encuentra."""
        for li in soup.select("ul li"):
            # Buscar div dentro del li (puede tener data-mdl, data-url, o onclick)
            div = li.find("div")
            if div:
                # Buscar data-mdl o data-url
                url = div.get("data-mdl") or div.get("data-url")
                if url and self._is_known_server(url):
                    language = self._extract_server_language(li)
                    return {
                        "url": url if url.startswith("http") else urljoin(self._base, url),
                        "language": language,
                    }

                # Buscar onclick en el div
                onclick = div.get("onclick")
                if onclick:
                    match = re.search(r'["\'](https?://[^"\']+)["\']', onclick)
                    if match and self._is_known_server(match.group(1)):
                        language = self._extract_server_language(li)
                        return {"url": match.group(1), "language": language}

            # Buscar onclick en el li (fallback)
            onclick = li.get("onclick")
            if onclick:
                match = re.search(r'["\'](https?://[^"\']+)["\']', onclick)
                if match and self._is_known_server(match.group(1)):
                    language = self._extract_server_language(li)
                    return {"url": match.group(1), "language": language}

            # Buscar enlaces dentro del li
            for a in li.find_all("a", href=True):
                if self._is_known_server(a["href"]):
                    href = a["href"]
                    language = self._extract_server_language(li)
                    return {
                        "url": href if href.startswith("http") else urljoin(self._base, href),
                        "language": language,
                    }

        return None

    def _extract_server_from_scripts(self, soup) -> Optional[str]:
        """Busca URLs de servidores en scripts inline."""
        for script in soup.find_all("script"):
            if not script.string:
                continue
            text = script.string
            # Buscar patrones de URL en el script
            for match in re.finditer(r'["\'](https?://[^"\']+)["\']', text):
                url = match.group(1)
                if self._is_known_server(url):
                    return url
        return None

    async def close(self) -> None:
        await self._client.aclose()