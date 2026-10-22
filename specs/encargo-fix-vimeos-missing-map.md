---
name: fix-vimeos-missing-in-extractor-map
description: Agregar vimeos.net al _EXTRACTOR_MAP en mediaflow_bridge.py — el obrero lo olvidó en la ronda anterior.
---

# Corrección: vimeos.net falta en _EXTRACTOR_MAP

## Qué hacer
En `src/services/mediaflow_bridge.py`, agregar `"vimeos.net": VimeosResolver,` al diccionario `_EXTRACTOR_MAP`.

El import ya existe (línea ~14): `from .resolvers.vimeos import VimeosResolver`
Solo falta la entrada en el mapa.

## ACEPTACION
grep -q "vimeos.net" src/services/mediaflow_bridge.py
cd /app && python3 -m py_compile src/services/mediaflow_bridge.py

## PREMISES
- src/services/mediaflow_bridge.py tiene el import de VimeosResolver pero NO la entrada en _EXTRACTOR_MAP
- VimeosResolver está en src/services/resolvers/vimeos.py (ya creado)
- El _EXTRACTOR_MAP está en la línea ~37 del archivo
