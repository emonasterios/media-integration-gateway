#!/usr/bin/env python3
"""Spike: intentar extraer URL de video directo de un servidor de Cuevana3."""
import asyncio
import sys
import re

sys.path.insert(0, "/home/emon/media-integration-gateway/src")

from adapters.cuevana3 import Cuevana3Adapter


async def main():
    url = "https://cuevana3i.cc/pelicula/signal-one/"
    print(f"=== Spike: extracción de video directo ===")
    print(f"Película: {url}")
    print()

    adapter = Cuevana3Adapter()

    # 1. Obtener detalles
    print("1. Obteniendo detalles...")
    details = await adapter.get_details(url)
    if not details:
        print("   ERROR: no se pudieron obtener detalles")
        return

    print(f"   Título: {details.title}")
    print(f"   Servidores disponibles: {len(details.sources)}")
    for s in details.sources:
        print(f"   - {s.name}: {s.url}")
    print()

    # 2. Resolver playback del primer servidor
    if not details.sources:
        print("   No hay servidores disponibles")
        return

    source = details.sources[0]
    print(f"2. Resolving playback de '{source.name}'...")
    print(f"   URL del servidor: {source.url}")

    playback = await adapter.resolve_playback(source.url)
    if not playback:
        print("   ERROR: no se pudo resolver playback")
        return

    print(f"   Servidor: {playback.server_name}")
    print(f"   ¿Video directo? {playback.is_direct}")
    print(f"   URL: {playback.url}")
    if playback.quality:
        print(f"   Calidad: {playback.quality}")
    print()

    # 3. Analizar resultado
    print("3. Análisis:")
    if playback.is_direct:
        print("   ✅ VIDEO DIRECTO disponible")
        print(f"   Formato: {playback.url.split('.')[-1].split('?')[0]}")
    else:
        print("   ❌ NO es video directo")
        print(f"   La URL apunta a una página web, no a un archivo de video")
        # Intentar extraer dominio del host
        if "dood" in playback.url:
            print("   Servidor: Doodstream")
            print("   Problema conocido: requiere headers especiales y decodificación")
        elif "voe" in playback.url:
            print("   Servidor: Voe")
            print("   Problema conocido: protección anti-bot")
        else:
            print(f"   Dominio: {playback.url.split('/')[2]}")

    print()
    print("=== Fin del spike ===")


if __name__ == "__main__":
    asyncio.run(main())
