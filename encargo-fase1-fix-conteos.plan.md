<!-- spec:76087e4b3df3dcb6435d6ab01f77b7bc -->
# Encargo: Fix Fase 1 — Conteos Xtream y Protocolo de Fixture Real

Reglas obligatorias para el ejecutor:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

---

## PASO 1: Actualizar conteos de películas en `tests/test_xtream.py`

Archivo a modificar:
- `tests/test_xtream.py`

Objetivo:
Actualizar las aserciones de conteo de películas en los tests de Xtream (`test_player_api_get_vod_streams` y `test_panel_api`), ya que el FakeProvider devuelve 3 películas (2 de cuevana3 y 1 de cuevan_net) en lugar de 2.

Modificaciones requeridas:
1. Localizar en `tests/test_xtream.py` dentro de la función `test_player_api_get_vod_streams` la aserción:
   ```python
   assert len(data) == 2  # Dos películas del FakeProvider
   ```
   y sustituirla por:
   ```python
   assert len(data) == 3  # Dos cuevana3 + 1 cuevan_net del FakeProvider
   ```

2. Localizar en `tests/test_xtream.py` dentro de la función `test_panel_api` la aserción:
   ```python
   assert panel["vod_streams"] == 2  # Dos películas
   ```
   y sustituirla por:
   ```python
   assert panel["vod_streams"] == 3  # Dos cuevana3 + 1 cuevan_net
   ```

El resto de `tests/test_xtream.py` debe permanecer intacto.

---

## PASO 2: Actualizar aserción de protocolo en `tests/test_cuevana3_real.py`

Archivo a modificar:
- `tests/test_cuevana3_real.py`

Objetivo:
Actualizar la aserción de protocolo en el test `test_resolve_playback_real_fixture`. El fixture real `tests/fixtures/cuevana3_pelicula_signal-one.html` contiene enlaces a Doodstream que el resolver procesa ahora como `mp4` en lugar de `embed`.

Modificaciones requeridas:
1. Localizar en `tests/test_cuevana3_real.py` dentro de la función `test_resolve_playback_real_fixture` la aserción:
   ```python
   assert result.protocol == "embed"
   ```
   y sustituirla por:
   ```python
   assert result.protocol == "mp4"
   ```

El resto de `tests/test_cuevana3_real.py` debe permanecer intacto.

---

ACEPTACION
grep -q 'assert len(data) == 3' tests/test_xtream.py
grep -q 'assert panel\["vod_streams"\] == 3' tests/test_xtream.py
grep -q 'assert result.protocol == "mp4"' tests/test_cuevana3_real.py

PREMISES
- tests/test_xtream.py:292 — `assert len(data) == 2` falla porque data tiene 3 elementos
- tests/test_xtream.py:356 — `assert panel["vod_streams"] == 2` falla porque vod_streams es 3
- tests/test_cuevana3_real.py:121 — `assert result.protocol == "embed"` falla porque protocol es "mp4"
- El fixture `cuevana3_pelicula_signal-one.html` contiene URLs doodstream reales (`doodstream.com/e/jtri5tfbukk6`)
- El FakeProvider en test_xtream.py:78-110 registra 3 películas (2 cuevana3 + 1 cuevan_net)
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
