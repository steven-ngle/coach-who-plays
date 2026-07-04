from __future__ import annotations
import logging
from typing import Optional
import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

from music import GuildPlayer, LoopMode, extract_tracks

log = logging.getLogger(__name__)


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._players: dict[int, GuildPlayer] = {}

    def _player_for(self, guild_id: int) -> GuildPlayer:
        player = self._players.get(guild_id)
        if player is None:
            player = GuildPlayer(self.bot, guild_id)
            self._players[guild_id] = player
        return player

    async def _ensure_voice(
        self, interaction: discord.Interaction
    ) -> Optional[discord.VoiceClient]:
        """Connect (or move) to the invoking user's voice channel. Returns
        the VoiceClient, or None if anything blocked us (with a user-visible
        followup already sent)."""
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.followup.send(
                "This command only works inside a server.", ephemeral=True
            )
            return None

        if user.voice is None or user.voice.channel is None:
            await interaction.followup.send(
                "You need to be in a voice channel first.", ephemeral=True
            )
            return None

        target = user.voice.channel
        voice = guild.voice_client
        try:
            if voice is None:
                voice = await target.connect(self_deaf=True)
            elif voice.channel != target:
                await voice.move_to(target)
        except discord.ClientException:
            await interaction.followup.send(
                "I couldn't join that voice channel.", ephemeral=True
            )
            return None
        return voice

    @app_commands.command(
        name="play",
        description="Play a song (URL or search query). Joins your voice channel.",
    )
    @app_commands.describe(
        query="A YouTube/SoundCloud URL, a playlist URL, or a free-text search."
    )
    async def play(
        self, interaction: discord.Interaction, query: str
    ) -> None:
        await interaction.response.defer(thinking=True)

        voice = await self._ensure_voice(interaction)
        if voice is None:
            return

        try:
            tracks = await extract_tracks(query, interaction.user)
        except yt_dlp.utils.DownloadError as e:
            log.warning("yt-dlp DownloadError for %r: %s", query, e)
            await interaction.followup.send(
                f"Couldn't find anything for `{query}`.", ephemeral=True
            )
            return
        except Exception:
            log.exception("yt-dlp failed for query %r", query)
            await interaction.followup.send(
                "Something went wrong fetching that track.", ephemeral=True
            )
            return

        if not tracks:
            await interaction.followup.send(
                f"No results for `{query}`.", ephemeral=True
            )
            return

        assert interaction.guild_id is not None
        player = self._player_for(interaction.guild_id)
        player.voice = voice
        if interaction.channel is not None:
            player.text_channel = interaction.channel

        for track in tracks:
            await player.queue.put(track)
        player.ensure_running()

        if len(tracks) == 1:
            await interaction.followup.send(
                f"➕ Queued: **{tracks[0].title}** `[{tracks[0].pretty_duration()}]`"
            )
        else:
            await interaction.followup.send(
                f"➕ Queued **{len(tracks)}** tracks from playlist."
            )

    @app_commands.command(name="skip", description="Skip the current song.")
    async def skip(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        player = self._players.get(interaction.guild_id)
        if player is None or not player.skip():
            await interaction.response.send_message(
                "Nothing is playing right now.", ephemeral=True
            )
            return
        await interaction.response.send_message("⏭️ Skipped.")

    @app_commands.command(name="pause", description="Pause the current song.")
    async def pause(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        voice = guild.voice_client if guild else None
        if voice is None or not voice.is_playing():
            await interaction.response.send_message(
                "Nothing is playing right now.", ephemeral=True
            )
            return
        voice.pause()
        await interaction.response.send_message("⏸️ Paused.")

    @app_commands.command(name="loop", description="Set loop mode: off, track, or queue.")
    @app_commands.describe(mode="What to loop.")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="off", value=LoopMode.OFF.value),
            app_commands.Choice(name="current track", value=LoopMode.TRACK.value),
            app_commands.Choice(name="queue", value=LoopMode.QUEUE.value),
        ]
    )
    async def loop(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
    ) -> None:
        if interaction.guild_id is None:
            return
        player = self._player_for(interaction.guild_id)
        player.loop_mode = LoopMode(mode.value)
        labels = {
            LoopMode.OFF.value: "⏹️ off",
            LoopMode.TRACK.value: "🔂 current track",
            LoopMode.QUEUE.value: "🔁 queue",
        }
        await interaction.response.send_message(f"Loop: {labels[mode.value]}")

    @app_commands.command(name="resume", description="Resume the paused song.")
    async def resume(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        voice = guild.voice_client if guild else None
        if voice is None or not voice.is_paused():
            await interaction.response.send_message(
                "Nothing is paused.", ephemeral=True
            )
            return
        voice.resume()
        await interaction.response.send_message("▶️ Resumed.")

    @app_commands.command(
        name="stop",
        description="Stop playback, clear the queue, and leave the voice channel.",
    )
    async def stop(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        player = self._players.pop(interaction.guild_id, None)
        if player is not None:
            await player.shutdown()
            await interaction.response.send_message("⏹️ Stopped and disconnected.")
            return

        guild = interaction.guild
        if guild and guild.voice_client:
            await guild.voice_client.disconnect(force=False)
            await interaction.response.send_message("⏹️ Disconnected.")
            return

        await interaction.response.send_message(
            "I'm not playing anything.", ephemeral=True
        )

    @app_commands.command(
        name="nowplaying", description="Show the song that's currently playing."
    )
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        player = self._players.get(interaction.guild_id)
        if player is None or player.current is None:
            await interaction.response.send_message(
                "Nothing is playing right now.", ephemeral=True
            )
            return

        track = player.current
        link = f"\n<{track.webpage_url}>" if track.webpage_url else ""
        await interaction.response.send_message(
            f"🎵 Now playing: **{track.title}** `[{track.pretty_duration()}]`"
            f" — requested by {track.requester.mention}{link}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="queue", description="Show the upcoming queue.")
    async def queue_cmd(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            return
        player = self._players.get(interaction.guild_id)
        if player is None or (player.current is None and player.queue.empty()):
            await interaction.response.send_message(
                "The queue is empty.", ephemeral=True
            )
            return

        lines: list[str] = []
        if player.current is not None:
            lines.append(
                f"**Now playing:** {player.current.title} "
                f"`[{player.current.pretty_duration()}]`"
            )

        upcoming = player.queue_snapshot()
        if upcoming:
            lines.append("**Up next:**")
            for i, track in enumerate(upcoming[:10], start=1):
                lines.append(
                    f"`{i}.` {track.title} `[{track.pretty_duration()}]`"
                )
            if len(upcoming) > 10:
                lines.append(f"… and **{len(upcoming) - 10}** more")

        if player.loop_mode is not LoopMode.OFF:
            loop_label = "🔂 track" if player.loop_mode is LoopMode.TRACK else "🔁 queue"
            lines.append(f"**Loop:** {loop_label}")

        await interaction.response.send_message(
            "\n".join(lines), allowed_mentions=discord.AllowedMentions.none()
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """If every non-bot member leaves the bot's voice channel, disconnect."""
        guild = member.guild
        voice = guild.voice_client
        if voice is None or voice.channel is None:
            return

        if member.bot:
            return

        if before.channel != voice.channel:
            return
        if after.channel == voice.channel:
            return

        humans_left = [m for m in voice.channel.members if not m.bot]
        if humans_left:
            return

        log.info("Channel emptied in guild %s — disconnecting", guild.id)
        player = self._players.pop(guild.id, None)
        if player is not None:
            await player.shutdown()
        else:
            await voice.disconnect(force=False)

    async def cog_unload(self) -> None:
        for player in list(self._players.values()):
            await player.shutdown()
        self._players.clear()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
