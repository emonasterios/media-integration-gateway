#!/usr/bin/env python3
"""Aceptación EN VIVO del adapter Cuevana3, contra el sitio real.

Por qué es así (2026-10-01): la versión anterior solo comprobaba que la búsqueda devolviera
algo. Con eso, una fase 2 cuyo resolve_playback fallaba en TODAS las películas daba verde, y
las pruebas unitarias también, porque usaban HTML inventado a partir de una premisa falsa.

Aquí lo esperado se saca del HTML CRUDO de la página con expresiones regulares propias, sin
pasar por el adapter: si el adapter lee otra cosa que la que está en la página, da rojo.
Sale 0 solo si todas las comprobaciones pasan; imprime cada una.
"""
import asyncio
import html as htmllib
import re
import sys
from pathlib import Path

import httpx

# El adapter importa "src.adapters...": hace falta la RAÍZ del repo en el path, no src/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.adapters.cuevana3 import Cuevana3Adapter  # noqa: E402

BASE = "https://cuevana3i.cc"
fallos = 0


def check(nombre: str, ok: bool, detalle: str = "") -> None:
    global fallos
    print(f"  {'ok  ' if ok else 'NO  '} {nombre}" + (f" — {detalle}" if detalle else ""))
    if not ok:
        fallos += 1


def texto(fragmento: str) -> str:
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", fragmento)).split())


def sin_espacios(t) -> str:
    # La sinopsis lleva <strong> dentro: según cómo se extraiga, cambian los espacios alrededor.
    # Lo que se comprueba es de DÓNDE sale el texto, no su espaciado.
    return re.sub(r"\s+", "", t or "")


async def esperado_de_la_pagina(slug: str) -> dict:
    """Lo que la página de la película dice de verdad, leído del HTML crudo."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=30,
                                 headers={"User-Agent": "Mozilla/5.0"}) as c:
        s = (await c.get(f"{BASE}/pelicula/{slug}/")).text
    desc = re.search(r'<div class="Description[^"]*">\s*<p>(.*?)</p>', s, re.S)
    meta = re.search(r'<p class="meta">(.*?)</p>', s, re.S)
    anio = re.search(r"\b(19|20)\d{2}\b", texto(meta.group(1))) if meta else None
    return {
        "overview": texto(desc.group(1)) if desc else None,
        "year": int(anio.group(0)) if anio else None,
        "servers": set(re.findall(r'<li [^>]*data-server="([^"]+)"', s)),
    }


async def main() -> int:
    a = Cuevana3Adapter()
    try:
        r = await a.search("Signal")
        check("search devuelve resultados", len(r.items) > 0, f"{len(r.items)} items")

        cat = await a.get_catalog()
        pelis = [i for i in cat if str(i.media_type).lower().endswith("movie")]
        check("catálogo con películas", len(pelis) >= 10, f"{len(pelis)} películas")
        con_anio = [i for i in pelis if i.year]
        check("el catálogo trae el año", len(con_anio) >= len(pelis) // 2,
              f"{len(con_anio)}/{len(pelis)} con año")

        for it in pelis[:2]:
            print(f"película: {it.provider_id}")
            esp = await esperado_de_la_pagina(it.provider_id)
            if not esp["servers"]:
                check("la página trae servidores (premisa del sitio)", False,
                      "sin li[data-server]: el sitio cambió, revisar antes de culpar al adapter")
                continue
            d = await a.get_details(it.provider_id)
            check("detalle: sinopsis = div.Description p",
                  sin_espacios(d.overview) == sin_espacios(esp["overview"]),
                  f"obtenido {(d.overview or '')[:50]!r}")
            check("detalle: año = p.meta", d.year == esp["year"],
                  f"obtenido {d.year}, esperado {esp['year']}")
            try:
                p = await a.resolve_playback(it.provider_id)
                check("reproducción: URL es uno de los li[data-server] de la página",
                      p.url in esp["servers"], f"obtenido {p.url}")
            except Exception as e:  # noqa: BLE001
                check("reproducción resuelta", False, f"{type(e).__name__}: {e}")
    finally:
        await a.close()
    print("ACEPTADO" if fallos == 0 else f"RECHAZADO — {fallos} comprobación(es) fallan")
    return 0 if fallos == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
