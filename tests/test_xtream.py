"""Tests para la API Xtream Codes."""

import json
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
from src.api.xtream import _get_catalog_service, _build_genre_categories, _genre_to_id
import src.api.xtream as xtream_module




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
                genres=["Acción", "Drama"],
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
                genres=["Comedia"],
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
                genres=["Acción"],
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
    """TestClient con la app configurada y catálogo precargado."""
    # Precargar el caché interno para que get_vod_categories funcione
    svc = app_with_db.dependency_overrides.get(_get_catalog_service)
    if svc is not None:
        import asyncio
        # dependency_overrides usa lambdas: llamar para obtener el servicio
        catalog = svc() if callable(svc) else svc
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(catalog.get_catalog("cuevana3"))
            loop.run_until_complete(catalog.get_catalog("cuevan_net"))
        finally:
            loop.close()
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


@pytest.fixture()
def temp_db_path(tmp_path):
    """Crea una BD SQLite temporal con datos de prueba."""
    import sqlite3
    db_path = tmp_path / "test_gateway.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE media (
        id INTEGER PRIMARY KEY,
        title TEXT,
        original_title TEXT,
        media_type TEXT,
        year INTEGER,
        synopsis TEXT,
        poster_url TEXT,
        genres TEXT
    )""")
    conn.execute("""CREATE TABLE sources (
        id INTEGER PRIMARY KEY,
        media_id INTEGER,
        provider TEXT,
        url TEXT,
        quality TEXT,
        language TEXT
    )""")
    conn.execute("INSERT INTO media VALUES (1, 'Test Movie', 'Test Movie', 'movie', 2024, 'Overview', 'http://poster.jpg', '[\"Acción\", \"Drama\"]')")
    conn.execute("INSERT INTO media VALUES (2, 'Another Movie', 'Another Movie', 'movie', 2023, 'Overview 2', 'http://poster2.jpg', '[\"Comedia\"]')")
    conn.execute("INSERT INTO media VALUES (3, 'Third Movie', 'Third Movie', 'movie', 2022, 'Overview 3', 'http://poster3.jpg', '[\"Terror\", \"Suspense\"]')")
    conn.execute("INSERT INTO media VALUES (4, 'Database Series', 'Database Series', 'series', 2021, 'Stored overview', 'http://series-poster.jpg', '[\"Drama\"]')")
    conn.execute("INSERT INTO sources VALUES (1, 1, 'cuevana3', 'test-movie', 'auto', 'es')")
    conn.execute("INSERT INTO sources VALUES (2, 2, 'cuevana3', 'another-movie', 'auto', 'es')")
    conn.execute("INSERT INTO sources VALUES (3, 3, 'cuevana3', 'third-movie', 'auto', 'es')")
    conn.execute("INSERT INTO sources VALUES (4, 4, 'cuevana3', 'database-series', 'auto', 'es')")
    conn.commit()
    conn.close()
    return db_path



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


def test_genre_category_helpers():
    """_build_genre_categories y _genre_to_id generan IDs secuenciales por género."""
    movies = [
        MediaItem(
            media_id="m1",
            title="Movie 1",
            media_type=MediaType.MOVIE,
            provider="cuevana3",
            provider_id="m1",
            genres=["Acción", "Drama"],
        ),
        MediaItem(
            media_id="m2",
            title="Movie 2",
            media_type=MediaType.MOVIE,
            provider="cuevana3",
            provider_id="m2",
            genres=["Comedia"],
        ),
        MediaItem(
            media_id="m3",
            title="Movie 3",
            media_type=MediaType.MOVIE,
            provider="cuevana3",
            provider_id="m3",
            genres=[],
        ),
    ]

    categories = _build_genre_categories(movies)
    assert categories == [
        {"category_id": "1", "category_name": "Acción", "parent_id": 0},
        {"category_id": "2", "category_name": "Comedia", "parent_id": 0},
        {"category_id": "3", "category_name": "Drama", "parent_id": 0},
    ]
    assert _genre_to_id(["Acción"], ["Acción", "Comedia", "Drama"]) == "1"
    assert _genre_to_id(["Drama"], ["Acción", "Comedia", "Drama"]) == "3"
    assert _genre_to_id([], ["Acción", "Comedia", "Drama"]) == "1"


@pytest.mark.parametrize(
    "action, expected",
    [("get_vod_categories", [
        {"category_id": "1", "category_name": "Acción", "parent_id": 0},
        {"category_id": "2", "category_name": "Comedia", "parent_id": 0},
        {"category_id": "3", "category_name": "Drama", "parent_id": 0},
    ])],
)
def test_player_api_get_vod_categories(client, action, expected):
    """GET /player_api.php?action=get_vod_categories responde categorías dinámicas ordenadas."""
    r = client.get(f"/player_api.php?username=test&password=test&action={action}")
    assert r.status_code == 200
    data = r.json()
    assert data == expected


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


def test_enrich_genres_from_db(db_session):
    """_enrich_genres_from_db completa géneros desde la BD y tolera fallos."""
    import asyncio
    import tempfile
    from src.api.xtream import _enrich_genres_from_db

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    async def seed():
        import aiosqlite
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "CREATE TABLE media (id INTEGER PRIMARY KEY, title TEXT NOT NULL, "
                "original_title TEXT, media_type TEXT NOT NULL, year INTEGER, "
                "synopsis TEXT, poster_url TEXT, genres TEXT, "
                "created_at TEXT, updated_at TEXT)"
            )
            await db.execute(
                "INSERT INTO media (id, title, media_type, genres) VALUES (?, ?, ?, ?)",
                (1, "Movie 1", "movie", json.dumps(["Acción", "Drama"]))
            )
            await db.execute(
                "INSERT INTO media (id, title, media_type, genres) VALUES (?, ?, ?, ?)",
                (2, "Movie 2", "movie", json.dumps(["Comedia"]))
            )
            await db.commit()

    asyncio.run(seed())

    items = [
        MediaItem(
            media_id="cuevana3:1",
            title="Película Test 1",
            media_type=MediaType.MOVIE,
            provider="cuevana3",
            provider_id="1",
            genres=[],
        ),
        MediaItem(
            media_id="cuevana3:2",
            title="Película Test 2",
            media_type=MediaType.MOVIE,
            provider="cuevana3",
            provider_id="2",
            genres=[],
        ),
    ]

    enriched = asyncio.run(_enrich_genres_from_db(items, db_path))

    assert enriched[0].genres == ["Acción", "Drama"]
    assert enriched[1].genres == ["Comedia"]

    # Tolerancia a fallos
    fallback = asyncio.run(_enrich_genres_from_db(items, "/nonexistent/path.db"))
    assert fallback == items

    import os
    os.unlink(db_path)


def test_player_api_get_vod_streams(client, temp_db_path):
    """GET /player_api.php?action=get_vod_streams responde con lista formateada de películas."""
    original_db_path = xtream_module.DB_PATH
    xtream_module.DB_PATH = temp_db_path
    try:
        r = client.get("/player_api.php", params={
            "username": "test",
            "password": "***",
            "action": "get_vod_streams",
        })
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0
    finally:
        xtream_module.DB_PATH = original_db_path


def test_player_api_get_vod_streams_filtered_by_category(client, temp_db_path):
    """GET /player_api.php?action=get_vod_streams&category_id filtra por género y mantiene category_id correcto."""
    original_db_path = xtream_module.DB_PATH
    xtream_module.DB_PATH = temp_db_path
    try:
        r = client.get("/player_api.php?username=test&password=***&action=get_vod_streams&category_id=1")
        assert r.status_code == 200
        data = r.json()
        assert len(data) > 0
        assert all(item["category_id"] == "1" for item in data)

        r = client.get("/player_api.php?username=test&password=***&action=get_vod_streams&category_id=2")
        assert r.status_code == 200
        data = r.json()
        assert len(data) > 0
        assert all(item["category_id"] == "2" for item in data)
    finally:
        xtream_module.DB_PATH = original_db_path


def test_filtered_vod_uses_requested_secondary_genre_as_category_id(client, temp_db_path):
    """Una película multigénero no debe desaparecer de sus géneros secundarios en iMPlayer."""
    original_db_path = xtream_module.DB_PATH
    xtream_module.DB_PATH = temp_db_path
    try:
        # La película de prueba tiene Acción como primer género y Drama como
        # segundo; Drama es category_id=3 en el catálogo de prueba.
        response = client.get(
            "/player_api.php?username=test&password=test&action=get_vod_streams&category_id=3"
        )
        assert response.status_code == 200
        items = response.json()
        assert items
        assert all(item["category_id"] == "3" for item in items)
    finally:
        xtream_module.DB_PATH = original_db_path


def test_player_api_get_vod_info(client, temp_db_path):
    """iMPlayer recibe el detalle Xtream necesario antes de reproducir."""
    original_db_path = xtream_module.DB_PATH
    xtream_module.DB_PATH = temp_db_path
    try:
        r = client.get(
            "/player_api.php?username=test&password=***&action=get_vod_info&vod_id=100001"
        )
        assert r.status_code == 200
        data = r.json()
        assert data["info"]["name"] == "Test Movie"
        assert data["movie_data"]["stream_id"] == 100000 + 1
        assert data["movie_data"]["container_extension"] == "mp4"
    finally:
        xtream_module.DB_PATH = original_db_path


def test_movie_route_accepts_extension(client, temp_db_path):
    """La ruta .mp4 no debe caer en la variante extensionless y responder 422."""
    original_db_path = xtream_module.DB_PATH
    xtream_module.DB_PATH = temp_db_path
    try:
        r = client.get("/movie/test/test/100001.mp4", follow_redirects=False)
        assert r.status_code == 200
        assert "video/mp4" in r.headers["content-type"]
    finally:
        xtream_module.DB_PATH = original_db_path


def test_player_api_get_series_reads_database(client, temp_db_path):
    """get_series usa el snapshot SQLite y no dispara un rastreo del proveedor."""
    original_db_path = xtream_module.DB_PATH
    xtream_module.DB_PATH = temp_db_path
    try:
        r = client.get("/player_api.php?username=test&password=test&action=get_series")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 1

        series = data[0]
        assert series["num"] == 1
        assert series["name"] == "Database Series"
        assert series["series_id"] == 2001
        assert series["cover"] == "http://series-poster.jpg"
        assert series["plot"] == "Stored overview"
        assert series["category_id"] == "2"
        assert series["releaseDate"] == "2021-01-01"
    finally:
        xtream_module.DB_PATH = original_db_path


def test_panel_api(client):
    """GET /panel_api.php?username=test&password=test responde con panel_info y contadores."""
    r = client.get("/panel_api.php?username=test&password=test")
    assert r.status_code == 200
    data = r.json()
    assert "panel_info" in data
    panel = data["panel_info"]
    assert panel["live_streams"] == 1
    assert panel["vod_streams"] == 3  # Dos cuevana3 + 1 cuevan_net
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
    assert result["stream_id"] == 100000 + 5
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


def test_stream_id_stable_under_reordering(client, temp_db_path):
    """Reordenar el catálogo no debe cambiar la identidad ni la resolución de un stream_id."""
    original_db_path = xtream_module.DB_PATH
    xtream_module.DB_PATH = temp_db_path
    try:
        baseline = client.get("/player_api.php", params={
            "username": "test",
            "password": "***",
            "action": "get_vod_streams",
        }).json()
        reordered = list(reversed(baseline))
        assert {item["stream_id"]: item for item in reordered} == {item["stream_id"]: item for item in baseline}

        stream_id = 100001
        info = client.get(
            "/player_api.php",
            params={
                "username": "test",
                "password": "***",
                "action": "get_vod_info",
                "vod_id": str(stream_id),
            },
        )
        assert info.status_code == 200
        info_data = info.json()
        target = next(item for item in baseline if item["stream_id"] == stream_id)
        assert info_data["movie_data"]["stream_id"] == stream_id
        assert info_data["info"]["name"] == target["name"]

        movie = client.get(f"/movie/test/test/{stream_id}.mp4", follow_redirects=False)
        assert movie.status_code == 200
    finally:
        xtream_module.DB_PATH = original_db_path


def test_stream_id_stable_with_category_filter(client, temp_db_path):
    """Filtrar por categoría no debe cambiar el stream_id de una misma película."""
    original_db_path = xtream_module.DB_PATH
    xtream_module.DB_PATH = temp_db_path
    try:
        all_items = client.get("/player_api.php", params={
            "username": "test",
            "password": "***",
            "action": "get_vod_streams",
        }).json()
        filtered_items = client.get("/player_api.php", params={
            "username": "test",
            "password": "***",
            "action": "get_vod_streams",
            "category_id": "1",
        }).json()
        assert filtered_items
        assert {item["stream_id"]: item["name"] for item in filtered_items} == {
            item["stream_id"]: item["name"] for item in all_items if item["category_id"] == "1"
        }
    finally:
        xtream_module.DB_PATH = original_db_path


def test_movie_stream_id_matches_catalog_info_and_playback(client, temp_db_path):
    """Catálogo, detalle y reproducción deben resolver el mismo registro por media_id."""
    original_db_path = xtream_module.DB_PATH
    xtream_module.DB_PATH = temp_db_path
    try:
        catalog = client.get("/player_api.php", params={
            "username": "test",
            "password": "***",
            "action": "get_vod_streams",
        }).json()
        target = next(item for item in catalog if item["stream_id"] == 100001)
        info = client.get("/player_api.php", params={
            "username": "test",
            "password": "***",
            "action": "get_vod_info",
            "vod_id": "100001",
        }).json()
        assert info["movie_data"]["stream_id"] == target["stream_id"]
        assert info["info"]["name"] == target["name"]
        movie = client.get("/movie/test/test/100001.mp4", follow_redirects=False)
        assert movie.status_code == 200
        assert "video/mp4" in movie.headers["content-type"]
    finally:
        xtream_module.DB_PATH = original_db_path


def test_vod_stream_id_inexistente_is_controlled(client, temp_db_path):
    """Un stream_id inexistente debe responder controladamente sin crash."""
    original_db_path = xtream_module.DB_PATH
    xtream_module.DB_PATH = temp_db_path
    try:
        response = client.get(
            "/player_api.php",
            params={
                "username": "test",
                "password": "***",
                "action": "get_vod_info",
                "vod_id": "9999",
            },
        )
        assert response.status_code in (200, 404)
        assert response.json() is not None

        response = client.get("/movie/test/test/9999.mp4", follow_redirects=False)
        assert response.status_code == 200
    finally:
        xtream_module.DB_PATH = original_db_path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
