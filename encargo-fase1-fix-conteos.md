# Encargo: Fix Fase 1 — Conteos Xtream + Fixture Real

Fix trivial de 3 tests fallidos por aserciones desactualizadas.

## Contexto

El FakeProvider en `test_xtream.py` devuelve 3 películas (2 cuevana3 + 1 cuevan_net), pero los tests esperan 2. El fixture real en `test_cuevana3_real.py` ahora resuelve doodstream a mp4 (antes devolvía embed), pero el test espera embed.

## Cambios

### 1. tests/test_xtream.py — línea 292
Cambiar conteo de películas de 2 a 3.

```python
# ANTES (línea 292):
assert len(data) == 2  # Dos películas del FakeProvider

# DESPUÉS:
assert len(data) == 3  # Dos cuevana3 + 1 cuevan_net del FakeProvider
```

### 2. tests/test_xtream.py — línea 356
Cambiar conteo vod_streams en panel de 2 a 3.

```python
# ANTES (línea 356):
assert panel["vod_streams"] == 2  # Dos películas

# DESPUÉS:
assert panel["vod_streams"] == 3  # Dos cuevana3 + 1 cuevan_net
```

### 3. tests/test_cuevana3_real.py — línea 121
El fixture real (signal-one.html) tiene URLs doodstream que el resolver convierte a mp4. Cambiar aserción de protocolo.

```python
# ANTES (línea 121):
assert result.protocol == "embed"

# DESPUÉS:
assert result.protocol == "mp4"
```

## NO tocar
- Nada en src/ (código de producción)
- Ningún otro test
- Fixtures HTML

## ACEPTACION
```
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/test_xtream.py::test_player_api_get_vod_streams tests/test_xtream.py::test_panel_api tests/test_cuevana3_real.py::test_resolve_playback_real_fixture -v
```

## PREMISES
- tests/test_xtream.py:292 — `assert len(data) == 2` falla porque data tiene 3 elementos
- tests/test_xtream.py:356 — `assert panel["vod_streams"] == 2` falla porque vod_streams es 3
- tests/test_cuevana3_real.py:121 — `assert result.protocol == "embed"` falla porque protocol es "mp4"
- El fixture `cuevana3_pelicula_signal-one.html` contiene URLs doodstream reales (`doodstream.com/e/jtri5tfbukk6`)
- El FakeProvider en test_xtream.py:78-110 registra 3 películas (2 cuevana3 + 1 cuevan_net)
