import os
from ctypes.util import find_library
from pathlib import Path

# Try to import config.py for local development; not required in Docker
try:
    from config import TOKEN as _config_token
    from config import ffmpeg_options as _config_ffmpeg_options
    from config import music_channel as _config_music_channel
    from config import ytdl_format_options as _config_ytdl_format_options
except ImportError:
    _config_token = None
    _config_ffmpeg_options = None
    _config_music_channel = None
    _config_ytdl_format_options = None

BASE_DIR = Path(__file__).resolve().parent.parent

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or _config_token or ""

# Opus library path: prefer env var, then system detection, then macOS fallback
_opus_env = os.getenv("DISCORD_OPUS_PATH")
if _opus_env:
    OPUS_PATH = Path(_opus_env)
else:
    _found = find_library("opus")
    OPUS_PATH = Path(_found) if _found else Path("/opt/homebrew/lib/libopus.dylib")

PID_FILE_PATH = BASE_DIR / "bot.pid"
LOG_LEVEL = os.getenv("BOT_LOG_LEVEL", "INFO").upper()
YTDL_MAX_RETRIES = int(os.getenv("YTDL_MAX_RETRIES", "2"))
YTDL_RETRY_BASE_DELAY_SECONDS = float(os.getenv("YTDL_RETRY_BASE_DELAY_SECONDS", "1.0"))

MUSIC_CHANNEL = os.getenv("MUSIC_CHANNEL") or _config_music_channel or "음악채널"

# bgutil base URL — override via env var (e.g. http://bgutil:4416 in Docker)
_bgutil_url_env = os.getenv("BGUTIL_BASE_URL")

if _config_ytdl_format_options:
    YTDL_FORMAT_OPTIONS = dict(_config_ytdl_format_options)
    if _bgutil_url_env:
        YTDL_FORMAT_OPTIONS["bgutil_base_url"] = _bgutil_url_env
else:
    YTDL_FORMAT_OPTIONS = {
        "format": "bestaudio/best",
        "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
        "restrictfilenames": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "logtostderr": False,
        "quiet": False,
        "no_warnings": True,
        "default_search": "auto",
        "source_address": "0.0.0.0",
        "cachedir": False,
        "bgutil_base_url": _bgutil_url_env or "http://localhost:4416",
    }

FFMPEG_OPTIONS = _config_ffmpeg_options or {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

PANEL_COLOR = 0x1DB954
PANEL_IDLE_TITLE = "🎵 음악 컨트롤 패널"
PANEL_IDLE_DESCRIPTION = "이 채널에 듣고 싶은 노래 제목이나 유튜브 URL을 입력하세요!"
PANEL_PLAYING_TITLE = "🎵 현재 재생 중"
PANEL_FOOTER_DEFAULT = "음악 봇 | 디스코드"
PANEL_FOOTER_PREFIX = "음악 봇"

ERROR_HANDLER_PATH = BASE_DIR / "error_handler.py"
