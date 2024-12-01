import asyncio


from discord.ui import View, Button
import discord
import yt_dlp as youtube_dl
from discord.ext import commands
from config import TOKEN

# Suppress noise about console usage from errors
youtube_dl.utils.bug_reports_message = lambda: ""
discord.opus.load_opus("/opt/homebrew/lib/libopus.dylib")


ytdl_format_options = {
    "format": "bestaudio/best",
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "logtostderr": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",  # bind to ipv4 since ipv6 addresses cause issues sometimes
    "cookiefile": "cookies.txt",  # 쿠키 파일 경로 설정
}

ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)  # 명령어 접두사 설정
music_channel = "박찬영육점구센티"


@bot.event
async def on_ready():
    print("ㅎㅇㅎㅇ")


@bot.command(aliases=["입장"])
async def join(ctx):
    embed = discord.Embed(title="디스코드 봇 도우미(개발용)", description="음성 채널 개발용 디스코드 봇", color=0x00FF56)

    if ctx.author.voice is None:
        embed.add_field(name=":exclamation:", value="음성 채널에 유저가 존재하지 않습니다. 1명 이상 입장해주세요.")
        await ctx.send(embed=embed)
        raise commands.CommandInvokeError("사용자가 존재하는 음성 채널을 찾지 못했습니다.")

    channel = ctx.author.voice.channel

    if ctx.voice_client is not None and channel != ctx.voice_client.channel:
        embed.add_field(name=":robot:", value="사용자가 있는 채널로 이동합니다.", inline=False)
        await ctx.send(embed=embed)
        print("음성 채널 정보: {0.author.voice}".format(ctx))
        print("음성 채널 이름: {0.author.voice.channel}".format(ctx))
        return await ctx.voice_client.move_to(channel)

    if ctx.voice_client is None:
        await channel.connect()


@bot.command(aliases=["음악채널생성"])
async def create_music_channel(ctx):
    """음악 채널 생성 및 패널 추가"""
    guild = ctx.guild
    existing_channel = discord.utils.get(guild.text_channels, name=music_channel)

    if existing_channel:
        await ctx.send(f"'{music_channel}' 채널이 이미 존재합니다!")
        return

    # 새로운 채널 생성
    new_channel = await guild.create_text_channel(music_channel)
    await ctx.send(f"새로운 채팅 채널 '{music_channel}'이(가) 생성되었습니다!")

    # 음악 패널 생성
    embed = discord.Embed(
        title="🎵 음악 컨트롤 패널",
        description="아래 버튼을 사용해 음악을 제어하세요!",
        color=0x1DB954,
    )
    embed.set_footer(text="음악 봇 | 디스코드")

    view = MusicControlPanel(bot, ctx)
    await new_channel.send(embed=embed, view=view)


@bot.event
async def on_voice_state_update(member, before, after):
    guild = member.guild
    embed = discord.Embed(title="디스코드 봇 도우미(개발용)", description="음성 채널 개발용 디스코드 봇", color=0x00FF56)
    # 음성 채널 상태 변화 감지
    voice_client = discord.utils.get(bot.voice_clients, guild=member.guild)

    if voice_client and len(voice_client.channel.members) == 1:  # 봇만 남아있다면
        text_channel = discord.utils.get(guild.text_channels, name="일반")
        embed.add_field(name=":exit:", value="사용자가 없어서 자동으로 퇴장합니다.", inline=False)
        await text_channel.send(embed=embed)
        await voice_client.disconnect()  # 음성 채널에서 나가기
        channel = voice_client.channel
        print(f"{channel.name} 채널에서 자동으로 퇴장했습니다.")


def is_in_music_channel():
    async def predicate(ctx):
        return ctx.channel.name == music_channel

    return commands.check(predicate)


@bot.event
async def on_message(message):
    # 봇 자신의 메시지나 DM 채널의 메시지는 무시
    if message.author == bot.user or not message.guild:
        return

    if message.channel.name == music_channel:
        ctx = await bot.get_context(message)  # 명령어 컨텍스트 생성
        await ctx.invoke(bot.get_command("join"))
        await ctx.invoke(bot.get_command("add"), url=message.content)
        await message.delete()
    # 명령어 처리를 위해 추가
    await bot.process_commands(message)


# youtube 음악과 로컬 음악의 재생을 구별하기 위한 클래스 작성.
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("webpage_url")
        self.thumbnail = data.get("thumbnail")

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if "entries" in data:
            # take first item from a playlist
            data = data["entries"][0]

        filename = data["url"] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


music_queue = []
is_playing = False


@bot.command()
async def add(ctx, *, url):
    """음악 대기열에 곡 추가"""
    async with ctx.typing():
        player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)

        # 곡 정보를 딕셔너리로 대기열에 추가
        music_queue.append(player)

    await ctx.send(f"🎵 대기열에 추가되었습니다: {url}", delete_after=5)

    if not is_playing:
        await play_next(ctx)


@bot.command()
async def queue(ctx):
    """현재 대기열 보기"""
    if not music_queue:
        await ctx.send("🎵 대기열이 비어 있습니다.", delete_after=5)
    else:
        queue_list = "\n".join([f"{i+1}. {url}" for i, url in enumerate(music_queue)])
        embed = discord.Embed(
            title="🎶 현재 대기열",
            description=queue_list,
            color=0x1DB954,
        )
        msg = await ctx.send(embed=embed)
        await msg.delete(delay=5)  # 10초 후 삭제


@bot.command()
async def remove(ctx, index: int):
    """대기열에서 곡 제거"""
    if index < 1 or index > len(music_queue):
        await ctx.send("❌ 잘못된 곡 번호입니다.", delete_after=5)
        return

    removed = music_queue.pop(index - 1)
    await ctx.send(f"🎵 대기열에서 제거되었습니다: {removed}", delete_after=5)


async def play_next(ctx):
    """대기열에서 다음 곡 재생"""
    global is_playing

    if music_queue:
        is_playing = True
        player = music_queue.pop(0)

        ctx.voice_client.play(player, after=lambda e: bot.loop.create_task(play_next(ctx)))

        await ctx.send(f"🎶 재생 중: {player.title}", delete_after=5)
    else:
        is_playing = False
        await ctx.send("🎵 대기열이 비어 있습니다.", delete_after=5)


class MusicControlPanel(View):
    def __init__(self, bot, ctx, current_track=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.ctx = ctx
        self.current_track = current_track

    @discord.ui.button(label="▶️ 재생", style=discord.ButtonStyle.green)
    async def play_button(self, interaction: discord.Interaction, button: Button):
        """재생 버튼"""
        if not self.ctx.voice_client:
            await interaction.response.send_message("음성 채널에 연결되지 않았습니다.", ephemeral=True)
            return

        if self.ctx.voice_client.is_playing():
            await interaction.response.send_message("음악이 이미 재생 중입니다.", ephemeral=True)
            return

        self.ctx.voice_client.resume()
        await interaction.response.send_message("음악을 다시 재생합니다!", ephemeral=True)

    @discord.ui.button(label="⏸️ 일시정지", style=discord.ButtonStyle.blurple)
    async def pause_button(self, interaction: discord.Interaction, button: Button):
        """일시 정지 버튼"""
        if not self.ctx.voice_client:
            await interaction.response.send_message("음성 채널에 연결되지 않았습니다.", ephemeral=True)
            return

        if not self.ctx.voice_client.is_playing():
            await interaction.response.send_message("현재 재생 중인 음악이 없습니다.", ephemeral=True)
            return

        self.ctx.voice_client.pause()
        await interaction.response.send_message("음악을 일시 정지했습니다.", ephemeral=True)

    @discord.ui.button(label="⏹️ 정지", style=discord.ButtonStyle.red)
    async def stop_button(self, interaction: discord.Interaction, button: Button):
        """정지 버튼"""
        if not self.ctx.voice_client:
            await interaction.response.send_message("봇이 음성 채널에 연결되어 있지 않습니다.", ephemeral=True)
            return

        await self.ctx.voice_client.disconnect()
        await interaction.response.send_message("음악을 멈추고 음성 채널에서 나갔습니다.", ephemeral=True)

    @discord.ui.button(label="⏭️ 다음 곡", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        """다음 곡 버튼"""
        if not self.ctx.voice_client or not music_queue:
            await interaction.response.send_message("대기열에 곡이 없습니다.", ephemeral=True)
            return

        next_track = music_queue.pop(0)
        self.ctx.voice_client.stop()  # 기존 곡 정지
        self.ctx.voice_client.play(
            next_track,
            after=lambda e: print(f"Player error: {e}") if e else None,
        )

        # 패널 업데이트
        embed = discord.Embed(
            title="🎵 현재 재생 중",
            description=f"**{self.current_track.title}**",
            color=0x1DB954,
        )
        if self.current_track.thumbnail:
            embed.set_thumbnail(url=self.current_track.thumbnail)
        await interaction.response.send_message("다음 곡을 재생합니다.", ephemeral=True)
        await interaction.message.edit(embed=embed, view=self)


bot.run(TOKEN)
