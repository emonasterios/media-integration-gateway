"""Puente entre mediaflow-proxy extractors y PlaybackDescriptor del gateway."""

from __future__ import annotations

import logging
from typing import Optional

from mediaflow_proxy.extractors.doodstream import DoodStreamExtractor
from mediaflow_proxy.extractors.voe import VoeExtractor
from mediaflow_proxy.extractors.filelions import FileLionsExtractor
from mediaflow_proxy.extractors.streamwish import StreamWishExtractor
from mediaflow_proxy.extractors.base import ExtractorError

from .resolvers.vimeos import VimeosResolver
from .resolvers.waaw import WaawResolver
from .resolvers.vidhide import VidhideResolver
from .resolvers.bysejikuar import BysejikuarResolver

from src.models.catalog import PlaybackDescriptor

logger = logging.getLogger(__name__)

# Mapeo de dominio → clase extractor
_EXTRACTOR_MAP = {
    "doodstream.com": DoodStreamExtractor,
    "dood.la": DoodStreamExtractor,
    "dood.ws": DoodStreamExtractor,
    "playmogo.com": DoodStreamExtractor,
    "d000d.com": DoodStreamExtractor,
    "dood.yt": DoodStreamExtractor,
    "dooood.com": DoodStreamExtractor,
    "voe.sx": VoeExtractor,
    "voe-unblock.com": VoeExtractor,
    "voeunblock.com": VoeExtractor,
    "voeunbl0ck.com": VoeExtractor,
    "voeunblocker.com": VoeExtractor,
    "filelions.to": FileLionsExtractor,
    "filelions.com": FileLionsExtractor,
    "vidhide.com": FileLionsExtractor,
    "vimeos.net": VimeosResolver,
    "waaw.to": WaawResolver,
    "vidhidepro.com": VidhideResolver,
    "bysejikuar.com": BysejikuarResolver,
    "streamwish.to": StreamWishExtractor,
    "streamwish.com": StreamWishExtractor,
    "ajmidyad.sbs": StreamWishExtractor,
}

_DOOD_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


async def resolve_with_mediaflow(embed_url: str, domain: str) -> Optional[PlaybackDescriptor]:
    """Resolver una URL de embed usando el extractor de mediaflow-proxy correspondiente.

    Returns PlaybackDescriptor con protocol='mp4' (o 'hls' para Voe) y headers necesarios.
    """
    extractor_cls = _EXTRACTOR_MAP.get(domain)
    if not extractor_cls:
        logger.warning("No hay extractor mediaflow para dominio %s", domain)
        return None

    request_headers = {
        "User-Agent": _DOOD_UA,
        "Referer": embed_url,
    }

    try:
        extractor = extractor_cls(request_headers=request_headers)
        result = await extractor.extract(embed_url)
    except ExtractorError as e:
        logger.warning("mediaflow extractor falló para %s: %s", embed_url, e)
        return None

    dest_url = result.get("destination_url")
    if not dest_url:
        logger.warning("Extractor no devolvió destination_url para %s", embed_url)
        return None

    req_headers = result.get("request_headers", {})
    endpoint = result.get("mediaflow_endpoint", "")

    # Doodstream devuelve mp4 directo; Voe y los resolvers propios (vimeos…) devuelven HLS
    is_hls = "hls" in endpoint.lower() or ".m3u8" in dest_url.lower()
    protocol = "hls" if is_hls else "mp4"

    return PlaybackDescriptor(
        protocol=protocol,
        url=dest_url,
        headers=req_headers,
    )
