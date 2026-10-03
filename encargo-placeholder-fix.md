# Fix: Rechazar placeholder URLs y devolver 500 cuando no hay video real

## Problema
Cuando Doodstream no puede resolver un video, devuelve un placeholder (test-videos.co.uk). El gateway acepta esto como válido y redirige al cliente, que reproduce el video de prueba en vez de la película.

## Cambios requeridos

### 1. src/services/video_resolver.py — Rechazar URLs sospechosas

En `_validate_video_url()`, agregar verificación de que la URL final no sea un placeholder conocido:

```python
# Lista de dominios de placeholder/test a rechazar
PLACEHOLDER_DOMAINS = (
    "test-videos.co.uk",
    "sample-videos.com",
    "file-examples.com",
)

# Después de seguir redirects y obtener final_url:
from urllib.parse import urlparse
final_host = urlparse(str(final_url)).hostname or ""
if any(domain in final_host for domain in PLACEHOLDER_DOMAINS):
    logger.warning("URL rechazada: placeholder detectado (%s)", final_url[:80])
    return False
```

### 2. src/api/xtream.py — No hacer fallback a embed cuando resolver falla

En `stream_movie()` (líneas ~280-304), cambiar el comportamiento:

```python
# Si es embed HTML, intentar resolver el video real
if result.protocol == "embed":
    from src.services.video_resolver import VideoResolver
    resolver = VideoResolver()
    try:
        if VideoResolver.is_voe(result.url):
            direct = await resolver.resolve_voe(result.url)
            if direct and direct.protocol in ("hls", "mp4"):
                result = direct
                logger.info("Redirecting to direct %s URL: %s", result.protocol, result.url[:80])
                return RedirectResponse(url=result.url, status_code=302)
        elif VideoResolver.is_doodstream(result.url):
            direct = await resolver.resolve_doodstream(result.url)
            if direct and direct.protocol in ("hls", "mp4"):
                result = direct
                logger.info("Redirecting to direct %s URL: %s", result.protocol, result.url[:80])
                return RedirectResponse(url=result.url, status_code=302)
    except Exception as e:
        logger.warning("Fallo resolviendo embed %s: %s", result.url, e)
    finally:
        await resolver.close()
    
    # Si llegamos aquí, el resolver falló - NO hacer fallback al embed
    logger.error("No se pudo resolver video real para embed: %s", result.url)
    raise HTTPException(status_code=500, detail="No se pudo resolver fuente de video")

# Si es video directo (hls/mp4), redirigir al CDN
if result.protocol in ("hls", "mp4"):
    logger.info("Redirecting to direct %s URL: %s", result.protocol, result.url[:80])
    return RedirectResponse(url=result.url, status_code=302)

# Ya no hay fallback a embed - si llegamos aquí, error
raise HTTPException(status_code=500, detail="Fuente de video no disponible")
```

### 3. Importar HTTPException

Agregar al inicio de xtream.py:
```python
from fastapi import HTTPException
```

## ACEPTACION
1. curl -s -o /dev/null -w "%{http_code}" http://100.78.94.51:9193/movie/test/test/1012.mp4 → debe devolver 500 (no 302)
2. curl -s -o /dev/null -w "%{http_code}" http://100.78.94.51:9193/movie/test/test/1044.mp4 → debe devolver 302 (video válido)
3. docker logs media-integration-gateway | grep "placeholder detectado" → debe aparecer al probar 1012

## PREMISES
- src/api/xtream.py:280-304 — código actual de embed fallback que redirige sin validar
- src/api/xtream.py:237 — imports actuales (falta HTTPException)
- src/services/video_resolver.py:55-120 — _validate_video_url() que sigue redirects pero no rechaza placeholders
- Movie 1012 actualmente devuelve 302 a test-videos.co.uk (Big Buck Bunny placeholder)
- Movie 1044 funciona correctamente (cloudatacdn.com → video/mp4)
