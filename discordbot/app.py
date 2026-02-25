import asyncio
import logging
import os
from typing import Optional

import discord
from discord.ext import commands
from discord.ui import Button, View
from yt_dlp.utils import DownloadError

from discordbot.configuration import (
    BOT_TOKEN,
    LOG_LEVEL,
    MUSIC_CHANNEL,
    PANEL_COLOR,
    PID_FILE_PATH,
    YTDL_MAX_RETRIES,
    YTDL_RETRY_BASE_DELAY_SECONDS,
)
from discordbot.media import YTDLSource, run_error_handler, setup_opus
from discordbot.state import GuildState, get_guild_state, get_guild_state_sync
from discordbot.ui import build_music_panel_embed, is_music_panel_message


def configure_logging() -> None:
    configured_level = getattr(logging, LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=configured_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


configure_logging()
logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

setup_opus()

DOWNLOAD_RECOVERY_PATTERNS = (
    "sign in to confirm you're not a bot",
    "unable to extract",
    "nsig",
    "signature",
    "cipher",
    "player response",
    "http error 403",
)


def should_trigger_auto_recovery(error_text: str) -> bool:
    lowered = error_text.lower()
    if "youtube" not in lowered and "yt" not in lowered:
        return False
    return any(pattern in lowered for pattern in DOWNLOAD_RECOVERY_PATTERNS)


async def fetch_player_with_retry(url: str) -> YTDLSource:
    max_retries = max(0, YTDL_MAX_RETRIES)
    total_attempts = max_retries + 1
    last_exception: Optional[DownloadError] = None

    for attempt in range(1, total_attempts + 1):
        try:
            return await YTDLSource.from_url(url, loop=bot.loop, stream=True)
        except DownloadError as exc:
            last_exception = exc
            if attempt >= total_attempts:
                break

            delay = YTDL_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "yt-dlp 추출 실패 (시도 %d/%d, %.1fs 후 재시도): %s",
                attempt,
                total_attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)

    assert last_exception is not None
    raise last_exception


def write_pid_file() -> None:
    PID_FILE_PATH.write_text(str(os.getpid()), encoding="utf-8")
    logger.info("PID 파일 생성: %s", PID_FILE_PATH)


def cleanup_pid_file() -> None:
    try:
        if not PID_FILE_PATH.exists():
            return

        pid_text = PID_FILE_PATH.read_text(encoding="utf-8").strip()
        if pid_text == str(os.getpid()):
            PID_FILE_PATH.unlink()
            logger.info("PID 파일 삭제: %s", PID_FILE_PATH)
    except Exception:
        logger.exception("PID 파일 정리 중 오류가 발생했습니다.")


async def ensure_voice_connected(ctx: commands.Context) -> discord.VoiceClient:
    state = await get_guild_state(ctx.guild.id)

    if ctx.author.voice is None:
        await ctx.send(":exclamation: 음성 채널에 먼저 입장해주세요.", delete_after=5)
        raise commands.CommandError("사용자가 음성 채널에 없습니다.")

    channel = ctx.author.voice.channel
    try:
        if state.voice_client and state.voice_client.is_connected():
            if state.voice_client.channel != channel:
                await state.voice_client.move_to(channel)
        else:
            state.voice_client = await channel.connect()
    except Exception as exc:
        state.voice_client = None
        logger.exception("음성 채널 연결 실패 (guild_id=%s): %s", ctx.guild.id, exc)
        if isinstance(exc, IndexError):
            raise commands.CommandError(
                "음성 연결에 실패했습니다. discord.py 버전이 오래됐을 가능성이 큽니다. "
                "discord.py를 최신 버전으로 업데이트한 뒤 봇을 재시작해주세요."
            ) from exc
        raise commands.CommandError("음성 채널 연결에 실패했습니다. 잠시 후 다시 시도해주세요.") from exc

    return state.voice_client


async def handle_music_channel_message(message: discord.Message) -> None:
    ctx = await bot.get_context(message)
    try:
        join_command = bot.get_command("join")
        add_command = bot.get_command("add")
        if join_command is None or add_command is None:
            await message.channel.send("음악 명령어를 찾을 수 없습니다.", delete_after=5)
            return

        await ctx.invoke(join_command)
        await ctx.invoke(add_command, url=message.content, author=message.author.display_name)
    except commands.CommandError as exc:
        await message.channel.send(f"오류가 발생했습니다: {exc}", delete_after=8)
    except Exception:
        logger.exception("음악 채널 메시지 처리 실패 (guild_id=%s)", message.guild.id)
        await message.channel.send("오류가 발생했습니다. 잠시 뒤 다시 시도해주세요.", delete_after=5)
    finally:
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass


@bot.command(aliases=["금지어목록"])
async def print_banded_list(ctx: commands.Context) -> None:
    state = await get_guild_state(ctx.guild.id)
    if not state.banded_list:
        await ctx.send("금지어 목록이 비어있습니다.")
        return
    await ctx.send(", ".join(state.banded_list))


@bot.command(aliases=["금지어추가"])
async def add_banded(ctx: commands.Context, *, s: str) -> None:
    state = await get_guild_state(ctx.guild.id)
    if s in state.banded_list:
        await ctx.send("이미 금지어 목록에 있습니다.")
        return
    state.banded_list.append(s)
    await ctx.send(f"금지어에 '{s}' 가(이) 추가 되었습니다")


@bot.command(aliases=["금지어제거"])
async def delete_banded(ctx: commands.Context, *, s: str) -> None:
    state = await get_guild_state(ctx.guild.id)
    if s not in state.banded_list:
        await ctx.send(f"'{s}'는 금지어 목록에 없습니다")
        return
    state.banded_list.remove(s)
    await ctx.send(f"금지어 목록에서 '{s}'가(이) 제거되었습니다.")


@bot.command(aliases=["입장"])
async def join(ctx: commands.Context) -> None:
    await ensure_voice_connected(ctx)


@bot.command(aliases=["음악채널생성"])
async def create_music_channel(ctx: commands.Context) -> None:
    guild = ctx.guild
    existing_channel = discord.utils.get(guild.text_channels, name=MUSIC_CHANNEL)
    if existing_channel:
        await ctx.send(f"'{MUSIC_CHANNEL}' 채널이 이미 존재합니다!", delete_after=5)
        return

    new_channel = await guild.create_text_channel(MUSIC_CHANNEL)
    view = MusicControlPanel(bot, guild.id)
    state = await get_guild_state(guild.id)
    state.music_panel_message = await new_channel.send(embed=build_music_panel_embed(), view=view)
    await ctx.send(f"새로운 채팅 채널 '{MUSIC_CHANNEL}'이(가) 생성되었습니다!", delete_after=5)


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
    if member.bot:
        return

    guild = member.guild
    state = await get_guild_state(guild.id)
    voice_client = state.voice_client

    if not voice_client or not voice_client.channel:
        return
    if len(voice_client.channel.members) != 1:
        return

    text_channel = discord.utils.get(guild.text_channels, name=MUSIC_CHANNEL) or guild.system_channel
    if text_channel:
        await text_channel.send(":exit: 채널에 아무도 없어 봇이 퇴장합니다.", delete_after=10)

    await state.clear_queue()
    state.reset_playback()

    try:
        await voice_client.disconnect()
        logger.info("음성 채널 인원 없음으로 자동 퇴장 (guild_id=%s)", guild.id)
    finally:
        state.voice_client = None

    await retrieve_panel_and_update(guild.id)


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot or not message.guild:
        return

    if message.channel.name == MUSIC_CHANNEL and not message.content.startswith(bot.command_prefix):
        await handle_music_channel_message(message)
        return

    await bot.process_commands(message)


@bot.command()
async def add(ctx: commands.Context, *, url: str, author: Optional[str] = None) -> None:
    state = await get_guild_state(ctx.guild.id)
    request_author = author or ctx.author.display_name

    async with ctx.typing():
        async with state.ytdl_lock:
            try:
                player = await fetch_player_with_retry(url)
                player_title = player.title or "제목 없음"
                logger.info("대기열 추가 대상 추출 성공 (guild_id=%s, title=%s, by=%s)", ctx.guild.id, player_title, request_author)

                for banded in state.banded_list:
                    if banded.lower() in player_title.lower():
                        await ctx.send(f"금지어가 포함된 제목입니다: {player_title}", delete_after=5)
                        return

                await state.add_song(player, request_author)
                embed = discord.Embed(
                    title="🎵 대기열 추가",
                    description=f"[{player_title}]({player.url or url})",
                    color=PANEL_COLOR,
                )
                if player.thumbnail:
                    embed.set_thumbnail(url=player.thumbnail)
                embed.set_footer(text=f"신청자: {request_author}")
                await ctx.send(embed=embed, delete_after=5)

                if not state.is_playing and state.voice_client and not state.voice_client.is_playing():
                    await play_next(ctx)
            except DownloadError as exc:
                error_text = str(exc)
                logger.warning("yt-dlp 추출 최종 실패 (guild_id=%s): %s", ctx.guild.id, error_text)
                await ctx.send("오류가 발생했습니다. 잠시 뒤에 다시 입력해주세요.", delete_after=5)

                if should_trigger_auto_recovery(error_text):
                    logger.warning("업데이트/재시작 자동 복구 조건 만족. error_handler 실행.")
                    run_error_handler()
            except Exception as exc:
                logger.exception("음악 추가 처리 중 예외 (guild_id=%s): %s", ctx.guild.id, exc)
                await ctx.send(f"❌ 오류가 발생했습니다: {exc}", delete_after=5)


async def update_panel(
    guild_id: int,
    title: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    author: Optional[str] = None,
    uploader: Optional[str] = None,
) -> None:
    state = await get_guild_state(guild_id)
    if not state.music_panel_message:
        return

    song_url = state.current_song_info.url if state.current_song_info else None
    embed = build_music_panel_embed(
        title=title, song_url=song_url, thumbnail_url=thumbnail_url, author=author, uploader=uploader
    )

    try:
        await state.music_panel_message.edit(embed=embed)
    except discord.NotFound:
        state.music_panel_message = None


@bot.command()
async def remove(ctx: commands.Context, index: int) -> None:
    state = await get_guild_state(ctx.guild.id)
    queue_list = await state.get_queue_list()

    if not (1 <= index <= len(queue_list)):
        await ctx.send("❌ 잘못된 곡 번호입니다.", delete_after=5)
        return

    removed_item = queue_list.pop(index - 1)
    await state.rebuild_queue(queue_list)
    await ctx.send(f"🎵 대기열에서 제거되었습니다: {removed_item[0].title}", delete_after=5)


async def retrieve_panel_and_update(guild_id: int) -> None:
    guild = bot.get_guild(guild_id)
    if not guild:
        return

    state = await get_guild_state(guild_id)
    channel = discord.utils.get(guild.text_channels, name=MUSIC_CHANNEL)
    if not channel:
        return

    if bot.user is None:
        return
    bot_user_id = bot.user.id

    panel_to_keep: Optional[discord.Message] = None
    async for msg in channel.history(limit=100):
        if is_music_panel_message(msg, bot_user_id) and panel_to_keep is None:
            panel_to_keep = msg
            continue

        try:
            await msg.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

    state.music_panel_message = panel_to_keep
    if not state.music_panel_message:
        return

    new_view = MusicControlPanel(bot, guild_id)
    try:
        await state.music_panel_message.edit(view=new_view)
        if state.is_playing and state.current_song_info:
            info = state.current_song_info
            await update_panel(guild_id, info.title, info.thumbnail, uploader=info.uploader)
        else:
            await update_panel(guild_id)
    except discord.NotFound:
        state.music_panel_message = None


async def prefetch_autoplay_song(guild_id: int) -> None:
    """현재 곡 재생 중에 다음 추천곡을 미리 가져옵니다."""
    state = await get_guild_state(guild_id)
    if state.prefetched_song is not None or not state.autoplay:
        return
    if not state.current_song_info or not state.current_song_info.url:
        return

    try:
        recommended_url = await YTDLSource.get_recommended_url(
            state.current_song_info.url,
            loop=bot.loop,
            exclude_ids=list(state.recently_played),
        )
        if not recommended_url:
            return

        state = await get_guild_state(guild_id)
        if state.prefetched_song is not None or not state.autoplay:
            return

        async with state.ytdl_lock:
            player = await fetch_player_with_retry(recommended_url)

        state.prefetched_song = (player, "자동재생")
        logger.info("자동재생 프리페치 완료 (guild_id=%s, title=%s)", guild_id, player.title)
    except Exception:
        logger.exception("자동재생 프리페치 실패 (guild_id=%s)", guild_id)


async def play_next(ctx: commands.Context) -> None:
    state = await get_guild_state(ctx.guild.id)
    next_song = await state.get_next_song()

    if not next_song:
        if state.autoplay and state.current_song_info and state.current_song_info.url:
            try:
                recommended_url = await YTDLSource.get_recommended_url(
                    state.current_song_info.url,
                    loop=bot.loop,
                    exclude_ids=list(state.recently_played),
                )
                if recommended_url:
                    async with state.ytdl_lock:
                        player = await fetch_player_with_retry(recommended_url)
                    await state.add_song(player, "자동재생")
                    next_song = await state.get_next_song()
                    logger.info("자동재생 추천곡 추가 (guild_id=%s, title=%s)", ctx.guild.id, player.title)
            except Exception:
                logger.exception("자동재생 추천곡 가져오기 실패 (guild_id=%s)", ctx.guild.id)

        if not next_song:
            state.reset_playback()
            await update_panel(ctx.guild.id)
            return

    player, author = next_song
    state.is_playing = True
    state.current_song_info = player
    # 새 곡 시작 시 이전 프리페치 제거 후 현재 곡 기준으로 새로 시작
    state._cleanup_prefetched()
    if player.video_id:
        state.record_played(player.video_id)

    if not state.voice_client or not state.voice_client.is_connected():
        state.reset_playback()
        await ctx.send("봇이 음성 채널에 없어 재생을 중단합니다.", delete_after=5)
        await update_panel(ctx.guild.id)
        return

    state.voice_client.play(player, after=lambda _: bot.loop.create_task(play_next(ctx)))

    # 큐가 비었고 자동재생 ON이면 다음 추천곡을 백그라운드에서 미리 준비
    queue_list = await state.get_queue_list()
    if state.autoplay and not queue_list:
        bot.loop.create_task(prefetch_autoplay_song(ctx.guild.id))

    # 패널 메시지가 이미 있으면 채널 스캔 없이 바로 업데이트
    if state.music_panel_message:
        new_view = MusicControlPanel(bot, ctx.guild.id)
        try:
            await state.music_panel_message.edit(view=new_view)
        except discord.NotFound:
            state.music_panel_message = None
            await retrieve_panel_and_update(ctx.guild.id)
    else:
        await retrieve_panel_and_update(ctx.guild.id)

    await update_panel(ctx.guild.id, player.title, player.thumbnail, author, player.uploader)


class MusicControlPanel(View):
    def __init__(self, bot_instance: commands.Bot, guild_id: int):
        super().__init__(timeout=None)
        self.bot = bot_instance
        self.guild_id = guild_id

        # 패널 재생성 시 길드 상태에 맞춰 자동재생 버튼 시각 동기화
        current_state = get_guild_state_sync(guild_id)
        autoplay_on = current_state.autoplay if current_state is not None else True
        if not autoplay_on:
            for item in self.children:
                if isinstance(item, Button) and item.label and "자동재생" in item.label:
                    item.style = discord.ButtonStyle.gray
                    item.label = "🔀 자동재생"
                    break

    async def get_current_guild_state(self, interaction: discord.Interaction) -> GuildState:
        return await get_guild_state(interaction.guild.id)

    # ── Row 0: 재생 컨트롤 ─────────────────────────────────────────────────

    @discord.ui.button(label="▶️ 재생", style=discord.ButtonStyle.green, row=0)
    async def play_button(self, interaction: discord.Interaction, button: Button) -> None:
        state = await self.get_current_guild_state(interaction)

        if not state.voice_client or not state.voice_client.is_connected():
            await interaction.response.send_message("음성 채널에 연결되지 않았습니다.", ephemeral=True, delete_after=5)
            return

        if state.voice_client.is_playing():
            await interaction.response.send_message("이미 재생 중입니다.", ephemeral=True, delete_after=5)
            return

        if state.voice_client.is_paused():
            state.voice_client.resume()
            await interaction.response.send_message("▶️ 음악을 다시 재생합니다.", ephemeral=True, delete_after=5)
            return

        await interaction.response.send_message("재생할 음악이 없습니다.", ephemeral=True, delete_after=5)

    @discord.ui.button(label="⏸️ 일시정지", style=discord.ButtonStyle.blurple, row=0)
    async def pause_button(self, interaction: discord.Interaction, button: Button) -> None:
        state = await self.get_current_guild_state(interaction)
        if not state.voice_client or not state.voice_client.is_playing():
            await interaction.response.send_message("현재 재생 중인 음악이 없습니다.", ephemeral=True, delete_after=5)
            return

        state.voice_client.pause()
        await interaction.response.send_message("⏸️ 음악을 일시 정지했습니다.", ephemeral=True, delete_after=5)

    @discord.ui.button(label="⏹️ 정지", style=discord.ButtonStyle.red, row=0)
    async def stop_button(self, interaction: discord.Interaction, button: Button) -> None:
        state = await self.get_current_guild_state(interaction)
        if not state.voice_client:
            await interaction.response.send_message("봇이 음성 채널에 없습니다.", ephemeral=True, delete_after=5)
            return

        await state.clear_queue()
        if state.voice_client.is_playing() or state.voice_client.is_paused():
            state.voice_client.stop()

        await state.voice_client.disconnect()
        state.voice_client = None
        state.reset_playback()
        await update_panel(self.guild_id)
        await interaction.response.send_message("⏹️ 음악을 멈추고 음성 채널에서 나갔습니다.", ephemeral=True, delete_after=5)

    @discord.ui.button(label="⏭️ 다음 곡", style=discord.ButtonStyle.blurple, row=0)
    async def next_button(self, interaction: discord.Interaction, button: Button) -> None:
        state = await self.get_current_guild_state(interaction)
        if not state.voice_client or not state.is_playing:
            await interaction.response.send_message("재생 중인 곡이 없습니다.", ephemeral=True, delete_after=5)
            return

        queue_list = await state.get_queue_list()
        if not queue_list and not state.autoplay:
            await interaction.response.send_message("대기열에 다음 곡이 없습니다.", ephemeral=True, delete_after=5)
            return

        state.voice_client.stop()
        await interaction.response.send_message("⏭️ 다음 곡을 재생합니다.", ephemeral=True, delete_after=5)

    # ── Row 1: 유틸리티 ────────────────────────────────────────────────────

    @discord.ui.button(label="🎶 대기열", style=discord.ButtonStyle.gray, row=1)
    async def queue_button(self, interaction: discord.Interaction, button: Button) -> None:
        state = await self.get_current_guild_state(interaction)
        queue_list = await state.get_queue_list()

        embed = discord.Embed(title="🎶 현재 대기열", color=PANEL_COLOR)
        if not queue_list:
            embed.description = "대기열이 비어 있습니다."
        else:
            for index, (player, author) in enumerate(queue_list, start=1):
                embed.add_field(name=f"{index}. {player.title}", value=f"신청자: {author}", inline=False)
            if queue_list[0][0].thumbnail:
                embed.set_thumbnail(url=queue_list[0][0].thumbnail)

        await interaction.response.send_message(embed=embed, ephemeral=True, delete_after=15)

    @discord.ui.button(label="🔀 자동재생 ON", style=discord.ButtonStyle.green, row=1)
    async def autoplay_button(self, interaction: discord.Interaction, button: Button) -> None:
        state = await self.get_current_guild_state(interaction)
        state.autoplay = not state.autoplay
        if state.autoplay:
            button.style = discord.ButtonStyle.green
            button.label = "🔀 자동재생 ON"
        else:
            button.style = discord.ButtonStyle.gray
            button.label = "🔀 자동재생"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"🔀 자동재생이 {'켜졌습니다.' if state.autoplay else '꺼졌습니다.'}", ephemeral=True
        )


@bot.event
async def on_ready() -> None:
    logger.info("%s으로 로그인 성공!", bot.user)
    for guild in bot.guilds:
        await retrieve_panel_and_update(guild.id)
    logger.info("모든 서버의 음악 패널을 재연결했습니다.")


def run_bot() -> None:
    write_pid_file()
    try:
        bot.run(BOT_TOKEN)
    finally:
        cleanup_pid_file()
