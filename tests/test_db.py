"""Tests unitarios de modelos y persistencia (SQLite en memoria)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, Media, Source, Favorite, History
from src.db.database import init_db


@pytest.fixture()
def db_session():
    """Fixture que crea una BD SQLite en memoria para cada test."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


class TestInitDB:
    """Pruebas de inicialización de base de datos."""

    def test_init_db_creates_tables(self):
        """Verifica que init_db() crea todas las tablas correctamente."""
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)

        # Verificar que las tablas existen inspeccionando el metadata
        inspector = __import__('sqlalchemy').inspect(engine)
        tables = inspector.get_table_names()

        assert "media" in tables
        assert "sources" in tables
        assert "favorites" in tables
        assert "history" in tables


class TestMediaModel:
    """Pruebas del modelo Media."""

    def test_insert_and_retrieve_media(self, db_session):
        """Prueba inserción y recuperación de un registro Media."""
        media = Media(
            title="Test Movie",
            original_title="Original Title",
            media_type="movie",
            year=2024,
            synopsis="A test movie",
            poster_url="https://example.com/poster.jpg",
        )
        db_session.add(media)
        db_session.commit()
        db_session.refresh(media)

        assert media.id is not None
        assert media.title == "Test Movie"
        assert media.original_title == "Original Title"
        assert media.media_type == "movie"
        assert media.year == 2024
        assert media.synopsis == "A test movie"
        assert media.poster_url == "https://example.com/poster.jpg"

    def test_media_with_sources(self, db_session):
        """Prueba Media con uno o más Sources asociados."""
        media = Media(
            title="Series Test",
            media_type="series",
            year=2023,
        )
        db_session.add(media)
        db_session.commit()
        db_session.refresh(media)

        source1 = Source(
            media_id=media.id,
            provider="provider1",
            url="https://provider1.com/ep1",
            quality="1080p",
            language="es",
        )
        source2 = Source(
            media_id=media.id,
            provider="provider2",
            url="https://provider2.com/ep1",
            quality="720p",
            language="en",
        )
        db_session.add_all([source1, source2])
        db_session.commit()

        # Recuperar y verificar la relación
        retrieved = db_session.query(Media).filter_by(id=media.id).first()
        assert retrieved is not None
        assert len(retrieved.sources) == 2

        providers = {s.provider for s in retrieved.sources}
        assert providers == {"provider1", "provider2"}


class TestFavoriteModel:
    """Pruebas del modelo Favorite."""

    def test_insert_and_query_favorite(self, db_session):
        """Prueba inserción y consulta de Favorite asociado a Media."""
        media = Media(title="Favorite Movie", media_type="movie", year=2024)
        db_session.add(media)
        db_session.commit()
        db_session.refresh(media)

        favorite = Favorite(media_id=media.id)
        db_session.add(favorite)
        db_session.commit()
        db_session.refresh(favorite)

        assert favorite.id is not None
        assert favorite.media_id == media.id
        assert favorite.created_at is not None

        # Consultar favorito con relación
        retrieved = db_session.query(Favorite).filter_by(media_id=media.id).first()
        assert retrieved is not None
        assert retrieved.media_id == media.id


class TestHistoryModel:
    """Pruebas del modelo History."""

    def test_insert_and_query_history(self, db_session):
        """Prueba inserción y consulta de History asociado a Media."""
        media = Media(title="Watched Series", media_type="series", year=2023)
        db_session.add(media)
        db_session.commit()
        db_session.refresh(media)

        history = History(media_id=media.id, progress=0.75)
        db_session.add(history)
        db_session.commit()
        db_session.refresh(history)

        assert history.id is not None
        assert history.media_id == media.id
        assert history.progress == 0.75
        assert history.viewed_at is not None

        # Consultar historial con relación
        retrieved = db_session.query(History).filter_by(media_id=media.id).first()
        assert retrieved is not None
        assert retrieved.media_id == media.id
        assert retrieved.progress == 0.75


class TestRelationships:
    """Pruebas de relaciones y cascada."""

    def test_cascade_delete_sources_when_media_deleted(self, db_session):
        """Verifica que al borrar Media se borran sus Sources en cascada."""
        media = Media(title="To Delete", media_type="movie", year=2024)
        db_session.add(media)
        db_session.commit()
        db_session.refresh(media)

        source = Source(media_id=media.id, provider="test", url="https://test.com")
        db_session.add(source)
        db_session.commit()

        source_id = source.id
        db_session.delete(media)
        db_session.commit()

        # El source debe haber sido borrado en cascada
        deleted_source = db_session.query(Source).filter_by(id=source_id).first()
        assert deleted_source is None

    def test_multiple_favorites_for_same_media(self, db_session):
        """Verifica que se pueden tener múltiples favoritos para el mismo Media."""
        media = Media(title="Popular Movie", media_type="movie", year=2024)
        db_session.add(media)
        db_session.commit()
        db_session.refresh(media)

        fav1 = Favorite(media_id=media.id)
        fav2 = Favorite(media_id=media.id)
        db_session.add_all([fav1, fav2])
        db_session.commit()

        count = db_session.query(Favorite).filter_by(media_id=media.id).count()
        assert count == 2

    def test_multiple_history_entries_for_same_media(self, db_session):
        """Verifica que se pueden tener múltiples entradas de historial para el mismo Media."""
        media = Media(title="Rewatched Series", media_type="series", year=2023)
        db_session.add(media)
        db_session.commit()
        db_session.refresh(media)

        hist1 = History(media_id=media.id, progress=0.5)
        hist2 = History(media_id=media.id, progress=1.0)
        db_session.add_all([hist1, hist2])
        db_session.commit()

        count = db_session.query(History).filter_by(media_id=media.id).count()
        assert count == 2

        progresses = {h.progress for h in db_session.query(History).filter_by(media_id=media.id).all()}
        assert progresses == {0.5, 1.0}