# Encargo: Mockear `_validate_video_url` en 5 tests de doodstream

## Qué hacer
En `tests/test_video_resolver.py`, envolver la llamada `await resolver.resolve_doodstream(...)` con `patch.object(resolver, "_validate_video_url", return_value=True)` en estos 5 tests:

1. `test_resolve_doodstream_success` (línea ~149)
2. `test_resolve_doodstream_pass_md5_error` (línea ~233)
3. `test_resolve_doodstream_invalid_pass_md5_response` (línea ~249)
4. `test_resolve_doodstream_alternative_token_format` (línea ~264)
5. `test_resolve_doodstream_different_domain` (línea ~282)

### Patrón exacto
```python
# ANTES:
result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")

# DESPUÉS:
with patch.object(resolver, "_validate_video_url", return_value=True):
    result = await resolver.resolve_doodstream("https://doodstream.com/e/abc123")
```

Para `test_resolve_doodstream_different_domain`, el patch va dentro del `for` donde se llama `resolve_doodstream(embed_url)`.

Si no existe ya, agregar `from unittest.mock import patch` en los imports del archivo.

## NO tocar
- Nada en `src/`
- Ningún otro test
- La lógica de `_validate_video_url`

## ACEPTACION
```
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/test_video_resolver.py -v -k doodstream
```

## PREMISES
- src/services/video_resolver.py:87 — `_validate_video_url` crea su propio `httpx.AsyncClient`, no usa `self._client`
- src/services/video_resolver.py:200 — `resolve_doodstream` llama `await self._validate_video_url(video_url, ...)` al final
- tests/test_video_resolver.py:158 — mockea `resolver._client.get` pero no intercepta `_validate_video_url`
