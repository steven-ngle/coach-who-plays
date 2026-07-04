from __future__ import annotations

import asyncio
import ctypes.util
import logging
import os
import sys
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("coach-who-plays")


class _DropMessageContentWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "message content intent" not in record.getMessage().lower()


logging.getLogger("discord.ext.commands.bot").addFilter(_DropMessageContentWarning())


def _load_opus() -> None:
    if discord.opus.is_loaded():
        return

    candidates: list[str] = []
    found = ctypes.util.find_library("opus")
    if found:
        candidates.append(found)
    if sys.platform == "darwin":
        candidates += [
            "/opt/homebrew/opt/opus/lib/libopus.dylib",
            "/opt/homebrew/lib/libopus.dylib",
            "/usr/local/opt/opus/lib/libopus.dylib",
            "/usr/local/lib/libopus.dylib",
        ]

    for path in candidates:
        try:
            discord.opus.load_opus(path)
            if discord.opus.is_loaded():
                log.info("Loaded libopus from %s", path)
                return
        except OSError:
            continue

    log.warning(
        "libopus could not be loaded — voice playback will fail. "
        "Install it (macOS: `brew install opus`)."
    )


_load_opus()

INITIAL_EXTENSIONS: tuple[str, ...] = ("cogs.music",)


class CoachWhoPlaysBot(commands.Bot):
    """Custom Bot subclass so we can override setup_hook for async init."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.voice_states = True
        intents.guilds = True

        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self) -> None:
        """Runs once after login but before connecting to the gateway."""
        for ext in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Loaded extension: %s", ext)
            except Exception:
                log.exception("Failed to load extension: %s", ext)

        dev_guild_id = os.getenv("DEV_GUILD_ID")
        if dev_guild_id:
            guild = discord.Object(id=int(dev_guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d command(s) to dev guild %s", len(synced), dev_guild_id)
            
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
        else:
            synced = await self.tree.sync()
            log.info("Synced %d command(s) globally", len(synced))

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info("Logged in as %s (id=%s)", self.user, self.user.id)


async def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    if not Path("cogs").is_dir():
        raise RuntimeError("`cogs/` directory is missing — project layout is broken.")

    bot = CoachWhoPlaysBot()
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down.")
