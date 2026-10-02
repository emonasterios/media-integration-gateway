"""Tests unitarios de caché y flujo completo en CatalogService."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.db.models import Base, Media, Source
from src.services.cache import CatalogCache
from src.services.catalog import CatalogService
from src.adapters.base import MediaProvider
from src.models.catalog import MediaItem, MediaType, SearchResult


# Fixture: base de datos en memoria para cada test (async)
@pytest.fixture()
async def db_session():
    """Crea una BD SQLite en memoria con tablas frescas (async)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    AsyncSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


# Fixture: adaptador mock
@pytest.fixture()
def mock_provider():
    """Proveedor mock que registra cuántas veces se llama."""
    provider = AsyncMock(spec=MediaProvider)
    provider.name = "test_provider"
    provider.search = AsyncMock(return_value=SearchResult(items=[], total=0, query="test"))
    provider.get_details = AsyncMock()
    provider.get_seasons = AsyncMock(return_value=[])
    provider.get_episodes = AsyncMock(return_value=[])
    provider.resolve_playback = AsyncMock()
    provider.get_catalog = AsyncMock(return_value=[])
    return provider


# Fixture: servicio de catálogo con caché y proveedor mock
@pytest.fixture()
async def catalog_service(db_session, mock_provider):
    """CatalogService con caché real y proveedor mock."""
    cache = CatalogCache(db_session, ttl_seconds=3600)  # 1 hora TTL
    service = CatalogService(providers=[mock_provider], cache=cache)
    return service


class TestCacheHit:
    """Tests de HIT de caché: contenido en DB y dentro del TTL."""

    @pytest.mark.asyncio
    async def test_get_details_cache_hit_returns_db_content(self, catalog_service, mock_provider, db_session):
        """Cuando un medio existe en DB y no ha expirado, se retorna desde DB sin invocar adapter."""
        now = datetime.utcnow()
        media = Media(
            title="cached-movie-2024",
            original_title="Cached Movie",
            media_type="movie",
            year=2024,
            synopsis="Sinopsis desde caché",
            poster_url="https://example.com/cached.jpg",
            created_at=now,
            updated_at=now,
        )
        db_session.add(media)
        await db_session.commit()
        await db_session.refresh(media)

        source = Source(
            media_id=media.id,
            provider="test_provider",
            url="cached-movie-2024",
            quality="1080p",
            language="es",
        )
        db_session.add(source)
        await db_session.commit()

        result = await catalog_service.get_details("test_provider", "test_provider:cached-movie-2024")

        assert isinstance(result, MediaItem)
        assert result.title == "cached-movie-2024"
        assert result.year == 2024
        assert result.overview == "Sinopsis desde caché"
        assert result.poster_url == "https://example.com/cached.jpg"
        assert result.provider == "test_provider"
        assert result.provider_id == "cached-movie-2024"

        mock_provider.get_details.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_details_cache_hit_with_media_type_filter(self, catalog_service, mock_provider, db_session):
        """Cache hit respeta el filtro de media_type (movie vs series)."""
        now = datetime.utcnow()
        movie = Media(title="movie-same", media_type="movie", year=2024, updated_at=now)
        series = Media(title="movie-same", media_type="series", year=2023, updated_at=now)
        db_session.add_all([movie, series])
        await db_session.commit()
        await db_session.refresh(movie)
        await db_session.refresh(series)

        source_movie = Source(media_id=movie.id, provider="test_provider", url="movie-same", quality="1080p", language="es")
        source_series = Source(media_id=series.id, provider="test_provider", url="series-same", quality="1080p", language="es")
        db_session.add_all([source_movie, source_series])
        await db_session.commit()

        result = await catalog_service.get_details("test_provider", "test_provider:movie-same")
        assert result.media_type == MediaType.MOVIE
        assert result.year == 2024

        mock_provider.get_details.assert_not_called()


class TestCacheMiss:
    """Tests de MISS de caché: contenido NO existe en DB."""

    @pytest.mark.asyncio
    async def test_get_details_cache_miss_invokes_adapter_and_persists(self, catalog_service, mock_provider, db_session):
        """Cuando un medio NO existe en DB, se invoca adapter y resultado se persiste en SQLite."""
        mock_item = MediaItem(
            media_id="test_provider:new-movie-2024",
            title="New Movie 2024",
            media_type=MediaType.MOVIE,
            year=2024,
            poster_url="https://example.com/new.jpg",
            overview="Sinopsis del adapter",
            provider="test_provider",
            provider_id="new-movie-2024",
        )
        mock_provider.get_details.return_value = mock_item

        result = await catalog_service.get_details("test_provider", "test_provider:new-movie-2024")

        mock_provider.get_details.assert_called_once_with("test_provider:new-movie-2024")

        assert result.title == "New Movie 2024"
        assert result.year == 2024
        assert result.overview == "Sinopsis del adapter"

        # Verificar: se persistió en DB
        from sqlalchemy import select
        stmt = select(Media).filter_by(title="New Movie 2024")
        result_db = await db_session.execute(stmt)
        saved_media = result_db.scalar_one_or_none()
        assert saved_media is not None
        assert saved_media.media_type == "movie"
        assert saved_media.year == 2024
        assert saved_media.synopsis == "Sinopsis del adapter"
        assert saved_media.poster_url == "https://example.com/new.jpg"

        stmt = select(Source).filter_by(media_id=saved_media.id)
        result_db = await db_session.execute(stmt)
        sources = result_db.scalars().all()
        assert len(sources) == 1
        assert sources[0].provider == "test_provider"
        assert sources[0].url == "new-movie-2024"

    @pytest.mark.asyncio
    async def test_get_details_cache_miss_creates_new_record(self, catalog_service, mock_provider, db_session):
        """Cache miss crea nuevo registro Media (no actualiza existente)."""
        mock_item = MediaItem(
            media_id="test_provider:another-movie",
            title="Another Movie",
            media_type=MediaType.MOVIE,
            year=2023,
            provider="test_provider",
            provider_id="another-movie",
        )
        mock_provider.get_details.return_value = mock_item

        result = await catalog_service.get_details("test_provider", "test_provider:another-movie")

        from sqlalchemy import select, func
        stmt = select(func.count()).select_from(Media).filter_by(title="Another Movie")
        result_db = await db_session.execute(stmt)
        count = result_db.scalar()
        assert count == 1


class TestTTLExpiration:
    """Tests de expiración de TTL: registro antiguo fuerza nueva consulta."""

    @pytest.mark.asyncio
    async def test_get_details_ttl_expired_forces_adapter_call_and_updates_db(self, catalog_service, mock_provider, db_session):
        """Cuando updated_at es más antiguo que TTL, se detecta expirado y se fuerza adapter actualizando DB."""
        old_time = datetime.utcnow() - timedelta(hours=2)
        media = Media(
            title="Expired Movie",
            original_title="Expired Movie",
            media_type="movie",
            year=2022,
            synopsis="Sinopsis vieja",
            poster_url="https://example.com/old.jpg",
            created_at=old_time,
            updated_at=old_time,
        )
        db_session.add(media)
        await db_session.commit()
        await db_session.refresh(media)

        source = Source(media_id=media.id, provider="test_provider", url="expired-movie", quality="720p", language="es")
        db_session.add(source)
        await db_session.commit()

        mock_item = MediaItem(
            media_id="test_provider:expired-movie",
            title="Expired Movie",
            media_type=MediaType.MOVIE,
            year=2024,
            poster_url="https://example.com/new.jpg",
            overview="Sinopsis ACTUALIZADA",
            provider="test_provider",
            provider_id="expired-movie",
        )
        mock_provider.get_details.return_value = mock_item

        result = await catalog_service.get_details("test_provider", "test_provider:expired-movie")

        mock_provider.get_details.assert_called_once_with("test_provider:expired-movie")

        assert result.year == 2024
        assert result.overview == "Sinopsis ACTUALIZADA"
        assert result.poster_url == "https://example.com/new.jpg"

        from sqlalchemy import select
        stmt = select(Media).filter_by(title="Expired Movie")
        result_db = await db_session.execute(stmt)
        saved_media = result_db.scalar_one_or_none()
        assert saved_media is not None
        assert saved_media.year == 2024
        assert saved_media.synopsis == "Sinopsis ACTUALIZADA"
        assert saved_media.poster_url == "https://example.com/new.jpg"
        assert saved_media.updated_at > old_time

        stmt = select(Source).filter_by(media_id=saved_media.id)
        result_db = await db_session.execute(stmt)
        sources = result_db.scalars().all()
        assert len(sources) == 1

    @pytest.mark.asyncio
    async def test_get_details_ttl_not_expired_uses_cache(self, catalog_service, mock_provider, db_session):
        """Cuando updated_at es reciente (dentro del TTL), se usa caché sin llamar adapter."""
        recent_time = datetime.utcnow() - timedelta(minutes=30)
        media = Media(
            title="fresh-movie",
            media_type="movie",
            year=2024,
            synopsis="Sinopsis fresca",
            updated_at=recent_time,
        )
        db_session.add(media)
        await db_session.commit()
        await db_session.refresh(media)

        source = Source(media_id=media.id, provider="test_provider", url="fresh-movie", quality="1080p", language="es")
        db_session.add(source)
        await db_session.commit()

        result = await catalog_service.get_details("test_provider", "test_provider:fresh-movie")

        mock_provider.get_details.assert_not_called()

        assert result.year == 2024
        assert result.overview == "Sinopsis fresca"


class TestCacheIntegration:
    """Tests de integración: flujo completo con múltiples operaciones."""

    @pytest.mark.asyncio
    async def test_multiple_get_details_same_item_only_first_calls_adapter(self, catalog_service, mock_provider, db_session):
        """Primera llamada miss -> adapter, segunda llamada hit -> caché."""
        mock_item = MediaItem(
            media_id="test_provider:repeat-movie",
            title="repeat-movie",
            media_type=MediaType.MOVIE,
            year=2024,
            provider="test_provider",
            provider_id="repeat-movie",
        )
        mock_provider.get_details.return_value = mock_item

        result1 = await catalog_service.get_details("test_provider", "test_provider:repeat-movie")
        assert mock_provider.get_details.call_count == 1

        result2 = await catalog_service.get_details("test_provider", "test_provider:repeat-movie")
        assert mock_provider.get_details.call_count == 1

        assert result1.title == result2.title == "repeat-movie"

    @pytest.mark.asyncio
    async def test_different_media_ids_independent_cache(self, catalog_service, mock_provider, db_session):
        """Diferentes media_ids tienen entradas de caché independientes."""
        mock_item1 = MediaItem(media_id="test_provider:movie-a", title="movie-a", media_type=MediaType.MOVIE, year=2024, provider="test_provider", provider_id="movie-a")
        mock_item2 = MediaItem(media_id="test_provider:movie-b", title="movie-b", media_type=MediaType.MOVIE, year=2023, provider="test_provider", provider_id="movie-b")
        
        async def side_effect(media_id):
            if "movie-a" in media_id:
                return mock_item1
            return mock_item2
        
        mock_provider.get_details.side_effect = side_effect

        result_a = await catalog_service.get_details("test_provider", "test_provider:movie-a")
        assert result_a.title == "movie-a"
        assert mock_provider.get_details.call_count == 1

        result_b = await catalog_service.get_details("test_provider", "test_provider:movie-b")
        assert result_b.title == "movie-b"
        assert mock_provider.get_details.call_count == 2

        result_a2 = await catalog_service.get_details("test_provider", "test_provider:movie-a")
        assert result_a2.title == "movie-a"
        assert mock_provider.get_details.call_count == 2


class TestCatalogCacheDirect:
    """Tests directos del CatalogCache (sin CatalogService)."""

    @pytest.mark.asyncio
    async def test_get_media_returns_none_when_not_exists(self, db_session):
        """get_media retorna None si no existe el título."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        result = await cache.get_media("No Existe")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_media_returns_media_when_valid(self, db_session):
        """get_media retorna Media si existe y está dentro del TTL."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        now = datetime.utcnow()
        media = Media(title="Test", media_type="movie", updated_at=now)
        db_session.add(media)
        await db_session.commit()
        await db_session.refresh(media)

        result = await cache.get_media("Test")
        assert result is not None
        assert result.title == "Test"

    @pytest.mark.asyncio
    async def test_get_media_returns_none_when_expired(self, db_session):
        """get_media retorna None si existe pero TTL expiró."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        old_time = datetime.utcnow() - timedelta(hours=2)
        media = Media(title="Expired", media_type="movie", updated_at=old_time)
        db_session.add(media)
        await db_session.commit()

        result = await cache.get_media("Expired")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_media_respects_media_type_filter(self, db_session):
        """get_media con media_type filtra correctamente."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        now = datetime.utcnow()
        movie = Media(title="Same", media_type="movie", updated_at=now)
        series = Media(title="Same", media_type="series", updated_at=now)
        db_session.add_all([movie, series])
        await db_session.commit()

        result = await cache.get_media("Same", media_type="movie")
        assert result is not None
        assert result.media_type == "movie"

        result = await cache.get_media("Same", media_type="series")
        assert result is not None
        assert result.media_type == "series"

    @pytest.mark.asyncio
    async def test_save_media_creates_new_record(self, db_session):
        """save_media crea nuevo registro si no existe."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        item_data = {"title": "New Movie", "media_type": "movie", "year": 2024, "synopsis": "New synopsis"}
        sources_data = [{"provider": "test", "url": "new-movie", "quality": "1080p", "language": "es"}]

        media = await cache.save_media(item_data, sources_data)

        assert media.id is not None
        assert media.title == "New Movie"
        assert media.media_type == "movie"
        assert media.year == 2024
        assert media.synopsis == "New synopsis"

        from sqlalchemy import select
        stmt = select(Source).filter_by(media_id=media.id)
        result = await db_session.execute(stmt)
        sources = result.scalars().all()
        assert len(sources) == 1
        assert sources[0].provider == "test"

    @pytest.mark.asyncio
    async def test_save_media_updates_existing_record(self, db_session):
        """save_media actualiza registro existente y reemplaza sources."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        old_time = datetime.utcnow() - timedelta(days=1)
        media = Media(title="Existing", media_type="movie", year=2020, synopsis="Old", updated_at=old_time)
        db_session.add(media)
        await db_session.commit()
        await db_session.refresh(media)

        old_source = Source(media_id=media.id, provider="old_provider", url="old", quality="720p", language="en")
        db_session.add(old_source)
        await db_session.commit()

        item_data = {"title": "Existing", "media_type": "movie", "year": 2024, "synopsis": "Updated", "poster_url": "https://new.jpg"}
        sources_data = [{"provider": "new_provider", "url": "new-url", "quality": "4K", "language": "es"}]

        updated_media = await cache.save_media(item_data, sources_data)

        assert updated_media.id == media.id
        assert updated_media.year == 2024
        assert updated_media.synopsis == "Updated"
        assert updated_media.poster_url == "https://new.jpg"
        assert updated_media.updated_at > old_time

        from sqlalchemy import select
        stmt = select(Source).filter_by(media_id=media.id)
        result = await db_session.execute(stmt)
        sources = result.scalars().all()
        assert len(sources) == 1
        assert sources[0].provider == "new_provider"
        assert sources[0].url == "new-url"

    def test_is_valid_true_when_within_ttl(self, db_session):
        """is_valid retorna True si updated_at dentro del TTL."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        recent = datetime.utcnow() - timedelta(minutes=30)
        media = Media(title="Test", media_type="movie", updated_at=recent)
        assert cache.is_valid(media) is True

    def test_is_valid_false_when_expired(self, db_session):
        """is_valid retorna False si updated_at fuera del TTL."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        old = datetime.utcnow() - timedelta(hours=2)
        media = Media(title="Test", media_type="movie", updated_at=old)
        assert cache.is_valid(media) is False

    def test_is_valid_false_when_updated_at_none(self, db_session):
        """is_valid retorna False si updated_at es None."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        media = Media(title="Test", media_type="movie", updated_at=None)
        assert cache.is_valid(media) is False

    @pytest.mark.asyncio
    async def test_get_by_source(self, db_session):
        """get_by_source retorna Media cuando existe source con provider y url."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        await cache.save_media(
            {"title": "La primera vez", "media_type": "movie"},
            [{"provider": "cuevana3", "url": "la-primera-vez"}],
        )

        found = await cache.get_by_source("cuevana3", "la-primera-vez")
        assert found is not None
        assert found.title == "La primera vez"

        not_found = await cache.get_by_source("cuevana3", "otra")
        assert not_found is None


class TestCacheWithTTLZero:
    """Tests con TTL = 0 (caché siempre expirada)."""

    @pytest.mark.asyncio
    async def test_ttl_zero_always_miss(self, db_session, mock_provider):
        """Con TTL=0, cada consulta es miss y llama al adapter."""
        cache = CatalogCache(db_session, ttl_seconds=0)
        service = CatalogService(providers=[mock_provider], cache=cache)

        mock_item = MediaItem(media_id="test_provider:zero-ttl", title="Zero TTL", media_type=MediaType.MOVIE, year=2024, provider="test_provider", provider_id="zero-ttl")
        mock_provider.get_details.return_value = mock_item

        await service.get_details("test_provider", "test_provider:zero-ttl")
        assert mock_provider.get_details.call_count == 1

        await service.get_details("test_provider", "test_provider:zero-ttl")
        assert mock_provider.get_details.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
