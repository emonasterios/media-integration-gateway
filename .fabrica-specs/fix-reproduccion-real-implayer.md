# Encargo: impedir falsos positivos de reproducción Xtream

## PREMISAS VERIFICADAS

- Repositorio canónico: `/home/emon/media-integration-gateway`, rama `main`, limpio y sincronizado con `origin/main`.
- Producción vive en `vm-infra:/opt/media-integration-gateway` y atiende en `127.0.0.1:9193`; no desplegar desde esta corrida.
- Los commits `b5af6d7` y `616d3de` ya validan URLs y prueban mirrors, pero la validación real del 2026-10-02 sigue fallando.
- Caso real `stream_id=1044`: el gateway responde 302; al seguir redirecciones termina intentando `odw7bf.dood.video:443`, conexión rechazada.
- Caso real `stream_id=1695`: el gateway responde 302 a un embed y al seguirlo devuelve `content-type: text/html`, no HLS/MP4.
- iMPlayer sí autentica, carga catálogo, pide `get_vod_info` y pide `/movie/...mp4`; el defecto está en aceptar una fuente final no reproducible.
- No almacenar URLs firmadas, cookies, credenciales ni secretos en Git o pruebas.

## OBJETIVO

Corregir el resolver y la ruta Xtream de películas para que nunca anuncien como reproducción válida un host inaccesible ni un documento HTML. Debe probar mirrors alternativos y aceptar solamente una respuesta multimedia real. Si no existe fuente reproducible, devolver un error explícito controlado en vez de redirigir a un embed/HTML.

## ALCANCE

- Validar conectividad y respuesta final del candidato, siguiendo redirecciones de forma acotada.
- Aceptar HLS por playlist válida y MP4/video por `Content-Type` multimedia o firma binaria razonable cuando el servidor no etiquete bien.
- Rechazar HTML, páginas anti-bot, 4xx/5xx, errores DNS/conexión y cadenas que terminan en un host caído.
- Conservar y usar `Referer`, `User-Agent`, cookies y demás headers del descriptor durante la validación; no exponerlos al cliente.
- Probar todos los mirrors conocidos antes de declarar que no hay fuente.
- La ruta `/movie/...` no debe redirigir al embed como fallback. Sin medio válido debe responder 502/503 con JSON estable y sin filtrar la URL externa.
- Añadir pruebas deterministas que simulen exactamente: redirect a host caído, 200 HTML, 403 anti-bot y mirror posterior con MP4/HLS válido.
- No modificar catálogo, autenticación, Tailscale, credenciales ni despliegue.

## ACEPTACION

```bash
python -m pytest -q tests/test_video_resolver.py tests/test_xtream.py tests/test_cuevana3.py
python -m compileall -q src
git diff --check
```

## ENTREGA

Cambio pequeño, documentado y probado. Dejar commit y push canónicos; no desplegar producción. El Supervisor verificará y desplegará después.
