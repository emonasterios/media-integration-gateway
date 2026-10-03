"""Adapter para Cuevana3 (cuevana3i.cc).

Extrae películas y series del sitio mediante scraping HTTP + BeautifulSoup.
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
from src.services.flaresolverr import FlareSolverrClient
from src.services.video_resolver import VideoResolver

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
        self._flaresolverr = FlareSolverrClient()
        self._video_resolver = VideoResolver()

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
        """Lista películas o series recientes con paginación completa."""
        path = "/peliculas/" if not category else f"/genero/{category}/"
        all_items: list[MediaItem] = []
        page = 1
        max_pages = 20  # límite razonable (~1,500 items)

        while page <= max_pages:
            page_path = path
            if page > 1:
                # Cuevana3 usa /peliculas/page/N/
                base = path.rstrip("/")
                page_path = f"{base}/page/{page}/"

            try:
                resp = await self._client.get(page_path)
                resp.raise_for_status()
            except httpx.TimeoutException:
                logger.warning("Timeout en catálogo página %d: %s", page, page_path)
                break
            except httpx.HTTPError as e:
                logger.warning("Error HTTP en catálogo página %d: %s", page, e)
                break

            soup = BeautifulSoup(resp.text, "lxml")
            posts = soup.select("div.TPost")
            if not posts:
                logger.debug("No hay más posts en página %d, fin de paginación", page)
                break

            for post in posts:
                link = post.find("a", href=True)
                if not link:
                    continue

                title_text = link.get_text(strip=True)
                title, year = self._parse_title_and_year(title_text)

                year_el = post.select_one("span.Year")
                if year is None and year_el:
                    m = re.search(r"\b(19|20)\d{2}\b", year_el.get_text())
                    year = int(m.group(0)) if m else None

                img_el = post.select_one("figure.Objf img") or post.find("img")
                poster_url = None
                if img_el:
                    src = img_el.get("src")
                    if src and src.startswith("data:"):
                        src = img_el.get("data-src")
                    if src and not src.startswith("data:"):
                        poster_url = urljoin(self._base, src) if not src.startswith("http") else src

                provider_id = self._slug_from_url(link["href"])
                media_type = MediaType.SERIES if "/serie/" in link["href"] else MediaType.MOVIE

                all_items.append(
                    MediaItem(
                        media_id=f"cuevana3:{provider_id}",
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

            logger.info("Página %d: %d items (total acumulado: %d)", page, len(posts), len(all_items))

            # Delay entre páginas para no ser baneado
            await asyncio.sleep(1)

            page += 1

        logger.info("Catálogo completo: %d items en %d páginas", len(all_items), page - 1)
        return all_items

    # ------------------------------------------------------------------
    # Detalles
    # ------------------------------------------------------------------
    async def get_details(self, media_id: str) -> MediaItem:
        slug = media_id.removeprefix("cuevana3:")
        html = None
        media_type = MediaType.MOVIE

        for prefix, mtype in (("pelicula", MediaType.MOVIE), ("serie", MediaType.SERIES)):
            html, resp = await self._fetch_with_flare_fallback(f"/{prefix}/{slug}/")
            if html is not None:
                media_type = mtype
                break

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
        
        # Campos enriquecidos
        director = self._extract_director(soup)
        cast = self._extract_cast(soup)
        country = self._extract_country(soup)
        trailer = self._extract_trailer(soup)
        rating = self._extract_rating(soup)
        
        # Idiomas disponibles
        available_languages = self._extract_available_languages(soup)
        
        return MediaItem(
            media_id=f"cuevana3:{slug}",
            title=title or slug,
            media_type=media_type,
            year=year,
            poster_url=poster,
            overview=overview,
            provider=self.name,
            provider_id=slug,
            available_languages=available_languages,
            director=director,
            cast=cast,
            country=country,
            trailer_url=trailer,
            duration=duration,
            genres=genres,
            rating=rating,
        )

    # ------------------------------------------------------------------
    # Temporadas y episodios
    # ------------------------------------------------------------------
    async def get_seasons(self, media_id: str) -> list[Season]:
        """Cuevana3 no expone temporadas de forma estructurada; se parsean de la página."""
        slug = media_id.replace("cuevana3:", "")
        html, resp = await self._fetch_with_flare_fallback(f"/serie/{slug}/")
        if html is None:
            return []
        soup = BeautifulSoup(html, "lxml")

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
        html, resp = await self._fetch_with_flare_fallback(f"/serie/{slug}/")
        if html is None:
            return []
        soup = BeautifulSoup(html, "lxml")

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
    async def _build_playback_descriptor(self, server_url: str) -> PlaybackDescriptor:
        if VideoResolver.is_doodstream(server_url):
            try:
                direct = await self._video_resolver.resolve_doodstream(server_url)
                if direct:
                    return direct
            except Exception as e:
                logger.warning("Fallo resolviendo video directo de %s: %s", server_url, e)
        elif VideoResolver.is_voe(server_url):
            try:
                direct = await self._video_resolver.resolve_voe(server_url)
                if direct:
                    return direct
            except Exception as e:
                logger.warning("Fallo resolviendo Voe %s: %s", server_url, e)
        return PlaybackDescriptor(
            protocol="embed",
            url=server_url,
            headers={"Referer": self._base},
        )

    @staticmethod
    def _is_cloudflare_challenge(resp: httpx.Response | None, html: str | None) -> bool:
        """Detecta si la respuesta indica un desafío Cloudflare."""
        if resp is not None and resp.status_code in (403, 503):
            return True
        if html is None:
            return False
        html_lower = html.lower()
        cf_markers = [
            "just a moment...",
            "cf-browser-verification",
            "<title>attention required! | cloudflare</title>",
            "cf-challenge-running",
            "cloudflare-ray-id",
        ]
        return any(marker in html_lower for marker in cf_markers)

    async def _fetch_with_flare_fallback(self, path: str) -> tuple[str | None, httpx.Response | None]:
        """Intenta obtener contenido con httpx, y si hay challenge Cloudflare usa FlareSolverr como fallback."""
        url = urljoin(self._base, path)
        
        # Primer intento con httpx estándar
        try:
            resp = await self._client.get(path)
            if resp.status_code >= 400:
                # Status code de error (4xx, 5xx) -> no es contenido válido
                logger.warning("HTTP %d en %s", resp.status_code, url)
                return None, resp
            html = resp.text
            if not self._is_cloudflare_challenge(resp, html):
                return html, resp
            logger.info("Cloudflare challenge detectado en %s, intentando FlareSolverr", url)
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            logger.warning("Error HTTP/Timeout en %s: %s", url, e)
            html = None
            resp = None
        
        # Fallback a FlareSolverr
        try:
            solution = self._flaresolverr.get_solution(url)
            if solution and solution.get("response"):
                logger.info("FlareSolverr resolvió challenge para %s", url)
                return solution["response"], None
            elif solution and solution.get("cookies"):
                # Si solo hay cookies, hacer request con ellas
                cookies = solution["cookies"]
                try:
                    resp2 = await self._client.get(path, cookies=cookies)
                    html2 = resp2.text
                    if not self._is_cloudflare_challenge(resp2, html2):
                        return html2, resp2
                except (httpx.TimeoutException, httpx.HTTPError):
                    pass
        except Exception:
            # FlareSolverr no disponible o falló - fallback silencioso
            pass
        
        # Si todo falla, devolver lo que tengamos (puede ser None)
        return html, resp

    async def resolve_playback(self, media_id: str) -> PlaybackDescriptor:
        """Navega a la página del título y extrae URLs de servidores (Doodstream, Voe, Vidhide).
        
        NO asumir que existe un iframe con src en el HTML estático inicial.
        Los servidores se cargan dinámicamente o sus identificadores residen en
        atributos como data-mdl / scripts.
        Integra FlareSolverr como bypass opcional para desafíos Cloudflare."""
        slug = media_id.removeprefix("cuevana3:")
        html = None

        for prefix in ("pelicula", "serie"):
            html, resp = await self._fetch_with_flare_fallback(f"/{prefix}/{slug}/")
            if html is not None:
                break

        if html is None:
            raise ValueError(f"Timeout resolviendo reproducción para {media_id}")

        soup = BeautifulSoup(html, "lxml")

        # 1. Buscar servidores en etiquetas li con data-server (NUEVO: estructura real)
        li = soup.select_one("li[data-server]")
        if li and li.get("data-server"):
            return await self._build_playback_descriptor(li["data-server"])

        # 2. Buscar servidores en la lista ul/li con data-mdl o data-url (PRIORIDAD ALTA)
        server_info = self._extract_server_from_list(soup)
        if server_info:
            return await self._build_playback_descriptor(server_info["url"])

        # 3. Buscar en scripts inline (data-url, onclick, etc.)
        server_url = self._extract_server_from_scripts(soup)
        if server_url:
            return await self._build_playback_descriptor(server_url)

        # 4. Fallback: buscar cualquier enlace a servidor conocido
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if self._is_known_server(href):
                server_url = urljoin(self._base, href) if not href.startswith("http") else href
                return await self._build_playback_descriptor(server_url)

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

    def _extract_available_languages(self, soup) -> list[str]:
        """Recopila todos los idiomas disponibles en los servidores de una película."""
        languages = set()
        for li in soup.select("ul li"):
            lang = self._extract_server_language(li)
            if lang:
                languages.add(lang)
        return sorted(languages)

    @staticmethod
    def _count_episodes(soup) -> int:
        return len(soup.select("a[href*='capitulo-']"))

    # ------------------------------------------------------------------
    # Métodos de extracción enriquecida
    # ------------------------------------------------------------------
    def _extract_director(self, soup) -> Optional[str]:
        """Extrae el director de la página de detalle."""
        for label in ["Director", "director"]:
            el = soup.find(string=re.compile(label, re.I))
            if el:
                parent = el.find_parent(["div", "p", "li", "span"])
                if parent:
                    # Buscar el enlace o texto después del label
                    a = parent.find("a")
                    if a:
                        return a.get_text(strip=True)
                    # O el texto siguiente
                    next_el = el.find_next_sibling(["a", "span"])
                    if next_el:
                        return next_el.get_text(strip=True)
        return None

    def _extract_cast(self, soup) -> list[str]:
        """Extrae el reparto/actores de la página de detalle."""
        cast = []
        for label in ["Reparto", "Actores", "Cast", "Elenco"]:
            el = soup.find(string=re.compile(label, re.I))
            if el:
                parent = el.find_parent(["div", "p", "li", "span"])
                if parent:
                    # Buscar todos los enlaces de actores
                    for a in parent.find_all("a"):
                        name = a.get_text(strip=True)
                        if name and name not in cast:
                            cast.append(name)
                    # Si no hay enlaces, buscar texto separado por comas
                    if not cast:
                        text = parent.get_text()
                        # Remover el label
                        text = re.sub(r'^[^:]*:\s*', '', text)
                        cast = [a.strip() for a in text.split(",") if a.strip()]
                break
        return cast

    def _extract_country(self, soup) -> Optional[str]:
        """Extrae el país de origen."""
        for label in ["País", "Pais", "Country", "Origen"]:
            el = soup.find(string=re.compile(label, re.I))
            if el:
                parent = el.find_parent(["div", "p", "li", "span"])
                if parent:
                    a = parent.find("a")
                    if a:
                        return a.get_text(strip=True)
                    next_el = el.find_next_sibling(["a", "span"])
                    if next_el:
                        return next_el.get_text(strip=True)
        return None

    def _extract_trailer(self, soup) -> Optional[str]:
        """Extrae la URL del tráiler si existe."""
        # Buscar iframe de YouTube
        iframe = soup.find("iframe", src=re.compile(r'youtube\.com|youtu\.be'))
        if iframe:
            return iframe.get("src")
        # Buscar enlace con texto "Tráiler" o "Trailer"
        for a in soup.find_all("a", string=re.compile(r'Trailer|Tráiler', re.I)):
            href = a.get("href")
            if href:
                return href if href.startswith("http") else urljoin(self._base, href)
        return None

    def _extract_rating(self, soup) -> Optional[float]:
        """Extrae la calificación/rating de la página."""
        # Buscar elementos con clase rating, score, imdb
        for cls in ["rating", "score", "imdb", "calificacion", "calificación"]:
            el = soup.find(class_=re.compile(cls, re.I))
            if el:
                # Buscar número decimal
                text = el.get_text()
                match = re.search(r'(\d+\.?\d*)', text)
                if match:
                    val = float(match.group(1))
                    if 0 <= val <= 10:
                        return val
        return None

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
        await self._video_resolver.close()
        await self._client.aclose()