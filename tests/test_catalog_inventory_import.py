"""Pruebas unitarias e integración para import_inventory_to_catalog.

Valida la importación transaccional e idempotente del inventario de películas
(corregido por categorías, recorrido 1) al catálogo operativo (media + sources).

Todas las pruebas usan SQLite temporal en ``tmp_path``; nunca tocan red ni
``/home/emon/media-integration-gateway/media_gateway.db``.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.services.catalog_inventory import import_inventory_to_catalog


# ---------------------------------------------------------------------------
# Fixtures y helpers
# ---------------------------------------------------------------------------


def _create_inventory_db(db_path: Path) -> sqlite3.Connection:
    """Crea esquema del inventario (runs, categories, movies, movie_categories)."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT DEFAULT 'in_progress',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            error TEXT
        );
        CREATE TABLE categories (
            slug TEXT PRIMARY KEY,
            name TEXT,
            url TEXT,
            last_page INTEGER DEFAULT 0,
            confirmed_page INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            error TEXT
        );
        CREATE TABLE movies (
            provider TEXT,
            provider_id TEXT,
            title TEXT,
            year INTEGER,
            url TEXT,
            poster TEXT,
            PRIMARY KEY (provider, provider_id)
        );
        CREATE TABLE movie_categories (
            provider TEXT,
            provider_id TEXT,
            category_slug TEXT,
            PRIMARY KEY (provider, provider_id, category_slug),
            FOREIGN KEY (category_slug) REFERENCES categories(slug)
        );
    """)
    conn.commit()
    return conn


def _create_catalog_db(db_path: Path) -> sqlite3.Connection:
    """Crea esquema del catálogo operativo (media, sources) según models.py."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            original_title TEXT,
            media_type TEXT NOT NULL,
            year INTEGER,
            synopsis TEXT,
            poster_url TEXT,
            genres TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id INTEGER NOT NULL REFERENCES media(id),
            provider TEXT NOT NULL,
            url TEXT NOT NULL,
            page_url TEXT,
            quality TEXT,
            language TEXT,
            catalog_presence TEXT(16) NOT NULL DEFAULT 'present',
            last_seen_at TIMESTAMP,
            last_seen_run_id TEXT(36),
            missing_since TIMESTAMP,
            consecutive_misses INTEGER NOT NULL DEFAULT 0,
            UNIQUE(provider, url)
        );
    """)
    conn.commit()
    return conn


def _make_complete_inventory(inv_conn: sqlite3.Connection) -> None:
    """Puebla el inventario con un run completo y categorías completas."""
    inv_conn.execute("BEGIN IMMEDIATE")
    inv_conn.execute(
        "INSERT INTO runs (status, error) VALUES ('complete', NULL)"
    )
    # Categorías completas
    inv_conn.execute(
        "INSERT INTO categories (slug, name, url, last_page, confirmed_page, status) "
        "VALUES (?, ?, ?, ?, ?, 'complete')",
        ("accion", "Acción", "https://cuevana3i.cc/genero/accion/", 1, 1),
    )
    inv_conn.execute(
        "INSERT INTO categories (slug, name, url, last_page, confirmed_page, status) "
        "VALUES (?, ?, ?, ?, ?, 'complete')",
        ("aventura", "Aventura", "https://cuevana3i.cc/genero/aventura/", 1, 1),
    )
    inv_conn.execute(
        "INSERT INTO categories (slug, name, url, last_page, confirmed_page, status) "
        "VALUES (?, ?, ?, ?, ?, 'complete')",
        ("terror", "Terror", "https://cuevana3i.cc/genero/terror/", 1, 1),
    )
    inv_conn.commit()


@pytest.fixture
def inventory_db(tmp_path: Path) -> Path:
    """Ruta a un archivo SQLite temporal con esquema de inventario."""
    db_path = tmp_path / "inventory_test.sqlite"
    _create_inventory_db(db_path)
    return db_path


@pytest.fixture
def catalog_db(tmp_path: Path) -> Path:
    """Ruta a un archivo SQLite temporal con esquema de catálogo operativo."""
    db_path = tmp_path / "catalog_test.sqlite"
    _create_catalog_db(db_path)
    return db_path


@pytest.fixture
def complete_inventory_db(inventory_db: Path) -> Path:
    """Inventario con run 'complete' y categorías 'complete' + páginas confirmadas."""
    conn = sqlite3.connect(inventory_db)
    _make_complete_inventory(conn)
    conn.close()
    return inventory_db


# ---------------------------------------------------------------------------
# 1. test_reject_incomplete_run
# ---------------------------------------------------------------------------


def test_reject_incomplete_run(complete_inventory_db: Path, catalog_db: Path) -> None:
    """Debe fallar con ValueError si la última corrida en runs no tiene status='complete'."""
    conn = sqlite3.connect(complete_inventory_db)
    conn.execute("BEGIN IMMEDIATE")
    # Cambiar el run a 'in_progress'
    conn.execute("UPDATE runs SET status = 'in_progress'")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="El inventario no tiene una corrida completada"):
        import_inventory_to_catalog(
            inventory_db_path=str(complete_inventory_db),
            catalog_db_path=str(catalog_db),
        )


# ---------------------------------------------------------------------------
# 2. test_reject_category_incomplete_or_page_mismatch
# ---------------------------------------------------------------------------


def test_reject_category_incomplete_status(complete_inventory_db: Path, catalog_db: Path) -> None:
    """Debe fallar si una categoría tiene status != 'complete'."""
    conn = sqlite3.connect(complete_inventory_db)
    conn.execute("BEGIN IMMEDIATE")
    # Cambiar una categoría a 'incomplete'
    conn.execute("UPDATE categories SET status = 'incomplete' WHERE slug = 'accion'")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="Hay categorías incompletas o con discrepancia de páginas"):
        import_inventory_to_catalog(
            inventory_db_path=str(complete_inventory_db),
            catalog_db_path=str(catalog_db),
        )


def test_reject_category_page_mismatch(complete_inventory_db: Path, catalog_db: Path) -> None:
    """Debe fallar si confirmed_page != last_page aunque status sea 'complete'."""
    conn = sqlite3.connect(complete_inventory_db)
    conn.execute("BEGIN IMMEDIATE")
    # status='complete' pero confirmed_page (0) != last_page (1)
    conn.execute("UPDATE categories SET confirmed_page = 0 WHERE slug = 'accion'")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="Hay categorías incompletas o con discrepancia de páginas"):
        import_inventory_to_catalog(
            inventory_db_path=str(complete_inventory_db),
            catalog_db_path=str(catalog_db),
        )


# ---------------------------------------------------------------------------
# 3. test_import_movies_canonical_url_and_visible_genres
# ---------------------------------------------------------------------------


def test_import_movies_canonical_url_and_visible_genres(
    complete_inventory_db: Path, catalog_db: Path
) -> None:
    """Importa una película y verifica campos canónicos en sources y genres visible en media."""
    conn = sqlite3.connect(complete_inventory_db)
    conn.execute("BEGIN IMMEDIATE")
    # Insertar película
    conn.execute(
        "INSERT INTO movies (provider, provider_id, title, year, url, poster) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cuevana3", "matrix-1999", "The Matrix", 1999, "https://cuevana3i.cc/pelicula/matrix-1999/", "https://img/poster.jpg"),
    )
    # Asociar a categoría 'accion' (nombre visible "Acción")
    conn.execute(
        "INSERT INTO movie_categories (provider, provider_id, category_slug) VALUES (?, ?, ?)",
        ("cuevana3", "matrix-1999", "accion"),
    )
    conn.commit()
    conn.close()

    summary = import_inventory_to_catalog(
        inventory_db_path=str(complete_inventory_db),
        catalog_db_path=str(catalog_db),
    )

    assert summary["inserted"] == 1
    assert summary["updated"] == 0
    assert summary["unchanged"] == 0
    assert summary["inventory_read"] == 1
    assert summary["category_relations_read"] == 1

    # Verificar en catálogo destino
    cat_conn = sqlite3.connect(catalog_db)
    cat_conn.row_factory = sqlite3.Row
    try:
        media_row = cat_conn.execute("SELECT * FROM media").fetchone()
        assert media_row is not None
        assert media_row["title"] == "The Matrix"
        assert media_row["year"] == 1999
        assert media_row["poster_url"] == "https://img/poster.jpg"
        assert media_row["media_type"] == "movie"

        # genres debe ser JSON con nombre visible "Acción" (no slug "accion")
        genres = json.loads(media_row["genres"])
        assert genres == ["Acción"], f"genres={genres}"

        source_row = cat_conn.execute("SELECT * FROM sources").fetchone()
        assert source_row is not None
        # sources.url == provider_id
        assert source_row["url"] == "matrix-1999"
        # sources.page_url == URL canónica de la película
        assert source_row["page_url"] == "https://cuevana3i.cc/pelicula/matrix-1999/"
        # catalog_presence == 'present'
        assert source_row["catalog_presence"] == "present"
        # consecutive_misses == 0
        assert source_row["consecutive_misses"] == 0
        # missing_since is None
        assert source_row["missing_since"] is None
        # last_seen_at no nulo
        assert source_row["last_seen_at"] is not None
    finally:
        cat_conn.close()


# ---------------------------------------------------------------------------
# 4. test_movie_in_multiple_categories_deduplicated
# ---------------------------------------------------------------------------


def test_movie_in_multiple_categories_deduplicated(
    complete_inventory_db: Path, catalog_db: Path
) -> None:
    """Película en 3 categorías genera 1 fila en media, 1 en sources, genres con 3 nombres ordenados."""
    conn = sqlite3.connect(complete_inventory_db)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO movies (provider, provider_id, title, year, url, poster) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cuevana3", "multi-cat-movie", "Multi Category Movie", 2020, "https://cuevana3i.cc/pelicula/multi-cat-movie/", "https://img/poster.jpg"),
    )
    # Asociar a 3 categorías
    conn.execute(
        "INSERT INTO movie_categories (provider, provider_id, category_slug) VALUES (?, ?, ?)",
        ("cuevana3", "multi-cat-movie", "accion"),
    )
    conn.execute(
        "INSERT INTO movie_categories (provider, provider_id, category_slug) VALUES (?, ?, ?)",
        ("cuevana3", "multi-cat-movie", "aventura"),
    )
    conn.execute(
        "INSERT INTO movie_categories (provider, provider_id, category_slug) VALUES (?, ?, ?)",
        ("cuevana3", "multi-cat-movie", "terror"),
    )
    conn.commit()
    conn.close()

    summary = import_inventory_to_catalog(
        inventory_db_path=str(complete_inventory_db),
        catalog_db_path=str(catalog_db),
    )

    assert summary["inserted"] == 1
    assert summary["inventory_read"] == 1
    assert summary["category_relations_read"] == 3

    cat_conn = sqlite3.connect(catalog_db)
    cat_conn.row_factory = sqlite3.Row
    try:
        media_count = cat_conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
        assert media_count == 1, f"media count={media_count}"

        sources_count = cat_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        assert sources_count == 1, f"sources count={sources_count}"

        media_row = cat_conn.execute("SELECT genres FROM media").fetchone()
        genres = json.loads(media_row["genres"])
        # Nombres visibles ordenados alfabéticamente
        assert genres == ["Acción", "Aventura", "Terror"], f"genres={genres}"
    finally:
        cat_conn.close()


# ---------------------------------------------------------------------------
# 5. test_preserves_unrelated_existing_rows
# ---------------------------------------------------------------------------


def test_preserves_unrelated_existing_rows(
    complete_inventory_db: Path, catalog_db: Path
) -> None:
    """Filas previas de otro proveedor u otra película no se modifican ni eliminan."""
    # Poblar catálogo destino con datos previos
    cat_conn = sqlite3.connect(catalog_db)
    cat_conn.execute("BEGIN IMMEDIATE")
    # Película de otro proveedor
    cat_conn.execute(
        "INSERT INTO media (title, year, media_type, poster_url, genres, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Other Provider Movie", 2021, "movie", "https://img/other.jpg", '["Drama"]', "2024-01-01", "2024-01-01"),
    )
    other_media_id = cat_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    cat_conn.execute(
        "INSERT INTO sources (media_id, provider, url, page_url, catalog_presence, last_seen_at, missing_since, consecutive_misses) "
        "VALUES (?, ?, ?, ?, 'present', ?, NULL, 0)",
        (other_media_id, "otherprovider", "other-id", "https://other.com/movie/", "2024-01-01"),
    )
    # Película del mismo proveedor pero distinta (no en inventario)
    cat_conn.execute(
        "INSERT INTO media (title, year, media_type, poster_url, genres, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("Existing Cuevana3 Movie", 2019, "movie", "https://img/exist.jpg", '["Comedia"]', "2024-01-01", "2024-01-01"),
    )
    exist_media_id = cat_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    cat_conn.execute(
        "INSERT INTO sources (media_id, provider, url, page_url, catalog_presence, last_seen_at, missing_since, consecutive_misses) "
        "VALUES (?, ?, ?, ?, 'present', ?, NULL, 0)",
        (exist_media_id, "cuevana3", "existing-id", "https://cuevana3i.cc/pelicula/existing-id/", "2024-01-01"),
    )
    cat_conn.commit()
    cat_conn.close()

    # Inventario con UNA película nueva
    inv_conn = sqlite3.connect(complete_inventory_db)
    inv_conn.execute("BEGIN IMMEDIATE")
    inv_conn.execute(
        "INSERT INTO movies (provider, provider_id, title, year, url, poster) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cuevana3", "new-movie", "New Movie", 2023, "https://cuevana3i.cc/pelicula/new-movie/", "https://img/new.jpg"),
    )
    inv_conn.execute(
        "INSERT INTO movie_categories (provider, provider_id, category_slug) VALUES (?, ?, ?)",
        ("cuevana3", "new-movie", "accion"),
    )
    inv_conn.commit()
    inv_conn.close()

    summary = import_inventory_to_catalog(
        inventory_db_path=str(complete_inventory_db),
        catalog_db_path=str(catalog_db),
    )

    assert summary["inserted"] == 1
    assert summary["updated"] == 0
    assert summary["unchanged"] == 0

    # Verificar que filas previas siguen intactas
    cat_conn = sqlite3.connect(catalog_db)
    cat_conn.row_factory = sqlite3.Row
    try:
        # Contar totales
        media_count = cat_conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
        sources_count = cat_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        assert media_count == 3  # 2 previas + 1 nueva
        assert sources_count == 3

        # Verificar película otro proveedor intacta
        other_source = cat_conn.execute(
            "SELECT * FROM sources WHERE provider = 'otherprovider'"
        ).fetchone()
        assert other_source is not None
        assert other_source["url"] == "other-id"
        assert other_source["catalog_presence"] == "present"

        # Verificar película existente cuevana3 intacta
        exist_source = cat_conn.execute(
            "SELECT * FROM sources WHERE provider = 'cuevana3' AND url = 'existing-id'"
        ).fetchone()
        assert exist_source is not None
        assert exist_source["catalog_presence"] == "present"

        # Verificar nueva película
        new_source = cat_conn.execute(
            "SELECT * FROM sources WHERE provider = 'cuevana3' AND url = 'new-movie'"
        ).fetchone()
        assert new_source is not None
        assert new_source["catalog_presence"] == "present"
    finally:
        cat_conn.close()


# ---------------------------------------------------------------------------
# 6. test_update_existing_source_idempotent
# ---------------------------------------------------------------------------


def test_update_existing_source_idempotent(
    complete_inventory_db: Path, catalog_db: Path
) -> None:
    """Segunda ejecución produce 0 inserciones y conteos idénticos."""
    inv_conn = sqlite3.connect(complete_inventory_db)
    inv_conn.execute("BEGIN IMMEDIATE")
    inv_conn.execute(
        "INSERT INTO movies (provider, provider_id, title, year, url, poster) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cuevana3", "idempotent-movie", "Idempotent Movie", 2022, "https://cuevana3i.cc/pelicula/idempotent-movie/", "https://img/ide.jpg"),
    )
    inv_conn.execute(
        "INSERT INTO movie_categories (provider, provider_id, category_slug) VALUES (?, ?, ?)",
        ("cuevana3", "idempotent-movie", "accion"),
    )
    inv_conn.commit()
    inv_conn.close()

    # Primera importación
    summary1 = import_inventory_to_catalog(
        inventory_db_path=str(complete_inventory_db),
        catalog_db_path=str(catalog_db),
    )
    assert summary1["inserted"] == 1
    assert summary1["updated"] == 0
    assert summary1["unchanged"] == 0

    # Segunda importación (idempotente)
    summary2 = import_inventory_to_catalog(
        inventory_db_path=str(complete_inventory_db),
        catalog_db_path=str(catalog_db),
    )
    assert summary2["inserted"] == 0, f"Segunda corrida insertó {summary2['inserted']}"
    assert summary2["updated"] == 0
    assert summary2["unchanged"] == 1

    # Verificar conteos en BD destino
    cat_conn = sqlite3.connect(catalog_db)
    media_count = cat_conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    sources_count = cat_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    cat_conn.close()

    assert media_count == 1
    assert sources_count == 1


# ---------------------------------------------------------------------------
# 7. test_dry_run_leaves_destination_unmodified
# ---------------------------------------------------------------------------


def test_dry_run_leaves_destination_unmodified(
    complete_inventory_db: Path, catalog_db: Path
) -> None:
    """Con dry_run=True reporta resumen pero BD destino queda idéntica (cero filas persistidas)."""
    inv_conn = sqlite3.connect(complete_inventory_db)
    inv_conn.execute("BEGIN IMMEDIATE")
    inv_conn.execute(
        "INSERT INTO movies (provider, provider_id, title, year, url, poster) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cuevana3", "dryrun-movie", "Dry Run Movie", 2024, "https://cuevana3i.cc/pelicula/dryrun-movie/", "https://img/dry.jpg"),
    )
    inv_conn.execute(
        "INSERT INTO movie_categories (provider, provider_id, category_slug) VALUES (?, ?, ?)",
        ("cuevana3", "dryrun-movie", "accion"),
    )
    inv_conn.commit()
    inv_conn.close()

    # Ejecutar con dry_run=True
    summary = import_inventory_to_catalog(
        inventory_db_path=str(complete_inventory_db),
        catalog_db_path=str(catalog_db),
        dry_run=True,
    )

    assert summary["status"] == "dry-run/rolled-back"
    assert summary["inserted"] == 1  # Reporta lo que *habría* hecho
    assert summary["updated"] == 0
    assert summary["unchanged"] == 0

    # Verificar BD destino vacía
    cat_conn = sqlite3.connect(catalog_db)
    media_count = cat_conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    sources_count = cat_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    cat_conn.close()

    assert media_count == 0, f"media count={media_count} (debería ser 0 en dry-run)"
    assert sources_count == 0, f"sources count={sources_count} (debería ser 0 en dry-run)"


# ---------------------------------------------------------------------------
# 8. test_error_during_import_rolls_back_completely
# ---------------------------------------------------------------------------


class FailingConnection:
    """Wrapper de sqlite3.Connection que falla en la N-ésima llamada a execute."""

    def __init__(self, real_conn: sqlite3.Connection, fail_on_n: int, fail_pattern: str):
        self._conn = real_conn
        self._fail_on_n = fail_on_n
        self._fail_pattern = fail_pattern
        self._call_count = 0

    def execute(self, sql, params=None):
        if self._fail_pattern in sql:
            self._call_count += 1
            if self._call_count == self._fail_on_n:
                raise sqlite3.OperationalError("Simulated failure mid-import")
        if params is None:
            return self._conn.execute(sql)
        return self._conn.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_error_during_import_rolls_back_completely(
    complete_inventory_db: Path, catalog_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simula un fallo a mitad de inserción y verifica rollback completo (cero filas parciales)."""
    inv_conn = sqlite3.connect(complete_inventory_db)
    inv_conn.execute("BEGIN IMMEDIATE")
    # Insertar 3 películas
    for i in range(3):
        provider_id = f"rollback-movie-{i}"
        inv_conn.execute(
            "INSERT INTO movies (provider, provider_id, title, year, url, poster) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("cuevana3", provider_id, f"Rollback Movie {i}", 2020 + i, f"https://cuevana3i.cc/pelicula/{provider_id}/", f"https://img/{i}.jpg"),
        )
        inv_conn.execute(
            "INSERT INTO movie_categories (provider, provider_id, category_slug) VALUES (?, ?, ?)",
            ("cuevana3", provider_id, "accion"),
        )
    inv_conn.commit()
    inv_conn.close()

    # Monkeypatch para fallar en la 2da inserción dentro de import_inventory_to_catalog
    original_connect = sqlite3.connect

    def failing_connect(*args, **kwargs):
        real_conn = original_connect(*args, **kwargs)
        # La importación abre dos conexiones: una al inventario (ro) y otra al catálogo (rw)
        # Solo envolvemos la conexión al catálogo (la que NO tiene mode=ro)
        uri = args[0] if args else kwargs.get('database', '')
        if 'mode=ro' in str(uri):
            return real_conn
        return FailingConnection(real_conn, fail_on_n=2, fail_pattern="INSERT INTO media")

    monkeypatch.setattr(sqlite3, "connect", failing_connect)

    with pytest.raises(sqlite3.OperationalError, match="Simulated failure mid-import"):
        import_inventory_to_catalog(
            inventory_db_path=str(complete_inventory_db),
            catalog_db_path=str(catalog_db),
            dry_run=False,
        )

    # Verificar rollback: BD destino debe tener CERO filas
    cat_conn = sqlite3.connect(catalog_db)
    media_count = cat_conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    sources_count = cat_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    cat_conn.close()

    assert media_count == 0, f"Rollback fallido: media count={media_count}"
    assert sources_count == 0, f"Rollback fallido: sources count={sources_count}"


# ---------------------------------------------------------------------------
# 9. test_cli_inventory_import_help_and_invocation
# ---------------------------------------------------------------------------


def test_cli_inventory_import_requires_args() -> None:
    """CLI --inventory-import exige --inventory-db y --catalog-db."""
    # Sin argumentos requeridos -> exit code != 0 y mensaje de error
    result = subprocess.run(
        [sys.executable, "scripts/sync_catalog.py", "--inventory-import"],
        capture_output=True,
        text=True,
        cwd="/home/emon/media-integration-gateway-inventario-r2",
    )
    assert result.returncode != 0
    assert "ERROR: --inventory-import requiere --inventory-db y --catalog-db" in result.stderr


def test_cli_inventory_import_successful(
    complete_inventory_db: Path, catalog_db: Path, tmp_path: Path
) -> None:
    """CLI ejecuta importación exitosamente e imprime el resumen."""
    # Poblar inventario con una película
    inv_conn = sqlite3.connect(complete_inventory_db)
    inv_conn.execute("BEGIN IMMEDIATE")
    inv_conn.execute(
        "INSERT INTO movies (provider, provider_id, title, year, url, poster) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cuevana3", "cli-import-movie", "CLI Import Movie", 2025, "https://cuevana3i.cc/pelicula/cli-import-movie/", "https://img/cli.jpg"),
    )
    inv_conn.execute(
        "INSERT INTO movie_categories (provider, provider_id, category_slug) VALUES (?, ?, ?)",
        ("cuevana3", "cli-import-movie", "accion"),
    )
    inv_conn.commit()
    inv_conn.close()

    result = subprocess.run(
        [
            sys.executable,
            "scripts/sync_catalog.py",
            "--inventory-import",
            "--inventory-db",
            str(complete_inventory_db),
            "--catalog-db",
            str(catalog_db),
        ],
        capture_output=True,
        text=True,
        cwd="/home/emon/media-integration-gateway-inventario-r2",
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    stdout = result.stdout
    assert "Inventario leído: 1" in stdout
    assert "Relaciones de categorías: 1" in stdout
    assert "Insertados: 1" in stdout
    assert "Actualizados: 0" in stdout
    assert "Sin cambios: 0" in stdout
    assert "Estado: committed" in stdout

    # Verificar en BD destino
    cat_conn = sqlite3.connect(catalog_db)
    media_count = cat_conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    sources_count = cat_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    cat_conn.close()
    assert media_count == 1
    assert sources_count == 1


def test_cli_inventory_import_dry_run(
    complete_inventory_db: Path, catalog_db: Path
) -> None:
    """CLI con --dry-run reporta resumen pero no persiste."""
    inv_conn = sqlite3.connect(complete_inventory_db)
    inv_conn.execute("BEGIN IMMEDIATE")
    inv_conn.execute(
        "INSERT INTO movies (provider, provider_id, title, year, url, poster) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("cuevana3", "cli-dryrun-movie", "CLI Dry Run Movie", 2025, "https://cuevana3i.cc/pelicula/cli-dryrun-movie/", "https://img/cli.jpg"),
    )
    inv_conn.execute(
        "INSERT INTO movie_categories (provider, provider_id, category_slug) VALUES (?, ?, ?)",
        ("cuevana3", "cli-dryrun-movie", "accion"),
    )
    inv_conn.commit()
    inv_conn.close()

    result = subprocess.run(
        [
            sys.executable,
            "scripts/sync_catalog.py",
            "--inventory-import",
            "--inventory-db",
            str(complete_inventory_db),
            "--catalog-db",
            str(catalog_db),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd="/home/emon/media-integration-gateway-inventario-r2",
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    stdout = result.stdout
    assert "Inventario leído: 1" in stdout
    assert "Insertados: 1" in stdout
    assert "Estado: dry-run/rolled-back" in stdout

    # Verificar BD destino vacía
    cat_conn = sqlite3.connect(catalog_db)
    media_count = cat_conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    sources_count = cat_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    cat_conn.close()
    assert media_count == 0
    assert sources_count == 0