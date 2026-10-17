# Fix trivial: aserción de protocolo en test_cuevana3_real.py

## Problema
`tests/test_cuevana3_real.py` línea 121 espera `protocol == "embed"` pero el fixture
contiene un doodstream URL que el adapter resuelve a `"mp4"`.

## Qué hacer
En `tests/test_cuevana3_real.py` línea 121, cambiar:
```python
    assert result.protocol == "embed"
```
por:
```python
    assert result.protocol == "mp4"
```

## Qué NO tocar
- Nada más en test_cuevana3_real.py
- Nada en src/
- Nada en fixtures/
- Solo esa línea

## ACEPTACIÓN
```
cd /home/emon/media-integration-gateway && . .venv/bin/activate && pytest tests/test_cuevana3_real.py -v -k test_resolve_playback_real
```

## PREMISES
- tests/test_cuevana3_real.py:121 contiene `assert result.protocol == "embed"`
- El fixture `FAKE_VOD_FIXTURES` en test_cuevana3_real.py contiene un doodstream URL
- El adapter resuelve doodstream a protocolo "mp4"
- tests/test_xtream.py ya tiene los conteos corregidos (commit previo)
