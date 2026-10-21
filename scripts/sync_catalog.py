#!/usr/bin/env python
"""Sincroniza un snapshot completo del catálogo con la BD.

Usa (provider, provider_id) como identidad estable. Los borrados solo se
habilitan con un rastreo completo, sin --limit y dentro del umbral de seguridad.
El enriquecimiento costoso queda separado mediante --enrich-new.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from src.adapters.cuevana3 import Cuevana3Adapter
from src.db.database import AsyncSessionLocal
from src.db.models import Media, Source

PROVIDER = "cuevana3"


async def sync_catalog(
    limit: int | None = None,
    delay: float = 1.0,
    *,
    dry_run: bool = False,
    allow_large_delete: bool = False,
    enrich_new: bool = False,
) -> None:
    adapter = Cuevana3Adapter()
    try:
        print("Descubriendo catálogo completo de cuevana3...")
        catalog = await adapter.get_catalog()
        snapshot = {
            item.provider_id: item
            for item in catalog
            if item.media_type.value == "movie"
        }
        print(f"Snapshot completo: {len(snapshot)} películas únicas")

        delete_enabled = limit is None
        items = list(snapshot.values())
        if limit is not None:
            items = items[:limit]
            delete_enabled = False
            print(f"Limitando escrituras a {limit}; borrados DESHABILITADOS")

        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(Source, Media)
                    .join(Media, Source.media_id == Media.id)
                    .where(Source.provider == PROVIDER, Media.media_type == "movie")
                )
            ).all()
            existing = {source.url: (source, media) for source, media in rows}
            missing_ids = set(existing) - set(snapshot)

            if delete_enabled and len(existing) >= 10:
                ratio = len(missing_ids) / len(existing)
                if ratio > 0.25 and not allow_large_delete:
                    raise RuntimeError(
                        f"Protección activada: se eliminaría {len(missing_ids)}/"
                        f"{len(existing)} ({ratio:.1%}). Revise el snapshot y use "
                        "--allow-large-delete si el cambio es intencional."
                    )

            added = updated = deleted_sources = deleted_media = enriched = errors = 0
            new_media: dict[str, Media] = {}

            for item in items:
                current = existing.get(item.provider_id)
                if current:
                    _source, media = current
                    media.title = item.title
                    media.original_title = item.title
                    media.year = item.year
                    if item.poster_url:
                        media.poster_url = item.poster_url
                    updated += 1
                else:
                    media = Media(
                        title=item.title,
                        original_title=item.title,
                        media_type=item.media_type.value,
                        year=item.year,
                        poster_url=item.poster_url,
                        synopsis=item.overview,
                        genres=json.dumps(item.genres or []),
                    )
                    media.sources.append(
                        Source(
                            provider=PROVIDER,
                            url=item.provider_id,
                            quality="auto",
                            language="es",
                        )
                    )
                    db.add(media)
                    new_media[item.provider_id] = media
                    added += 1

            if delete_enabled:
                for provider_id in missing_ids:
                    source, media = existing[provider_id]
                    await db.delete(source)
                    await db.flush()
                    remaining = await db.scalar(
                        select(Source.id).where(Source.media_id == media.id).limit(1)
                    )
                    if remaining is None:
                        await db.delete(media)
                        deleted_media += 1
                    deleted_sources += 1

            # Limpia residuos si SQLite no aplicó la FK en ejecuciones anteriores.
            orphan_sources = (
                await db.execute(
                    select(Source).where(~Source.media_id.in_(select(Media.id)))
                )
            ).scalars().all()
            for source in orphan_sources:
                await db.delete(source)

            if enrich_new:
                for index, (provider_id, media) in enumerate(new_media.items(), 1):
                    try:
                        details = await adapter.get_details(provider_id)
                        media.title = details.title
                        media.original_title = details.title
                        media.year = details.year
                        media.synopsis = details.overview
                        media.poster_url = details.poster_url
                        media.genres = json.dumps(details.genres or [])
                        enriched += 1
                        print(f"[{index}/{len(new_media)}] enriquecida: {details.title}")
                        await asyncio.sleep(delay)
                    except Exception as exc:
                        errors += 1
                        print(f"[{index}/{len(new_media)}] error {provider_id}: {exc}")

            if dry_run:
                await db.rollback()
                action = "SIMULACIÓN (rollback)"
            else:
                await db.commit()
                action = "APLICADO"

            print(
                f"{action}: {added} nuevas, {updated} actualizadas, "
                f"{deleted_sources} fuentes retiradas, {deleted_media} medios retirados, "
                f"{len(orphan_sources)} fuentes huérfanas limpiadas, "
                f"{enriched} enriquecidas, {errors} errores"
            )
    finally:
        await adapter.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sincronizar catálogo con la BD")
    parser.add_argument("--limit", type=int, default=None, help="Limitar escrituras (nunca borra)")
    parser.add_argument("--delay", type=float, default=1.0, help="Pausa del enriquecimiento")
    parser.add_argument("--dry-run", action="store_true", help="Validar y revertir la transacción")
    parser.add_argument(
        "--allow-large-delete",
        action="store_true",
        help="Autorizar que desaparezca más del 25%% del catálogo existente",
    )
    parser.add_argument(
        "--enrich-new",
        action="store_true",
        help="Consultar detalles solo para las películas nuevas",
    )
    args = parser.parse_args()
    asyncio.run(
        sync_catalog(
            limit=args.limit,
            delay=args.delay,
            dry_run=args.dry_run,
            allow_large_delete=args.allow_large_delete,
            enrich_new=args.enrich_new,
        )
    )
