#!/usr/bin/env python
"""Sincroniza un snapshot completo del catálogo con la BD.

Usa (provider, provider_id) como identidad estable. Los borrados solo se
habilitan con un rastreo completo, sin --limit y dentro del umbral de seguridad.
El enriquecimiento costoso queda separado mediante --enrich-new.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.adapters.cuevana3 import Cuevana3Adapter
from src.db.database import AsyncSessionLocal, Base, engine
from src.db.models import CatalogSyncPage, CatalogSyncRun, Media, Source
from src.services.catalog_checkpoint import (
    CatalogCheckpoint,
    CheckpointCorruptedError,
    IncompleteSnapshotError,
    IncompatibleCheckpointError,
    load_checkpoint,
    validate_for_reconciliation,
    save_checkpoint,
)

PROVIDER = "cuevana3"
DEFAULT_CHECKPOINT_PATH = "data/cuevana3_checkpoint.json"


async def run_discovery(
    adapter: Cuevana3Adapter,
    checkpoint_path: Path,
    category: str | None,
    page_limit: int | None = None,
    on_page_progress: Optional[Callable[[int, int], Awaitable[None]]] = None,
) -> CatalogCheckpoint:
    """Ejecuta la fase de descubrimiento con checkpoint duradero y persistencia por página."""
    print(f"Descubriendo catálogo (checkpoint: {checkpoint_path})...")
    
    async def on_page_callback(page_items: list[dict], checkpoint: CatalogCheckpoint) -> None:
        """Callback invocado tras cada página: persiste el lote y guarda checkpoint."""
        from sqlalchemy.ext.asyncio import async_sessionmaker
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        added, updated = await persist_page_batch(session_factory, page_items, checkpoint, checkpoint_path)
        if added or updated:
            print(f"  Página: {added} nuevas, {updated} actualizadas; checkpoint guardado")
        # Callback de progreso por página (no intrusivo): se invoca tras persistir
        # el lote y guardar el checkpoint de la página.
        if on_page_progress is not None:
            pages_count = len(checkpoint.pages_completed)
            total_items = len(checkpoint.items)
            await on_page_progress(pages_count, total_items)
    
    checkpoint = await adapter.discover_resumable(
        checkpoint_path=checkpoint_path,
        category=category,
        page_limit=page_limit,
        on_page=on_page_callback,
    )
    print(
        f"Descubrimiento {'completo' if checkpoint.status == 'complete' else 'pausado'}: "
        f"{len(checkpoint.items)} items en {len(checkpoint.pages_completed)} páginas"
    )
    if checkpoint.next_page:
        print(f"Próxima página: {checkpoint.next_page}")
    return checkpoint


def _next_page_number(checkpoint: CatalogCheckpoint) -> int:
    return (max(checkpoint.pages_completed) + 1) if checkpoint.pages_completed else 1


def print_checkpoint_status(checkpoint: CatalogCheckpoint) -> None:
    """Imprime el resumen del checkpoint."""
    print(f"Proveedor: {checkpoint.provider}")
    print(f"Categoría: {checkpoint.category or 'todas'}")
    print(f"Páginas completadas: {len(checkpoint.pages_completed)}")
    print(f"Total de ítems descubiertos: {len(checkpoint.items)}")
    print(f"Estado: {checkpoint.status}")
    print(f"Razón de parada: {checkpoint.stop_reason or 'ninguna'}")
    print(f"Próxima página: {checkpoint.next_page or 'ninguna (final)'}")


async def persist_page_batch(
    session_factory: async_sessionmaker,
    movies: list[dict],
    checkpoint: CatalogCheckpoint,
    checkpoint_path: Path,
    run_id: str | None = None,
    page_number: int | None = None,
    page_url: str | None = None,
    next_page_url: str | None = None,
) -> tuple[int, int]:
    """Persiste un lote de películas de una página en una transacción aislada.

    Hace upsert idempotente por (provider, provider_id) y confirma la transacción.
    Luego guarda el checkpoint actualizado en disco de forma atómica.

    Returns:
        tuple[int, int]: (added, updated) conteos de este lote.
    """
    added = updated = unchanged = 0
    observed_at = datetime.now(timezone.utc)
    async with session_factory() as db:
        try:
            fingerprint = hashlib.sha256(json.dumps(movies, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            page_row = None
            if run_id is not None and page_number is not None:
                existing_page = await db.execute(
                    select(CatalogSyncPage).where(
                        CatalogSyncPage.run_id == run_id,
                        CatalogSyncPage.page_number == page_number,
                    )
                )
                page_row = existing_page.scalar_one_or_none()
                if page_row is None:
                    page_row = CatalogSyncPage(
                        run_id=run_id,
                        page_number=page_number,
                        page_url=page_url or "",
                        next_page_url=next_page_url,
                        page_fingerprint=fingerprint,
                    )
                    db.add(page_row)
            run_row = None
            if run_id is not None:
                run_row = await db.get(CatalogSyncRun, run_id)
            for item in movies:
                if item.get("media_type") != "movie":
                    continue
                provider_id = item["provider_id"]
                result = await db.execute(
                    select(Source, Media)
                    .join(Media, Source.media_id == Media.id)
                    .where(Source.provider == PROVIDER, Source.url == provider_id)
                )
                current = result.first()
                if current:
                    source, media = current
                    before = (media.title, media.year, media.synopsis, media.poster_url, source.page_url)
                    after = (item["title"], item.get("year"), item.get("overview"), item.get("poster"), item.get("url"))
                    presence_changed = (
                        source.catalog_presence != "present"
                        or source.consecutive_misses != 0
                        or source.missing_since is not None
                    )
                    if before != after or presence_changed:
                        media.title = item["title"]
                        media.original_title = item["title"]
                        media.year = item.get("year")
                        media.synopsis = item.get("overview")
                        media.poster_url = item.get("poster")
                        if item.get("url"):
                            source.page_url = item.get("url")
                        updated += 1
                    else:
                        unchanged += 1
                    source.catalog_presence = "present"
                    source.last_seen_at = observed_at
                    source.last_seen_run_id = run_id if run_id else None
                    source.missing_since = None
                    source.consecutive_misses = 0
                else:
                    media = Media(
                        title=item["title"],
                        original_title=item["title"],
                        media_type=item.get("media_type", "movie"),
                        year=item.get("year"),
                        synopsis=item.get("overview"),
                        poster_url=item.get("poster"),
                        genres=json.dumps(item.get("genres") or []),
                    )
                    media.sources.append(
                        Source(
                            provider=PROVIDER,
                            url=provider_id,
                            page_url=item.get("url"),
                            quality="auto",
                            language="es",
                            catalog_presence="present",
                            last_seen_at=observed_at,
                            last_seen_run_id=run_id if run_id else None,
                            missing_since=None,
                            consecutive_misses=0,
                        )
                    )
                    db.add(media)
                    added += 1
            if page_row is not None:
                page_row.seen = len(movies)
                page_row.unique = len(movies)
                page_row.inserted = added
                page_row.updated = updated
                page_row.unchanged = unchanged
                page_row.duplicate_in_run = 0
                page_row.rejected = 0
            if run_row is not None:
                run_row.pages_completed += 1
                run_row.items_seen += len(movies)
                run_row.items_unique += len(movies)
                run_row.items_inserted += added
                run_row.items_updated += updated
                run_row.items_unchanged += unchanged
                run_row.items_duplicate_in_run += 0
                run_row.items_rejected += 0
                run_row.items_discovered = run_row.items_unique
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    save_checkpoint(checkpoint, checkpoint_path)
    return added, updated


async def sync_from_checkpoint(
    checkpoint_path: Path,
    limit: int | None = None,
    delay: float = 1.0,
    *,
    dry_run: bool = False,
    allow_large_delete: bool = False,
    enrich_new: bool = False,
    expected_category: str | None = None,
    run_id: str | None = None,
) -> None:
    """Reconcilia el catálogo desde un checkpoint en disco.

    Barrera estricta: valida que el checkpoint sea completo y compatible
    ANTES de abrir la base de datos. Si no pasa, aborta con código != 0
    y CERO escrituras en BD.

    La reconciliación de bajas y limpieza de huérfanos solo se ejecuta si
    el checkpoint tiene status='complete' Y stop_reason='natural_end'.
    """
    # 1) Cargar y validar checkpoint (barrera ANTES de BD)
    try:
        checkpoint = load_checkpoint(checkpoint_path)
        validate_for_reconciliation(
            checkpoint,
            expected_provider=PROVIDER,
            expected_category=expected_category,
        )
    except (CheckpointCorruptedError, IncompleteSnapshotError, IncompatibleCheckpointError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    # 2) Construir snapshot desde checkpoint (solo movies)
    snapshot = {
        item["provider_id"]: item
        for item in checkpoint.items
        if item.get("media_type") == "movie"
    }
    print(f"Snapshot desde checkpoint: {len(snapshot)} películas únicas")

    delete_enabled = limit is None
    items = list(snapshot.values())
    if limit is not None:
        items = items[:limit]
        delete_enabled = False
        print(f"Limitando escrituras a {limit}; borrados DESHABILITADOS")

    # 3) Reconciliación por lotes usando persist_page_batch
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    total_added = total_updated = 0

    # Procesar en lotes (páginas) - usamos el callback para persistir por página
    # Pero aquí el checkpoint ya está completo, así que hacemos todo en una transacción
    # para mantener compatibilidad. La persistencia por página ocurre durante discover.
    adapter = Cuevana3Adapter() if enrich_new else None
    observed_at = datetime.now(timezone.utc)
    try:
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
                provider_id = item["provider_id"]
                current = existing.get(provider_id)
                if current:
                    source, media = current
                    media.title = item["title"]
                    media.original_title = item["title"]
                    media.year = item.get("year")
                    if item.get("poster"):
                        media.poster_url = item["poster"]
                    # Actualizar page_url solo si el dato entrante lo trae y no es vacío
                    incoming_page_url = item.get("url")
                    if incoming_page_url:
                        source.page_url = incoming_page_url
                    source.catalog_presence = "present"
                    source.last_seen_at = observed_at
                    source.last_seen_run_id = run_id if run_id else None
                    source.missing_since = None
                    source.consecutive_misses = 0
                    updated += 1
                else:
                    media = Media(
                        title=item["title"],
                        original_title=item["title"],
                        media_type=item.get("media_type", "movie"),
                        year=item.get("year"),
                        poster_url=item.get("poster"),
                        synopsis=item.get("overview"),
                        genres=json.dumps(item.get("genres") or []),
                    )
                    media.sources.append(
                        Source(
                            provider=PROVIDER,
                            url=provider_id,
                            page_url=item.get("url"),
                            quality="auto",
                            language="es",
                            catalog_presence="present",
                            last_seen_at=observed_at,
                            last_seen_run_id=run_id if run_id else None,
                            missing_since=None,
                            consecutive_misses=0,
                        )
                    )
                    db.add(media)
                    new_media[provider_id] = media
                    added += 1

            # FASE DE BAJAS Y HUÉRFANOS - solo si snapshot completo y parada natural
            if checkpoint.status == "complete" and checkpoint.stop_reason == "natural_end":
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
            else:
                print(
                    f"Snapshot incompleto o parada por heurística/límite "
                    f"(razón: {checkpoint.stop_reason}). Bajas deshabilitadas."
                )

            if enrich_new and adapter is not None:
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
                f"{len(orphan_sources) if 'orphan_sources' in locals() else 0} fuentes huérfanas limpiadas, "
                f"{enriched} enriquecidas, {errors} errores"
            )
    finally:
        if adapter is not None:
            await adapter.close()


async def sync_catalog(
    limit: int | None = None,
    delay: float = 1.0,
    *,
    dry_run: bool = False,
    allow_large_delete: bool = False,
    enrich_new: bool = False,
    checkpoint_path: Path | str = DEFAULT_CHECKPOINT_PATH,
    category: str | None = None,
    page_limit: int | None = None,
    on_page_progress: Optional[Callable[[int, int], Awaitable[None]]] = None,
) -> CatalogCheckpoint:
    """Flujo completo: descubrimiento (con checkpoint) + reconciliación."""
    adapter = Cuevana3Adapter()
    try:
        checkpoint = await run_discovery(
            adapter,
            Path(checkpoint_path),
            category,
            page_limit,
            on_page_progress,
        )
        if checkpoint.status != "complete":
            print(
                f"Descubrimiento incompleto ({len(checkpoint.pages_completed)} páginas). "
                f"Use --from-checkpoint {checkpoint_path} para reanudar o reconciliar."
            )
            return checkpoint
        await sync_from_checkpoint(
            Path(checkpoint_path),
            limit=limit,
            delay=delay,
            dry_run=dry_run,
            allow_large_delete=allow_large_delete,
            enrich_new=enrich_new,
            expected_category=category,
        )
        return checkpoint
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
    parser.add_argument(
        "--checkpoint-path",
        type=str,
        default=DEFAULT_CHECKPOINT_PATH,
        help=f"Ruta del archivo de checkpoint (por defecto: {DEFAULT_CHECKPOINT_PATH})",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Categoría/género a rastrear (ej: accion, drama, comedia)",
    )
    parser.add_argument(
        "--page-limit",
        type=int,
        default=None,
        help="Limitar número de páginas a rastrear (checkpoint queda incomplete)",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Ejecutar solo la fase de descubrimiento y guardar checkpoint, sin reconciliar",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Mostrar resumen del checkpoint actual y salir con código 0",
    )
    parser.add_argument(
        "--from-checkpoint",
        action="store_true",
        help="Reconciliar catálogo desde checkpoint en disco (sin rastreo en vivo)",
    )
    args = parser.parse_args()

    if args.status:
        try:
            checkpoint = load_checkpoint(args.checkpoint_path)
            print_checkpoint_status(checkpoint)
            sys.exit(0)
        except CheckpointCorruptedError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)

    if args.from_checkpoint:
        asyncio.run(
            sync_from_checkpoint(
                Path(args.checkpoint_path),
                limit=args.limit,
                delay=args.delay,
                dry_run=args.dry_run,
                allow_large_delete=args.allow_large_delete,
                enrich_new=args.enrich_new,
                expected_category=args.category,
            )
        )
    elif args.discover_only:
        adapter = Cuevana3Adapter()
        try:
            asyncio.run(
                run_discovery(adapter, Path(args.checkpoint_path), args.category, args.page_limit)
            )
        finally:
            asyncio.run(adapter.close())
    else:
        asyncio.run(
            sync_catalog(
                limit=args.limit,
                delay=args.delay,
                dry_run=args.dry_run,
                allow_large_delete=args.allow_large_delete,
                enrich_new=args.enrich_new,
                checkpoint_path=args.checkpoint_path,
                category=args.category,
                page_limit=args.page_limit,
            )
        )
