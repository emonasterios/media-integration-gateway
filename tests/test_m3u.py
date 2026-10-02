"""Tests para el endpoint M3U y resolución GET para clientes IPTV."""

import pytest
from datetime import datetime
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.main import create_app
from src.db.database import Base, get_db
from src.db.models import Media, Source
from src.services.catalog import CatalogService
from src.adapters.base import MediaProvider
from src.models.catalog import (
    MediaItem, MediaType, SearchResult, PlaybackDescriptor, Season, Episode
)


class FakeProvider(MediaProvider):
    """Proveedor fake para saltar el lifespan real de la app."""

    @property
    def name(self) -> str:
        return "fake"

    async def search(self, query: str) -> SearchResult:
        return SearchResult(items=[], total=0, query=query)

    async def get_details(self, media_id: str) -> MediaItem:
        return MediaItem(
            media_id=f"fake:{media_id}", title="Test", media_type=MediaType.MOVIE,
            provider="fake", provider_id=media_id,
        )

    async def get_seasons(self, media_id: str) -> list[Season]:
        return []

    async def get_episodes(self, media_id: str, season_number: int) -> list[Episode]:
        return []

    async def resolve_playback(self, media_id: str) -> PlaybackDescriptor:
        return PlaybackDescriptor(protocol="mp4", url="https://example.com/video.mp4")

    async def get_catalog(self, category: str | None = None) -> list[MediaItem]:
        return []


@pytest.fixture()
async def db_engine():
    """Crea un engine SQLite async en memoria para tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Crear tablas de forma async
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
def app_with_db(db_engine):
    """App FastAPI con override de BD async en memoria y catalog fake."""
    svc = CatalogService(providers=[FakeProvider()])

    TestingAsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    async def override_get_db():
        async with TestingAsyncSessionLocal() as session:
            yield session

    # Crear app SIN lifespan (para tests)
    from src.api.routes import _get_catalog
    from src.api.xtream import _get_catalog_service as _xtream_get_catalog
    from src.main import _build_app
    app = _build_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[_get_catalog] = lambda: svc
    app.dependency_overrides[_xtream_get_catalog] = lambda: svc
    return app


@pytest.fixture()
async def db_session(db_engine):
    """Sesión de BD async para insertar datos de prueba."""
    TestingAsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = TestingAsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_get_playlist_empty_cache(app_with_db):
    """GET /playlist.m3u con caché vacía devuelve 200, Content-Type correcto y #EXTM3U."""
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/playlist.m3u")
    assert r.status_code == 200
    assert "application/x-mpegurl" in r.headers["content-type"]
    assert r.text == "#EXTM3U\n"


@pytest.mark.asyncio
async def test_get_playlist_with_cached_items(app_with_db, db_session):
    """GET /playlist.m3u con items en caché genera playlist M3U válida."""
    now = datetime.utcnow()
    media = Media(
        title="Signal One",
        original_title="signal-one",
        media_type="movie",
        year=2026,
        synopsis="Una película de prueba",
        poster_url="https://example.com/signal-one.jpg",
        created_at=now,
        updated_at=now,
    )
    db_session.add(media)
    await db_session.commit()
    await db_session.refresh(media)

    source = Source(
        media_id=media.id,
        provider="cuevana3",
        url="signal-one",
        quality="1080p",
        language="es",
    )
    db_session.add(source)
    await db_session.commit()

    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/playlist.m3u")
    assert r.status_code == 200
    assert "application/x-mpegurl" in r.headers["content-type"]

    content = r.text
    assert "#EXTM3U" in content
    assert '#EXTINF:-1 group-title="Peliculas",Signal One (2026)' in content
    assert "/api/v1/resolve/cuevana3/signal-one" in content


@pytest.mark.asyncio
async def test_get_resolve_endpoint(app_with_db, db_session):
    """GET /api/v1/resolve/{provider}/{media_id} no da 405 (ruta existe)."""
    now = datetime.utcnow()
    media = Media(
        title="Signal One",
        original_title="signal-one",
        media_type="movie",
        year=2026,
        synopsis="Una película de prueba",
        poster_url="https://example.com/signal-one.jpg",
        created_at=now,
        updated_at=now,
    )
    db_session.add(media)
    await db_session.commit()
    await db_session.refresh(media)

    source = Source(
        media_id=media.id,
        provider="cuevana3",
        url="signal-one",
        quality="1080p",
        language="es",
    )
    db_session.add(source)
    await db_session.commit()

    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/resolve/cuevana3/signal-one", follow_redirects=False)
    # Lo importante es que la ruta existe y no da 405
    assert r.status_code != 405, f"Se esperaba no 405, se recibió {r.status_code}: {r.text}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
