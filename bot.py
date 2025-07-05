import asyncio
from discord.ui import View, Button
import discord
import yt_dlp as youtube_dl
from yt_dlp.utils import DownloadError
from discord.ext import commands
from config import TOKEN, ytdl_format_options, ffmpeg_options, music_channel
import os
import sys
from openai import OpenAI
import random
import traceback

# OpenAI 클라이언트 초기화
client = OpenAI()

# yt_dlp 오류 메시지 숨기기
youtube_dl.utils.bug_reports_message = lambda *args, **kwargs: ""

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

# 각 서버(guild)의 상태를 저장하는 딕셔너리
guild_states = {}

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
images_dir = os.path.join(os.getcwd(), "images")

class GuildState:
    def __init__(self):
        self.music_queue = asyncio.Queue()
        self.voice_client = None
        self.is_playing = False
        self.current_song_info = None
        self.music_panel_message = None
        self.music_queue_lock = asyncio.Lock()
        self.banded_list = []
        self.ytdl_lock = asyncio.Lock() 

    async def get_next_song(self):
        async with self.music_queue_lock:
            if not self.music_queue.empty():
                return await self.music_queue.get()
            return None

    async def add_song(self, player_info, author):
        async with self.music_queue_lock:
            await self.music_queue.put((player_info, author))

    async def clear_queue(self):
        async with self.music_queue_lock:
            self.music_queue = asyncio.Queue()

    async def get_queue_list(self):
        async with self.music_queue_lock:
            return list(self.music_queue._queue)

async def get_guild_state(guild_id):
    if guild_id not in guild_states:
        guild_states[guild_id] = GuildState()
    return guild_states[guild_id]

 

@bot.command(aliases=["금지어목록"])
async def print_banded_list(ctx):
    state = await get_guild_state(ctx.guild.id)
    if not state.banded_list:
        await ctx.send("금지어 목록이 비어있습니다.")
        return
    await ctx.send(", ".join(state.banded_list)) 

@bot.command(aliases=["금지어추가"])
async def add_banded(ctx, *, s:str):
    state = await get_guild_state(ctx.guild.id)
    if s in state.banded_list:
        await ctx.send("이미 금지어 목록에 있습니다.")
        return
    state.banded_list.append(s)
    await ctx.send(f"금지어에 '{s}' 가(이) 추가 되었습니다")

@bot.command(aliases=["금지어제거"])
async def delete_banded(ctx, *, s:str):
    state = await get_guild_state(ctx.guild.id)
    if s not in state.banded_list:
        await ctx.send(f"'{s}'는 금지어 목록에 없습니다")
        return
    state.banded_list.remove(s)
    await ctx.send(f"금지어 목록에서 '{s}'가(이) 제거되었습니다.")

@bot.command(aliases=["입장"])
async def join(ctx):
    state = await get_guild_state(ctx.guild.id)
    
    if ctx.author.voice is None:
        await ctx.send(":exclamation: 음성 채널에 먼저 입장해주세요.", delete_after=5)
        raise commands.CommandError("사용자가 음성 채널에 없습니다.")

    channel = ctx.author.voice.channel

    if state.voice_client and state.voice_client.is_connected():
        if state.voice_client.channel != channel:
            await state.voice_client.move_to(channel)
    else:
        state.voice_client = await channel.connect()

@bot.command(aliases=["음악채널생성"])
async def create_music_channel(ctx):
    guild = ctx.guild
    existing_channel = discord.utils.get(guild.text_channels, name=music_channel)

    if existing_channel:
        await ctx.send(f"'{music_channel}' 채널이 이미 존재합니다!", delete_after=5)
        return

    new_channel = await guild.create_text_channel(music_channel)
    embed = discord.Embed(
        title="🎵 음악 컨트롤 패널",
        description="이 채널에 듣고 싶은 노래 제목이나 유튜브 URL을 입력하세요!",
        color=0x1DB954,
    )
    embed.set_footer(text="음악 봇 | 디스코드")

    view = MusicControlPanel(bot, ctx.guild.id)
    state = await get_guild_state(ctx.guild.id)
    state.music_panel_message = await new_channel.send(embed=embed, view=view)
    await ctx.send(f"새로운 채팅 채널 '{music_channel}'이(가) 생성되었습니다!", delete_after=5)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    guild = member.guild
    state = await get_guild_state(guild.id)
    voice_client = state.voice_client

    if voice_client and len(voice_client.channel.members) == 1:
        text_channel = discord.utils.get(guild.text_channels, name=music_channel) or member.guild.system_channel
        if text_channel:
            await text_channel.send(":exit: 채널에 아무도 없어 봇이 퇴장합니다.", delete_after=10)

        await state.clear_queue()
        state.is_playing = False
        state.current_song_info = None
        await voice_client.disconnect()
        state.voice_client = None
        await retrieve_panel_and_update(guild.id)

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    # 음악 채널에 입력된 메시지 처리
    if message.channel.name == music_channel:
        ctx = await bot.get_context(message)
        
        # 입력된 내용이 '!명령어' 형태가 아닐 때만 음악 추가로 간주
        if not message.content.startswith(bot.command_prefix):
            try:
                # 봇을 음성 채널에 먼저 참여시킴
                join_command = bot.get_command('join')
                await ctx.invoke(join_command)
                
                # 그 다음, add 명령어를 호출
                add_command = bot.get_command('add')
                await ctx.invoke(add_command, url=message.content, author=message.author.display_name)
            except Exception as e:
                traceback.print_exc()
                await message.channel.send(f"오류가 발생했습니다: {e}", delete_after=5)

            return # 음악 추가 로직이 끝났으므로 여기서 함수 종료

    # 모든 메시지에 대해 명령어 처리를 시도
    await bot.process_commands(message)

@bot.command()
async def add(ctx: commands.Context, *, url: str, author: str):
    state = await get_guild_state(ctx.guild.id)

    async with ctx.typing():
       async with state.ytdl_lock:
            try:
                player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)

                for banded in state.banded_list:
                    if banded.lower() in player.title.lower():
                        await ctx.send(f"금지어가 포함된 제목입니다: {player.title}", delete_after=5)
                        return
                
                await state.add_song(player, author)

                embed = discord.Embed(
                    title="🎵 대기열 추가",
                    description=f"[{player.title}]({player.url})",
                    color=0x1DB954,
                )
                embed.set_thumbnail(url=player.thumbnail)
                embed.set_footer(text=f"신청자: {author}")
                await ctx.send(embed=embed, delete_after=5)

                if not state.is_playing and state.voice_client and not state.voice_client.is_playing():
                    await play_next(ctx)

            except DownloadError:
                await ctx.send("오류가 발생했습니다 잠시 뒤에 다시 입력해주세요",delete_after=5)
                os.system('python error_handler.py')
            except Exception as e:
                traceback.print_exc()
                await ctx.send(f"❌ 오류가 발생했습니다: {e}", delete_after=5)
    
async def update_panel(guild_id, title=None, thumbnail_url=None, author=None):
    state = await get_guild_state(guild_id)
    
    if not state.music_panel_message:
        return 

    embed = state.music_panel_message.embeds[0]

    if title:
        embed.title = "🎵 현재 재생 중"
        # state.current_song_info가 None이 아닐 때만 url에 접근하도록 수정
        if state.current_song_info:
            embed.description = f"[{title}]({state.current_song_info.url})"
        else:
            embed.description = title
    else:
        embed.title = "🎵 음악 컨트롤 패널"
        embed.description = "이 채널에 듣고 싶은 노래 제목이나 유튜브 URL을 입력하세요!"

    if thumbnail_url:
        embed.set_image(url=thumbnail_url)
    else:
        # ⭐️ 이 부분을 None으로 수정합니다.
        embed.set_image(url=None)

    if author:
        embed.set_footer(text=f"음악 봇 | 신청자: {author}")
    else:
        embed.set_footer(text="음악 봇 | 디스코드")
        
    try:
        await state.music_panel_message.edit(embed=embed)
    except discord.NotFound:
        # 메시지가 삭제된 경우
        state.music_panel_message = None

@bot.command()
async def remove(ctx, index: int):
    state = await get_guild_state(ctx.guild.id)
    queue_list = await state.get_queue_list()
    
    if not (1 <= index <= len(queue_list)):
        await ctx.send("❌ 잘못된 곡 번호입니다.", delete_after=5)
        return

    removed_item = queue_list.pop(index - 1)
    
    await state.clear_queue()
    for item in queue_list:
        await state.add_song(item[0], item[1])

    await ctx.send(f"🎵 대기열에서 제거되었습니다: {removed_item[0].title}", delete_after=5)

async def retrieve_panel_and_update(guild_id):
    """
    패널을 찾아 다시 연결하고, 채널의 다른 메시지들을 정리합니다.
    """
    guild = bot.get_guild(guild_id)
    if not guild:
        return

    state = await get_guild_state(guild_id)
    channel = discord.utils.get(guild.text_channels, name=music_channel)
    if not channel:
        return

    panel_to_keep = None
    async for msg in channel.history(limit=100):
        # 메시지가 음악 패널인지 확인
        is_panel = (
            msg.author.id == bot.user.id and
            msg.embeds and
            msg.embeds[0].footer and
            "음악 봇" in msg.embeds[0].footer.text
        )

        if is_panel and panel_to_keep is None:
            # 가장 최신 패널을 처음 발견한 경우, 이 메시지를 유지하도록 지정
            panel_to_keep = msg
        else:
            # 그 외 모든 메시지 (사용자 메시지, 봇의 다른 응답, 오래된 패널)는 삭제
            try:
                await msg.delete()
            except discord.NotFound:
                # 이미 삭제된 메시지는 무시
                pass
            except discord.Forbidden:
                # 권한이 없는 경우 무시
                pass
    
    # 루프가 끝난 후, 유지하기로 한 패널이 있다면 상태를 업데이트
    state.music_panel_message = panel_to_keep
    if state.music_panel_message:
        new_view = MusicControlPanel(bot, guild_id)
        try:
            await state.music_panel_message.edit(view=new_view)
            
            # 봇의 현재 상태에 맞게 패널 내용을 다시 그림
            if state.is_playing and state.current_song_info:
                # 현재 재생 중인 곡의 신청자는 찾기 어려우므로, 기본 정보로 업데이트
                await update_panel(guild_id, state.current_song_info.title, state.current_song_info.thumbnail)
            else:
                await update_panel(guild_id) # 기본 상태로 업데이트
        except discord.NotFound:
            state.music_panel_message = None # 수정하려는데 메시지가 없다면 None으로 처리
            
async def play_next(ctx: commands.Context):
    state = await get_guild_state(ctx.guild.id)
    
    next_song = await state.get_next_song()

    if next_song:
        state.is_playing = True
        player, author = next_song
        state.current_song_info = player

        if state.voice_client and state.voice_client.is_connected():
            state.voice_client.play(player, after=lambda _: bot.loop.create_task(play_next(ctx)))
            await retrieve_panel_and_update(ctx.guild.id)
            await update_panel(ctx.guild.id, player.title, player.thumbnail, author)
        else:
            state.is_playing = False
            state.current_song_info = None
            await ctx.send("봇이 음성 채널에 없어 재생을 중단합니다.", delete_after=5)
            await update_panel(ctx.guild.id)
    else:
        state.is_playing = False
        state.current_song_info = None
        await update_panel(ctx.guild.id)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("webpage_url")
        self.thumbnail = data.get("thumbnail")
        self.uploader = data.get('uploader')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if "entries" in data:
            data = data["entries"][0]

        filename = data["url"] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

class MusicControlPanel(View):
    def __init__(self, bot, guild_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        
    async def get_current_guild_state(self, interaction: discord.Interaction):
        return await get_guild_state(interaction.guild.id)

    # --- 버튼들 ---
    @discord.ui.button(label="▶️ 재생", style=discord.ButtonStyle.green)
    async def play_button(self, interaction: discord.Interaction, button: Button):
        state = await self.get_current_guild_state(interaction)
        
        if not state.voice_client or not state.voice_client.is_connected():
            return await interaction.response.send_message("음성 채널에 연결되지 않았습니다.", ephemeral=True, delete_after=5)
        if state.voice_client.is_playing():
            return await interaction.response.send_message("이미 재생 중입니다.", ephemeral=True, delete_after=5)
        if state.voice_client.is_paused():
            state.voice_client.resume()
            await interaction.response.send_message("▶️ 음악을 다시 재생합니다.", ephemeral=True, delete_after=5)
        else:
            await interaction.response.send_message("재생할 음악이 없습니다.", ephemeral=True, delete_after=5)

    @discord.ui.button(label="⏸️ 일시정지", style=discord.ButtonStyle.blurple)
    async def pause_button(self, interaction: discord.Interaction, button: Button):
        state = await self.get_current_guild_state(interaction)
        if not state.voice_client or not state.voice_client.is_playing():
            return await interaction.response.send_message("현재 재생 중인 음악이 없습니다.", ephemeral=True, delete_after=5)
        state.voice_client.pause()
        await interaction.response.send_message("⏸️ 음악을 일시 정지했습니다.", ephemeral=True, delete_after=5)

    @discord.ui.button(label="⏹️ 정지", style=discord.ButtonStyle.red)
    async def stop_button(self, interaction: discord.Interaction, button: Button):
        state = await self.get_current_guild_state(interaction)
        if not state.voice_client:
            return await interaction.response.send_message("봇이 음성 채널에 없습니다.", ephemeral=True, delete_after=5)
        
        await state.clear_queue()
        if state.voice_client.is_playing() or state.voice_client.is_paused():
            state.voice_client.stop() # play_next의 after 콜백을 방지하고 바로 정지

        await state.voice_client.disconnect()
        state.voice_client = None
        state.is_playing = False
        state.current_song_info = None
        await update_panel(self.guild_id)
        await interaction.response.send_message("⏹️ 음악을 멈추고 음성 채널에서 나갔습니다.", ephemeral=True, delete_after=5)

    @discord.ui.button(label="🎶 대기열", style=discord.ButtonStyle.blurple)
    async def queue_button(self, interaction: discord.Interaction, button: Button):
        state = await self.get_current_guild_state(interaction)
        queue_list = await state.get_queue_list()
        
        embed = discord.Embed(title="🎶 현재 대기열", color=0x1DB954)

        if not queue_list:
            embed.description = "대기열이 비어 있습니다."
        else:
            for i, (player, author) in enumerate(queue_list, start=1):
                embed.add_field(name=f"{i}. {player.title}", value=f"신청자: {author}", inline=False)
            embed.set_thumbnail(url=queue_list[0][0].thumbnail)
        
        await interaction.response.send_message(embed=embed, ephemeral=True, delete_after=15)

    @discord.ui.button(label="⏭️ 다음 곡", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        state = await self.get_current_guild_state(interaction)
        if not state.voice_client or not state.is_playing:
            return await interaction.response.send_message("재생 중인 곡이 없습니다.", ephemeral=True, delete_after=5)
        
        queue_list = await state.get_queue_list()
        if not queue_list:
             return await interaction.response.send_message("대기열에 다음 곡이 없습니다.", ephemeral=True, delete_after=5)

        state.voice_client.stop()
        await interaction.response.send_message("⏭️ 다음 곡을 재생합니다.", ephemeral=True, delete_after=5)

@bot.event
async def on_ready():
    print(f'{bot.user}으로 로그인 성공!')
    for guild in bot.guilds:
        await retrieve_panel_and_update(guild.id)
    print("모든 서버의 음악 패널을 재연결했습니다.")


if __name__ == "__main__":
    bot.run(TOKEN)