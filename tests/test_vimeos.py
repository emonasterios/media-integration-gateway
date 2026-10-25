import asyncio
from pathlib import Path

from src.services.resolvers import vimeos

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeSession:
    def __init__(self, *args, **kwargs):
        pass

    async def get(self, url, headers=None):
        packed = (FIXTURES / "vimeos_packed.js").read_text()
        return _FakeResponse(f"<html><body><script>{packed}</script></body></html>")


def test_extracts_m3u8_from_real_packed_embed(monkeypatch):
    monkeypatch.setattr(vimeos.requests, "AsyncSession", _FakeSession)

    result = asyncio.run(
        vimeos.VimeosResolver("https://vimeos.net/embed-0xw2x9uteple.html").extract()
    )

    assert ".m3u8" in result["destination_url"]
    assert result["destination_url"].startswith("http")
