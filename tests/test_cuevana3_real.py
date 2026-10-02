"""Tests de integración para Cuevana3Adapter usando fixtures HTML reales."""

import pytest
import httpx
from unittest.mock import AsyncMock, patch
from pathlib import Path

from src.adapters.cuevana3 import Cuevana3Adapter
from src.models.catalog import MediaType, PlaybackDescriptor


# ----------------------------------------------------------------------
# Helpers para cargar fixtures
# ----------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Carga un archivo HTML de fixture."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


CATALOG_HTML = load_fixture("cuevana3_catalogo_peliculas.html")
DETAIL_HTML = load_fixture("cuevana3_pelicula_signal-one.html")


# ----------------------------------------------------------------------
# Fixture de adapter con cliente mockeado
# ----------------------------------------------------------------------


@pytest.fixture
def adapter():
    """Fixture que provee un Cuevana3Adapter con cliente mockeado."""
    adapter = Cuevana3Adapter()
    adapter._client = AsyncMock()
    yield adapter


# ----------------------------------------------------------------------
# Prueba de catálogo con fixture real
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_catalog_real_fixture(adapter):
    """Validar get_catalog con HTML real del catálogo (cuevana3_catalogo_peliculas.html)."""
    adapter._client.get.return_value = AsyncMock(
        text=CATALOG_HTML,
        status_code=200,
        raise_for_status=lambda: None,
    )

    items = await adapter.get_catalog()

    # Buscar la película signal-one en la lista resultante
    signal_one = next((item for item in items if item.provider_id == "signal-one"), None)
    assert signal_one is not None, "La película 'signal-one' debe estar en el catálogo"

    # Verificar que el año es 2026
    assert signal_one.year == 2026, f"Se esperaba year=2026, se obtuvo {signal_one.year}"

    # Verificar otros campos básicos (title puede incluir el año por extracción de texto real)
    assert "Signal One" in signal_one.title
    assert signal_one.media_type == MediaType.MOVIE
    assert signal_one.provider == "cuevana3"
    assert signal_one.media_id == "cuevana3:signal-one"


# ----------------------------------------------------------------------
# Prueba de detalles con fixture real
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_details_real_fixture(adapter):
    """Validar get_details con HTML real de la película (cuevana3_pelicula_signal-one.html)."""
    adapter._client.get.return_value = AsyncMock(
        text=DETAIL_HTML,
        status_code=200,
        raise_for_status=lambda: None,
    )

    item = await adapter.get_details("cuevana3:signal-one")

    # Verificar overview comienza con el texto esperado
    assert item.overview is not None
    assert item.overview.startswith(
        "Entre las producciones más comentadas"
    ), f"overview debe empezar con 'Entre las producciones más comentadas', empieza con: {item.overview[:80]}"

    # Verificar año
    assert item.year == 2026, f"Se esperaba year=2026, se obtuvo {item.year}"

    # Verificar otros campos
    assert item.title == "Signal One"
    assert item.media_type == MediaType.MOVIE
    assert item.provider == "cuevana3"
    assert item.provider_id == "signal-one"


# ----------------------------------------------------------------------
# Prueba de reproducción con fixture real
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_playback_real_fixture(adapter):
    """Validar resolve_playback con HTML real de la película (cuevana3_pelicula_signal-one.html)."""
    adapter._client.get.return_value = AsyncMock(
        text=DETAIL_HTML,
        status_code=200,
        raise_for_status=lambda: None,
    )

    result = await adapter.resolve_playback("cuevana3:signal-one")

    # Verificar descriptor de reproducción
    assert isinstance(result, PlaybackDescriptor)
    assert result.protocol == "embed"
    assert result.url == "https://doodstream.com/e/jtri5tfbukk6"
    assert result.headers.get("Referer") == "https://cuevana3i.cc"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])