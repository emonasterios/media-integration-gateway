# Corregir sincronización que avanza páginas sin progreso

## Objetivo

Impedir que `scripts/sync_catalog.py` recorra indefinidamente páginas sin añadir
elementos y garantizar que una reanudación solo avance cuando existe progreso
real verificable.

## Hechos verificados en producción

- Repositorio canónico: `emonasterios/media-integration-gateway`, rama `main`.
- El 2026-10-21 se reanudó
  `/app/data/cuevana3-discovery-v1.json` desde la página 2831.
- El proceso avanzó hasta la página 5336 manteniendo exactamente 19528 ítems en
  el checkpoint.
- SQLite permaneció en 19520 filas de `media` y 20327 de `sources`; su archivo
  no cambió durante la corrida.
- El checkpoint terminó `incomplete`, sin `stop_reason`, apuntando a la página
  5337.
- El contenedor de sincronización fue detenido; el gateway continúa saludable.
- El código declara una parada por `no_new_items`, pero esa protección no cortó
  la corrida real.

## Encargo

1. Reproducir en una prueba el comportamiento observado, incluyendo la
   reanudación desde un checkpoint grande y páginas que no aumentan el conjunto
   de identidades.
2. Encontrar la causa real; no limitarse a aumentar umbrales ni a ocultar el
   síntoma.
3. Corregir el descubrimiento para que el contador de falta de progreso sea
   fiable durante una corrida y seguro al reanudar.
4. Añadir un fusible determinista adicional que impida miles de solicitudes si
   el sitio entrega paginación anómala. No debe convertir una parada artificial
   en `natural_end` ni habilitar reconciliación destructiva.
5. Conservar el contrato: únicamente `complete` + `natural_end` permite bajas;
   una parada por falta de progreso queda `incomplete` con razón explícita.
6. Mejorar la observabilidad mínima necesaria para que logs/checkpoint indiquen
   progreso real, páginas sin novedades y causa de parada.
7. No modificar ni desplegar la base o el checkpoint de producción. No relanzar
   el crawler desde la fábrica.

## Restricciones

- Mantener compatibilidad de lectura con checkpoints existentes.
- Persistencia atómica por página.
- No borrar películas ni fuentes.
- No tocar credenciales, configuración de Telegram ni infraestructura.
- Cambios acotados al crawler, checkpoint, CLI y sus pruebas/documentación
  directamente relacionadas.

## ACEPTACION

```bash
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest -q tests/test_catalog_sync.py tests/test_catalog_checkpoint.py tests/test_cuevana3.py
```

Además, las pruebas deben demostrar de forma explícita que:

- tres páginas consecutivas sin identidades nuevas detienen la corrida;
- el checkpoint queda `incomplete` y con `stop_reason=no_new_items`;
- una reanudación anómala no puede realizar miles de solicitudes;
- ninguna parada artificial habilita reconciliación de bajas;
- una paginación normal con novedades sigue llegando a `natural_end`.

PREMISES

I `discover_resumable` declara `no_new_pages_threshold=3` — src/adapters/cuevana3.py:261
I El contador `pages_without_new` se inicializa en memoria al comenzar cada invocación — src/adapters/cuevana3.py:358
I La falta de progreso se calcula comparando la longitud del checkpoint antes y después de deduplicar — src/adapters/cuevana3.py:468
I Al alcanzar el umbral, el código asigna `stop_reason=no_new_items` — src/adapters/cuevana3.py:487
I El callback de persistencia se ejecuta antes de guardar nuevamente el checkpoint — src/adapters/cuevana3.py:498
I El CLI persiste por página mediante `persist_page_batch` y guarda el checkpoint tras confirmar la transacción — scripts/sync_catalog.py:47
I La validación para reconciliación rechaza snapshots cuya parada no sea natural — src/services/catalog_checkpoint.py:167
I Ya existen pruebas unitarias para `repeated_page`, `no_new_items` y `max_pages` — tests/test_catalog_sync.py:325
