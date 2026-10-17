<!-- spec:6d9731c86c6937a06df149e93fbedefe -->
# ENCARGO: Integrar mediaflow_bridge en video_resolver

## REGLAS OBLIGATORIAS
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.
- No tocar `src/adapters/cuevana3.py`, `src/adapters/cuevan_net.py`, ni archivos de tests.
- No modificar `resolve_streamtape` ni `resolve_morencius`.

---

## PASO 1: Integrar mediaflow_bridge en resolve_doodstream dentro de src/services/video_resolver.py

**Archivo a modificar:** `src/services/video_resolver.py`

**Instrucciones:**
1. Abrir y leer `src/services/video_resolver.py`.
2. Localizar el método `resolve_doodstream` (alrededor de la línea 132).
3. Justo después de su docstring, antes de la lógica existente de conexión httpx, insertar el siguiente bloque exacto:

```python
        # Intentar con mediaflow-proxy primero
        from src.services.mediaflow_bridge import resolve_with_mediaflow
        result = await resolve_with_mediaflow(embed_url, "doodstream.com")
        if result:
            return result
```

4. Verificar que la indentación coincida con el cuerpo del método.
5. Dejar el archivo compilando sin errores sintácticos (`python3 -m py_compile src/services/video_resolver.py`).

---

## PASO 2: Integrar mediaflow_bridge en resolve_voe dentro de src/services/video_resolver.py

**Archivo a modificar:** `src/services/video_resolver.py`

**Instrucciones:**
1. Abrir y leer `src/services/video_resolver.py`.
2. Localizar el método `resolve_voe` (alrededor de la línea 206).
3. Justo después de su docstring, antes de la lógica existente que invoca FlareSolverr, insertar el siguiente bloque exacto:

```python
        # Intentar con mediaflow-proxy primero
        from src.services.mediaflow_bridge import resolve_with_mediaflow
        result = await resolve_with_mediaflow(embed_url, "voe.sx")
        if result:
            return result
```

4. Verificar que la indentación coincida con el cuerpo del método.
5. Dejar el archivo compilando sin errores sintácticos (`python3 -m py_compile src/services/video_resolver.py`).

---

ACEPTACION
grep -q "from src.services.mediaflow_bridge import resolve_with_mediaflow" src/services/video_resolver.py
grep -q 'resolve_with_mediaflow(embed_url, "doodstream.com")' src/services/video_resolver.py
grep -q 'resolve_with_mediaflow(embed_url, "voe.sx")' src/services/video_resolver.py
python3 -m py_compile src/services/video_resolver.py

PREMISES
- src/services/mediaflow_bridge.py existe con función resolve_with_mediaflow(embed_url, domain)
- src/services/video_resolver.py:132 — resolve_doodstream empieza con httpx directo
- src/services/video_resolver.py:206 — resolve_voe usa FlareSolverr
- mediaflow-proxy ya está instalado en .venv
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
