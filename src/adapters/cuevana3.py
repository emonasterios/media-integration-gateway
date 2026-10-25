"""Adapter para Cuevana3 (cuevana3i.cc).

Extrae películas y series del sitio mediante scraping HTTP + BeautifulSoup.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from src.services.resolvers.unpacker import unpack_js as unpack

from src.adapters.base import MediaProvider
from src.models.catalog import (
    Episode,
    MediaItem,
    MediaType,
    PlaybackDescriptor,
    Season,
    SearchResult,
)
from src.services.catalog import normalize_catalog_url
from src.services.catalog_checkpoint import (
    CatalogCheckpoint,
    IncompatibleCheckpointError,
    add_items_deduplicated,
    load_checkpoint,
    save_checkpoint,
)
from src.services.flaresolverr import FlareSolverrClient
from src.services.video_resolver import VideoResolver
from src.services.mediaflow_bridge import resolve_with_mediaflow

BASE_URL = "https://cuevana3i.cc"

_FLARE_UNPACK_DOMAINS = {
    "streamwish.to", "streamwish.com", "ajmidyad.sbs",
    "vimeos.net",
    "bysejikuar.com",
    "vidhide.com", "vidhidepro.com",
    "filelions.to", "filelions.com",
    "voe.sx", "voe-unblock.com", "voeunblock.com", "voeunbl0ck.com", "voeunblocker.com",
}

logger = logging.getLogger(__name__)


class CatalogCrawlError(RuntimeError):
    """El catálogo no pudo recorrerse completo y no es un snapshot fiable."""


def _compute_page_fingerprint(provider_ids: Iterable[str]) -> str:
    """Huella estable de una página de catálogo.

    Ordena canónicamente los ``provider_id`` extraídos de los elementos de
    la página y devuelve el digest SHA-256 hex (64 caracteres) de la
    secuencia resultante: dos páginas con las mismas identidades producen
    exactamente la misma huella.
    """
    joined = ",".join(sorted(provider_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _extract_genre_slug(href: str) -> Optional[str]:
    """Extrae el slug del patrón ``/genero/<slug>/`` de un ``href``.

    Normaliza el slug (minúsculas, sin barra al inicio ni al final).
    Devuelve ``None`` si el ``href`` no corresponde al patrón esperado.
    """
    if not href:
        return None
    m = re.search(r"/genero/([^/]+)/?", href)
    if not m:
        return None
    return m.group(1).strip("/").lower()


def extract_menu_categories(
    html: str, base_url: str = BASE_URL
) -> list[dict]:
    """Extrae categorías del menú a partir de enlaces ``/genero/<slug>/``.

    Parsea el HTML localizando enlaces cuyo ``href`` contiene el patrón
    ``/genero/<slug>/``. Normaliza el slug (minúsculas, sin barra al inicio
    ni al final), deduplica por slug conservando el primer nombre visible
    limpio encontrado, y devuelve una lista de diccionarios con las claves
    ``slug``, ``name`` y ``url`` (URL canónica absoluta). Si ``html`` está
    vacío o no contiene enlaces del patrón, devuelve una lista vacía.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    categories: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        slug = _extract_genre_slug(href)
        if slug is None:
            continue
        if slug in seen:
            continue
        seen.add(slug)
        name = a.get_text(" ", strip=True)
        # Colapsar espacios en el nombre visible
        name = " ".join(name.split())
        canonical_url = urljoin(base_url.rstrip("/") + "/", href)
        categories.append({"slug": slug, "name": name, "url": canonical_url})
    return categories


def extract_last_page(html: str) -> int:
    """Determina el límite de paginación numérica a partir del HTML de una página.

    Busca enlaces/anclas de paginación (``a.page-link``, ``.page-numbers``,
    ``a[href*='page/']`` y similares) y extrae todos los números enteros
    anunciados como páginas. Devuelve el valor entero máximo encontrado.

    El límite se fija **exclusivamente** a partir de la paginación numérica
    leída en la primera página: el rastreo debe recorrer estrictamente
    ``1..last_page`` sin solicitar jamás ``last_page + 1``. No se utiliza
    ``a.next`` para determinar el límite, ya que puede conducir a solicitar
    páginas inexistentes (``last_page + 1``) entrando en bucles o fallando
    silenciosamente.

    Si no hay paginación numérica en el HTML, devuelve ``1``.
    """
    if not html:
        return 1
    soup = BeautifulSoup(html, "lxml")

    page_numbers: set[int] = set()

    def _is_next_link(el) -> bool:
        classes = el.get("class", []) or []
        cls_str = " ".join(classes).lower()
        # Etiquetas genéricas de "siguiente"/"next" que NO anuncian un número
        # de página real y deben excluirse del cálculo del límite.
        for token in cls_str.split():
            if token in ("next", "prev", "previous", "first", "last", "nav-next", "nav-prev"):
                return True
        text = el.get_text(" ", strip=True).lower()
        if re.fullmatch(r"\s*(siguiente|next|>\u00bb|»)\s*", text):
            return True
        return False

    # Anclas de paginación numérica: a.page-link, .page-numbers, etc.
    # Se excluyen explícitamente los enlaces "next" (a.next) para que el
    # límite dependa únicamente de la paginación numérica anunciada.
    for selector in (
        "a.page-link",
        ".page-numbers",
        "a[href*='page/']",
        "a[href*='/page/']",
        ".pagination a",
    ):
        for el in soup.select(selector):
            if _is_next_link(el):
                continue
            for token in re.findall(r"\d+", el.get_text(strip=True)):
                page_numbers.add(int(token))

    # 2) href: extrae el segmento numérico de /page/N/ o ?paged=N / ?page=N
    #    ignorando los enlaces de "next" cuyo href lleva a last_page+1.
    for el in soup.find_all("a", href=True):
        if _is_next_link(el):
            continue
        href = el["href"]
        m = re.search(r"[?&](?:paged|page|pg|p)=(\d+)", href)
        if m:
            page_numbers.add(int(m.group(1)))
            continue
        m = re.search(r"/page/(\d+)", href)
        if m:
            page_numbers.add(int(m.group(1)))

    if not page_numbers:
        return 1
    return max(page_numbers)


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

            # Normalización de título: si el texto plano comienza con el
            # mismo año del ítem (ej. "2018Aquaman"), recortar el prefijo;
            # si el prefijo numérico no coincide con el año, no alterarlo.
            title = self._normalize_title_with_year(title_text, year)

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
        seen_provider_ids: set[str] = set()
        visited_pages: set[str] = set()
        page = 1
        initial_url = path
        page_path = path

        page_path = page_path or initial_url
        while page_path:
            absolute_page = urljoin(f"{self._base}/", page_path)
            if absolute_page in visited_pages:
                raise CatalogCrawlError(
                    f"Paginación cíclica detectada en página {page}: {absolute_page}"
                )
            visited_pages.add(absolute_page)

            last_error: httpx.HTTPError | None = None
            for attempt in range(1, 4):
                try:
                    resp = await self._client.get(page_path)
                    resp.raise_for_status()
                    last_error = None
                    break
                except httpx.HTTPError as exc:
                    last_error = exc
                    logger.warning(
                        "Fallo en catálogo página %d (intento %d/3): %s",
                        page,
                        attempt,
                        exc,
                    )
                    if attempt < 3:
                        await asyncio.sleep(attempt * 2)

            if last_error is not None:
                raise CatalogCrawlError(
                    f"Error en página {page} tras 3 intentos; snapshot incompleto: "
                    f"{last_error}"
                ) from last_error

            soup = BeautifulSoup(resp.text, "lxml")
            posts = soup.select("div.TPost")
            if not posts:
                raise CatalogCrawlError(
                    f"Página {page} no contiene elementos; snapshot incompleto"
                )

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

                # Normalización de título: si el texto plano comienza con el
                # mismo año del ítem (ej. "2018Aquaman"), recortar el prefijo;
                # si el prefijo numérico no coincide con el año, no alterarlo.
                title = self._normalize_title_with_year(title_text, year)

                img_el = post.select_one("figure.Objf img") or post.find("img")
                poster_url = None
                if img_el:
                    src = img_el.get("src")
                    if src and src.startswith("data:"):
                        src = img_el.get("data-src")
                    if src and not src.startswith("data:"):
                        poster_url = urljoin(self._base, src) if not src.startswith("http") else src

                provider_id = self._slug_from_url(link["href"])
                if not provider_id or provider_id in seen_provider_ids:
                    continue
                seen_provider_ids.add(provider_id)
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

            next_link = soup.select_one("a.next.page-numbers[href]")
            if next_link is None:
                page_path = None
                continue
            page_path = next_link["href"]
            page += 1
            # Delay entre páginas para no ser baneado
            await asyncio.sleep(1)

        logger.info("Catálogo completo: %d items en %d páginas", len(all_items), page)
        return all_items

    # ------------------------------------------------------------------
    # Catálogo reanudable con checkpoint duradero
    # ------------------------------------------------------------------
    async def discover_resumable(
        self,
        checkpoint_path: Path | str,
        category: Optional[str] = None,
        page_limit: Optional[int] = None,
        on_page: Optional[
            Callable[[list[dict], CatalogCheckpoint], Awaitable[None]]
        ] = None,
    ) -> CatalogCheckpoint:
        """Descubre el catálogo página a página con checkpoint duradero.

        Si ``checkpoint_path`` existe se carga con ``load_checkpoint``: un
        checkpoint ``complete`` se retorna tal cual y uno ``incomplete`` se
        reanuda desde ``next_page`` sin volver a solicitar las páginas ya
        registradas en ``pages_completed``. Si no existe, se inicializa uno
        nuevo en estado ``incomplete``. Tras cada página descargada y
        parseada con éxito se deduplican los elementos en el acumulador, se
        actualizan ``pages_completed`` y ``next_page`` y se persiste el
        checkpoint de forma atómica con ``save_checkpoint``. Un fallo de red
        no recuperable propaga :class:`CatalogCrawlError` dejando íntegro en
        disco el último checkpoint guardado.

        Terminación del rastreo: solo el fin natural (la página actual no
        tiene enlace ``next`` en el HTML) marca ``status="complete"`` con
        ``stop_reason="natural_end"``. Cualquier otra terminación deja
        ``status="incomplete"`` con la causa precisa en ``stop_reason``:
        ``pagination_cycle`` (la URL siguiente normalizada ya fue visitada
        en la corrida actual), ``repeated_page`` (la huella de
        ``provider_id`` ordenados de la página coincide exactamente con la
        página anterior y no hay avance) o ``max_pages`` (se alcanzó el
        fusible ``page_limit``). ``no_new_items`` ya no se emite en corridas
        nuevas; un checkpoint previo que lo traiga se lee sin fallo y la
        causa se descarta al reanudar. Estas paradas artificiales jamás
        habilitan la reconciliación de bajas contra la base de datos.

        Si se provee ``on_page`` (corutina), se espera su resultado tras
        procesar y validar cada página, con los ítems parseados de la página
        y el checkpoint actualizado, justo antes de persistir en disco.
        """
        path = "/peliculas/" if not category else f"/genero/{category}/"
        ckpt_file = Path(checkpoint_path)

        from src.services.catalog_checkpoint import add_items_deduplicated

        checkpoint: CatalogCheckpoint | None = None
        page_path: Optional[str] = None
        visited_pages: set[str] = set()
        seen_fingerprints: set[tuple[str, ...]] = set()
        page = 1
        if ckpt_file.is_file():
            loaded = load_checkpoint(ckpt_file)
            if loaded.provider != self.name or (loaded.category or None) != (
                category or None
            ):
                raise IncompatibleCheckpointError(
                    f"El checkpoint {ckpt_file} pertenece a "
                    f"provider={loaded.provider!r}, category={loaded.category!r}; "
                    f"no coincide con provider={self.name!r}, category={category!r}"
                )
            if loaded.status == "complete":
                logger.info(
                    "Checkpoint ya completo (%d items) en %s; sin rastreo",
                    len(loaded.items),
                    ckpt_file,
                )
                return loaded
            # Reanudación: conservar items y páginas ya confirmadas.
            # Deduplicar items existentes por si el checkpoint previo ya tenía duplicados.
            # Un ``stop_reason`` heredado (p. ej. ``no_new_items``) se lee sin
            # fallo pero se descarta: nunca se reemite en corridas nuevas.
            checkpoint = CatalogCheckpoint(
                version=loaded.version,
                provider=loaded.provider,
                category=loaded.category,
                initial_path=loaded.initial_path,
                next_page=loaded.next_page,
                pages_completed=loaded.pages_completed,
                items=add_items_deduplicated([], loaded.items),
                status=loaded.status,
            )
            page_path = checkpoint.next_page
            if checkpoint.next_page:
                initial_url = checkpoint.next_page
            logger.info(
                "Reanudando descubrimiento en %s desde %r (%d páginas completadas)",
                ckpt_file,
                checkpoint.next_page,
                len(checkpoint.pages_completed),
            )
        else:
            checkpoint = CatalogCheckpoint(
                provider=self.name,
                category=category,
                initial_path=path,
                next_page=path,
                pages_completed=[],
                items=[],
                status="incomplete",
            )
            page_path = checkpoint.next_page

        page = (max(checkpoint.pages_completed) + 1) if checkpoint.pages_completed else 1

        while page_path:
            if page_limit is not None and len(checkpoint.pages_completed) >= page_limit:
                logger.info(
                    "Fusible de %d páginas alcanzado; el checkpoint queda "
                    "incomplete con stop_reason=max_pages para reanudar más tarde",
                    page_limit,
                )
                checkpoint.status = "incomplete"
                checkpoint.stop_reason = "max_pages"
                save_checkpoint(checkpoint, ckpt_file)
                break

            normalized_page = normalize_catalog_url(urljoin(f"{self._base}/", page_path))
            if normalized_page is not None and normalized_page in visited_pages:
                checkpoint.status = "incomplete"
                checkpoint.stop_reason = "pagination_cycle"
                save_checkpoint(checkpoint, ckpt_file)
                break
            if normalized_page is not None:
                visited_pages.add(normalized_page)

            last_error: httpx.HTTPError | None = None
            resp: httpx.Response | None = None
            for attempt in range(1, 4):
                try:
                    resp = await self._client.get(page_path)
                    resp.raise_for_status()
                    last_error = None
                    break
                except httpx.HTTPError as exc:
                    last_error = exc
                    logger.warning(
                        "Fallo en catálogo página %d (intento %d/3): %s",
                        page,
                        attempt,
                        exc,
                    )
                    if attempt < 3:
                        await asyncio.sleep(attempt * 2)

            if last_error is not None or resp is None:
                raise CatalogCrawlError(
                    f"Error en página {page} tras 3 intentos; el checkpoint en "
                    f"{ckpt_file} conserva el progreso previo: {last_error}"
                ) from last_error

            soup = BeautifulSoup(resp.text, "lxml")
            posts = soup.select("div.TPost")
            if not posts:
                raise CatalogCrawlError(
                    f"Página {page} no contiene elementos; el checkpoint en "
                    f"{ckpt_file} conserva el progreso previo"
                )

            new_items: list[dict] = []
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

                # Normalización de título: si el texto plano comienza con el
                # mismo año del ítem (ej. "2018Aquaman"), recortar el prefijo;
                # si el prefijo numérico no coincide con el año, no alterarlo.
                title = self._normalize_title_with_year(title_text, year)

                img_el = post.select_one("figure.Objf img") or post.find("img")
                poster_url = None
                if img_el:
                    src = img_el.get("src")
                    if src and src.startswith("data:"):
                        src = img_el.get("data-src")
                    if src and not src.startswith("data:"):
                        poster_url = urljoin(self._base, src) if not src.startswith("http") else src

                provider_id = self._slug_from_url(link["href"])
                if not provider_id:
                    continue
                media_type = MediaType.SERIES if "/serie/" in link["href"] else MediaType.MOVIE

                new_items.append(
                    {
                        "provider": self.name,
                        "provider_id": provider_id,
                        "title": title,
                        "url": urljoin(self._base, link["href"]),
                        "poster": poster_url,
                        "media_type": media_type.value,
                        "year": year,
                        "category": checkpoint.category,
                    }
                )

            # Huella determinista de la página: provider_id extraídos,
            # ordenados canónicamente y resumidos en un digest estable.
            page_fingerprint = tuple(sorted(item["provider_id"] for item in new_items))

            total_previo = len(checkpoint.items)
            checkpoint.items = add_items_deduplicated(checkpoint.items, new_items)
            nuevos_en_pagina = len(checkpoint.items) - total_previo
            checkpoint.pages_completed.append(page)

            next_link = soup.select_one("a.next.page-numbers[href]")
            next_href = next_link["href"] if next_link else None
            stop_reason: Optional[str] = None
            if not next_href:
                checkpoint.next_page = None
                checkpoint.status = "complete"
                checkpoint.stop_reason = "natural_end"
            else:
                checkpoint.next_page = next_href
                checkpoint.status = "incomplete"
                normalized_next = normalize_catalog_url(
                    urljoin(f"{self._base}/", next_href)
                )
                if normalized_next is not None and normalized_next in visited_pages:
                    checkpoint.stop_reason = "pagination_cycle"
                    stop_reason = "pagination_cycle"
                elif page_fingerprint in seen_fingerprints and nuevos_en_pagina == 0:
                    checkpoint.stop_reason = "repeated_page"
                    stop_reason = "repeated_page"
                else:
                    checkpoint.stop_reason = None
            seen_fingerprints.add(page_fingerprint)

            if on_page is not None:
                await on_page(new_items, checkpoint)

            save_checkpoint(checkpoint, ckpt_file)
            if stop_reason is not None:
                logger.warning(
                    "Página %d: parada artificial (%s); checkpoint incomplete "
                    "guardado en %s con %d items",
                    page,
                    stop_reason,
                    ckpt_file,
                    len(checkpoint.items),
                )
            else:
                logger.info(
                    "Página %d: %d items (%d nuevos; total acumulado: %d); "
                    "checkpoint guardado en %s",
                    page,
                    len(posts),
                    nuevos_en_pagina,
                    len(checkpoint.items),
                    ckpt_file,
                )

            if stop_reason is not None:
                break

            if checkpoint.next_page is None:
                page_path = None
                continue
            page_path = checkpoint.next_page
            page += 1
            # Delay entre páginas para no ser baneado
            await asyncio.sleep(1)


        if checkpoint.status == "complete":
            logger.info(
                "Descubrimiento completo: %d items en %d páginas",
                len(checkpoint.items),
                len(checkpoint.pages_completed),
            )
        else:
            logger.info(
                "Descubrimiento pausado: %d items en %d páginas; próxima página: %s",
                len(checkpoint.items),
                len(checkpoint.pages_completed),
                checkpoint.next_page,
            )
        return checkpoint

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
    async def _build_playback_descriptor(self, server_url: str) -> Optional[PlaybackDescriptor]:
        # Intentar primero con mediaflow-proxy extractors (FileLions, StreamWish, DoodStream, Voe, etc.)
        from urllib.parse import urlparse
        parsed = urlparse(server_url)
        domain = parsed.hostname or ""
        # Normalizar: quitar subdominios para matching
        parts = domain.split(".")
        if len(parts) > 2:
            base_domain = ".".join(parts[-2:])
        else:
            base_domain = domain

        # Intentar con mediaflow_bridge usando el dominio completo y el base
        for candidate in [domain, base_domain]:
            try:
                mf_result = await resolve_with_mediaflow(server_url, candidate)
                if mf_result:
                    return mf_result
            except Exception as e:
                logger.debug("mediaflow_bridge falló para %s: %s", candidate, e)

        if domain in _FLARE_UNPACK_DOMAINS or base_domain in _FLARE_UNPACK_DOMAINS:
            try:
                flaresolverr = FlareSolverrClient()
                solution = await asyncio.to_thread(
                    flaresolverr.get_solution,
                    server_url,
                    max_timeout=60000,
                )
                if solution and solution.get("response"):
                    html = solution["response"]
                    m3u8_url = self._unpack_eval_and_extract_m3u8(html)
                    if m3u8_url and await self._check_cdn_alive(m3u8_url):
                        return PlaybackDescriptor(protocol="hls", url=m3u8_url, headers={})
            except Exception as e:
                logger.debug("FlareSolverr+unpack falló para %s: %s", server_url, e)

        # Fallback a resolvers custom
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
        elif VideoResolver.is_streamtape(server_url):
            try:
                direct = await self._video_resolver.resolve_streamtape(server_url)
                if direct:
                    return direct
            except Exception as e:
                logger.warning("Fallo resolviendo Streamtape %s: %s", server_url, e)
        elif VideoResolver.is_morencius(server_url):
            try:
                direct = await self._video_resolver.resolve_morencius(server_url)
                if direct:
                    return direct
            except Exception as e:
                logger.warning("Fallo resolviendo Morencius %s: %s", server_url, e)
        # No devolver embed — si ningún resolver funciona, retornar None
        logger.warning("Ningún resolver pudo obtener video directo de %s", server_url[:80])
        return None

    @staticmethod
    def _unpack_eval_and_extract_m3u8(html: str) -> Optional[str]:
        import re
        from src.services.resolvers.unpacker import unpack_js

        # Find all script tags that might contain packed JS
        script_pattern = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL)
        scripts = script_pattern.findall(html)

        # Also check the full HTML for packed JS
        sources = [html] + scripts

        for source in sources:
            # Try the new unpack_js which handles the actual Dean Edwards format
            try:
                unpacked = unpack_js(source)
                if unpacked and unpacked != source:
                    # Look for m3u8 URLs in unpacked result
                    matches = re.findall(r"https?://[^\s\"'<>]+\.m3u8[^\s\"'<>]*", unpacked)
                    for url in matches:
                        if "master" in url or "playlist" in url or url.endswith(".m3u8"):
                            return url
                    if matches:
                        return matches[0]
            except Exception:
                continue

        return None

    @staticmethod
    async def _check_cdn_alive(m3u8_url: str) -> bool:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=headers) as client:
                resp = await client.head(m3u8_url)
                return resp.status_code in (200, 206)
        except Exception:
            return False

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
            # Un error de transporte no demuestra un challenge de Cloudflare.
            # El llamador debe poder probar la siguiente ruta o reportar timeout.
            return None, None
        
        # Fallback a FlareSolverr
        try:
            solution = await asyncio.to_thread(self._flaresolverr.get_solution, url)
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
        """Navega a la página del título, extrae TODOS los servidores y prueba cada uno
        hasta encontrar uno que sirva video real. Si ninguno funciona, lanza ValueError."""
        slug = media_id.removeprefix("cuevana3:")
        html = None

        for prefix in ("pelicula", "serie"):
            html, resp = await self._fetch_with_flare_fallback(f"/{prefix}/{slug}/")
            if html is not None:
                break

        if html is None:
            raise ValueError(f"Timeout resolviendo reproducción para {media_id}")

        soup = BeautifulSoup(html, "lxml")

        # Recopilar TODOS los servidores candidatos
        candidates = []

        # 1. Servidores en li[data-server]
        for li in soup.select("li[data-server]"):
            if li.get("data-server"):
                candidates.append(li["data-server"])

        # 2. Servidores en lista ul/li con data-mdl o data-url
        server_info = self._extract_server_from_list(soup)
        if server_info:
            candidates.append(server_info["url"])

        # 3. Servidores en scripts inline
        server_url = self._extract_server_from_scripts(soup)
        if server_url:
            candidates.append(server_url)

        # 4. Cualquier enlace a servidor conocido
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if self._is_known_server(href):
                full = urljoin(self._base, href) if not href.startswith("http") else href
                candidates.append(full)

        # Eliminar duplicados manteniendo orden
        seen = set()
        unique = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                unique.append(c)

        if not unique:
            raise ValueError(f"No se encontró fuente de reproducción para {media_id}")

        logger.info("resolve_playback: %d candidatos para %s", len(unique), media_id)

        # Probar cada candidato hasta encontrar uno válido
        for i, server_url in enumerate(unique):
            logger.info("Probando servidor %d/%d: %s", i+1, len(unique), server_url[:80])
            try:
                descriptor = await self._build_playback_descriptor(server_url)
                if descriptor:
                    logger.info("Servidor %d válido: %s", i+1, descriptor.url[:80])
                    return descriptor
                else:
                    logger.info("Servidor %d rechazado (None)", i+1)
            except Exception as e:
                logger.info("Servidor %d falló: %s", i+1, e)

        raise ValueError(f"Ningún servidor funcionó para {media_id} ({len(unique)} candidatos)")

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
    def _normalize_title_with_year(title_text: str, year: Optional[int]) -> str:
        """Recorta el prefijo de año pegado al título solo si coincide con ``year``.

        Cuevana a veces renderiza el año pegado al título sin separador
        (ej. ``"2018Aquaman"``). Si el título comienza con el año del ítem
        se recorta el prefijo (``"2018Aquaman"`` -> ``"Aquaman"``); si el
        prefijo numérico no coincide con ``year``, el título no se altera.
        """
        if year is None:
            return title_text
        match = re.match(rf"^{year}\s*(.+)$", title_text)
        if match:
            return match.group(1).strip()
        return title_text

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
