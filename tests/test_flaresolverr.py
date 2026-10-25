"""El cliente de FlareSolverr no debe dejar navegadores abiertos.

Cada sesión de FlareSolverr es un Chromium vivo hasta `sessions.destroy`. El 2026-10-25 un
cliente que creaba una sesión por petición y nunca la cerraba llenó la memoria de vm-infra.
Sin sesión, FlareSolverr abre un navegador para la petición y lo cierra al terminar.
"""

import httpx

from src.services.flaresolverr import FlareSolverrClient


class _Respuesta:
    def __init__(self, cuerpo, status_code=200):
        self._cuerpo = cuerpo
        self.status_code = status_code

    def json(self):
        return self._cuerpo


def _espiar(monkeypatch, respuesta):
    comandos = []

    def post(url, json=None, **kwargs):
        comandos.append(json)
        if json.get("cmd") == "sessions.create":
            return _Respuesta({"status": "ok", "session": "s1"})
        return respuesta

    monkeypatch.setattr(httpx, "post", post)
    return comandos


def _sesiones_abiertas(comandos):
    creadas = {c.get("session", "s1") for c in comandos if c.get("cmd") == "sessions.create"}
    cerradas = {c.get("session") for c in comandos if c.get("cmd") == "sessions.destroy"}
    return creadas - cerradas


def test_exito_no_deja_sesiones_abiertas(monkeypatch):
    solucion = {"url": "https://x", "response": "<html></html>"}
    comandos = _espiar(monkeypatch, _Respuesta({"status": "ok", "solution": solucion}))

    assert FlareSolverrClient("http://fs").get_solution("https://x") == solucion
    assert _sesiones_abiertas(comandos) == set()


def test_fallo_no_deja_sesiones_abiertas(monkeypatch):
    comandos = _espiar(monkeypatch, _Respuesta({"status": "error"}, status_code=500))

    assert FlareSolverrClient("http://fs").get_solution("https://x") is None
    assert _sesiones_abiertas(comandos) == set()


def test_una_sola_peticion_de_pagina(monkeypatch):
    comandos = _espiar(monkeypatch, _Respuesta({"status": "ok", "solution": {}}))

    FlareSolverrClient("http://fs").get_solution("https://x", max_timeout=5000)

    pagina = [c for c in comandos if c.get("cmd") == "request.get"]
    assert len(pagina) == 1
    assert pagina[0]["url"] == "https://x"
    assert pagina[0]["maxTimeout"] == 5000
