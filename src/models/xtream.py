"""Modelos Pydantic para compatibilidad con Xtream Codes API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class XtreamUserInfo(BaseModel):
    """Información del usuario Xtream Codes."""

    username: str
    password: str
    auth: int = 1
    status: str = "Active"
    exp_date: str = "4102444800"
    is_trial: str = "0"
    active_cons: str = "0"
    created_at: str = ""
    max_connections: str = "1"
    allowed_output_formats: list[str] = ["m3u8", "mp4", "ts"]


class XtreamServerInfo(BaseModel):
    """Información del servidor Xtream Codes."""

    url: str
    port: str = "8080"
    https_port: str = ""
    server_protocol: str = "http"
    rtmp_port: str = ""
    timezone: str = "America/Caracas"
    timestamp_now: str = ""
    time_now: str = ""


class XtreamAccountInfo(BaseModel):
    """Información completa de la cuenta Xtream Codes."""

    user_info: XtreamUserInfo
    server_info: XtreamServerInfo


class XtreamCategory(BaseModel):
    """Categoría Xtream Codes."""

    category_id: str
    category_name: str
    parent_id: int = 0


class XtreamCategoriesResponse(BaseModel):
    """Respuesta de categorías Xtream Codes."""

    categories: list[XtreamCategory]


class XtreamVodStream(BaseModel):
    """Stream VOD (película) Xtream Codes."""

    num: int
    name: str
    stream_type: str = "movie"
    stream_id: int
    stream_icon: str = ""
    rating: str = "0"
    rating_5based: float = 0.0
    added: str = ""
    category_id: str = "1"
    container_extension: str = "mp4"
    custom_sid: str = ""
    direct_source: str = ""


class XtreamSeriesStream(BaseModel):
    """Stream de serie Xtream Codes."""

    num: int
    name: str
    series_id: int
    cover: str = ""
    plot: str = ""
    cast: str = ""
    director: str = ""
    genre: str = ""
    releaseDate: str = ""
    last_modified: str = ""
    rating: str = "0"
    rating_5based: float = 0.0
    backdrop_path: list = []
    youtube_trailer: str = ""
    episode_run_time: int = 0
    category_id: str = "2"


class XtreamPanelInfo(BaseModel):
    """Información del panel Xtream Codes."""

    live_streams: int = 0
    vod_streams: int = 0
    series_streams: int = 0
    episodes: int = 0
    active_connections: int = 0
    max_connections: int = 1


class XtreamPanelResponse(BaseModel):
    """Respuesta del panel Xtream Codes."""

    panel_info: XtreamPanelInfo