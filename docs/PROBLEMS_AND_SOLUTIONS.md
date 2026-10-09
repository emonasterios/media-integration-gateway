# Media Integration Gateway — Problemas Actuales y Posibles Soluciones

Fecha: 2026-10-03  
Versión analizada: commit actual (`main`)

---

## Problemas Críticos (Bloqueantes en Producción)

### 1. FlareSolverrClient Síncrono Bloquea el Event Loop

**Archivo**: `src/services/flaresolverr.py:16-51`  
**Impacto**: Cada llamada a `get_solution()` bloquea el loop asyncio ~10-60s. Con carga concurrente, el gateway se congela.

```python
# ACTUAL (síncrono - PROBLEMA)
def get_solution(self, url: str, max_timeout: int = 60000) -> dict | None:
    response = httpx.post(...)  # BLOQUEA
    return data.get("solution")
```

**Uso en código**:
- `src/adapters/cuevana3.py:418` — `_fetch_with_flare_fallback()` llama `self._flaresolverr.get_solution(url)`
- `src/services/video_resolver.py:225` — `resolve_voe()` crea cliente y llama `get_solution()`
- `src/services/video_resolver.py:403` — `resolve_morencius()` igual

**Solución**: Migrar a `httpx.AsyncClient`

```python
# PROPUESTO (async)
class FlareSolverrClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.FLARESOLVERR_URL
        self._client = httpx.AsyncClient(timeout=70.0)

    async def get_solution(self, url: str, max_timeout: int = 60000) -> dict | None:
        payload = {"cmd": "request.get", "url": url, "maxTimeout": max_timeout}
        try:
            response = await self._client.post(
                f"{self.base_url}/v1", json=payload, headers={"Content-Type": "application/json"}
            )
            if response.status_code != 200:
                return None
            data = response.json()
            if data.get("status") != "ok":
                return None
            return data.get("solution")
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError, ValueError):
            return None

    async def close(self):
        await self._client.aclose()
```

**Cambios en cascada requeridos**:
- `Cuevana3Adapter._flaresolverr` → `await self._flaresolverr.get_solution(url)`
- `VideoResolver.resolve_voe()` → `await flaresolverr.get_solution(embed_url)`
- `VideoResolver.resolve_morencius()` → `await flaresolverr.get_solution(embed_url)`
- Añadir `async def close()` en adapters y resolver para cerrar cliente compartido

---

### 2. CuevanNetAdapter Sin Protección Anti-Bot

**Archivo**: `src/adapters/cuevan_net.py`  
**Impacto**: Si cuevan.net activa Cloudflare (común en sitios de streaming), **todo el adapter falla** — búsqueda, catálogo, detalles, reproducción.

**Evidencia**: `Cuevana3Adapter` tiene `_fetch_with_flare_fallback()` (líneas 396-437) que detecta challenge Cloudflare y usa FlareSolverr. `CuevanNetAdapter` usa `httpx` directo sin fallback.

**Solución**: Replicar patrón `_fetch_with_flare_fallback` en `CuevanNetAdapter`

```python
# En CuevanNetAdapter
def __init__(self, ...):
    ...
    self._flaresolverr = FlareSolverrClient()  # Async tras fix #1

async def _fetch_with_flare_fallback(self, path: str) -> tuple[str | None, httpx.Response | None]:
    # Copiar lógica de Cuevana3Adapter líneas 396-437
    # Detectar 403/503, "just a moment", cf-ray-id, etc.
    # Fallback a self._flaresolverr.get_solution(url)
    ...

# Usar en get_details, get_seasons, get_episodes, resolve_playback
```

---

### 3. Duplicación de Resolución en `stream_movie`

**Archivo**: `src/api/xtream.py:272-312`  
**Impacto**: El adapter YA resolvió el video a URL directa (MP4/HLS). El endpoint Xtream **vuelve a resolver** Voe/Doodstream si el protocol es "embed", duplicando trabajo y latencia.

```python
# ACTUAL (duplicado)
result = await catalog_service.resolve_playback(media.provider, media.provider_id)

if result.protocol == "embed":  # <-- Ya falló en adapter si devolvió embed
    resolver = VideoResolver()
    if VideoResolver.is_voe(result.url):
        direct = await resolver.resolve_voe(result.url)  # SEGUNDA resolución
    ...
```

**Causa raíz**: `Cuevana3Adapter.resolve_playback()` **nunca devuelve protocol="embed"** (línea 506: lanza `ValueError` si ningún servidor funciona). El código de fallback en `stream_movie` es **código muerto**.

**Solución**: 
1. Eliminar bloque de re-resolución en `stream_movie` (líneas 280-304)
2. Confiar en `resolve_playback` del adapter
3. Si adapter lanza `ValueError` → `HTTPException(500, "Fuente no disponible")`

```python
# LIMPIO
result = await catalog_service.resolve_playback(media.provider, media.provider_id)

if result.protocol in ("hls", "mp4"):
    return RedirectResponse(url=result.url, status_code=302)

raise HTTPException(status_code=500, detail="Fuente de video no disponible")
```

---

## Problemas de Arquitectura / Mantenibilidad

### 4. Adapters Hardcodeados en `main.py`

**Archivo**: `src/main.py:58-60`  
**Impacto**: No se puede habilitar/deshabilitar proveedores por config. Testing requiere monkey-patch.

```python
# ACTUAL
adapter = Cuevana3Adapter()
cuevan_net = CuevanNetAdapter()
catalog = CatalogService(providers=[adapter, cuevan_net], cache=CatalogCache(db))
```

**Solución**: Config-driven factory

```python
# src/core/config.py
class Settings(BaseSettings):
    enabled_providers: list[str] = Field(default_factory=lambda: ["cuevana3", "cuevan_net"])
    ...

# src/main.py
def _build_providers(settings: Settings) -> list[MediaProvider]:
    providers = []
    if "cuevana3" in settings.enabled_providers:
        providers.append(Cuevana3Adapter())
    if "cuevan_net" in settings.enabled_providers:
        providers.append(CuevanNetAdapter())
    # Futuro: if "jellyfin" in ...: providers.append(JellyfinAdapter())
    return providers

# En lifespan:
providers = _build_providers(settings)
catalog = CatalogService(providers=providers, cache=CatalogCache(db))
```

---

### 5. Dos DATABASE_URL en Config

**Archivo**: `src/core/config.py:16,20`

```python
database_url: str = "sqlite+aiosqlite:///./data/gateway.db"  # Usado en docker-compose
DATABASE_URL: str = "sqlite:///./media_gateway.db"           # Usado en scripts/accept_cache.py
```

**Impacto**: Confusión; scripts de aceptación usan BD distinta que la app.

**Solución**: Unificar a `database_url` (async) y derivar sync URL para scripts si hace falta.

---

### 6. Falta de Índices en Base de Datos

**Archivo**: `src/db/models.py`  
**Impacto**: Consultas de caché (`get_by_source`, `get_media`) harán **full table scan** al crecer la tabla `media` (>10k filas).

**Solución**: Añadir índices compuestos

```python
from sqlalchemy import Index

class Media(Base):
    __tablename__ = "media"
    ...
    __table_args__ = (
        Index("ix_media_title_type", "title", "media_type"),
    )

class Source(Base):
    __tablename__ = "sources"
    ...
    __table_args__ = (
        Index("ix_source_provider_url", "provider", "url"),
    )
```

---

### 7. Cliente FlareSolverr por Llamada en VideoResolver

**Archivo**: `src/services/video_resolver.py:224, 402`

```python
# ACTUAL - crea cliente nuevo cada vez
async def resolve_voe(self, embed_url: str):
    flaresolverr = FlareSolverrClient()  # NUEVA instancia cada llamada
    solution = flaresolverr.get_solution(embed_url)
    ...
```

**Impacto**: Desperdicio de recursos; no aprovecha connection pooling; dificulta timeouts globales.

**Solución**: Inyectar `FlareSolverrClient` compartido (singleton) en `VideoResolver.__init__`

```python
class VideoResolver:
    def __init__(self, flaresolverr: FlareSolverrClient | None = None):
        self._flaresolverr = flaresolverr or FlareSolverrClient()
        ...
```

---

## Problemas de Calidad / Testing

### 8. `.fabrica-verify` Incompleto

**Archivo**: `.fabrica-verify`  
**Actual**: Solo `pytest tests/ -v`  
**Falta**: `ruff check . && mypy src/ && pytest tests/ -v`

**Solución**:
```bash
# .fabrica-verify
cd /home/emon/media-integration-gateway && . .venv/bin/activate && ruff check . && mypy src/ && pytest tests/ -v
```

---

### 9. Tests de Aceptación No Integrados en CI

**Archivos**: `scripts/accept_cuevana3.py`, `scripts/accept_cache.py`  
**Impacto**: Validación real contra sitios externos no corre en pipeline; solo manual.

**Solución**: 
- Marcar como `pytest.mark.live` (requiere red + FlareSolverr)
- Documentar en README que `pytest -m live` es opcional
- O: job separado en CI programado (nightly) con FlareSolverr service

---

### 10. Manejo de Errores Inconsistente en Adapters

| Método | Timeout → | HTTP Error → |
|--------|-----------|--------------|
| `get_catalog` | `[]` | `[]` |
| `search` | `SearchResult(items=[])` | `SearchResult(items=[])` |
| `get_details` | `ValueError` | `ValueError` (tras intentar /pelicula/ y /serie/) |
| `get_seasons` | `[]` | `[]` |
| `get_episodes` | `[]` | `[]` |
| `resolve_playback` | `ValueError` | `ValueError` |

**Problema**: `get_details` lanza excepción; `get_catalog` devuelve lista vacía. Consumidores deben conocer cada caso.

**Solución**: Unificar a `Result<T, E>` o levantar excepción tipada (`ProviderUnavailable`, `MediaNotFound`) en todos los métodos públicos.

---

## Mejoras de Funcionalidad (No Bloqueantes)

### 11. Caché Redis Opcional No Implementado

**README** menciona `REDIS_URL` pero `CatalogCache` solo usa SQLite.  
**Solución**: Implementar `RedisCatalogCache` con mismo interface; factory en `main.py` según `settings.REDIS_URL`.

---

### 12. Rate Limiting / Backoff en Adapters

**Actual**: `await asyncio.sleep(1)` fijo entre páginas (`cuevana3.py:203`).  
**Mejora**: Exponential backoff + `Retry-After` header + jitter.

---

### 13. Métricas / Observabilidad

**Falta**: `/metrics` (Prometheus), logging estructurado (JSON), tracing (OpenTelemetry).  
**Mínimo**: `structlog` + middleware request ID + latencia por endpoint.

---

### 14. Autenticación Xtream Codes Débil

**Actual**: `username`/`password` en query params sin validar contra BD.  
**Mejora**: Tabla `User` con hash bcrypt; validar en `xtream_player_api`; tokens JWT para sesiones.

---

## Resumen de Priorización

| Prioridad | Issue | Esfuerzo | Riesgo si no se arregla |
|-----------|-------|----------|-------------------------|
| **P0** | #1 FlareSolverr síncrono | M | Gateway se congela bajo carga |
| **P0** | #2 CuevanNet sin anti-bot | M | Adapter inútil si Cloudflare |
| **P0** | #3 Duplicación resolución | S | Latencia 2x, código muerto |
| **P1** | #4 Adapters hardcodeados | S | No se puede testear aisladamente |
| **P1** | #5 Dual DATABASE_URL | S | Confusión, bugs de entorno |
| **P1** | #6 Índices DB faltantes | S | Degradación rendimiento >10k items |
| **P2** | #7 FlareSolverr por llamada | S | Desperdicio recursos |
| **P2** | #8 Verify incompleto | XS | Lint/type errors en main |
| **P2** | #9 Aceptación no en CI | M | Regresiones silenciosas en vivo |
| **P3** | #10 Errores inconsistentes | M | Bugs sutiles en consumidores |
| **P3** | #11 Redis cache | M | No escala horizontal |
| **P4** | #12 Rate limiting | M | Baneos de IP proveedores |
| **P4** | #13 Observabilidad | L | Debugging producción ciego |
| **P4** | #14 Auth Xtream real | L | Seguridad mínima |

---

## Plan de Acción Sugerido (Próximos 3 Sprints)

### Sprint 1 — Estabilidad Core (P0)
- [ ] Migrar `FlareSolverrClient` a async (#1)
- [ ] Añadir `_fetch_with_flare_fallback` a `CuevanNetAdapter` (#2)
- [ ] Eliminar re-resolución duplicada en `stream_movie` (#3)
- [ ] Añadir `ruff` + `mypy` a `.fabrica-verify` (#8)

### Sprint 2 — Arquitectura Limpia (P1)
- [ ] Factory de providers config-driven (#4)
- [ ] Unificar `DATABASE_URL` (#5)
- [ ] Añadir índices SQLAlchemy (#6)
- [ ] Inyectar `FlareSolverrClient` compartido en `VideoResolver` (#7)

### Sprint 3 — Calidad y Escalabilidad (P2-P3)
- [ ] Integrar tests de aceptación como `pytest -m live` (#9)
- [ ] Unificar manejo de errores en adapters (#10)
- [ ] Implementar `RedisCatalogCache` opcional (#11)
- [ ] Rate limiting con backoff exponencial (#12)

---

## Notas de Implementación

- **No romper tests existentes**: Cada cambio debe pasar `pytest tests/ -v` antes de commit
- **Verificación real**: Tras cada fix P0, ejecutar `scripts/accept_cuevana3.py` y `scripts/accept_cache.py`
- **Feature flags**: Nuevos adapters tras `#4` se activan por `ENABLED_PROVIDERS` — seguro para deploy
- **Backwards compat**: Endpoints Xtream/REST/M3U no cambian firma; solo comportamiento interno