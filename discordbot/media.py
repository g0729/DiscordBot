import asyncio
import logging
import re
import subprocess
import sys
from typing import Optional

import discord
import yt_dlp as youtube_dl
from yt_dlp.utils import DownloadError

from discordbot.configuration import ERROR_HANDLER_PATH, FFMPEG_OPTIONS, OPUS_PATH, YTDL_FORMAT_OPTIONS

# yt_dlp 오류 메시지 숨기기
youtube_dl.utils.bug_reports_message = lambda *args, **kwargs: ""
ytdl = youtube_dl.YoutubeDL(YTDL_FORMAT_OPTIONS)
logger = logging.getLogger(__name__)


def setup_opus() -> None:
    if discord.opus.is_loaded():
        return

    try:
        discord.opus.load_opus(str(OPUS_PATH))
        logger.info("Opus loaded successfully from %s", OPUS_PATH)
    except OSError:
        logger.warning("Opus 라이브러리를 찾을 수 없습니다. 경로를 확인해주세요.")


def run_error_handler() -> None:
    if not ERROR_HANDLER_PATH.exists():
        logger.warning("error_handler.py 파일이 없어 복구 작업을 건너뜁니다: %s", ERROR_HANDLER_PATH)
        return
    logger.info("error_handler.py를 실행해 yt-dlp 업데이트 및 봇 재시작을 시도합니다.")
    subprocess.run([sys.executable, str(ERROR_HANDLER_PATH)], check=False)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source: discord.AudioSource, *, data: dict, volume: float = 0.5) -> None:
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("webpage_url")
        self.thumbnail = self._select_best_thumbnail(data)
        self.uploader = data.get("uploader")
        self.video_id = data.get("id")

    @classmethod
    async def from_url(cls, url: str, *, loop=None, stream: bool = False) -> "YTDLSource":
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if data is None:
            raise DownloadError("미디어 정보를 가져오지 못했습니다.")

        data = cls._pick_playable_entry(data)

        filename = data.get("url") if stream else ytdl.prepare_filename(data)
        if not filename:
            raise DownloadError("재생 URL을 찾지 못했습니다.")

        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)

    @classmethod
    async def from_search(
        cls,
        query: str,
        *,
        loop=None,
        max_results: int = 10,
    ) -> "YTDLSource":
        loop = loop or asyncio.get_event_loop()
        search_target = f"ytsearch{max(1, max_results)}:{query}"
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search_target, download=False))

        if data is None:
            raise DownloadError("검색 결과를 가져오지 못했습니다.")

        selected_data = cls._pick_playable_entry(data)
        stream_url = selected_data.get("url")
        if not stream_url:
            raise DownloadError("재생 URL을 찾지 못했습니다.")

        return cls(discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS), data=selected_data)

    @classmethod
    async def get_recommended_url(
        cls, current_url: str, *, loop=None, exclude_ids: Optional[list[str]] = None
    ) -> Optional[str]:
        """현재 곡의 YouTube 믹스에서 다음 추천 곡 URL을 반환합니다."""
        loop = loop or asyncio.get_event_loop()

        match = re.search(r"[?&]v=([^&]+)", current_url)
        if not match:
            return None

        video_id = match.group(1)
        mix_url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
        excluded = set(exclude_ids or []) | {video_id}

        flat_opts = {
            **YTDL_FORMAT_OPTIONS,
            "extract_flat": True,
            "noplaylist": False,
            "playlistend": 10,
            "quiet": True,
        }

        try:
            with youtube_dl.YoutubeDL(flat_opts) as ydl:
                data = await loop.run_in_executor(None, lambda: ydl.extract_info(mix_url, download=False))

            if not data or "entries" not in data:
                return None

            entries = [e for e in data["entries"] if e and e.get("id") not in excluded]
            if not entries:
                return None

            return f"https://www.youtube.com/watch?v={entries[0]['id']}"
        except Exception:
            logger.exception("추천곡 URL 가져오기 실패 (video_id=%s)", video_id)
            return None

    @staticmethod
    def _select_best_thumbnail(data: dict) -> Optional[str]:
        """썸네일 목록에서 가장 높은 해상도의 URL을 반환합니다."""
        thumbnails = data.get("thumbnails") or []
        valid = [t for t in thumbnails if t.get("url") and t.get("width") and t.get("height")]
        if valid:
            return max(valid, key=lambda t: t["width"] * t["height"])["url"]
        return data.get("thumbnail")

    @classmethod
    def _pick_playable_entry(cls, data: dict) -> dict:
        entries = [entry for entry in data.get("entries", []) if entry] if "entries" in data else None

        if entries is None:
            return data

        if not entries:
            raise DownloadError("재생 가능한 항목이 없습니다.")

        return entries[0]
