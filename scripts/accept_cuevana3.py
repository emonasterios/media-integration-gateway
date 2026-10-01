#!/usr/bin/env python3
"""Script de aceptación para el adapter Cuevana3."""
import asyncio
import sys
sys.path.insert(0, "/home/emon/media-integration-gateway/src")

from adapters.cuevana3 import Cuevana3Adapter


async def main():
    adapter = Cuevana3Adapter()
    try:
        result = await adapter.search("Signal")
        print(f"Search: {len(result.items)} items found")
        if result.items:
            item = result.items[0]
            print(f"  First: {item.title} ({item.year})")
        return len(result.items) > 0
    finally:
        await adapter.close()


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
