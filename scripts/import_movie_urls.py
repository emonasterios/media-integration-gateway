#!/usr/bin/env python3
"""Importa una película desde uno o más mirrors mediante el servicio de catálogo."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.database import AsyncSessionLocal  # noqa: E402
from src.services.cache import CatalogCache  # noqa: E402


PROVIDERS = {
    "cuevana3s.live": "cuevana3",
    "cuevanavideo.pro": "cuevanavideo",
}


def identity_from_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    provider = PROVIDERS.get(host)
    if provider is None:
        raise ValueError(f"mirror no admitido: {host}")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0] not in {"pelicula", "peliculas"}:
        raise ValueError(f"URL de película no reconocida: {url}")
    return provider, parts[1]


async def fetch_metadata(client: httpx.AsyncClient, url: str) -> dict:
    response = await client.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    og_title = soup.select_one('meta[property="og:title"]')
    og_description = soup.select_one('meta[property="og:description"]')
    og_image = soup.select_one('meta[property="og:image"]')
    raw_title = (og_title.get("content") if og_title else None) or soup.title.string
    match = re.search(r"(?:Ver\s+)?(.+?)\s*\(((?:19|20)\d{2})\)", raw_title or "")
    if not match:
        raise ValueError(f"no se pudo extraer título y año de {url}")
    return {
        "title": match.group(1).strip(),
        "year": int(match.group(2)),
        "synopsis": (og_description.get("content") or "").strip() if og_description else None,
        "poster_url": (og_image.get("content") or "").strip() if og_image else None,
    }


async def import_movie(urls: list[str]) -> None:
    identities = [(*identity_from_url(url), url) for url in urls]
    slugs = {slug.casefold() for _, slug, _ in identities}
    if len(slugs) != 1:
        raise ValueError("los mirrors no tienen la misma identidad de película")

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:
        metadata = [await fetch_metadata(client, url) for url in urls]

    titles = {(item["title"].casefold(), item["year"]) for item in metadata}
    if len(titles) != 1:
        raise ValueError("los mirrors no describen la misma película")

    sources = [
        {
            "provider": provider,
            # El proveedor principal conserva el slug que consume la API Xtream.
            # Los mirrors secundarios usan su URL completa para que su identidad
            # sea inequívoca aunque compartan slug con el principal.
            "url": slug if provider == "cuevana3" else url.rstrip("/"),
            "page_url": url,
            "quality": "HD",
            "language": "es",
            "catalog_presence": "present",
        }
        for provider, slug, url in identities
    ]
    async with AsyncSessionLocal() as db:
        media = await CatalogCache(db).save_media(
            {**metadata[0], "original_title": metadata[0]["title"], "media_type": "movie"},
            sources,
        )
        print(f"media_id={media.id} title={media.title!r} year={media.year} sources={len(media.sources)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="+", help="URLs mirror de la misma película")
    args = parser.parse_args()
    asyncio.run(import_movie(args.urls))


if __name__ == "__main__":
    main()
