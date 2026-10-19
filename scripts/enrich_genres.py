from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import or_

from src.adapters.cuevana3 import Cuevana3Adapter
from src.db.database import AsyncSessionLocal
from src.db.models import Media


async def enrich_genres(limit: int | None = None, provider: str = "cuevana3") -> None:
    if provider != "cuevana3":
        raise ValueError(f"Unsupported provider: {provider}")

    adapter = Cuevana3Adapter()
    processed = 0

    async with AsyncSessionLocal() as session:
        query = session.query(Media).filter(
            Media.media_type == "movie",
            or_(Media.genres.is_(None), Media.genres == "[]"),
        )
        if limit is not None:
            query = query.limit(limit)

        result = await session.execute(query.statement)
        movies = result.scalars().all()

        for media in movies:
            details = await adapter.get_details(media.id)
            genres = getattr(details, "genres", None)
            if genres:
                media.genres = json.dumps(genres)
                await session.commit()

            processed += 1
            if processed % 10 == 0:
                print(f"Procesadas {processed} películas")

            await asyncio.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Enriquece géneros de películas sin géneros")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--provider", type=str, default="cuevana3")
    args = parser.parse_args()
    asyncio.run(enrich_genres(limit=args.limit, provider=args.provider))


if __name__ == "__main__":
    main()
