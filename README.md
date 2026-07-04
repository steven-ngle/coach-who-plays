# coach who plays

A small Discord music bot. Slash-command only, written in Python with
[discord.py](https://github.com/Rapptz/discord.py) and
[yt-dlp](https://github.com/yt-dlp/yt-dlp). Joins your voice channel, plays
audio from YouTube/SoundCloud links or a free-text search, and manages a
per-guild queue.

## Features

- `/play <url or search>` — joins the caller's voice channel and queues a song.
  Free-text queries are searched on YouTube by default.
- `/queue` — shows the current track and the next ten upcoming.
- `/nowplaying` — current song with link and requester.
- `/skip` — skips the current track.
- `/stop` — clears the queue and disconnects.
- Smart URL handling — `youtube.com/watch?v=X&list=Y` plays just video X
  (like YouTube itself does); `youtube.com/playlist?list=Y` enqueues the whole
  playlist.
- Auto-leave — disconnects after 5 minutes of idle queue, or immediately when
  every non-bot member leaves the voice channel.
- Per-guild queue isolation; safe cog reloads.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for dependency management
- **FFmpeg** on your `PATH` (audio decoding)
- **libopus** (voice encoding — discord.py needs it at runtime)
- A Discord application + bot token

### Installing the native dependencies

| Platform | Command |
|---|---|
| macOS (Homebrew) | `brew install ffmpeg opus` |
| Ubuntu / Debian | `sudo apt install ffmpeg libopus0` |
| Arch | `sudo pacman -S ffmpeg opus` |
| Windows (winget) | `winget install Gyan.FFmpeg` (libopus ships with discord.py wheels on Windows) |

Verify FFmpeg with `ffmpeg -version` in the same shell you'll run the bot from.

## Setup

```bash
# 1. Clone
git clone https://github.com/steven-ngle/coach-who-plays.git
cd coach-who-plays

# 2. Create the virtual environment and install Python deps
uv venv
uv pip install -r requirements.txt

# 3. Configure your token
cp .env.example .env
# then edit .env and paste your bot token
```

### Creating the Discord bot

1. Go to <https://discord.com/developers/applications> → **New Application**.
2. **Bot** tab → reveal the token and paste it into `.env` as `DISCORD_TOKEN`.
3. **OAuth2 → URL Generator** → scopes `bot` and `applications.commands`.
4. Bot permissions: View Channels, Send Messages, Embed Links, Connect, Speak,
   Use Voice Activity.
5. Open the generated URL and authorize the bot in your server.

### Running

```bash
uv run bot.py
```

You should see:

```
Loaded libopus from /opt/homebrew/opt/opus/lib/libopus.dylib
Loaded extension: cogs.music
Synced N command(s) globally
Logged in as coach who plays#1234 (id=...)
```

Global slash-command sync can take up to an hour to appear in Discord. While
developing, set `DEV_GUILD_ID` in `.env` to your test server's ID for instant
sync (enable Developer Mode in Discord and right-click the server name to copy
the ID).

## Commands

| Command | Description |
|---|---|
| `/play <query>` | URL or search. Joins your voice channel. |
| `/queue` | Show what's playing and the next ten tracks. |
| `/nowplaying` | Title, duration, link, requester. |
| `/skip` | Skip the current track. |
| `/pause` | Pause the current track. |
| `/resume` | Resume a paused track. |
| `/loop <off\|track\|queue>` | Set loop mode. `track` replays the current song; `queue` cycles the whole list. |
| `/stop` | Stop, clear queue, disconnect. |
| `/ping` | Health-check; reports gateway latency. |

## Configuration

Environment variables loaded from `.env`:

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | yes | Bot token from the Developer Portal. |
| `DEV_GUILD_ID` | no | If set, sync commands to just this guild (instant). |

Tunables live as constants at the top of `cogs/music.py`:

- `IDLE_TIMEOUT_SECONDS` — auto-leave timeout (default 300s).
- `YTDL_OPTIONS` / `FFMPEG_OPTIONS` — extractor and audio-pipeline tuning.