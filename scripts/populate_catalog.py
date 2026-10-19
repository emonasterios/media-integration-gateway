#!/usr/bin/env python
"""Poblar la BD con el catálogo completo desde el adapter, extrayendo géneros."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Agregar el directorio raíz del proyecto al sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.cuevana3 import Cuevana3Adapter
from src.db.database import AsyncSessionLocal
from src.db.models import Media
from src.services.cache import CatalogCache
from sqlalchemy import select


async def populate_catalog(limit: int | None = None, delay: float = 1.0) -> None:
    adapter = Cuevana3Adapter()
    
    async with AsyncSessionLocal() as db:
        cache = CatalogCache(db)
        
        # Obtener catálogo
        print("Obteniendo catálogo de cuevana3...")
        catalog = await adapter.get_catalog()
        print(f"Total items en catálogo: {len(catalog)}")
        
        if limit:
            catalog = catalog[:limit]
            print(f"Limitando a {limit} items")
        
        # Verificar cuáles ya están en la BD
        stmt = select(Media.title)
        result = await db.execute(stmt)
        existing_titles = {row[0] for row in result.fetchall()}
        
        enriched = 0
        skipped = 0
        errors = 0
        
        for i, item in enumerate(catalog, 1):
            title = item.title
            if title in existing_titles:
                skipped += 1
                continue
            
            try:
                # Obtener detalles con géneros
                details = await adapter.get_details(item.media_id)
                
                # Preparar datos para la BD
                item_data = {
                    "title": details.title,
                    "original_title": details.title,
                    "media_type": details.media_type.value,
                    "year": details.year,
                    "synopsis": details.overview,
                    "poster_url": details.poster_url,
                    "genres": json.dumps(details.genres) if details.genres else "[]",
                }
                
                sources_data = [{
                    "provider": details.provider,
                    "url": details.provider_id,
                    "quality": "auto",
                    "language": "es",
                }]
                
                await cache.save_media(item_data, sources_data)
                enriched += 1
                
                genres_str = ", ".join(details.genres[:3]) if details.genres else "sin géneros"
                print(f"[{i}/{len(catalog)}] ✓ {title} -> {genres_str}")
                
                await asyncio.sleep(delay)
                
            except Exception as e:
                errors += 1
                print(f"[{i}/{len(catalog)}] ✗ {title}: {e}")
        
        print(f"\nResumen: {enriched} nuevos, {skipped} existentes, {errors} errores")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Poblar BD con catálogo y géneros")
    parser.add_argument("--limit", type=int, default=None, help="Limitar a N items")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay entre requests")
    args = parser.parse_args()
    
    asyncio.run(populate_catalog(limit=args.limit, delay=args.delay))
