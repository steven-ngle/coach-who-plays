from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")

    missing = [
        name
        for name, value in (
            ("SPOTIFY_CLIENT_ID", client_id),
            ("SPOTIFY_CLIENT_SECRET", client_secret),
            ("SPOTIFY_REDIRECT_URI", redirect_uri),
        )
        if not value
    ]
    if missing:
        sys.stderr.write(
            "Missing required env vars in .env: "
            + ", ".join(missing)
            + "\nSet them and try again.\n"
        )
        return 1

    from spotipy.oauth2 import SpotifyOAuth

    from music.spotify import SPOTIFY_CACHE_PATH, SPOTIFY_SCOPES

    print(f"Opening browser to Spotify. Redirect URI: {redirect_uri}")
    print("Approve the request, then come back here.\n")

    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SPOTIFY_SCOPES,
        cache_path=SPOTIFY_CACHE_PATH,
        open_browser=True,
    )

    token = auth.get_access_token(as_dict=False)
    if not token:
        sys.stderr.write("Login failed — no token returned.\n")
        return 1

    try:
        os.chmod(SPOTIFY_CACHE_PATH, 0o600)
    except OSError:
        pass

    print(f"\n✓ Done. Refresh token cached to {SPOTIFY_CACHE_PATH}")
    print("You can now (re)start the bot; Spotify URLs should resolve fully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
