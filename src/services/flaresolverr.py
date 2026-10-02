"""Cliente HTTP para la API de FlareSolverr."""

from __future__ import annotations

import httpx

from src.core.config import settings


class FlareSolverrClient:
    """Cliente para interactuar con la API de FlareSolverr."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or settings.FLARESOLVERR_URL

    def get_solution(self, url: str, max_timeout: int = 60000) -> dict | None:
        """
        Realiza una petición GET a través de FlareSolverr.

        Args:
            url: URL a resolver
            max_timeout: Timeout máximo en milisegundos (default 60000)

        Returns:
            Diccionario con la solución (url, cookies, headers, response) o None si falla
        """
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": max_timeout,
        }

        try:
            response = httpx.post(
                f"{self.base_url}/v1",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=max_timeout / 1000 + 10,  # Convertir a segundos y añadir margen
            )

            if response.status_code != 200:
                return None

            data = response.json()
            if data.get("status") != "ok":
                return None

            return data.get("solution")

        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError, ValueError):
            # Cualquier error de conexión, timeout, HTTP o parsing JSON -> fallback silencioso
            return None