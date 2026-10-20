#!/usr/bin/env python
"""Sincronizar el catálogo completo desde el adapter con la BD.

Elimina huérfanos (películas que ya no existen en el catálogo) y agrega las nuevas.
"""
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
from sqlalchemy import select, delete


async def sync_catalog(limit: int | None = None, delay: float = 1.0) -> None:
    adapter = Cuevana3Adapter()
    
    async with AsyncSessionLocal() as db:
        cache = CatalogCache(db)
        
        # Obtener catálogo actual
        print("Obteniendo catálogo de cuevana3...")
        catalog = await adapter.get_catalog()
        movies = [m for m in catalog if m.media_type.value == 'movie']
        print(f"Catálogo actual: {len(movies)} películas")
        
        if limit:
            movies = movies[:limit]
            print(f"Limitando a {limit} items")
        
        # Obtener títulos existentes en la BD
        stmt = select(Media.title, Media.id)
        result = await db.execute(stmt)
        existing = {row[0]: row[1] for row in result.fetchall()}
        
        # Catálogo actual (títulos)
        catalog_titles = {m.title for m in movies}
        
        # Encontrar huérfanos (en BD pero no en catálogo)
        orphaned = {title: id for title, id in existing.items() if title not in catalog_titles}
        print(f"Huérfanos a eliminar: {len(orphaned)}")
        
        # Eliminar huérfanos
        if orphaned:
            for title, media_id in orphaned.items():
                await db.execute(delete(Media).where(Media.id == media_id))
                print(f"  ✗ Eliminado: {title} (id={media_id})")
            await db.commit()
        
        # Agregar nuevas películas
        new_movies = [m for m in movies if m.title not in existing]
        print(f"Nuevas películas a agregar: {len(new_movies)}")
        
        added = 0
        errors = 0
        
        for i, item in enumerate(new_movies, 1):
            title = item.title
            try:
                details = await adapter.get_details(item.media_id)
                
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
                added += 1
                
                genres_str = ", ".join(details.genres[:3]) if details.genres else "sin géneros"
                print(f"[{i}/{len(new_movies)}] ✓ {title} -> {genres_str}")
                
                await asyncio.sleep(delay)
                
            except Exception as e:
                errors += 1
                print(f"[{i}/{len(new_movies)}] ✗ {title}: {e}")
        
        # Contar resultado final
        stmt = select(Media.title)
        result = await db.execute(stmt)
        total = len(result.fetchall())
        print(f"\nResumen: {len(orphaned)} eliminados, {added} nuevos, {errors} errores")
        print(f"Total en BD: {total} películas")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sincronizar catálogo con la BD")
    parser.add_argument("--limit", type=int, default=None, help="Limitar a N items")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay entre requests")
    args = parser.parse_args()
    
    asyncio.run(sync_catalog(limit=args.limit, delay=args.delay))
