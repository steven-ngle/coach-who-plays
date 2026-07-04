from __future__ import annotations

import asyncio
import logging
from typing import Optional
from urllib.parse import parse_qs, urlparse

import discord
import yt_dlp

from .config import YTDL_OPTIONS
from .spotify import SpotifyNotConfigured, is_spotify_url, resolve_spotify

log = logging.getLogger(__name__)

_SPOTIFY_SEARCH_CONCURRENCY = 5


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


async def _extract_via_ytdl(query: str) -> list[dict]:
    """Raw yt-dlp extraction — returns the list of entry info dicts."""
    loop = asyncio.get_running_loop()
    ytdl = _ytdl_for(query)

    def _do_extract() -> dict | None:
        return ytdl.extract_info(query, download=False)

    info = await loop.run_in_executor(None, _do_extract)
    if not info:
        return []
    if "entries" in info:
        return [e for e in info["entries"] if e]
    return [info]


async def _spotify_to_tracks(url: str, requester: discord.abc.User) -> list[Track]:
    """Resolve a Spotify URL and search each track on YouTube in parallel."""
    loop = asyncio.get_running_loop()
    search_queries = await loop.run_in_executor(None, resolve_spotify, url)
    log.info("Spotify %r resolved to %d track(s)", url, len(search_queries))
    if not search_queries:
        return []

    sem = asyncio.Semaphore(_SPOTIFY_SEARCH_CONCURRENCY)

    async def _search_one(q: str) -> list[Track]:
        async with sem:
            try:
                entries = await _extract_via_ytdl(q)
            except Exception:
                log.warning("YouTube search failed for %r", q, exc_info=True)
                return []
        if not entries:
            log.warning("YouTube search returned nothing for %r", q)
        return [Track.from_info(e, requester) for e in entries[:1]]

    batches = await asyncio.gather(*(_search_one(q) for q in search_queries))
    tracks = [t for batch in batches for t in batch]
    log.info("Spotify %r → %d/%d YouTube hits", url, len(tracks), len(search_queries))
    return tracks


async def extract_tracks(query: str, requester: discord.abc.User) -> list[Track]:
    """Resolve a query (URL or search string) into playable Tracks.

    - Spotify URL → resolve metadata, then search each track on YouTube.
    - yt-dlp-supported URL → the video(s) it resolves to.
    - Plain text → the top YouTube search result.
    """
    if is_spotify_url(query):
        return await _spotify_to_tracks(query, requester)

    entries = await _extract_via_ytdl(query)
    return [Track.from_info(info, requester) for info in entries]
