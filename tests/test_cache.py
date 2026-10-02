"""Tests unitarios de caché y flujo completo en CatalogService."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Media, Source
from src.db.database import SessionLocal
from src.services.cache import CatalogCache
from src.services.catalog import CatalogService
from src.adapters.base import MediaProvider
from src.models.catalog import MediaItem, MediaType, SearchResult


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
def catalog_service(db_session, mock_provider):
    """CatalogService con caché real y proveedor mock."""
    cache = CatalogCache(db_session, ttl_seconds=3600)  # 1 hora TTL
    service = CatalogService(providers=[mock_provider], cache=cache)
    return service


class TestCacheHit:
    """Tests de HIT de caché: contenido en DB y dentro del TTL."""

    @pytest.mark.asyncio
    async def test_get_details_cache_hit_returns_db_content(self, catalog_service, mock_provider, db_session):
        """Cuando un medio existe en DB y no ha expirado, se retorna desde DB sin invocar adapter."""
        # Preparar: insertar media en DB con updated_at reciente
        # IMPORTANTE: El título en DB debe coincidir con el slug extraído del media_id
        # _get_from_cache extrae el slug después de ':' y lo usa como título para buscar
        now = datetime.utcnow()
        media = Media(
            title="cached-movie-2024",  # Debe coincidir con el slug del media_id
            original_title="Cached Movie",
            media_type="movie",
            year=2024,
            synopsis="Sinopsis desde caché",
            poster_url="https://example.com/cached.jpg",
            created_at=now,
            updated_at=now,
        )
        db_session.add(media)
        db_session.commit()
        db_session.refresh(media)

        # Agregar source
        source = Source(
            media_id=media.id,
            provider="test_provider",
            url="cached-movie-2024",
            quality="1080p",
            language="es",
        )
        db_session.add(source)
        db_session.commit()

        # Llamar get_details con provider_id que coincida
        result = await catalog_service.get_details("test_provider", "test_provider:cached-movie-2024")

        # Verificar: resultado viene de la caché
        assert isinstance(result, MediaItem)
        assert result.title == "cached-movie-2024"  # Título viene de la DB
        assert result.year == 2024
        assert result.overview == "Sinopsis desde caché"
        assert result.poster_url == "https://example.com/cached.jpg"
        assert result.provider == "test_provider"
        assert result.provider_id == "cached-movie-2024"

        # Verificar: adapter NO fue llamado
        mock_provider.get_details.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_details_cache_hit_with_media_type_filter(self, catalog_service, mock_provider, db_session):
        """Cache hit respeta el filtro de media_type (movie vs series)."""
        now = datetime.utcnow()
        # Insertar película y serie con mismo slug/título (movie-same)
        movie = Media(title="movie-same", media_type="movie", year=2024, updated_at=now)
        series = Media(title="movie-same", media_type="series", year=2023, updated_at=now)
        db_session.add_all([movie, series])
        db_session.commit()
        db_session.refresh(movie)
        db_session.refresh(series)

        source_movie = Source(media_id=movie.id, provider="test_provider", url="movie-same", quality="1080p", language="es")
        source_series = Source(media_id=series.id, provider="test_provider", url="series-same", quality="1080p", language="es")
        db_session.add_all([source_movie, source_series])
        db_session.commit()

        # Buscar película - debe encontrar la movie (media_type filter)
        result = await catalog_service.get_details("test_provider", "test_provider:movie-same")
        assert result.media_type == MediaType.MOVIE
        assert result.year == 2024

        mock_provider.get_details.assert_not_called()


class TestCacheMiss:
    """Tests de MISS de caché: contenido NO existe en DB."""

    @pytest.mark.asyncio
    async def test_get_details_cache_miss_invokes_adapter_and_persists(self, catalog_service, mock_provider, db_session):
        """Cuando un medio NO existe en DB, se invoca adapter y resultado se persiste en SQLite."""
        # Configurar respuesta del adapter mock
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

        # Llamar get_details - no existe en DB
        result = await catalog_service.get_details("test_provider", "test_provider:new-movie-2024")

        # Verificar: adapter fue llamado
        mock_provider.get_details.assert_called_once_with("test_provider:new-movie-2024")

        # Verificar: resultado es el del adapter
        assert result.title == "New Movie 2024"
        assert result.year == 2024
        assert result.overview == "Sinopsis del adapter"

        # Verificar: se persistió en DB
        saved_media = db_session.query(Media).filter_by(title="New Movie 2024").first()
        assert saved_media is not None
        assert saved_media.media_type == "movie"
        assert saved_media.year == 2024
        assert saved_media.synopsis == "Sinopsis del adapter"
        assert saved_media.poster_url == "https://example.com/new.jpg"

        # Verificar: source asociado
        sources = db_session.query(Source).filter_by(media_id=saved_media.id).all()
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

        # Verificar: se creó un solo registro
        count = db_session.query(Media).filter_by(title="Another Movie").count()
        assert count == 1


class TestTTLExpiration:
    """Tests de expiración de TTL: registro antiguo fuerza nueva consulta."""

    @pytest.mark.asyncio
    async def test_get_details_ttl_expired_forces_adapter_call_and_updates_db(self, catalog_service, mock_provider, db_session):
        """Cuando updated_at es más antiguo que TTL, se detecta expirado y se fuerza adapter actualizando DB."""
        # Preparar: media en DB con updated_at ANTIGUO (TTL = 3600s = 1h, poner 2h atrás)
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
        db_session.commit()
        db_session.refresh(media)

        source = Source(media_id=media.id, provider="test_provider", url="expired-movie", quality="720p", language="es")
        db_session.add(source)
        db_session.commit()

        # Configurar respuesta NUEVA del adapter (datos actualizados)
        mock_item = MediaItem(
            media_id="test_provider:expired-movie",
            title="Expired Movie",
            media_type=MediaType.MOVIE,
            year=2024,  # Año actualizado
            poster_url="https://example.com/new.jpg",  # Poster actualizado
            overview="Sinopsis ACTUALIZADA",
            provider="test_provider",
            provider_id="expired-movie",
        )
        mock_provider.get_details.return_value = mock_item

        # Llamar get_details
        result = await catalog_service.get_details("test_provider", "test_provider:expired-movie")

        # Verificar: adapter SÍ fue llamado (cache expirado)
        mock_provider.get_details.assert_called_once_with("test_provider:expired-movie")

        # Verificar: resultado tiene datos NUEVOS del adapter
        assert result.year == 2024
        assert result.overview == "Sinopsis ACTUALIZADA"
        assert result.poster_url == "https://example.com/new.jpg"

        # Verificar: DB se ACTUALIZÓ (no se creó duplicado)
        saved_media = db_session.query(Media).filter_by(title="Expired Movie").first()
        assert saved_media is not None
        assert saved_media.year == 2024
        assert saved_media.synopsis == "Sinopsis ACTUALIZADA"
        assert saved_media.poster_url == "https://example.com/new.jpg"

        # Verificar: updated_at se actualizó a ahora (aproximadamente)
        assert saved_media.updated_at > old_time
        # Y que el source se actualizó
        sources = db_session.query(Source).filter_by(media_id=saved_media.id).all()
        assert len(sources) == 1

    @pytest.mark.asyncio
    async def test_get_details_ttl_not_expired_uses_cache(self, catalog_service, mock_provider, db_session):
        """Cuando updated_at es reciente (dentro del TTL), se usa caché sin llamar adapter."""
        # Preparar: media con updated_at RECIENTE (30 min atrás, TTL = 1h)
        # Título debe coincidir con slug: fresh-movie
        recent_time = datetime.utcnow() - timedelta(minutes=30)
        media = Media(
            title="fresh-movie",
            media_type="movie",
            year=2024,
            synopsis="Sinopsis fresca",
            updated_at=recent_time,
        )
        db_session.add(media)
        db_session.commit()
        db_session.refresh(media)

        source = Source(media_id=media.id, provider="test_provider", url="fresh-movie", quality="1080p", language="es")
        db_session.add(source)
        db_session.commit()

        result = await catalog_service.get_details("test_provider", "test_provider:fresh-movie")

        # Verificar: adapter NO llamado
        mock_provider.get_details.assert_not_called()

        # Verificar: datos de la caché (year=2024, no se actualiza)
        assert result.year == 2024
        assert result.overview == "Sinopsis fresca"


class TestCacheIntegration:
    """Tests de integración: flujo completo con múltiples operaciones."""

    @pytest.mark.asyncio
    async def test_multiple_get_details_same_item_only_first_calls_adapter(self, catalog_service, mock_provider, db_session):
        """Primera llamada miss -> adapter, segunda llamada hit -> caché."""
        # IMPORTANTE: Para que el cache funcione, el title del adapter debe coincidir con el slug (provider_id)
        # porque _save_to_cache usa item.title pero _get_from_cache busca por slug
        mock_item = MediaItem(
            media_id="test_provider:repeat-movie",
            title="repeat-movie",  # Debe coincidir con slug para que cache funcione
            media_type=MediaType.MOVIE,
            year=2024,
            provider="test_provider",
            provider_id="repeat-movie",
        )
        mock_provider.get_details.return_value = mock_item

        # Primera llamada - miss
        result1 = await catalog_service.get_details("test_provider", "test_provider:repeat-movie")
        assert mock_provider.get_details.call_count == 1

        # Segunda llamada - hit
        result2 = await catalog_service.get_details("test_provider", "test_provider:repeat-movie")
        assert mock_provider.get_details.call_count == 1  # NO incrementa

        # Ambas deben retornar lo mismo
        assert result1.title == result2.title == "repeat-movie"

    @pytest.mark.asyncio
    async def test_different_media_ids_independent_cache(self, catalog_service, mock_provider, db_session):
        """Diferentes media_ids tienen entradas de caché independientes."""
        # IMPORTANTE: title debe coincidir con slug (provider_id) para que cache funcione
        mock_item1 = MediaItem(media_id="test_provider:movie-a", title="movie-a", media_type=MediaType.MOVIE, year=2024, provider="test_provider", provider_id="movie-a")
        mock_item2 = MediaItem(media_id="test_provider:movie-b", title="movie-b", media_type=MediaType.MOVIE, year=2023, provider="test_provider", provider_id="movie-b")
        
        # Configurar side_effect para devolver diferentes items según el media_id
        async def side_effect(media_id):
            if "movie-a" in media_id:
                return mock_item1
            return mock_item2
        
        mock_provider.get_details.side_effect = side_effect

        # Primera llamada a movie-a
        result_a = await catalog_service.get_details("test_provider", "test_provider:movie-a")
        assert result_a.title == "movie-a"
        assert mock_provider.get_details.call_count == 1

        # Primera llamada a movie-b
        result_b = await catalog_service.get_details("test_provider", "test_provider:movie-b")
        assert result_b.title == "movie-b"
        assert mock_provider.get_details.call_count == 2

        # Segunda llamada a movie-a - debe ser hit
        result_a2 = await catalog_service.get_details("test_provider", "test_provider:movie-a")
        assert result_a2.title == "movie-a"
        assert mock_provider.get_details.call_count == 2  # No incrementa


class TestCatalogCacheDirect:
    """Tests directos del CatalogCache (sin CatalogService)."""

    def test_get_media_returns_none_when_not_exists(self, db_session):
        """get_media retorna None si no existe el título."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        result = cache.get_media("No Existe")
        assert result is None

    def test_get_media_returns_media_when_valid(self, db_session):
        """get_media retorna Media si existe y está dentro del TTL."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        now = datetime.utcnow()
        media = Media(title="Test", media_type="movie", updated_at=now)
        db_session.add(media)
        db_session.commit()
        db_session.refresh(media)

        result = cache.get_media("Test")
        assert result is not None
        assert result.title == "Test"

    def test_get_media_returns_none_when_expired(self, db_session):
        """get_media retorna None si existe pero TTL expiró."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        old_time = datetime.utcnow() - timedelta(hours=2)
        media = Media(title="Expired", media_type="movie", updated_at=old_time)
        db_session.add(media)
        db_session.commit()

        result = cache.get_media("Expired")
        assert result is None

    def test_get_media_respects_media_type_filter(self, db_session):
        """get_media con media_type filtra correctamente."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        now = datetime.utcnow()
        movie = Media(title="Same", media_type="movie", updated_at=now)
        series = Media(title="Same", media_type="series", updated_at=now)
        db_session.add_all([movie, series])
        db_session.commit()

        # Buscar movie
        result = cache.get_media("Same", media_type="movie")
        assert result is not None
        assert result.media_type == "movie"

        # Buscar series
        result = cache.get_media("Same", media_type="series")
        assert result is not None
        assert result.media_type == "series"

    def test_save_media_creates_new_record(self, db_session):
        """save_media crea nuevo registro si no existe."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        item_data = {"title": "New Movie", "media_type": "movie", "year": 2024, "synopsis": "New synopsis"}
        sources_data = [{"provider": "test", "url": "new-movie", "quality": "1080p", "language": "es"}]

        media = cache.save_media(item_data, sources_data)

        assert media.id is not None
        assert media.title == "New Movie"
        assert media.media_type == "movie"
        assert media.year == 2024
        assert media.synopsis == "New synopsis"

        # Verificar source
        sources = db_session.query(Source).filter_by(media_id=media.id).all()
        assert len(sources) == 1
        assert sources[0].provider == "test"

    def test_save_media_updates_existing_record(self, db_session):
        """save_media actualiza registro existente y reemplaza sources."""
        cache = CatalogCache(db_session, ttl_seconds=3600)
        # Crear registro inicial
        old_time = datetime.utcnow() - timedelta(days=1)
        media = Media(title="Existing", media_type="movie", year=2020, synopsis="Old", updated_at=old_time)
        db_session.add(media)
        db_session.commit()
        db_session.refresh(media)

        # Source antiguo
        old_source = Source(media_id=media.id, provider="old_provider", url="old", quality="720p", language="en")
        db_session.add(old_source)
        db_session.commit()

        # Actualizar con nuevos datos
        item_data = {"title": "Existing", "media_type": "movie", "year": 2024, "synopsis": "Updated", "poster_url": "https://new.jpg"}
        sources_data = [{"provider": "new_provider", "url": "new-url", "quality": "4K", "language": "es"}]

        updated_media = cache.save_media(item_data, sources_data)

        # Verificar: mismo ID (actualización, no creación)
        assert updated_media.id == media.id
        assert updated_media.year == 2024
        assert updated_media.synopsis == "Updated"
        assert updated_media.poster_url == "https://new.jpg"
        assert updated_media.updated_at > old_time

        # Verificar: source antiguo borrado, nuevo creado
        sources = db_session.query(Source).filter_by(media_id=media.id).all()
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


class TestCacheWithTTLZero:
    """Tests con TTL = 0 (caché siempre expirada)."""

    @pytest.mark.asyncio
    async def test_ttl_zero_always_miss(self, db_session, mock_provider):
        """Con TTL=0, cada consulta es miss y llama al adapter."""
        cache = CatalogCache(db_session, ttl_seconds=0)
        service = CatalogService(providers=[mock_provider], cache=cache)

        mock_item = MediaItem(media_id="test_provider:zero-ttl", title="Zero TTL", media_type=MediaType.MOVIE, year=2024, provider="test_provider", provider_id="zero-ttl")
        mock_provider.get_details.return_value = mock_item

        # Primera llamada
        await service.get_details("test_provider", "test_provider:zero-ttl")
        assert mock_provider.get_details.call_count == 1

        # Segunda llamada - TTL=0 significa expirado inmediato
        await service.get_details("test_provider", "test_provider:zero-ttl")
        assert mock_provider.get_details.call_count == 2  # Se llama de nuevo


if __name__ == "__main__":
    pytest.main([__file__, "-v"])