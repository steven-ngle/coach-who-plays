from __future__ import annotations

import logging
import os
from typing import Optional
from urllib.parse import urlparse

from spotipy.exceptions import SpotifyException

log = logging.getLogger(__name__)

MAX_TRACKS_PER_RESOLVE = 100
SPOTIFY_CACHE_PATH = ".spotify-cache"
SPOTIFY_SCOPES = "playlist-read-private playlist-read-collaborative"


class SpotifyError(RuntimeError):
    """Base for user-facing Spotify resolution errors."""


class SpotifyNotConfigured(SpotifyError):
    """Raised when a Spotify URL is used without credentials configured."""


class SpotifyAccessDenied(SpotifyError):
    """Raised when Spotify's API refuses (401/403).

    Since Nov 27, 2024, Client Credentials can't access Spotify-owned
    editorial or algorithmic playlists — new apps get 401 there. Tracks,
    albums, and user-created playlists still work.
    """

_spotify_client: Optional["Spotify"] = None  # type: ignore[name-defined]  # noqa: F821


def is_spotify_url(query: str) -> bool:
    if not query.startswith(("http://", "https://")):
        return False
    try:
        host = (urlparse(query).hostname or "").lower()
    except ValueError:
        return False
    return host == "spotify.com" or host.endswith(".spotify.com")


def _get_client():
    """Build the Spotify client, preferring OAuth (broader access) over
    Client Credentials when a redirect URI is configured."""
    global _spotify_client
    if _spotify_client is not None:
        return _spotify_client

    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SpotifyNotConfigured(
            "Spotify link detected but no credentials configured. "
            "Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env, "
            "or paste a YouTube link instead."
        )

    from spotipy import Spotify
    from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth

    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")
    if redirect_uri:
        if not os.path.exists(SPOTIFY_CACHE_PATH):
            raise SpotifyNotConfigured(
                "SPOTIFY_REDIRECT_URI is set but no cached token exists. "
                "Run `uv run spotify_login.py` once to log in, then restart."
            )
        auth = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SPOTIFY_SCOPES,
            cache_path=SPOTIFY_CACHE_PATH,
            open_browser=False,
        )
        log.info("Spotify: using OAuth (cached token) — full API access")
    else:
        auth = SpotifyClientCredentials(
            client_id=client_id, client_secret=client_secret
        )
        log.info(
            "Spotify: using Client Credentials — editorial playlists blocked"
        )

    _spotify_client = Spotify(auth_manager=auth)
    return _spotify_client


def _classify(url: str) -> tuple[str, str]:
    """Return (kind, id) for a Spotify URL where kind ∈ {track, playlist, album}."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    parts = [p for p in parts if not p.startswith("intl-")]
    if len(parts) < 2:
        raise ValueError(f"Unsupported Spotify URL: {url}")
    kind, sp_id = parts[0], parts[1]
    if kind not in ("track", "playlist", "album"):
        raise ValueError(f"Unsupported Spotify link type: {kind}")
    return kind, sp_id


def _format_search(name: str, artist_names: list[str]) -> str:
    artists = ", ".join(a for a in artist_names if a) or "unknown"
    return f"{artists} - {name}"


def resolve_spotify(url: str) -> list[str]:
    """Convert a Spotify URL to a list of 'Artist — Title' search strings.

    Synchronous — call from an executor thread. Raises SpotifyNotConfigured
    if credentials are missing, SpotifyAccessDenied if the API refuses.
    """
    sp = _get_client()
    kind, sp_id = _classify(url)

    try:
        if kind == "track":
            info = sp.track(sp_id)
            return [
                _format_search(
                    info["name"], [a["name"] for a in info.get("artists") or []]
                )
            ]

        if kind == "playlist":
            return _paginate(
                fetch=lambda offset: sp.playlist_tracks(
                    sp_id,
                    offset=offset,
                    limit=100,
                    fields=(
                        "items(track(name,artists(name)),"
                        "item(name,artists(name))),next"
                    ),
                ),
                page_size=100,
                unwrap=lambda item: (
                    item.get("track") or item.get("item") or {}
                ),
            )

        return _paginate(
            fetch=lambda offset: sp.album_tracks(sp_id, offset=offset, limit=50),
            page_size=50,
            unwrap=lambda item: item,
        )
    except SpotifyException as e:
        if e.http_status in (401, 403):
            raise SpotifyAccessDenied(
                f"Spotify refused access to this {kind}. Since Nov 27, 2024, "
                "new apps can't use Client Credentials for Spotify-owned "
                "editorial or algorithmic playlists (e.g. Today's Top Hits, "
                "Discover Weekly). Try a track URL, an album URL, or a "
                "user-created playlist instead."
            ) from e
        raise SpotifyAccessDenied(
            f"Spotify API error ({e.http_status}): {e.msg or e}"
        ) from e


def _paginate(fetch, page_size: int, unwrap) -> list[str]:
    queries: list[str] = []
    offset = 0
    while len(queries) < MAX_TRACKS_PER_RESOLVE:
        batch = fetch(offset)
        for item in batch.get("items") or []:
            track = unwrap(item)
            name = track.get("name")
            artists = [a.get("name") for a in track.get("artists") or []]
            if name:
                queries.append(_format_search(name, artists))
            if len(queries) >= MAX_TRACKS_PER_RESOLVE:
                break
        if not batch.get("next"):
            break
        offset += page_size
    return queries
