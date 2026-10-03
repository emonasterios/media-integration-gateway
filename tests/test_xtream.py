"""Tests para la API Xtream Codes."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.main import create_app
from src.db.database import Base, get_db
from src.services.catalog import CatalogService
from src.adapters.base import MediaProvider
from src.models.catalog import MediaItem, MediaType, SearchResult, PlaybackDescriptor, Season, Episode
from src.api.xtream import _get_catalog_service


class FakeCuevana3Provider(MediaProvider):
    """Proveedor fake cuevana3 para tests de Xtream."""

    @property
    def name(self) -> str:
        return "cuevana3"

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
        return [
            MediaItem(
                media_id="cuevana3:movie1",
                title="Película Test 1",
                media_type=MediaType.MOVIE,
                provider="cuevana3",
                provider_id="movie1",
                poster_url="https://example.com/movie1.jpg",
                overview="Descripción película 1",
                year=2023,
            ),
            MediaItem(
                media_id="cuevana3:movie2",
                title="Película Test 2",
                media_type=MediaType.MOVIE,
                provider="cuevana3",
                provider_id="movie2",
                poster_url="https://example.com/movie2.jpg",
                overview="Descripción película 2",
                year=2024,
            ),
            MediaItem(
                media_id="cuevana3:series1",
                title="Serie Test 1",
                media_type=MediaType.SERIES,
                provider="cuevana3",
                provider_id="series1",
                poster_url="https://example.com/series1.jpg",
                overview="Descripción serie 1",
                year=2022,
            ),
        ]


class FakeCuevanNetProvider(MediaProvider):
    """Proveedor fake cuevan_net para tests de Xtream (catálogo fusionado)."""

    @property
    def name(self) -> str:
        return "cuevan_net"

    async def search(self, query: str) -> SearchResult:
        return SearchResult(items=[], total=0, query=query)

    async def get_details(self, media_id: str) -> MediaItem:
        return MediaItem(
            media_id=f"cuevan_net:{media_id}", title="Test CN", media_type=MediaType.MOVIE,
            provider="cuevan_net", provider_id=media_id,
        )

    async def get_seasons(self, media_id: str) -> list[Season]:
        return []

    async def get_episodes(self, media_id: str, season_number: int) -> list[Episode]:
        return []

    async def resolve_playback(self, media_id: str) -> PlaybackDescriptor:
        return PlaybackDescriptor(protocol="hls", url="https://example.com/stream.m3u8")

    async def get_catalog(self, category: str | None = None) -> list[MediaItem]:
        return [
            MediaItem(
                media_id="cuevan_net:cn1",
                title="Película CN 1",
                media_type=MediaType.MOVIE,
                provider="cuevan_net",
                provider_id="cn1",
                poster_url="https://example.com/cn1.jpg",
                overview="Descripción CN 1",
                year=2024,
            ),
        ]


@pytest.fixture()
def db_engine():
    """Crea un engine SQLite en memoria con StaticPool."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def app_with_db(db_engine):
    """App FastAPI con override de BD en memoria y catalog fake."""
    svc = CatalogService(providers=[FakeCuevana3Provider(), FakeCuevanNetProvider()])

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app = create_app(override_catalog=svc)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[_get_catalog_service] = lambda: svc
    return app


@pytest.fixture()
def client(app_with_db):
    """TestClient con la app configurada."""
    with TestClient(app_with_db) as c:
        yield c


@pytest.fixture()
def db_session(db_engine):
    """Sesión de BD para insertar datos de prueba."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_player_api_auth_valid(client):
    """GET /player_api.php?username=test&password=test responde 200 y user_info.auth == 1."""
    r = client.get("/player_api.php?username=test&password=test")
    assert r.status_code == 200
    data = r.json()
    assert data["user_info"]["auth"] == 1
    assert "server_info" in data


def test_player_api_auth_invalid(client):
    """GET /player_api.php sin username/password o con campos vacíos responde auth=0."""
    # Sin parámetros
    r = client.get("/player_api.php")
    assert r.status_code == 200
    data = r.json()
    assert data == {"user_info": {"auth": 0}, "server_info": {}}

    # Con username/password vacíos
    r = client.get("/player_api.php?username=&password=")
    assert r.status_code == 200
    data = r.json()
    assert data == {"user_info": {"auth": 0}, "server_info": {}}


def test_player_api_default_action(client):
    """GET /player_api.php con credenciales válidas y sin action responde user_info + server_info."""
    r = client.get("/player_api.php?username=test&password=test")
    assert r.status_code == 200
    data = r.json()
    assert "user_info" in data
    assert "server_info" in data
    assert data["user_info"]["auth"] == 1
    assert data["user_info"]["username"] == "test"
    assert data["user_info"]["status"] == "Active"
    assert "url" in data["server_info"]
    assert "timezone" in data["server_info"]
    assert data["server_info"]["url"] == "testserver"
    assert data["server_info"]["port"] == "80"
    assert data["server_info"]["server_protocol"] == "http"


def test_player_api_advertises_external_host_and_port(client):
    """Xtream anuncia la dirección vista por el cliente, no el puerto interno."""
    r = client.get(
        "/player_api.php?username=test&password=test",
        headers={"host": "192.168.50.229:9193"},
    )
    assert r.status_code == 200
    server_info = r.json()["server_info"]
    assert server_info["url"] == "192.168.50.229"
    assert server_info["port"] == "9193"
    assert server_info["server_protocol"] == "http"


def test_player_api_honors_forwarded_https(client):
    """Xtream anuncia HTTPS cuando un proxy TLS termina la conexión."""
    r = client.get(
        "/player_api.php?username=test&password=test",
        headers={
            "host": "codeserver.example.ts.net:9446",
            "x-forwarded-proto": "https",
        },
    )
    assert r.status_code == 200
    server_info = r.json()["server_info"]
    assert server_info["url"] == "codeserver.example.ts.net"
    assert server_info["port"] == "9446"
    assert server_info["https_port"] == "9446"
    assert server_info["server_protocol"] == "https"


def test_player_api_get_vod_categories(client):
    """GET /player_api.php?action=get_vod_categories responde con categoría Películas."""
    r = client.get("/player_api.php?username=test&password=test&action=get_vod_categories")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["category_id"] == "1"
    assert data[0]["category_name"] == "Peliculas"
    assert data[0]["parent_id"] == 0


def test_player_api_get_series_categories(client):
    """GET /player_api.php?action=get_series_categories responde con categoría Series."""
    r = client.get("/player_api.php?username=test&password=test&action=get_series_categories")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["category_id"] == "2"
    assert data[0]["category_name"] == "Series"
    assert data[0]["parent_id"] == 0


def test_player_api_get_live_categories(client):
    """GET /player_api.php?action=get_live_categories responde con categoría TV en Vivo."""
    r = client.get("/player_api.php?username=test&password=test&action=get_live_categories")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["category_id"] == "3"
    assert data[0]["category_name"] == "TV en Vivo"
    assert data[0]["parent_id"] == 0


def test_player_api_get_live_streams(client):
    """Xtream publica una entrada live para clientes que rechazan listas vacías."""
    r = client.get("/player_api.php?username=test&password=test&action=get_live_streams")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["stream_type"] == "live"
    assert data[0]["stream_id"] == 1
    assert data[0]["category_id"] == "3"


def test_player_api_get_vod_streams(client):
    """GET /player_api.php?action=get_vod_streams responde con lista formateada de películas."""
    r = client.get("/player_api.php?username=test&password=test&action=get_vod_streams")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 2  # Dos películas del FakeProvider

    # Verificar estructura de la primera película
    stream1 = data[0]
    assert stream1["num"] == 1
    assert stream1["name"] == "Película Test 1"
    assert stream1["stream_type"] == "movie"
    assert stream1["stream_id"] == 1001
    assert stream1["stream_icon"] == "https://example.com/movie1.jpg"
    assert stream1["category_id"] == "1"
    assert stream1["container_extension"] == "mp4"

    # Verificar segunda película
    stream2 = data[1]
    assert stream2["num"] == 2
    assert stream2["name"] == "Película Test 2"
    assert stream2["stream_id"] == 1002


def test_player_api_get_series(client):
    """GET /player_api.php?action=get_series responde con lista formateada de series."""
    r = client.get("/player_api.php?username=test&password=test&action=get_series")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1  # Una serie del FakeProvider

    series = data[0]
    assert series["num"] == 1
    assert series["name"] == "Serie Test 1"
    assert series["series_id"] == 2001
    assert series["cover"] == "https://example.com/series1.jpg"
    assert series["plot"] == "Descripción serie 1"
    assert series["category_id"] == "2"
    assert series["releaseDate"] == "2022-01-01"


def test_panel_api(client):
    """GET /panel_api.php?username=test&password=test responde con panel_info y contadores."""
    r = client.get("/panel_api.php?username=test&password=test")
    assert r.status_code == 200
    data = r.json()
    assert "panel_info" in data
    panel = data["panel_info"]
    assert panel["live_streams"] == 1
    assert panel["vod_streams"] == 2  # Dos películas
    assert panel["series_streams"] == 1  # Una serie
    assert panel["episodes"] == 0
    assert panel["active_connections"] == 0
    assert panel["max_connections"] == 1


def test_panel_api_auth_invalid(client):
    """GET /panel_api.php sin credenciales responde auth=0."""
    r = client.get("/panel_api.php")
    assert r.status_code == 200
    data = r.json()
    assert data == {"user_info": {"auth": 0}, "server_info": {}}


def test_vod_stream_conversion():
    """Test unitario de _media_item_to_vod_stream con MediaItem tipo MOVIE."""
    from src.api.xtream import _media_item_to_vod_stream

    item = MediaItem(
        media_id="cuevana3:movie1",
        title="Test Movie",
        media_type=MediaType.MOVIE,
        provider="cuevana3",
        provider_id="movie1",
        poster_url="https://example.com/test.jpg",
        overview="Test overview",
        year=2023,
    )

    result = _media_item_to_vod_stream(item, 5)

    assert result["num"] == 5
    assert result["name"] == "Test Movie"
    assert result["stream_type"] == "movie"
    assert result["stream_id"] == 1005
    assert result["stream_icon"] == "https://example.com/test.jpg"
    assert result["rating"] == "0"
    assert result["rating_5based"] == 0.0
    assert result["added"] == str(int(2023 * 31536000))
    assert result["category_id"] == "1"
    assert result["container_extension"] == "mp4"
    assert result["custom_sid"] == ""
    assert result["direct_source"] == ""


def test_series_stream_conversion():
    """Test unitario de _media_item_to_series_stream con MediaItem tipo SERIES."""
    from src.api.xtream import _media_item_to_series_stream

    item = MediaItem(
        media_id="cuevana3:series1",
        title="Test Series",
        media_type=MediaType.SERIES,
        provider="cuevana3",
        provider_id="series1",
        poster_url="https://example.com/series.jpg",
        overview="Test series overview",
        year=2022,
    )

    result = _media_item_to_series_stream(item, 3)

    assert result["num"] == 3
    assert result["name"] == "Test Series"
    assert result["series_id"] == 2003
    assert result["cover"] == "https://example.com/series.jpg"
    assert result["plot"] == "Test series overview"
    assert result["cast"] == ""
    assert result["director"] == ""
    assert result["genre"] == ""
    assert result["releaseDate"] == "2022-01-01"
    assert result["last_modified"] == ""
    assert result["rating"] == "0"
    assert result["rating_5based"] == 0.0
    assert result["backdrop_path"] == []
    assert result["youtube_trailer"] == ""
    assert result["episode_run_time"] == 0
    assert result["category_id"] == "2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
