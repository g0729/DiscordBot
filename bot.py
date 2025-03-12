import asyncio


from discord.ui import View, Button
import discord
import yt_dlp as youtube_dl
from discord.ext import commands
from config import TOKEN, ytdl_format_options, ffmpeg_options, music_channel

# Suppress noise about console usage from errors
youtube_dl.utils.bug_reports_message = lambda: ""


ytdl = youtube_dl.YoutubeDL(ytdl_format_options)
music_queue_lock = asyncio.Lock()  # 대기열 동기화를 위한 락 생성

panel = None
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)  # 명령어 접두사 설정


@bot.event
async def on_ready():
    print("ㅎㅇㅎㅇ")


@bot.command(aliases=["입장"])
async def join(ctx):
    embed = discord.Embed(title="디스코드 봇 도우미(개발용)", description="음성 채널 개발용 디스코드 봇", color=0x00FF56)

    if ctx.author.voice is None:
        embed.add_field(name=":exclamation:", value="음성 채널에 유저가 존재하지 않습니다. 1명 이상 입장해주세요.")
        await ctx.send(embed=embed, delete_after=5)
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
    global panel

    guild = ctx.guild
    existing_channel = discord.utils.get(guild.text_channels, name=music_channel)

    if existing_channel:
        await ctx.send(f"'{music_channel}' 채널이 이미 존재합니다!", delete_after=5)
        return

    new_channel = await guild.create_text_channel(music_channel)
    embed = discord.Embed(
        title="🎵 음악 컨트롤 패널",
        description="아래 버튼을 사용해 음악을 제어하세요!",
        color=0x1DB954,
    )
    embed.set_footer(text="음악 봇 | 디스코드")

    view = MusicControlPanel(bot, ctx)
    panel = await new_channel.send(embed=embed, view=view)  # 패널 메시지 저장
    await ctx.send(f"새로운 채팅 채널 '{music_channel}'이(가) 생성되었습니다!", delete_after=5)


@bot.event
async def on_voice_state_update(member, before, after):
    global music_queue
    global is_playing
    guild = member.guild
    embed = discord.Embed(title="디스코드 봇 도우미(개발용)", description="음성 채널 개발용 디스코드 봇", color=0x00FF56)
    # 음성 채널 상태 변화 감지
    voice_client = discord.utils.get(bot.voice_clients, guild=member.guild)

    if voice_client and len(voice_client.channel.members) == 1:  # 봇만 남아있다면
        text_channel = discord.utils.get(guild.text_channels, name="일반")
        embed.add_field(
            name=":exit:",
            value="사용자가 없어서 자동으로 퇴장합니다.",
            inline=False,
        )
        await text_channel.send(embed=embed, delete_after=5)

        music_queue = []
        is_playing = False

        await update_panel()
        await voice_client.disconnect()  # 음성 채널에서 나가기
        channel = voice_client.channel


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
        try:
            await ctx.invoke(bot.get_command("join"))
        except:
            await message.delete()
            return
        await add(ctx, url=message.content, author=message.author.nick)
        await message.delete()
    # 명령어 처리를 위해 추가
    await bot.process_commands(message)


music_queue = []
is_playing = False


@bot.command()
async def add(ctx, *, url, author):
    """음악 대기열에 곡 추가"""
    global music_queue_lock
    global is_playing
    async with ctx.typing():
        async with music_queue_lock:  # 락을 사용하여 동기화
            try:
                # URL에서 플레이어 데이터 가져오기
                player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)

                # 곡 정보를 대기열에 추가
                music_queue.append((player, author))

                # 대기열 추가 알림
                embed = discord.Embed(
                    title="🎵 대기열에 추가되었습니다",
                    description=player.title,
                    color=0x1DB954,
                )
                embed.set_thumbnail(url=player.thumbnail)
                await ctx.send(embed=embed, delete_after=5)

                if not is_playing and ctx.voice_client and not ctx.voice_client.is_playing():
                    await play_next(ctx)

            except Exception as e:
                await ctx.send(f"❌ 오류가 발생했습니다: {e}",delete_after=5)


async def update_panel(title=None, thumbnail_url=None, author=None):
    """음악 컨트롤 패널의 제목과 썸네일 업데이트"""
    global panel

    if not panel:
        return 

    # 기존 임베드 가져오기
    embed = panel.embeds[0]

    # 제목 업데이트
    if title:
        embed.title = f"🎵 현재 재생 중: {title}"
    else:
        embed.title = "🎵 현재 재생중인 음악이 없습니다"
    # 썸네일 업데이트
    if thumbnail_url:
        embed.set_image(url=thumbnail_url)
    else:
        embed.set_image(url=None)

    if author:
        embed.set_footer(text=f"음악 봇 | 디스코드 신청자 : {author}")
    # 패널 메시지 수정
    await panel.edit(embed=embed)


@bot.command()
async def remove(ctx, index: int):
    """대기열에서 곡 제거"""
    if index < 1 or index > len(music_queue):
        await ctx.send("❌ 잘못된 곡 번호입니다.", delete_after=5)
        return

    removed = music_queue.pop(index - 1)
    await ctx.send(f"🎵 대기열에서 제거되었습니다: {removed}", delete_after=5)


@bot.command(aliases=["테스트"])
async def retrieve_panel(ctx):
    global panel

    channel = discord.utils.get(ctx.guild.text_channels, name=music_channel)
    if not channel:
        return

    async for msg in channel.history(limit=50):
        # 혹시 이미 panel을 찾았으면 반복문 중단

        # 메시지가 봇이 보낸 것이고 임베드를 가지고 있는지 확인
        if msg.author.id == bot.user.id and msg.embeds:
            embed = msg.embeds[0]
            footer_text = embed.footer.text if embed.footer and embed.footer.text else ""

            # footer에 특정 문자열(패널 식별용)이 있는지 확인
            if "음악 봇 | 디스코드" in footer_text:
                # == 패널 메시지 찾음 ==
                panel = msg

                # 새 View를 달아준다
                new_view = MusicControlPanel(bot, ctx)
                await panel.edit(view=new_view)

            else:
                # 봇 메시지지만 패널이 아닌 다른 임베드라면 지울 수도 있음
                await msg.delete()
        else:
            # 일반 유저 메시지 또는 임베드 없는 메시지면 지우는 로직
            await msg.delete()


async def play_next(ctx):
    """대기열에서 다음 곡 재생"""
    global is_playing

    if music_queue:
        is_playing = True
        temp = music_queue.pop(0)
        player = temp[0]
        author = temp[1]
        ctx.voice_client.play(player, after=lambda _: asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop))

        await retrieve_panel(ctx)

        await update_panel(player.title, player.thumbnail, author)
    else:
        is_playing = False
        await ctx.send("🎵 대기열이 비어 있습니다.", delete_after=3)


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
            await interaction.response.send_message("음성 채널에 연결되지 않았습니다.", ephemeral=True, delete_after=5)
            return

        if self.ctx.voice_client.is_playing():
            await interaction.response.send_message("음악이 이미 재생 중입니다.", ephemeral=True, delete_after=5)
            return

        self.ctx.voice_client.resume()
        await interaction.response.send_message("음악을 다시 재생합니다!", ephemeral=True, delete_after=5)

    @discord.ui.button(label="⏸️ 일시정지", style=discord.ButtonStyle.blurple)
    async def pause_button(self, interaction: discord.Interaction, button: Button):
        """일시 정지 버튼"""
        if not self.ctx.voice_client:
            await interaction.response.send_message("음성 채널에 연결되지 않았습니다.", ephemeral=True, delete_after=5)
            return

        if not self.ctx.voice_client.is_playing():
            await interaction.response.send_message("현재 재생 중인 음악이 없습니다.", ephemeral=True, delete_after=5)
            return

        self.ctx.voice_client.pause()
        await interaction.response.send_message("음악을 일시 정지했습니다.", ephemeral=True, delete_after=5)

    @discord.ui.button(label="⏹️ 정지", style=discord.ButtonStyle.red)
    async def stop_button(self, interaction: discord.Interaction, button: Button):
        """정지 버튼"""
        if not self.ctx.voice_client:
            await interaction.response.send_message("봇이 음성 채널에 연결되어 있지 않습니다.", ephemeral=True, delete_after=5)
            return

        await self.ctx.voice_client.disconnect()
        await interaction.response.send_message("음악을 멈추고 음성 채널에서 나갔습니다.", ephemeral=True, delete_after=5)

    @discord.ui.button(label="🎶 대기열 확인", style=discord.ButtonStyle.blurple)
    async def queue_button(self, interaction: discord.Interaction, button: Button):
        """대기열 확인 버튼"""
        if not music_queue:
            await interaction.response.send_message("🎵 대기열이 비어 있습니다.", ephemeral=True, delete_after=5)
            return

        # 대기열 정보를 생성
        embed = discord.Embed(
            title="🎶 현재 대기열",
            color=0x1DB954,
        )
        for i, track in enumerate(music_queue, start=1):
            embed.add_field(name=f"{i}. {track[0].title}", value=f"[링크]({track[0].url})", inline=False)
        embed.set_thumbnail(url=music_queue[0][0].thumbnail)  # 첫 곡의 썸네일 설정
        await interaction.response.send_message(embed=embed, ephemeral=True, delete_after=10)

    @discord.ui.button(label="⏭️ 다음 곡", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        """다음 곡 버튼"""
        if not self.ctx.voice_client or not music_queue:
            await interaction.response.send_message("대기열에 곡이 없습니다.", ephemeral=True, delete_after=5)
            return
        self.ctx.voice_client.stop()  # 기존 곡 정지

        await interaction.response.send_message("다음 곡을 재생합니다.", ephemeral=True, delete_after=5)


bot.run(TOKEN)
