from __future__ import annotations

import asyncio
import logging
from typing import Optional

import discord
from discord.ext import commands

from .config import FFMPEG_OPTIONS, IDLE_TIMEOUT_SECONDS
from .source import Track

log = logging.getLogger(__name__)


class GuildPlayer:
    """One instance per guild that has active playback.

    The player owns a background task that loops:
      get next track → play → wait for finish → repeat.
    If the queue is empty for `IDLE_TIMEOUT_SECONDS`, it disconnects.
    """

    def __init__(self, bot: commands.Bot, guild_id: int) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.queue: asyncio.Queue[Track] = asyncio.Queue()
        self._track_finished = asyncio.Event()
        self.current: Optional[Track] = None
        self.voice: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.abc.Messageable] = None
        self._task: Optional[asyncio.Task[None]] = None

    def ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run(), name=f"player-{self.guild_id}"
            )

    async def shutdown(self) -> None:
        """Cancel the player task and disconnect from voice."""
        self._drain_queue()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        await self._disconnect_voice()
        self.current = None

    def _drain_queue(self) -> None:
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def queue_snapshot(self) -> list[Track]:
        return list(self.queue._queue)

    def skip(self) -> bool:
        """Stop the current source so the player loop advances. Returns True if there was something to skip."""
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            self.voice.stop()
            return True
        return False

    async def _disconnect_voice(self) -> None:
        if self.voice and self.voice.is_connected():
            try:
                await self.voice.disconnect(force=False)
            except Exception:
                log.exception("Error disconnecting voice in guild %s", self.guild_id)
        self.voice = None

    async def _announce(self, content: str) -> None:
        if self.text_channel is None:
            return
        try:
            await self.text_channel.send(content)
        except discord.HTTPException:
            log.debug("Failed to send announcement in guild %s", self.guild_id)

    async def _run(self) -> None:
        log.info("Player loop started for guild %s", self.guild_id)
        try:
            while True:
                try:
                    track = await asyncio.wait_for(
                        self.queue.get(), timeout=IDLE_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    log.info(
                        "Idle timeout in guild %s — disconnecting", self.guild_id
                    )
                    await self._announce(
                        "👋 Left the voice channel after being idle."
                    )
                    return

                if self.voice is None or not self.voice.is_connected():
                    log.info(
                        "Voice gone for guild %s — abandoning track %r",
                        self.guild_id,
                        track.title,
                    )
                    return

                self.current = track
                self._track_finished.clear()

                source = discord.FFmpegPCMAudio(track.stream_url, **FFMPEG_OPTIONS)

                def _after(err: Optional[Exception]) -> None:
                    if err:
                        log.error(
                            "FFmpeg playback error in guild %s: %s",
                            self.guild_id,
                            err,
                        )
                    self.bot.loop.call_soon_threadsafe(self._track_finished.set)

                try:
                    self.voice.play(source, after=_after)
                except discord.ClientException:
                    log.exception(
                        "voice.play() failed in guild %s", self.guild_id
                    )
                    self.current = None
                    continue

                await self._announce(
                    f"🎵 Now playing: **{track.title}** "
                    f"`[{track.pretty_duration()}]`"
                )

                await self._track_finished.wait()
                self.current = None
        except asyncio.CancelledError:
            log.info("Player loop cancelled for guild %s", self.guild_id)
            raise
        except Exception:
            log.exception("Player loop crashed for guild %s", self.guild_id)
        finally:
            await self._disconnect_voice()
