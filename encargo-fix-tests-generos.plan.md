<!-- spec:908d6e9473e4e1a053a7737f2c01d267 -->
# ENCARGO: Corrección de tests de géneros en base de datos para Xtream

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- NO modificar `src/api/xtream.py` bajo ninguna circunstancia.

---

## PASO 1: Corregir tipo de dato de ID en `test_enrich_genres_from_db`

- **Archivo a modificar:** `tests/test_xtream.py`
- **Problema:** El test `test_enrich_genres_from_db` inserta instancias en el modelo `Media` usando identificadores de tipo string (como `id="movie1"`), pero la columna `id` en `src/db/models.py` está definida como `INTEGER PRIMARY KEY`. Esto provoca un error `sqlite3.IntegrityError: datatype mismatch` durante la ejecución.
- **Qué debe quedar:**
  1. Localizar la función `test_enrich_genres_from_db` en `tests/test_xtream.py`.
  2. Modificar la creación de los registros de prueba para que utilicen valores enteros en el campo `id` (por ejemplo `id=1`, `id=2`). Si se comprueba el campo `media_id` o `provider_id`, mantener los strings correspondientes en sus atributos específicos sin alterar la clave primaria entera.
  3. Asegurar que las aserciones posteriores en este test hagan referencia a los nuevos identificadores numéricos donde corresponda.
  4. Mantener intacta la lógica que valida que los géneros se leen de la base de datos.

---

## PASO 2: Ajustar `test_player_api_get_vod_streams` para contemplar enriquecimiento de géneros

- **Archivo a modificar:** `tests/test_xtream.py`
- **Problema:** En `test_player_api_get_vod_streams` (alrededor de la línea 406), la aserción `assert stream1["category_id"] != "1"` falla porque en el test unitario la base de datos no contiene los registros del stream simulado, haciendo que `_enrich_genres_from_db` no encuentre géneros y asigne la categoría por defecto `"1"`.
- **Qué debe quedar:**
  1. Localizar la función `test_player_api_get_vod_streams` en `tests/test_xtream.py`.
  2. Aplicar un mock sobre `src.api.xtream._enrich_genres_from_db` (usando `unittest.mock.patch` o `monkeypatch`) dentro del test para que asigne géneros simulados (por ejemplo `["Acción"]` o `["Action"]`) a los items procesados, garantizando que el stream obtenga una categoría distinta a `"1"`.
  3. Alternativamente, si el test no requiere mock de base de datos, ajustar la aserción para verificar que el campo `category_id` esté presente y no sea nulo (`assert "category_id" in stream1 and stream1["category_id"]`).
  4. El archivo debe quedar compilando y todos los tests del módulo deben ejecutarse sin errores.

---

ACEPTACION
python3 -m pytest tests/test_xtream.py -k "test_enrich_genres_from_db"
python3 -m pytest tests/test_xtream.py -k "test_player_api_get_vod_streams"
python3 -m pytest tests/test_xtream.py

PREMISES
- `tests/test_xtream.py` línea ~390-410: test `test_player_api_get_vod_streams` asume `category_id != "1"`
- `tests/test_xtream.py` línea ~420-450: test `test_enrich_genres_from_db` crea items con `media_id="movie1"` (string)
- `src/api/xtream.py` línea 52-75: `_enrich_genres_from_db` lee de `data/gateway.db` y matchea por `provider_id` o `media_id`
- `src/db/models.py` columna `id` es `INTEGER PRIMARY KEY`
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
