"""Tests de humo para el Media Integration Gateway."""

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.services.catalog import CatalogService
from src.adapters.base import MediaProvider
from src.models.catalog import (
    MediaItem, MediaType, SearchResult, PlaybackDescriptor, Season, Episode
)


class FakeProvider(MediaProvider):
    @property
    def name(self) -> str:
        return "fake"

    async def search(self, query: str) -> SearchResult:
        return SearchResult(
            items=[
                MediaItem(
                    media_id="fake:1", title="Test Movie", media_type=MediaType.MOVIE,
                    provider="fake", provider_id="1",
                )
            ],
            total=1, query=query,
        )

    async def get_details(self, media_id: str) -> MediaItem:
        return MediaItem(
            media_id=f"fake:{media_id}", title="Test Movie", media_type=MediaType.MOVIE,
            provider="fake", provider_id=media_id,
        )

    async def get_seasons(self, media_id: str) -> list[Season]:
        return [Season(season_number=1, episode_count=3)]

    async def get_episodes(self, media_id: str, season_number: int) -> list[Episode]:
        return [
            Episode(episode_number=i, season_number=season_number, provider_id=f"ep-{i}", provider="fake")
            for i in range(1, 4)
        ]

    async def resolve_playback(self, media_id: str) -> PlaybackDescriptor:
        return PlaybackDescriptor(protocol="mp4", url="https://example.com/video.mp4")

    async def get_catalog(self, category: str | None = None) -> list[MediaItem]:
        return [
            MediaItem(
                media_id="fake:1", title="Test Movie", media_type=MediaType.MOVIE,
                provider="fake", provider_id="1",
            )
        ]


@pytest.fixture()
def client():
    svc = CatalogService(providers=[FakeProvider()])
    test_app = create_app(override_catalog=svc)
    with TestClient(test_app) as c:
        yield c


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_providers(client):
    r = client.get("/api/v1/providers")
    assert r.status_code == 200
    assert "fake" in r.json()


def test_search(client):
    r = client.get("/api/v1/search", params={"q": "test"})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["query"] == "test"


def test_catalog(client):
    r = client.get("/api/v1/catalog/fake")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_details(client):
    r = client.get("/api/v1/details/fake/1")
    assert r.status_code == 200
    assert r.json()["title"] == "Test Movie"


def test_seasons(client):
    r = client.get("/api/v1/seasons/fake/1")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_episodes(client):
    r = client.get("/api/v1/episodes/fake/1/1")
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_resolve_playback(client):
    r = client.post("/api/v1/playback/resolve/fake/1")
    assert r.status_code == 200
    assert r.json()["url"] == "https://example.com/video.mp4"


def test_unknown_provider(client):
    r = client.get("/api/v1/catalog/nonexistent")
    assert r.status_code == 404
