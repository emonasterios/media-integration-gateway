"""Servicio de enriquecimiento automático del catálogo."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from src.adapters.base import MediaProvider
from src.models.catalog import MediaItem, MediaType

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentStats:
    """Estadísticas de una corrida de enriquecimiento."""
    total: int = 0
    processed: int = 0
    enriched: int = 0
    failed: int = 0
    skipped: int = 0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    current_item: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def progress_pct(self) -> float:
        return (self.processed / self.total * 100) if self.total > 0 else 0.0

    @property
    def elapsed(self) -> float:
        end = self.finished_at or time.time()
        return end - (self.started_at or end)

    @property
    def eta_seconds(self) -> float:
        if self.processed == 0 or self.elapsed == 0:
            return 0.0
        rate = self.processed / self.elapsed
        remaining = self.total - self.processed
        return remaining / rate if rate > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "processed": self.processed,
            "enriched": self.enriched,
            "failed": self.failed,
            "skipped": self.skipped,
            "progress_pct": round(self.progress_pct, 1),
            "elapsed_s": round(self.elapsed, 1),
            "eta_s": round(self.eta_seconds, 1),
            "current_item": self.current_item,
            "running": self.finished_at is None,
            "errors": self.errors[-10:],  # últimos 10 errores
        }


class CatalogEnricher:
    """Recorre el catálogo y enriquece cada item con get_details del adapter."""

    def __init__(self, providers: list[MediaProvider] | None = None):
        self._providers: dict[str, MediaProvider] = {}
        if providers:
            self._providers = {p.name: p for p in providers}
        self._stats: Optional[EnrichmentStats] = None
        self._running = False

    def set_providers(self, providers: list[MediaProvider]) -> None:
        self._providers = {p.name: p for p in providers}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> Optional[dict]:
        return self._stats.to_dict() if self._stats else None

    async def run(
        self,
        provider: str | None = None,
        media_type: MediaType | None = MediaType.MOVIE,
        concurrency: int = 3,
        delay: float = 0.5,
        force: bool = False,
    ) -> dict:
        """Ejecuta el enriquecimiento del catálogo.

        Args:
            provider: Nombre del proveedor (None = todos).
            media_type: Tipo de medio a enriquecer (None = todos).
            concurrency: Número de items procesados en paralelo.
            delay: Segundos entre requests al mismo proveedor.
            force: Re-enriquecer incluso si ya tiene datos.
        """
        if self._running:
            return {"error": "Enriquecimiento ya en curso", "stats": self.stats}

        self._running = True
        self._stats = EnrichmentStats(started_at=time.time())

        targets = (
            [self._providers[provider]]
            if provider
            else list(self._providers.values())
        )

        # Recolectar catálogo
        all_items: list[MediaItem] = []
        for p in targets:
            try:
                catalog = await p.get_catalog()
                if media_type:
                    catalog = [i for i in catalog if i.media_type == media_type]
                all_items.extend(catalog)
            except Exception as e:
                logger.error("Error obteniendo catálogo de %s: %s", p.name, e)
                self._stats.errors.append(f"{p.name}: {e}")

        self._stats.total = len(all_items)
        logger.info("Iniciando enriquecimiento: %d items", self._stats.total)

        # Semáforo por proveedor para respetar delays
        semaphores = {p.name: asyncio.Semaphore(concurrency) for p in targets}
        stats = self._stats  # local ref for closure

        async def enrich_item(item: MediaItem) -> None:
            async with semaphores[item.provider]:
                stats.current_item = item.title
                stats.processed += 1

                # Verificar si ya está enriquecido
                if not force and item.overview and item.genres:
                    stats.skipped += 1
                    return

                try:
                    details = await self._providers[item.provider].get_details(
                        item.provider_id
                    )
                    # Actualizar campos enriquecidos
                    if details.overview:
                        item.overview = details.overview
                    if details.director:
                        item.director = details.director
                    if details.cast:
                        item.cast = details.cast
                    if details.country:
                        item.country = details.country
                    if details.trailer_url:
                        item.trailer_url = details.trailer_url
                    if details.duration:
                        item.duration = details.duration
                    if details.genres:
                        item.genres = details.genres
                    if details.rating:
                        item.rating = details.rating
                    if details.poster_url:
                        item.poster_url = details.poster_url
                    if details.year:
                        item.year = details.year
                    if details.available_languages:
                        item.available_languages = details.available_languages

                    stats.enriched += 1
                    logger.debug(
                        "Enriquecido: %s (%s)", item.title, item.provider
                    )
                except Exception as e:
                    stats.failed += 1
                    err_msg = f"{item.title}: {e}"
                    stats.errors.append(err_msg)
                    logger.warning("Fallo enriqueciendo %s: %s", item.title, e)

                await asyncio.sleep(delay)

        # Procesar en lotes
        tasks = [enrich_item(item) for item in all_items]
        await asyncio.gather(*tasks, return_exceptions=True)

        self._stats.finished_at = time.time()
        self._running = False
        logger.info(
            "Enriquecimiento completado: %d/%d enriquecidos, %d fallos",
            self._stats.enriched,
            self._stats.total,
            self._stats.failed,
        )
        return self._stats.to_dict()
