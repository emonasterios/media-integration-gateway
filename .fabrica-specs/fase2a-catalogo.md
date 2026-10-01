# Fase 2a: Adapter Cuevana3 — Catálogo

## Qué hacer
Reescribir `search()` y `get_catalog()` en `src/adapters/cuevana3.py` con selectores reales.

## Selectores reales (verificados)
- Items: `div.TPost a` → href a `/pelicula/{slug}/` o `/serie/{slug}/`
- Título: texto del link (ej: "Signal One (2026)")
- Imagen: `figure.Objf img` con `src`
- Año: extraer con regex `\((\d{4})\)`

## Límites
- NO tocar base.py, models, tests existentes
- Solo modificar cuevana3.py y agregar tests nuevos

## ACEPTACION
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v

## PREMISES
- src/adapters/cuevana3.py tiene selectores incorrectos (.item, .poster)
- src/adapters/base.py define search() y get_catalog()
- tests/test_smoke.py pasa (9/9)
