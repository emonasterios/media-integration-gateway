"""Tests del endpoint M3U playlist."""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from src.db.models import Base, Media, Source
from src.db.database import SessionLocal
from src.services.cache import CatalogCache
from src.services.catalog import CatalogService
from src.main import create_app


# Fixture: base de datos en memoria para cada test
@pytest.fixture()
def db_session():
    """Crea una BD SQLite en memoria con tablas frescas."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


# Fixture: cache con TTL largo para tests
@pytest.fixture()
def cache(db_session):
    """CatalogCache con TTL largo."""
    return CatalogCache(db_session, ttl_seconds=3600)


# Fixture: app de prueba con cache inyectado
@pytest.fixture()
def test_app(db_session, cache):
    """Crea la app FastAPI con catálogo que usa la BD de prueba."""
    catalog = CatalogService(providers=[], cache=cache)
    return create_app(override_catalog=catalog)


# Fixture: TestClient
@pytest.fixture()
def client(test_app):
    with TestClient(test_app) as c:
        yield c


def _add_media_with_source(db_session, title: str, media_type: str = "movie", year: int = 2024, provider: str = "test", provider_id: str = None):
    """Helper para insertar Media y Source en la BD de prueba."""
    if provider_id is None:
        provider_id = title.lower().replace(" ", "-")
    
    now = datetime.utcnow()
    media = Media(
        title=title,
        media_type=media_type,
        year=year,
        updated_at=now,
    )
    db_session.add(media)
    db_session.commit()
    db_session.refresh(media)

    source = Source(
        media_id=media.id,
        provider=provider,
        url=provider_id,
        quality="1080p",
        language="es",
    )
    db_session.add(source)
    db_session.commit()
    return media


class TestM3UPlaylist:
    """Tests del endpoint GET /playlist.m3u"""

    def test_m3u_empty_catalog_returns_200_with_extm3u(self, client, db_session):
        """GET /playlist.m3u con catálogo vacío devuelve HTTP 200, header mpegurl y #EXTM3U."""
        response = client.get("/playlist.m3u")
        
        assert response.status_code == 200
        # Content-Type compatible con mpegurl
        assert "mpegurl" in response.headers.get("content-type", "") or "text" in response.headers.get("content-type", "")
        # Cuerpo contiene #EXTM3U
        assert "#EXTM3U" in response.text
        # NO debe estar serializado como JSON (no comienza/termina con comillas dobles)
        assert not response.text.startswith('"')
        assert not response.text.endswith('"')

    def test_m3u_with_items_returns_valid_playlist(self, client, db_session):
        """GET /playlist.m3u con items en caché devuelve playlist M3U válida."""
        # Insertar item de prueba en la caché
        _add_media_with_source(
            db_session, 
            title="Signal One (2026)", 
            media_type="movie", 
            year=2026,
            provider="cuevana3",
            provider_id="signal-one-2026"
        )
        
        response = client.get("/playlist.m3u")
        
        assert response.status_code == 200
        # Content-Type compatible con mpegurl
        assert "mpegurl" in response.headers.get("content-type", "") or "text" in response.headers.get("content-type", "")
        # Cuerpo contiene cabecera #EXTM3U
        assert "#EXTM3U" in response.text
        # Contiene EXTINF con group-title y título
        assert '#EXTINF:-1 group-title="Peliculas",Signal One (2026)' in response.text
        # Contiene URL de resolución esperada
        assert "http://testserver/api/v1/playback/resolve/cuevana3/signal-one-2026" in response.text
        # NO debe estar serializado como JSON
        assert not response.text.startswith('"')
        assert not response.text.endswith('"')

    def test_m3u_multiple_items_all_included(self, client, db_session):
        """GET /playlist.m3u con múltiples items los incluye todos."""
        _add_media_with_source(db_session, "Movie A", "movie", 2024, "provider1", "movie-a")
        _add_media_with_source(db_session, "Movie B", "movie", 2023, "provider2", "movie-b")
        _add_media_with_source(db_session, "Series X", "series", 2024, "provider1", "series-x")
        
        response = client.get("/playlist.m3u")
        
        assert response.status_code == 200
        assert "#EXTM3U" in response.text
        assert '#EXTINF:-1 group-title="Peliculas",Movie A' in response.text
        assert '#EXTINF:-1 group-title="Peliculas",Movie B' in response.text
        assert '#EXTINF:-1 group-title="Series",Series X' in response.text
        assert "/api/v1/playback/resolve/provider1/movie-a" in response.text
        assert "/api/v1/playback/resolve/provider2/movie-b" in response.text
        assert "/api/v1/playback/resolve/provider1/series-x" in response.text
        # No JSON serialization
        assert not response.text.startswith('"')
        assert not response.text.endswith('"')

    def test_m3u_filters_expired_items(self, client, db_session, cache):
        """GET /playlist.m3u NO incluye items con TTL expirado."""
        # Item válido (updated_at reciente)
        _add_media_with_source(db_session, "Valid Movie", "movie", 2024, "provider", "valid-movie")
        
        # Item expirado (updated_at hace 2 horas, TTL = 1 hora)
        from datetime import timedelta
        old_time = datetime.utcnow() - timedelta(hours=2)
        expired_media = Media(
            title="Expired Movie",
            media_type="movie",
            year=2022,
            updated_at=old_time,
        )
        db_session.add(expired_media)
        db_session.commit()
        db_session.refresh(expired_media)
        
        expired_source = Source(
            media_id=expired_media.id,
            provider="provider",
            url="expired-movie",
            quality="720p",
            language="es",
        )
        db_session.add(expired_source)
        db_session.commit()
        
        response = client.get("/playlist.m3u")
        
        assert response.status_code == 200
        assert "Valid Movie" in response.text
        assert "Expired Movie" not in response.text  # Filtrado por TTL

    def test_m3u_skips_items_without_sources(self, client, db_session):
        """GET /playlist.m3u omite items sin sources asociados."""
        # Item con source
        _add_media_with_source(db_session, "With Source", "movie", 2024, "provider", "with-source")
        
        # Item SIN source
        now = datetime.utcnow()
        media_no_source = Media(
            title="No Source",
            media_type="movie",
            year=2024,
            updated_at=now,
        )
        db_session.add(media_no_source)
        db_session.commit()
        
        response = client.get("/playlist.m3u")
        
        assert response.status_code == 200
        assert "With Source" in response.text
        assert "No Source" not in response.text  # Omitido por no tener source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])