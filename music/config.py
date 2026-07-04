from __future__ import annotations
from typing import Any

IDLE_TIMEOUT_SECONDS: int = 5 * 60

YTDL_OPTIONS: dict[str, Any] = {
    "format": "bestaudio/best",
    "default_search": "ytsearch",
    "quiet": True,
    "no_warnings": True,
    "ignoreerrors": False,
    "skip_download": True,
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS: dict[str, str] = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
    ),
    "options": "-vn",
}
