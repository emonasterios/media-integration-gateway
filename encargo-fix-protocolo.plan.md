<!-- spec:d1df609c3a040835df279d92a2e5ecee -->
# ENCARGO: Corrección de aserción de protocolo en test_cuevana3_real.py

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

## PASO 1: Actualizar la aserción de protocolo en tests/test_cuevana3_real.py
- **Archivo a modificar:** `tests/test_cuevana3_real.py`
- **Contexto:** En la función de test `test_resolve_playback_real`, la aserción actual espera incorrectamente que `result.protocol` sea `"embed"`, pero el fixture utiliza una URL de Doodstream que el adaptador resuelve como `"mp4"`.
- **Acción:**
  1. Leer `tests/test_cuevana3_real.py` alrededor de la línea 121.
  2. Localizar la línea exacta:
     ```python
         assert result.protocol == "embed"
     ```
  3. Reemplazarla únicamente por:
     ```python
         assert result.protocol == "mp4"
     ```
- **Resultado esperado:** El archivo debe quedar idéntico en el resto de su contenido, modificando únicamente el valor esperado de la aserción a `"mp4"`.

ACEPTACION
grep -q 'assert result.protocol == "mp4"' tests/test_cuevana3_real.py
! grep -q 'assert result.protocol == "embed"' tests/test_cuevana3_real.py

PREMISES
- tests/test_cuevana3_real.py:121 contiene `assert result.protocol == "embed"`
- El fixture `FAKE_VOD_FIXTURES` en test_cuevana3_real.py contiene un doodstream URL
- El adapter resuelve doodstream a protocolo "mp4"
- tests/test_xtream.py ya tiene los conteos corregidos (commit previo)
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
