import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os
import yt_dlp
import logging
from dotenv import load_dotenv
from async_timeout import timeout
import re
import random
from collections import deque
import lyricsgenius

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('discord')

# Bot Configuration
BOT_TOKEN = os.getenv('DISCORD_TOKEN')
GENIUS_TOKEN = os.getenv('GENIUS_TOKEN')
COMMAND_PREFIX = '!'
STATUS_MESSAGE = '🎵 LapisMusic | /help'
BOT_STATUS = discord.Status.dnd

# FFmpeg configuration (Android/Pydroid3 path)
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
    'executable': 'ffmpeg'
}

# Optimized YouTube DL configuration
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': True,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'socket_timeout': 3,
    'extract_flat': True,
}

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)
bot.remove_command('help')
genius = lyricsgenius.Genius(GENIUS_TOKEN, timeout=15, remove_section_headers=True) if GENIUS_TOKEN else None

class MusicSource:
    __slots__ = ('title', 'url', 'duration', 'thumbnail', 'requester', 'stream_url')
    
    def __init__(self, data, requester):
        self.title = data.get('title', 'Unknown Title')[:100]
        self.url = data.get('webpage_url', data.get('url'))
        self.duration = data.get('duration', 0)
        self.thumbnail = data.get('thumbnail')
        self.requester = requester
        self.stream_url = data.get('url')

class MusicPlayer:
    def __init__(self, ctx):
        self.bot = ctx.bot
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.queue = deque()
        self.next = asyncio.Event()
        self.current = None
        self.volume = 0.5
        self.loop = False
        self._24_7 = False
        ctx.bot.loop.create_task(self.player_loop())

    async def player_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            self.next.clear()
            
            if not self.queue and not self._24_7:
                try:
                    await asyncio.wait_for(self.next.wait(), timeout=300)
                except asyncio.TimeoutError:
                    await self.destroy()
                    return
                continue
            
            if self.loop and self.current:
                self.queue.appendleft(self.current)
            
            try:
                async with timeout(10):
                    self.current = self.queue.popleft()
            except (asyncio.TimeoutError, IndexError):
                if not self._24_7:
                    await self.destroy()
                return
            
            voice = self.guild.voice_client
            if voice and not voice.is_playing():
                try:
                    voice.play(discord.FFmpegPCMAudio(
                        self.current.stream_url,
                        **FFMPEG_OPTIONS
                    ), after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set))
                    
                    embed = discord.Embed(
                        title="🎶 Now Playing",
                        description=f"[{self.current.title}]({self.current.url})",
                        color=discord.Color.green()
                    )
                    if self.current.thumbnail:
                        embed.set_thumbnail(url=self.current.thumbnail)
                    embed.add_field(name="Requested by", value=self.current.requester.mention)
                    await self.channel.send(embed=embed)
                except Exception as e:
                    logger.error(f"Play error: {e}")
                    self.next.set()
            
            await self.next.wait()

    async def destroy(self):
        if self.guild.voice_client and not self._24_7:
            await self.guild.voice_client.disconnect()
        self.queue.clear()

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.players = {}

    def get_player(self, ctx):
        player = self.players.get(ctx.guild.id)
        if not player:
            player = MusicPlayer(ctx)
            self.players[ctx.guild.id] = player
        return player

    async def ensure_voice(self, interaction):
        if not interaction.guild.voice_client:
            if interaction.user.voice:
                await interaction.user.voice.channel.connect()
                return True
            await interaction.response.send_message("❌ You must be in a voice channel!", ephemeral=True)
            return False
        return True

    @app_commands.command(name="play", description="Play a song from YouTube")
    @app_commands.describe(query="Song URL or search term")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        
        if not await self.ensure_voice(interaction):
            return
        
        ctx = await self.bot.get_context(interaction)
        player = self.get_player(ctx)
        
        try:
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ytdl:
                data = await self.bot.loop.run_in_executor(
                    None, 
                    lambda: ytdl.extract_info(
                        f"ytsearch:{query}" if not re.match(r"https?://", query) else query,
                        download=False
                    )
                )
                
                if 'entries' in data:
                    data = data['entries'][0]
                
                source = MusicSource(data, interaction.user)
                player.queue.append(source)
                
                embed = discord.Embed(
                    title="🎵 Added to Queue",
                    description=f"[{source.title}]({source.url})",
                    color=discord.Color.blue()
                )
                if source.thumbnail:
                    embed.set_thumbnail(url=source.thumbnail)
                embed.add_field(name="Position", value=f"{len(player.queue)}")
                await interaction.followup.send(embed=embed)
                
                player.next.set()
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}")

    @app_commands.command(name="skip", description="Skip current song")
    async def skip(self, interaction: discord.Interaction):
        player = self.players.get(interaction.guild.id)
        if not player or not interaction.guild.voice_client.is_playing():
            return await interaction.response.send_message("❌ Nothing playing!", ephemeral=True)
        
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ Skipped current song!")

    @app_commands.command(name="stop", description="Stop player without disconnecting")
    async def stop(self, interaction: discord.Interaction):
        player = self.players.get(interaction.guild.id)
        if player:
            player.queue.clear()
            if interaction.guild.voice_client.is_playing():
                interaction.guild.voice_client.stop()
            await interaction.response.send_message("⏹️ Stopped player and cleared queue!")
        else:
            await interaction.response.send_message("❌ No active player!", ephemeral=True)

    @app_commands.command(name="queue", description="Show current queue")
    async def queue(self, interaction: discord.Interaction):
        player = self.players.get(interaction.guild.id)
        if not player or not player.queue:
            return await interaction.response.send_message("📭 Queue is empty!", ephemeral=True)
        
        embed = discord.Embed(title="🎵 Music Queue", color=discord.Color.blue())
        for i, song in enumerate(player.queue[:10], 1):
            embed.add_field(
                name=f"{i}. {song.title}",
                value=f"Requested by {song.requester.mention}",
                inline=False
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="247", description="Enable 24/7 mode (Admin only)")
    @app_commands.default_permissions(administrator=True)
    async def twenty_four_seven(self, interaction: discord.Interaction):
        player = self.players.get(interaction.guild.id)
        if not player:
            return await interaction.response.send_message("❌ No active player!", ephemeral=True)
        
        player._24_7 = not player._24_7
        status = "ENABLED 🔒" if player._24_7 else "DISABLED 🔓"
        await interaction.response.send_message(f"🕒 24/7 Mode {status}")

    @app_commands.command(name="lyrics", description="Get current song lyrics")
    async def lyrics(self, interaction: discord.Interaction):
        player = self.players.get(interaction.guild.id)
        if not player or not player.current:
            return await interaction.response.send_message("❌ Nothing playing!", ephemeral=True)
        if not genius:
            return await interaction.response.send_message("❌ Lyrics service unavailable!", ephemeral=True)
        
        await interaction.response.defer()
        try:
            # Clean song title for better search
            clean_title = re.sub(r'\([^)]*\)|\[[^\]]*\]|\bMV\b|\bOfficial Video\b', '', player.current.title).strip()
            song = genius.search_song(clean_title, get_full_info=False)
            
            if song and song.lyrics:
                lyrics = f"**{song.title}**\n\n{song.lyrics[:1900]}..."
                await interaction.followup.send(lyrics)
            else:
                await interaction.followup.send("❌ Lyrics not found!")
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}")

    @app_commands.command(name="loop", description="Toggle loop mode")
    async def loop(self, interaction: discord.Interaction):
        player = self.players.get(interaction.guild.id)
        if not player:
            return await interaction.response.send_message("❌ No active player!", ephemeral=True)
        
        player.loop = not player.loop
        status = "🔁 Enabled" if player.loop else "➡️ Disabled"
        await interaction.response.send_message(f"Loop {status}")

    @app_commands.command(name="volume", description="Set volume (0-200%)")
    @app_commands.describe(level="Volume level (0-200)")
    async def volume(self, interaction: discord.Interaction, level: int):
        player = self.players.get(interaction.guild.id)
        if not player:
            return await interaction.response.send_message("❌ No active player!", ephemeral=True)
        
        if 0 <= level <= 200:
            player.volume = level / 100
            await interaction.response.send_message(f"🔊 Volume set to {level}%")
        else:
            await interaction.response.send_message("❌ Volume must be between 0-200!", ephemeral=True)

    @app_commands.command(name="nowplaying", description="Show current song info")
    async def nowplaying(self, interaction: discord.Interaction):
        player = self.players.get(interaction.guild.id)
        if not player or not player.current:
            return await interaction.response.send_message("❌ Nothing playing!", ephemeral=True)
        
        embed = discord.Embed(
            title="🎶 Now Playing",
            description=f"**{player.current.title}**\n{player.current.url}",
            color=discord.Color.green()
        )
        if player.current.thumbnail:
            embed.set_thumbnail(url=player.current.thumbnail)
        embed.set_footer(text=f"Requested by {player.current.requester}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="help", description="Show all commands")
    async def help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="NepCraft Music Bot Help",
            description="**Available Commands:**",
            color=discord.Color.blue()
        )
        
        commands_list = [
            ("/play [query]", "Play music from YouTube"),
            ("/skip", "Skip current song"),
            ("/stop", "Stop player and clear queue"),
            ("/queue", "Show current queue"),
            ("/loop", "Toggle loop mode"),
            ("/volume [0-200]", "Adjust playback volume"),
            ("/247", "24/7 mode (Admin only)"),
            ("/lyrics", "Get current song lyrics"),
            ("/nowplaying", "Show current track info"),
            ("/help", "Show this help menu")
        ]
        
        for cmd, desc in commands_list:
            embed.add_field(name=cmd, value=desc, inline=False)
        
        await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} commands")
    except Exception as e:
        logger.error(f"Command sync error: {e}")
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name=STATUS_MESSAGE
        ),
        status=BOT_STATUS
    )

async def setup():
    await bot.add_cog(Music(bot))

def main():
    try:
        asyncio.run(setup())
        bot.run(BOT_TOKEN)
    except Exception as e:
        logger.error(f"Startup error: {e}")

if __name__ == "__main__":
    main()
