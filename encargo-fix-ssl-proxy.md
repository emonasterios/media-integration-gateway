# Fix: SSL verify=False en proxy de video

## Problema
`_proxy_stream` en `src/api/xtream.py` línea 355 usa `httpx.AsyncClient` sin `verify=False`.
El CDN (`cloudatacdn.com`) tiene certificado SSL expirado → `httpx.ConnectError: certificate verify failed`.
Resultado: el IPTV no reproduce películas (HTTP 200 pero 0 bytes).

## Qué hacer

En `src/api/xtream.py`, línea 355, cambiar:

```python
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
```

por:

```python
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0, verify=False) as client:
```

Solo esa línea. Nada más.

## NO tocar
- No cambiar tests
- No cambiar otra función
- No cambiar Dockerfile

## ACEPTACION
```
cd /home/emon/media-integration-gateway && grep -q 'verify=False' src/api/xtream.py
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/ -v -q
```

## PREMISES
- `src/api/xtream.py` línea 355: `async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:`
- El CDN cloudatacdn.com tiene certificado SSL expirado (confirmado en logs del container)
- `_proxy_stream` es la única función que hace httpx.stream al CDN
