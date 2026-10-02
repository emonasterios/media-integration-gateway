#!/usr/bin/env python3
"""Aceptación EN VIVO de la caché (fase 3), contra el sitio real.

Por qué existe (2026-10-01): la fase 3 dio 56 pruebas en verde y la caché nunca acertaba
(guardaba por título, buscaba por slug) ni estaba conectada en main.py. Aquí:
  1. la SEGUNDA consulta del mismo detalle no debe tocar el sitio;
  2. la app real (create_app sin override) debe arrancar su CatalogService CON caché.
Sale 0 solo si todo pasa.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DB = ROOT / "_accept_cache.db"
DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"

from fastapi.testclient import TestClient  # noqa: E402

from src.adapters.cuevana3 import Cuevana3Adapter  # noqa: E402
from src.db.database import SessionLocal, init_db  # noqa: E402
from src.services.cache import CatalogCache  # noqa: E402
from src.services.catalog import CatalogService  # noqa: E402

fallos = 0


def check(ok, msg):
    global fallos
    print(("  ok   " if ok else "  FALLA ") + msg)
    fallos += 0 if ok else 1


async def segunda_consulta_sin_sitio():
    init_db()
    a = Cuevana3Adapter()
    svc = CatalogService([a], cache=CatalogCache(SessionLocal()))
    res = await svc.search("signal")
    items = [i for r in res for i in r.items]
    check(bool(items), f"búsqueda en vivo devuelve resultados — {len(items)}")
    if not items:
        return
    mid = items[0].provider_id
    llamadas = {"n": 0}
    original = a.get_details

    async def espia(x):
        llamadas["n"] += 1
        return await original(x)

    a.get_details = espia
    d1 = await svc.get_details(a.name, mid)
    d2 = await svc.get_details(a.name, mid)
    check(llamadas["n"] == 1, f"'{mid}': llamadas al sitio en 2 consultas = {llamadas['n']} (esperado 1)")
    check(d1.title == d2.title, f"la copia de caché trae el mismo título — {d2.title!r}")
    check(d2.provider_id == mid, f"la copia de caché conserva el id — {d2.provider_id!r}")
    await a.close()


def app_real_con_cache():
    from src.api.routes import _get_catalog
    from src.main import create_app

    app = create_app()
    with TestClient(app):
        svc = app.dependency_overrides[_get_catalog]()
        check(getattr(svc, "_cache", None) is not None, "create_app() arranca CatalogService con caché")


asyncio.run(segunda_consulta_sin_sitio())
app_real_con_cache()
DB.unlink(missing_ok=True)
print("ACEPTADO" if fallos == 0 else f"RECHAZADO — {fallos} fallo(s)")
sys.exit(0 if fallos == 0 else 1)
