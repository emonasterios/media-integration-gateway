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
