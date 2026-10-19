<!-- spec:effcfcdbe7cb38e938206bf6dee5f900 -->
REGLAS QUE DEBES SEGUIR:
- Leer cada archivo antes de editarlo y tocar SOLO lo necesario.
- NO reescribir archivos enteros: reescribir reintroduce fallos ya corregidos.
- No aprovechar para mejorar ni reorganizar nada más.

## PASO 1: Desactivar la verificación SSL en el cliente HTTP del proxy de streaming

Archivo a modificar: `src/api/xtream.py`

1. Leer `src/api/xtream.py` y localizar dentro de la función `_proxy_stream` (alrededor de la línea 355) la siguiente instrucción:
```python
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
```

2. Modificar únicamente esa línea para añadir el parámetro `verify=False`:
```python
    async with httpx.AsyncClient(follow_redirects=True, timeout=60.0, verify=False) as client:
```

3. No modificar ninguna otra línea, parámetro ni función del archivo `src/api/xtream.py`.
4. El archivo debe quedar con sintaxis de Python válida y compilando sin errores.

ACEPTACION
grep -q "verify=False" src/api/xtream.py
python3 -m py_compile src/api/xtream.py

PREMISES
- `src/api/xtream.py` línea 355: `async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:`
- El CDN cloudatacdn.com tiene certificado SSL expirado (confirmado en logs del container)
- `_proxy_stream` es la única función que hace httpx.stream al CDN
A el troceo de arriba lo hizo el planificador sobre el arbol REAL del repo
