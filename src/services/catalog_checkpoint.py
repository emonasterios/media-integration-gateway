"""Gestión de checkpoints atómicos para el descubrimiento de catálogo.

El rastreo completo del catálogo puede fallar a mitad de camino (p. ej., un
fallo de red en la página 860). Este módulo persiste el progreso del
descubrimiento en un checkpoint JSON escrito de forma atómica (archivo
temporal + ``os.replace``) para que una caída nunca deje un archivo truncado
ni parcial en la ruta final.

Regla de seguridad crítica: un checkpoint solo puede reconciliarse con la
base de datos si su ``status`` es estrictamente ``"complete"``. Reconciliar
un snapshot incompleto o corrupto haría que la sincronización lo interprete
como el catálogo completo y active el borrado masivo de registros válidos.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError

CHECKPOINT_VERSION = 2

CheckpointStatus = Literal["incomplete", "complete"]
StopReason = Literal[
    None,
    "natural_end",
    "pagination_cycle",
    "repeated_page",
    "no_new_items",
    "max_pages",
    "interrupted",
]


class CheckpointError(Exception):
    """Error base del sistema de checkpoints de catálogo."""


class CheckpointCorruptedError(CheckpointError):
    """El checkpoint no existe, está corrupto o tiene una versión incompatible."""


class IncompleteSnapshotError(CheckpointError):
    """El checkpoint no representa un snapshot completo; prohibido reconciliar."""


class IncompatibleCheckpointError(CheckpointError):
    """El checkpoint pertenece a otro proveedor o a otra categoría."""


class CatalogCheckpoint(BaseModel):
    """Estado duradero del descubrimiento página a página del catálogo.

    - ``version``: versión del formato para detectar incompatibilidades.
    - ``provider`` / ``category``: identidad del rastreo (ej. ``cuevana3``).
    - ``initial_path``: ruta inicial del rastreo (ej. ``/peliculas/``).
    - ``next_page``: enlace de la siguiente página pendiente (``None`` al final).
    - ``pages_completed``: números de páginas ya confirmadas en disco.
    - ``items``: elementos del listado con metadatos (``provider``, ``provider_id``,
      ``title``, ``url``, ``poster``, ``category``...), deduplicados por
      ``(provider, provider_id)``.
    - ``status``: estrictamente ``"incomplete"`` o ``"complete"``.
    - ``stop_reason``: razón de parada (``natural_end``, ``pagination_cycle``,
      ``repeated_page``, ``no_new_items``, ``max_pages``, ``interrupted``).
      Solo ``natural_end`` habilita la reconciliación de bajas.
    """

    version: int = CHECKPOINT_VERSION
    provider: str
    category: Optional[str] = None
    initial_path: str
    next_page: Optional[str] = None
    pages_completed: list[int] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    status: CheckpointStatus = "incomplete"
    stop_reason: StopReason = None


def save_checkpoint(checkpoint: CatalogCheckpoint, target_path: Path | str) -> None:
    """Persiste el checkpoint de forma atómica en ``target_path``.

    Escribe primero en un archivo temporal del mismo directorio, hace flush y
    ``fsync`` para forzar el contenido a disco y luego reemplaza el archivo
    final con ``os.replace`` (atómico). Una caída a mitad de escritura nunca
    deja un checkpoint truncado: como mucho pervive el checkpoint previo
    íntegro y el ``.tmp`` parcial, que nunca se lee como checkpoint válido.
    """
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    payload = json.dumps(
        checkpoint.model_dump(mode="json"), ensure_ascii=False, indent=2
    )
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        # La escritura falló: limpiar el temporal para no dejar residuos.
        # El checkpoint previo en target_path permanece inalterado.
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    # Mejor esfuerzo: hacer durable también el renombrado (fsync del directorio).
    try:
        dir_fd = os.open(target.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def load_checkpoint(target_path: Path | str) -> CatalogCheckpoint:
    """Carga y valida un checkpoint desde disco.

    Lanza :class:`CheckpointCorruptedError` si el archivo no existe, es
    ilegible, su JSON está corrupto, no es un objeto, su versión es
    incompatible o su esquema es inválido.
    """
    target = Path(target_path)
    if not target.is_file():
        raise CheckpointCorruptedError(f"Checkpoint inexistente: {target}")
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise CheckpointCorruptedError(f"Checkpoint ilegible: {target}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CheckpointCorruptedError(
            f"Checkpoint corrupto (JSON inválido): {target}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise CheckpointCorruptedError(
            f"Checkpoint corrupto (no es un objeto JSON): {target}"
        )
    version = payload.get("version")
    if version == 1:
        # Retrocompatibilidad: checkpoint v1 sin stop_reason
        payload = dict(payload)
        payload["version"] = CHECKPOINT_VERSION
        payload.setdefault("stop_reason", None)
    elif version != CHECKPOINT_VERSION:
        raise CheckpointCorruptedError(
            f"Versión de checkpoint incompatible: esperada {CHECKPOINT_VERSION}, "
            f"encontrada {version!r} en {target}"
        )
    try:
        return CatalogCheckpoint.model_validate(payload)
    except ValidationError as exc:
        raise CheckpointCorruptedError(
            f"Checkpoint corrupto (esquema inválido): {target}: {exc}"
        ) from exc


def validate_for_reconciliation(
    checkpoint: CatalogCheckpoint,
    expected_provider: str,
    expected_category: Optional[str] = None,
) -> None:
    """Compuerta estricta antes de reconciliar el checkpoint con la base de datos.

    - Exige ``status == "complete"``; si es ``"incomplete"`` lanza
      :class:`IncompleteSnapshotError` para impedir el borrado masivo basado
      en un snapshot parcial.
    - Exige ``stop_reason == "natural_end"``; cualquier otro valor
      (``pagination_cycle``, ``repeated_page``, ``no_new_items``,
      ``max_pages``, ``interrupted``, ``None``) lanza
      :class:`IncompleteSnapshotError` para impedir
      la reconciliación de bajas sobre snapshots truncados artificialmente.
    - Exige que proveedor y categoría coincidan con los esperados; si no,
      lanza :class:`IncompatibleCheckpointError`.
    """
    # Primero validar proveedor y categoría (compatibilidad con tests existentes)
    if checkpoint.provider != expected_provider:
        raise IncompatibleCheckpointError(
            f"Proveedor del checkpoint ({checkpoint.provider!r}) no coincide con "
            f"el esperado ({expected_provider!r})"
        )
    if (checkpoint.category or None) != (expected_category or None):
        raise IncompatibleCheckpointError(
            f"Categoría del checkpoint ({checkpoint.category!r}) no coincide con "
            f"la esperada ({expected_category!r})"
        )
    # Luego validar completitud y stop_reason
    if checkpoint.status != "complete":
        raise IncompleteSnapshotError(
            "Snapshot incompleto: prohibido reconciliar con la base de datos "
            f"(status={checkpoint.status!r}, next_page={checkpoint.next_page!r})"
        )
    # Aceptar parada natural explícita (natural_end) o compatibilidad v1/legacy:
    # next_page=None con stop_reason=None indica fin natural sin marcar explícitamente
    if not (
        checkpoint.stop_reason == "natural_end"
        or (checkpoint.next_page is None and checkpoint.stop_reason is None)
    ):
        raise IncompleteSnapshotError(
            "Snapshot con parada no natural: prohibido reconciliar bajas "
            f"(stop_reason={checkpoint.stop_reason!r}, next_page={checkpoint.next_page!r})"
        )


def add_items_deduplicated(
    existing_items: list[dict], new_items: list[dict]
) -> list[dict]:
    """Fusiona ``new_items`` en ``existing_items`` sin duplicados.

    Deduplica por la clave compuesta ``(item["provider"], item["provider_id"])``
    preservando el orden de aparición: los elementos existentes conservan su
    posición y los nuevos solo se añaden la primera vez que aparece su clave.
    """
    merged = list(existing_items)
    seen = {(item["provider"], item["provider_id"]) for item in existing_items}
    for item in new_items:
        key = (item["provider"], item["provider_id"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged
