from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import parse_qs, urlparse

import discord
import yt_dlp

from .config import YTDL_OPTIONS


class Track:
    """A queued track. `stream_url` is the direct audio URL FFmpeg will pull."""

    __slots__ = ("title", "stream_url", "webpage_url", "duration", "requester")

    def __init__(
        self,
        *,
        title: str,
        stream_url: str,
        webpage_url: str,
        duration: Optional[int],
        requester: discord.abc.User,
    ) -> None:
        self.title = title
        self.stream_url = stream_url
        self.webpage_url = webpage_url
        self.duration = duration
        self.requester = requester

    @classmethod
    def from_info(cls, info: dict, requester: discord.abc.User) -> "Track":
        return cls(
            title=info.get("title") or "Unknown title",
            stream_url=info["url"],
            webpage_url=info.get("webpage_url") or info.get("original_url") or "",
            duration=info.get("duration"),
            requester=requester,
        )

    def pretty_duration(self) -> str:
        if not self.duration:
            return "??:??"
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _is_playlist_url(query: str) -> bool:
    """Decide whether to expand `query` as a full playlist.

    Watch URLs that carry a `list=` param are treated as single videos —
    YouTube itself plays only that video when you click such a link, and
    resolving the whole playlist can take minutes. Only an explicit
    `/playlist` URL, or a list-only URL (no video id), counts as a playlist.
    """
    if not query.startswith(("http://", "https://")):
        return False
    try:
        parsed = urlparse(query)
    except ValueError:
        return False
    if "/playlist" in parsed.path:
        return True
    qs = parse_qs(parsed.query)
    return "list" in qs and "v" not in qs


def _ytdl_for(query: str) -> yt_dlp.YoutubeDL:
    """Build a yt-dlp instance with `noplaylist` chosen for this query."""
    opts = dict(YTDL_OPTIONS)
    opts["noplaylist"] = not _is_playlist_url(query)
    return yt_dlp.YoutubeDL(opts)


async def extract_tracks(query: str, requester: discord.abc.User) -> list[Track]:
    """Run yt-dlp in a thread and return one Track per resolved entry.

    A URL to a single video → one Track.
    A playlist URL → one Track per playlist entry.
    Plain text → one Track (top ytsearch result, per `default_search`).
    """
    loop = asyncio.get_running_loop()
    ytdl = _ytdl_for(query)

    def _do_extract() -> dict | None:
        return ytdl.extract_info(query, download=False)

    info = await loop.run_in_executor(None, _do_extract)
    if not info:
        return []

    if "entries" in info:
        return [
            Track.from_info(entry, requester)
            for entry in info["entries"]
            if entry
        ]

    return [Track.from_info(info, requester)]
