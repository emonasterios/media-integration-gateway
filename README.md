# Media Integration Gateway

Un **Media Integration Gateway** extensible que desacopla clientes de fuentes de contenido mediante adapters.

## Arquitectura

El sistema normaliza catálogos de múltiples proveedores (Jellyfin, Plex, M3U, APIs externas, contenido local) y expone una interfaz uniforme vía REST/JSON, M3U/XMLTV y Web UI.

### Principios
- **Desacoplamiento**: los clientes no conocen la implementación de cada proveedor
- **Extensibilidad**: nuevas fuentes se incorporan mediante un adapter
- **Modelo canónico**: películas, series, temporadas y episodios usan estructuras comunes
- **Resolución bajo demanda**: la URL de reproducción se obtiene cuando el usuario la necesita

## Estructura del proyecto

```
media-integration-gateway/
├── src/
│   ├── api/              # Endpoints FastAPI
│   ├── core/             # Configuración, logging
│   ├── models/           # Modelos Pydantic + SQLAlchemy
│   ├── services/         # Lógica de negocio
│   ├── adapters/         # Provider adapters
│   └── main.py           # Punto de entrada
├── tests/
├── data/                 # SQLite, caché (gitignored)
├── pyproject.toml
└── README.md
```

## Stack (MVP)
- **Backend/API**: FastAPI (Python)
- **Persistencia**: SQLite (escalable a PostgreSQL)
- **Adapters**: Python
- **Caché opcional**: Redis

## Desarrollo

```bash
# Crear entorno virtual
python3 -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install -e ".[dev]"

# Ejecutar tests
pytest

# Iniciar servidor
uvicorn src.main:app --reload
```


