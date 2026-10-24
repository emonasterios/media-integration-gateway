"""Pruebas de migraciones Alembic sobre bases SQLite preexistentes."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _alembic_upgrade(database_path: Path, revision: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _alembic_downgrade(database_path: Path, revision: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path}"
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "downgrade", revision],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_sources_integrity_migration_cleans_dirty_existing_database(tmp_path: Path) -> None:
    """La migración limpia sources inválidas sin eliminar media válida."""
    database_path = tmp_path / "dirty-sources.db"
    _alembic_upgrade(database_path, "b4c8d1e2f3a4")

    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            "INSERT INTO media (id, title, media_type) VALUES (?, ?, ?)",
            [(1, "First", "movie"), (2, "Second", "movie")],
        )
        connection.executemany(
            """
            INSERT INTO sources (id, media_id, provider, url, quality, language)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (10, 1, "provider", "shared-url", "1080p", "es"),
                (11, 2, "provider", "shared-url", "720p", "en"),
                (12, 999, "provider", "orphan-url", "1080p", "es"),
                (13, 2, "provider", "valid-url", "1080p", "es"),
            ],
        )

    _alembic_upgrade(database_path, "head")

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT id FROM media ORDER BY id").fetchall() == [(1,), (2,)]
        assert connection.execute(
            "SELECT id, media_id, provider, url FROM sources ORDER BY id"
        ).fetchall() == [
            (10, 1, "provider", "shared-url"),
            (13, 2, "provider", "valid-url"),
        ]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO sources (media_id, provider, url) VALUES (?, ?, ?)",
                (2, "provider", "shared-url"),
            )


def test_head_adds_nullable_page_url_column(tmp_path: Path) -> None:
    """Aplicar todas las migraciones deja page_url en sources, nullable."""
    database_path = tmp_path / "head-page-url.db"
    _alembic_upgrade(database_path, "head")

    with sqlite3.connect(database_path) as connection:
        columns = connection.execute("PRAGMA table_info(sources)").fetchall()
        page_url_columns = [column for column in columns if column[1] == "page_url"]
        assert len(page_url_columns) == 1
        # PRAGMA table_info: (cid, name, type, notnull, default_value, pk)
        assert page_url_columns[0][3] == 0

        # Nullable: una fila sin page_url se acepta y queda en NULL.
        connection.execute(
            "INSERT INTO media (id, title, media_type) VALUES (?, ?, ?)",
            (1, "Movie", "movie"),
        )
        connection.execute(
            "INSERT INTO sources (media_id, provider, url) VALUES (?, ?, ?)",
            (1, "provider", "provider-1"),
        )
        assert connection.execute(
            "SELECT page_url FROM sources WHERE id = 1"
        ).fetchall() == [(None,)]


def test_existing_sources_keep_data_with_null_page_url(tmp_path: Path) -> None:
    """Sources previas a la migración conservan sus datos con page_url en None."""
    database_path = tmp_path / "preserve-page-url.db"
    _alembic_upgrade(database_path, "c5d9e2f3a4b5")

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO media (id, title, media_type) VALUES (?, ?, ?)",
            (1, "Preserved", "movie"),
        )
        connection.executemany(
            """
            INSERT INTO sources (id, media_id, provider, url, quality, language)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (10, 1, "provider", "provider-1", "1080p", "es"),
                (11, 1, "provider", "provider-2", "720p", "en"),
            ],
        )

    _alembic_upgrade(database_path, "head")

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            """
            SELECT id, media_id, provider, url, quality, language, page_url
            FROM sources ORDER BY id
            """
        ).fetchall() == [
            (10, 1, "provider", "provider-1", "1080p", "es", None),
            (11, 1, "provider", "provider-2", "720p", "en", None),
        ]


def test_downgrade_d6e1f2a3b4c5_drops_page_url_column(tmp_path: Path) -> None:
    """El downgrade de d6e1f2a3b4c5 elimina page_url y permite volver a head."""
    database_path = tmp_path / "downgrade-page-url.db"
    _alembic_upgrade(database_path, "head")

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO media (id, title, media_type) VALUES (?, ?, ?)",
            (1, "Downgraded", "movie"),
        )
        connection.execute(
            "INSERT INTO sources (media_id, provider, url, page_url) VALUES (?, ?, ?, ?)",
            (1, "provider", "provider-1", "https://cuevana3.example/series/serie"),
        )

    _alembic_downgrade(database_path, "c5d9e2f3a4b5")

    with sqlite3.connect(database_path) as connection:
        column_names = [
            column[1]
            for column in connection.execute("PRAGMA table_info(sources)").fetchall()
        ]
        assert "page_url" not in column_names
        # Los datos de la fila sobreviven al downgrade menos la columna eliminada.
        assert connection.execute(
            "SELECT media_id, provider, url FROM sources"
        ).fetchall() == [(1, "provider", "provider-1")]

    # Ciclo completo: re-subir a head vuelve a crear la columna nullable.
    _alembic_upgrade(database_path, "head")
    with sqlite3.connect(database_path) as connection:
        columns = connection.execute("PRAGMA table_info(sources)").fetchall()
        page_url_columns = [column for column in columns if column[1] == "page_url"]
        assert len(page_url_columns) == 1
        assert page_url_columns[0][3] == 0


def test_catalog_presence_full_cycle_preserves_rows(tmp_path: Path) -> None:
    """El ciclo f8a3b2c1d4e5 -> head -> f8a3b2c1d4e5 -> head preserva los datos."""
    database_path = tmp_path / "catalog-presence-cycle.db"

    # 1) Base temporal en f8a3b2c1d4e5 con registros previos en media y sources.
    _alembic_upgrade(database_path, "f8a3b2c1d4e5")

    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            "INSERT INTO media (id, title, media_type) VALUES (?, ?, ?)",
            [(1, "Cycle Movie", "movie"), (2, "Cycle Series", "series")],
        )
        connection.executemany(
            """
            INSERT INTO sources (id, media_id, provider, url, quality, language)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (10, 1, "provider", "cycle-url-1", "1080p", "es"),
                (11, 2, "provider", "cycle-url-2", "720p", "en"),
            ],
        )

    # 2) Upgrade a head: filas previas intactas y defaults de presencia aplicados.
    _alembic_upgrade(database_path, "head")

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT id, title, media_type FROM media ORDER BY id"
        ).fetchall() == [(1, "Cycle Movie", "movie"), (2, "Cycle Series", "series")]
        assert connection.execute(
            """
            SELECT id, media_id, provider, url, quality, language, page_url
            FROM sources ORDER BY id
            """
        ).fetchall() == [
            (10, 1, "provider", "cycle-url-1", "1080p", "es", None),
            (11, 2, "provider", "cycle-url-2", "720p", "en", None),
        ]
        assert connection.execute(
            """
            SELECT catalog_presence, consecutive_misses, last_seen_at,
                   last_seen_run_id, missing_since
            FROM sources ORDER BY id
            """
        ).fetchall() == [
            ("present", 0, None, None, None),
            ("present", 0, None, None, None),
        ]

    # 3) Nueva fuente en head con valores explícitos de presencia.
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO sources (
                media_id, provider, url, catalog_presence, consecutive_misses,
                last_seen_at, last_seen_run_id, missing_since
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                2,
                "provider",
                "cycle-url-3",
                "missing",
                1,
                "2026-10-23 20:00:00",
                "run-test-id",
                "2026-10-23 21:00:00",
            ),
        )
        assert connection.execute(
            """
            SELECT media_id, provider, url, catalog_presence, consecutive_misses,
                   last_seen_at, last_seen_run_id, missing_since
            FROM sources WHERE url = 'cycle-url-3'
            """
        ).fetchall() == [
            (
                2,
                "provider",
                "cycle-url-3",
                "missing",
                1,
                "2026-10-23 20:00:00",
                "run-test-id",
                "2026-10-23 21:00:00",
            ),
        ]

    # 4) Downgrade: las cinco columnas nuevas desaparecen y los datos persisten.
    _alembic_downgrade(database_path, "f8a3b2c1d4e5")

    with sqlite3.connect(database_path) as connection:
        column_names = [
            column[1]
            for column in connection.execute("PRAGMA table_info(sources)").fetchall()
        ]
        assert "catalog_presence" not in column_names
        assert "last_seen_at" not in column_names
        assert "last_seen_run_id" not in column_names
        assert "missing_since" not in column_names
        assert "consecutive_misses" not in column_names
        assert connection.execute("SELECT id FROM media ORDER BY id").fetchall() == [(1,), (2,)]
        assert connection.execute(
            "SELECT id, media_id, provider, url FROM sources ORDER BY id"
        ).fetchall() == [
            (10, 1, "provider", "cycle-url-1"),
            (11, 2, "provider", "cycle-url-2"),
            (12, 2, "provider", "cycle-url-3"),
        ]

    # 5) Re-upgrade a head: completa exitosamente restableciendo defaults compatibles.
    _alembic_upgrade(database_path, "head")

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            """
            SELECT catalog_presence, consecutive_misses, last_seen_at,
                   last_seen_run_id, missing_since
            FROM sources ORDER BY id
            """
        ).fetchall() == [
            ("present", 0, None, None, None),
            ("present", 0, None, None, None),
            ("present", 0, None, None, None),
        ]
