# Contribuir a Media Integration Gateway

¡Las contribuciones son bienvenidas! Este proyecto busca normalizar el acceso a contenido multimedia desde múltiples fuentes.

## Cómo contribuir

### 1. Agregar un nuevo adapter

La forma más valiosa de contribuir es agregar soporte para nuevos proveedores.

```python
# src/adapters/mi_provider.py
from src.adapters.base import BaseAdapter
from src.models.catalog import MovieItem, SeriesItem, PlaybackDescriptor

class MiProviderAdapter(BaseAdapter):
    name = "mi_provider"
    base_url = "https://mi-provider.example.com"

    async def paginate(self, page: int = 1, **kwargs) -> list[dict]:
        """Retorna items crudos de una página del catálogo."""
        ...

    async def parse_item(self, raw: dict) -> MovieItem | SeriesItem:
        """Convierte un item crudo al modelo canónico."""
        ...

    async def get_playback_url(self, item_id: str) -> PlaybackDescriptor:
        """Resuelve la URL de reproducción directa."""
        ...
```

Luego regístralo en `src/main.py`:

```python
from src.adapters.mi_provider import MiProviderAdapter
providers.append(MiProviderAdapter())
```

### 2. Mejorar VideoResolver

Si encuentras un nuevo host de video (embed), agrega un método `resolve_*` en `src/services/video_resolver.py`:

```python
@staticmethod
def is_mi_host(url: str) -> bool:
    return "mi-host.com" in url.lower()

async def resolve_mi_host(self, embed_url: str) -> PlaybackDescriptor | None:
    """Resuelve embed de mi-host.com a URL directa."""
    ...
```

### 3. Reportar bugs

Abre un issue con:
- Pasos para reproducir
- Logs del gateway (`docker logs media-integration-gateway`)
- URL del embed o página afectada

### 4. Pull Requests

1. Fork el repo
2. Crea una rama (`git checkout -b feat/mi-adapter`)
3. Commit (`git commit -m 'feat: add mi-provider adapter'`)
4. Push y abre un PR

## Estilo de código

- Ruff para linting: `ruff check src/`
- Pytest para tests: `pytest`
- Línea máxima: 100 caracteres

## Desarrollo rápido

```bash
# Infraestructura (FlareSolverr + Redis)
docker compose -f docker-compose-infra.yml up -d

# Gateway en modo desarrollo
uvicorn src.main:app --reload
```

## ¿Por qué contribuir?

- Resolver un problema real: acceso unificado a contenido multimedia
- Aprender sobre web scraping, anti-bot, y streaming HLS/MP4
- Proyecto activo con deploy real en producción
