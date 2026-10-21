# Unidad: desacoplar todas las lecturas públicas del rastreo de catálogo

## Objetivo

Completar la separación entre lectura y sincronización: ningún endpoint público de
listado, búsqueda, conteo o selección de una serie debe llamar a
`provider.get_catalog()` ni iniciar un rastreo completo. Esas operaciones deben leer
exclusivamente el snapshot SQLite. El rastreo completo queda reservado a los scripts
explícitos de sincronización.

## Alcance

1. Extraer o reutilizar una única función/capa de lectura SQLite que convierta `media`
   y su `source` en `MediaItem`, con filtros opcionales por proveedor y tipo.
2. Hacer que `CatalogService.get_catalog()` y `CatalogService.search()` consulten la BD
   cuando el servicio tiene caché/sesiones configuradas, sin fallback de red para una
   lectura de catálogo vacía o ante un error del proveedor.
3. Hacer que `/api/v1/catalog/{provider}`, `/api/v1/search`, `search_vod`,
   `search_series`, `panel_api.php` y la selección previa de `/series/...` utilicen el
   snapshot SQLite y nunca `provider.get_catalog()`.
4. Mantener `get_details`, temporadas, episodios y `resolve_playback` con su conducta
   actual: pueden consultar una página específica cuando haga falta. No ampliar este
   encargo a extractores ni resolución de vídeo.
5. Mantener compatibilidad con las pruebas que inyectan un `CatalogService` sin BD;
   los dobles de prueba pueden conservar un catálogo en memoria, pero producción no
   debe rastrear el catálogo desde una petición pública.
6. Añadir pruebas de regresión que fallen si cualquiera de los endpoints enumerados
   intenta llamar `provider.get_catalog()` y que demuestren lectura/búsqueda/conteos
   desde una SQLite temporal.

## Restricciones

- No ejecutar sincronizaciones contra producción.
- No modificar la BD desplegada, Docker ni secretos.
- No cambiar scraping, playback ni extractores de hosts.
- No incorporar los archivos no relacionados que ya puedan estar sin seguimiento.

## ACEPTACION

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m pytest tests/test_xtream.py tests/test_smoke.py -q
! rg -n 'catalog_service\.get_catalog\(' src/api/xtream.py
```

## PREMISES

- `src/services/catalog.py:131-157` implementa `search()` mediante `self.get_catalog()` y hasta hace fallback al adapter, por lo que una petición pública puede acceder a red.
- `src/services/catalog.py:184-204` implementa `get_catalog()` llamando directamente a `provider.get_catalog(category)` cuando no hay caché de memoria.
- `src/api/routes.py:30-52` conecta `/api/v1/search` y `/api/v1/catalog/{provider}` con esos métodos del servicio.
- `src/api/xtream.py:313-315` demuestra el patrón ya aceptado: `get_series` lee `_load_catalog_from_db()`.
- `src/api/xtream.py:340-360` aún enruta `search_vod` y `search_series` a `catalog_service.search()`.
- `src/api/xtream.py:367-381` aún construye los conteos de `panel_api.php` llamando dos veces a `catalog_service.get_catalog()`.
- `src/api/xtream.py:512-529` aún localiza una serie mediante dos llamadas a `catalog_service.get_catalog()` antes del playback.
