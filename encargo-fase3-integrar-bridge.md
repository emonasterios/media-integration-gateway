# Encargo: Integrar mediaflow_bridge en video_resolver

## Qué hacer
En `src/services/video_resolver.py`, al inicio de `resolve_doodstream` (línea ~132) y `resolve_voe` (línea ~206), agregar intento con mediaflow_bridge antes del código existente.

### En resolve_doodstream, después del docstring, antes de todo lo demás:
```python
        # Intentar con mediaflow-proxy primero
        from src.services.mediaflow_bridge import resolve_with_mediaflow
        result = await resolve_with_mediaflow(embed_url, "doodstream.com")
        if result:
            return result
```

### En resolve_voe, después del docstring, antes de todo lo demás:
```python
        # Intentar con mediaflow-proxy primero
        from src.services.mediaflow_bridge import resolve_with_mediaflow
        result = await resolve_with_mediaflow(embed_url, "voe.sx")
        if result:
            return result
```

## Qué NO tocar
- Nada más en video_resolver.py
- adapters/cuevana3.py, adapters/cuevan_net.py
- Tests
- resolve_streamtape, resolve_morencius

## ACEPTACION
```
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v -x
```

## PREMISES
- src/services/mediaflow_bridge.py existe con función resolve_with_mediaflow(embed_url, domain)
- src/services/video_resolver.py:132 — resolve_doodstream empieza con httpx directo
- src/services/video_resolver.py:206 — resolve_voe usa FlareSolverr
- mediaflow-proxy ya está instalado en .venv
