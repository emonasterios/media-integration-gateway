"""Base de datos SQLite dedicada para el inventario de películas por categorías.

Este módulo implementa la capa de persistencia transaccional del inventario:
páginas confirmadas por categoría, películas únicas por
``(provider, provider_id)`` y sus relaciones con categorías. También expone
la consulta de estado fuera de línea (sin llamadas de red).

Reglas de seguridad del rastreo (ver plan del inventario):
- El límite de páginas de cada categoría se fija exclusivamente a partir de
  la paginación numérica anunciada en la primera página
  (``extract_last_page``); nunca a partir de ``a.next``.
- El rastreo recorre estrictamente ``1..last_page`` sin solicitar jamás
  ``last_page + 1``.
- No se abren fichas individuales (``get_details``) ni resolvers de video.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import suppress
from pathlib import Path
from typing import Any

from src.adapters.cuevana3 import (
    Cuevana3Adapter,
    extract_last_page,
    extract_menu_categories,
)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT DEFAULT 'in_progress',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    error TEXT
);

CREATE TABLE IF NOT EXISTS categories (
    slug TEXT PRIMARY KEY,
    name TEXT,
    url TEXT,
    last_page INTEGER DEFAULT 0,
    confirmed_page INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    error TEXT
);

CREATE TABLE IF NOT EXISTS movies (
    provider TEXT,
    provider_id TEXT,
    title TEXT,
    year INTEGER,
    url TEXT,
    poster TEXT,
    PRIMARY KEY (provider, provider_id)
);

CREATE TABLE IF NOT EXISTS movie_categories (
    provider TEXT,
    provider_id TEXT,
    category_slug TEXT,
    PRIMARY KEY (provider, provider_id, category_slug),
    FOREIGN KEY (category_slug) REFERENCES categories(slug)
);
"""


def _coerce_year(value: Any) -> int | None:
    """Convierte ``value`` a ``int`` para la columna ``movies.year``.

    Devuelve ``None`` si el valor no es convertible (p. ej. ``None`` o texto
    no numérico); el año se guarda como entero o NULL.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class CatalogInventoryDB:
    """Capa de acceso a datos SQLite para el inventario de catálogo.

    Tablas:
    - ``runs``: corridas del inventario (estado y último error).
    - ``categories``: categorías ``/genero/<slug>/`` con ``last_page`` (fijado
      exclusivamente por la paginación numérica), ``confirmed_page`` (última
      página persistida) y ``status`` (``pending``/``in_progress``/
      ``complete``/``incomplete``).
    - ``movies``: películas únicas por ``(provider, provider_id)``.
    - ``movie_categories``: relación N:M película-categoría.
    """

    def __init__(self, db_path: str) -> None:
        """Guarda la ruta del archivo SQLite y crea el directorio padre.

        Args:
            db_path: ruta del archivo SQLite (p. ej.
                ``data/cuevana3_inventory.sqlite``). El directorio padre se
                crea si no existe.
        """
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """Abre una conexión nueva con transacciones manuales.

        ``isolation_level=None`` desactiva el BEGIN implícito de sqlite3 para
        poder delimitar explícitamente ``BEGIN IMMEDIATE`` / ``COMMIT`` /
        ``ROLLBACK`` y garantizar la atomicidad por página.
        """
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self) -> None:
        """Crea las tablas del inventario si no existen (idempotente)."""
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA_SQL)
        finally:
            conn.close()

    def save_page_items(
        self, category_slug: str, page_number: int, items: list[dict]
    ) -> None:
        """Persiste de forma atómica los ítems de una página del inventario.

        En una única transacción:
        - Garantiza la fila de la categoría (stub mínimo ``slug`` si aún no
          estaba registrada) para que la FK de ``movie_categories`` se
          cumpla y la actualización posterior siempre aplique.
        - UPSERT en ``movies``: los duplicados por ``(provider, provider_id)``
          no se duplican; se actualizan ``title``, ``year`` y ``poster`` con
          los valores de la página nueva.
        - ``INSERT OR IGNORE`` en ``movie_categories`` (relación
          película-categoría, idempotente).
        - Actualiza ``categories``: ``confirmed_page = page_number`` y
          ``status`` en ``'in_progress'``, o ``'complete'`` cuando
          ``page_number`` alcanza el ``last_page`` fijado en la DB (valor
          que proviene exclusivamente de la paginación numérica).
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO categories (slug) VALUES (?)",
                (category_slug,),
            )
            for item in items or []:
                provider = item.get("provider")
                provider_id = item.get("provider_id")
                if not provider or not provider_id:
                    # Sin clave compuesta no hay fila persistible.
                    continue
                conn.execute(
                    "INSERT INTO movies (provider, provider_id, title, year, url, poster) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(provider, provider_id) DO UPDATE SET "
                    "title=excluded.title, year=excluded.year, poster=excluded.poster",
                    (
                        provider,
                        provider_id,
                        item.get("title"),
                        _coerce_year(item.get("year")),
                        item.get("url"),
                        item.get("poster"),
                    ),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO movie_categories "
                    "(provider, provider_id, category_slug) VALUES (?, ?, ?)",
                    (provider, provider_id, category_slug),
                )
            row = conn.execute(
                "SELECT last_page FROM categories WHERE slug = ?",
                (category_slug,),
            ).fetchone()
            last_page = int(row[0]) if row and row[0] else 0
            status = (
                "complete"
                if last_page > 0 and page_number >= last_page
                else "in_progress"
            )
            conn.execute(
                "UPDATE categories SET confirmed_page = ?, status = ? WHERE slug = ?",
                (page_number, status, category_slug),
            )
            conn.execute("COMMIT")
        except BaseException:
            with suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def get_status(self) -> dict:
        """Consulta el estado del inventario leyendo solo SQLite (sin red).

        Returns:
            dict con:
            - ``run_status``: estado del run actual (``'complete'``,
              ``'incomplete'`` o ``'in_progress'``). Sin run registrado se
              informa ``'in_progress'``; si el run figura en curso pero ya
              hay todas las categorías ``complete``, se informa ``'complete'``.
            - ``current_category``: slug de la categoría ``in_progress``
              (o ``None`` si ninguna está en curso).
            - ``confirmed_page`` / ``last_page``: de la categoría en curso
              (0 si no hay categoría en curso).
            - ``categories_completed`` / ``categories_total``.
            - ``unique_movies_count``: total de filas en ``movies``.
            - ``last_error``: último error registrado en ``runs`` o, si no
              hay, el de la última categoría fallida (``None`` si ninguno).
        """
        conn = self._connect()
        try:
            has_runs = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'runs'"
            ).fetchone()
            if has_runs is None:
                # Esquema inexistente: crearlo para responder sin red.
                conn.executescript(_SCHEMA_SQL)

            run_row = conn.execute(
                "SELECT status, error FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            run_status = (
                run_row[0] if run_row and run_row[0] else "in_progress"
            )
            run_error = run_row[1] if run_row else None

            categories_total = conn.execute(
                "SELECT COUNT(*) FROM categories"
            ).fetchone()[0]
            categories_completed = conn.execute(
                "SELECT COUNT(*) FROM categories WHERE status = 'complete'"
            ).fetchone()[0]
            unique_movies_count = conn.execute(
                "SELECT COUNT(*) FROM movies"
            ).fetchone()[0]

            current = conn.execute(
                "SELECT slug, confirmed_page, last_page FROM categories "
                "WHERE status = 'in_progress' "
                "ORDER BY confirmed_page DESC, slug ASC LIMIT 1"
            ).fetchone()

            failed_category = conn.execute(
                "SELECT error FROM categories "
                "WHERE status = 'incomplete' AND error IS NOT NULL "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()

            if (
                run_status == "in_progress"
                and categories_total > 0
                and categories_completed >= categories_total
            ):
                run_status = "complete"

            last_error = run_error or (
                failed_category[0] if failed_category else None
            )

            return {
                "run_status": run_status,
                "current_category": current[0] if current else None,
                "confirmed_page": current[1] if current else 0,
                "last_page": current[2] if current else 0,
                "categories_completed": categories_completed,
                "categories_total": categories_total,
                "unique_movies_count": unique_movies_count,
                "last_error": last_error,
            }
        finally:
            conn.close()


logger = logging.getLogger(__name__)


class CatalogInventoryService:
    """Servicio de orquestación reanudable del inventario por categorías.

    Coordena el rastreo completo del catálogo de películas por categorías,
    usando la base de datos SQLite como estado persistente y el adaptador
    para las peticiones HTTP y el parseo de listados.

    Reglas de seguridad:
    - El límite de páginas (last_page) se fija exclusivamente desde la
      paginación numérica de la primera página (extract_last_page).
    - El rastreo recorre estrictamente 1..last_page sin solicitar jamás
      last_page + 1 ni seguir a.next.
    - No se abren fichas individuales (get_details) ni resolvers de video.
    - Las series (URL conteniendo /serie/) se excluyen estrictamente.
    """

    def __init__(self) -> None:
        pass

    async def run_inventory(self, db_path: str, adapter: Cuevana3Adapter) -> dict:
        """Ejecuta el inventario completo por categorías de forma reanudable.

        Args:
            db_path: Ruta del archivo SQLite del inventario.
            adapter: Instancia de Cuevana3Adapter para peticiones HTTP y parseo.

        Returns:
            dict con el estado final del inventario (ver get_inventory_status).
        """
        db = CatalogInventoryDB(db_path)
        db.init_db()

        # Verificar si el run ya está completo
        status = db.get_status()
        if status["run_status"] == "complete":
            logger.info("Inventario ya completo; sin peticiones de red")
            return status

        # Crear/actualizar registro de run
        conn = db._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            run_row = conn.execute(
                "SELECT id, status FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if run_row and run_row[1] == "in_progress":
                run_id = run_row[0]
                conn.execute(
                    "UPDATE runs SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (run_id,),
                )
            else:
                conn.execute(
                    "INSERT INTO runs (status, error) VALUES ('in_progress', NULL)"
                )
                run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("COMMIT")
        except BaseException:
            with suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        # Verificar si hay categorías en la base de datos
        conn = db._connect()
        try:
            categories_count = conn.execute(
                "SELECT COUNT(*) FROM categories"
            ).fetchone()[0]
        finally:
            conn.close()

        if categories_count == 0:
            # Descubrir categorías desde /peliculas/
            logger.info("Descubriendo categorías desde /peliculas/...")
            try:
                resp = await adapter._client.get("/peliculas/")
                resp.raise_for_status()
                html = resp.text
            except Exception as exc:
                error_msg = f"Error descargando /peliculas/: {exc}"
                logger.error(error_msg)
                self._record_run_error(db, run_id, error_msg)
                return db.get_status()

            categories = extract_menu_categories(html)
            if not categories:
                error_msg = "No se encontraron categorías en /peliculas/"
                logger.error(error_msg)
                self._record_run_error(db, run_id, error_msg)
                return db.get_status()

            # Registrar categorías en la base de datos
            conn = db._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                for cat in categories:
                    conn.execute(
                        "INSERT OR IGNORE INTO categories (slug, name, url, status) VALUES (?, ?, ?, 'pending')",
                        (cat["slug"], cat["name"], cat["url"]),
                    )
                conn.execute("COMMIT")
            except BaseException:
                with suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
            logger.info("Registradas %d categorías", len(categories))

        # Iterar sobre todas las categorías
        conn = db._connect()
        try:
            all_categories = conn.execute(
                "SELECT slug, name, url, last_page, confirmed_page, status FROM categories ORDER BY slug"
            ).fetchall()
        finally:
            conn.close()

        for cat_slug, cat_name, cat_url, last_page, confirmed_page, cat_status in all_categories:
            # Si la categoría ya está completa, omitirla
            if cat_status == "complete":
                logger.info("Categoría %s ya completa; omitiendo", cat_slug)
                continue

            # Marcar categoría como in_progress
            conn = db._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE categories SET status = 'in_progress', error = NULL WHERE slug = ?",
                    (cat_slug,),
                )
                conn.execute("COMMIT")
            except BaseException:
                with suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

            # Si last_page no está fijado, obtenerlo de la primera página
            if last_page <= 0:
                logger.info("Obteniendo last_page para categoría %s...", cat_slug)
                try:
                    page1_url = f"/genero/{cat_slug}/"
                    resp = await adapter._client.get(page1_url)
                    resp.raise_for_status()
                    html = resp.text
                    last_page = extract_last_page(html)
                except Exception as exc:
                    error_msg = f"Error obteniendo last_page para {cat_slug}: {exc}"
                    logger.error(error_msg)
                    self._mark_category_incomplete(db, cat_slug, error_msg)
                    self._record_run_error(db, run_id, error_msg)
                    return db.get_status()

                if last_page < 1:
                    last_page = 1

                # Guardar last_page en la base de datos
                conn = db._connect()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "UPDATE categories SET last_page = ? WHERE slug = ?",
                        (last_page, cat_slug),
                    )
                    conn.execute("COMMIT")
                except BaseException:
                    with suppress(sqlite3.Error):
                        conn.execute("ROLLBACK")
                    raise
                finally:
                    conn.close()
                logger.info("Categoría %s: last_page = %d", cat_slug, last_page)

            # Determinar página de reanudación
            start_page = confirmed_page + 1
            if start_page > last_page:
                # Ya se completaron todas las páginas
                conn = db._connect()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "UPDATE categories SET status = 'complete' WHERE slug = ?",
                        (cat_slug,),
                    )
                    conn.execute("COMMIT")
                except BaseException:
                    with suppress(sqlite3.Error):
                        conn.execute("ROLLBACK")
                    raise
                finally:
                    conn.close()
                logger.info("Categoría %s ya completa (confirmadas %d/%d)",
                           cat_slug, confirmed_page, last_page)
                continue

            # Recorrer páginas de forma determinista: start_page .. last_page
            for page in range(start_page, last_page + 1):
                page_url = f"/genero/{cat_slug}/page/{page}/" if page > 1 else f"/genero/{cat_slug}/"
                logger.info("Descargando %s página %d/%d", cat_slug, page, last_page)

                try:
                    resp = await adapter._client.get(page_url)
                    resp.raise_for_status()
                    html = resp.text
                except Exception as exc:
                    error_msg = f"Error HTTP en {cat_slug} página {page}: {exc}"
                    logger.error(error_msg)
                    self._mark_category_incomplete(db, cat_slug, error_msg)
                    self._record_run_error(db, run_id, error_msg)
                    return db.get_status()

                # Extraer ítems del listado (solo películas, excluir series)
                items = self._parse_listing_page(html, adapter)

                if not items and page < last_page:
                    # Página vacía antes de last_page: error
                    error_msg = f"Página {page} de {cat_slug} vacía antes de last_page ({last_page})"
                    logger.error(error_msg)
                    self._mark_category_incomplete(db, cat_slug, error_msg)
                    self._record_run_error(db, run_id, error_msg)
                    return db.get_status()

                if items:
                    # Persistir página
                    db.save_page_items(cat_slug, page, items)
                    logger.info("Persistidos %d items en %s página %d",
                               len(items), cat_slug, page)
                else:
                    # Página vacía en la última página: confirmar pero sin items
                    db.save_page_items(cat_slug, page, [])
                    logger.info("Página %d de %s vacía (última página); confirmada",
                               page, cat_slug)

                # Delay entre páginas para no ser baneado
                await asyncio.sleep(1)

            # Todas las páginas 1..last_page confirmadas
            conn = db._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE categories SET status = 'complete' WHERE slug = ?",
                    (cat_slug,),
                )
                conn.execute("COMMIT")
            except BaseException:
                with suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
            logger.info("Categoría %s completada (%d/%d páginas)",
                       cat_slug, last_page, last_page)

        # Verificar si todas las categorías están completas
        final_status = db.get_status()
        if final_status["categories_completed"] >= final_status["categories_total"] and final_status["categories_total"] > 0:
            conn = db._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE runs SET status = 'complete', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (run_id,),
                )
                conn.execute("COMMIT")
            except BaseException:
                with suppress(sqlite3.Error):
                    conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()
            logger.info("Inventario completo: todas las categorías finalizadas")

        return db.get_status()

    def _parse_listing_page(self, html: str, adapter: Cuevana3Adapter) -> list[dict]:
        """Extrae ítems de listado de una página HTML (solo películas).

        Args:
            html: HTML de la página de listado.
            adapter: Instancia del adaptador para usar sus métodos de parseo.

        Returns:
            Lista de dicts con claves: provider, provider_id, url, title, year, poster.
            Excluye entradas con URL conteniendo /serie/.
        """
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        soup = BeautifulSoup(html, "lxml")
        posts = soup.select("div.TPost")
        items: list[dict] = []

        for post in posts:
            link = post.find("a", href=True)
            if not link:
                continue

            href = link["href"]
            # Excluir series estrictamente
            if "/serie/" in href:
                continue

            title_text = link.get_text(strip=True)
            title, year = adapter._parse_title_and_year(title_text)

            year_el = post.select_one("span.Year")
            if year is None and year_el:
                import re
                m = re.search(r"\b(19|20)\d{2}\b", year_el.get_text())
                year = int(m.group(0)) if m else None

            # Normalización de título
            title = adapter._normalize_title_with_year(title_text, year)

            img_el = post.select_one("figure.Objf img") or post.find("img")
            poster_url = None
            if img_el:
                src = img_el.get("src")
                if src and src.startswith("data:"):
                    src = img_el.get("data-src")
                if src and not src.startswith("data:"):
                    poster_url = urljoin(adapter._base, src) if not src.startswith("http") else src

            provider_id = adapter._slug_from_url(href)
            if not provider_id:
                continue

            items.append({
                "provider": adapter.name,
                "provider_id": provider_id,
                "title": title,
                "url": urljoin(adapter._base, href),
                "poster": poster_url,
                "year": year,
            })

        return items

    def _mark_category_incomplete(self, db: CatalogInventoryDB, category_slug: str, error: str) -> None:
        """Marca una categoría como incomplete con error."""
        conn = db._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE categories SET status = 'incomplete', error = ? WHERE slug = ?",
                (error, category_slug),
            )
            conn.execute("COMMIT")
        except BaseException:
            with suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def _record_run_error(self, db: CatalogInventoryDB, run_id: int, error: str) -> None:
        """Registra error en el run y lo marca como incomplete."""
        conn = db._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE runs SET status = 'incomplete', error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (error, run_id),
            )
            conn.execute("COMMIT")
        except BaseException:
            with suppress(sqlite3.Error):
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


def get_inventory_status(db_path: str) -> dict:
    """Consulta el estado del inventario sin realizar peticiones de red.

    Args:
        db_path: Ruta del archivo SQLite del inventario.

    Returns:
        dict con el estado (ver CatalogInventoryDB.get_status).
    """
    return CatalogInventoryDB(db_path).get_status()