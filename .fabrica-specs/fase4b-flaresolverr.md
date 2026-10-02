# Fase 4b: Integrar FlareSolverr para bypass Cloudflare

## Qué hacer
1. Añadir `src/services/flaresolverr.py` — cliente HTTP para FlareSolverr API
2. Modificar `src/adapters/cuevana3.py` — usar FlareSolverr antes de httpx cuando detecte Cloudflare
3. Añadir configuración `FLARESOLVERR_URL` en `src/core/config.py` (default: http://flaresolverr:8191)
4. Añadir `docker-compose.yml` servicio flaresolverr (imagen ghcr.io/flaresolverr/flaresolverr:latest)
5. Tests: mock del servicio, test fallback a httpx cuando FlareSolverr no está

## Límites
- NO cambiar modelos Pydantic ni estructura de la base de datos
- NO tocar endpoints existentes (M3U, Web UI)
- Solo modificar el flujo de resolución de URLs en el adapter

## ACEPTACION
- . .venv/bin/activate && pytest tests/ -v --tb=short
- python scripts/test_flaresolverr_integration.py

## PREMISES
- FlareSolverr API: POST /v1 con {cmd: "request.get", url: "...", maxTimeout: 60000}
- Respuesta: {status: "ok", solution: {url, cookies, headers, response}}
- Cookie cf_clearance se reusa en requests posteriores del mismo dominio
- El adapter ya tiene resolve_playback() que devuelve URL embed — ahí se inyecta el bypass
- Docker compose ya existe en la raíz del proyecto
