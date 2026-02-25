import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

import discord

SongRequest = tuple[Any, str]


@dataclass
class GuildState:
    music_queue: list[SongRequest] = field(default_factory=list)
    voice_client: Optional[discord.VoiceClient] = None
    is_playing: bool = False
    current_song_info: Optional[Any] = None
    music_panel_message: Optional[discord.Message] = None
    music_queue_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    banded_list: list[str] = field(default_factory=list)
    ytdl_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    autoplay: bool = True
    recently_played: list[str] = field(default_factory=list)
    prefetched_song: Optional[Any] = None  # tuple[YTDLSource, str] | None

    async def get_next_song(self) -> Optional[SongRequest]:
        async with self.music_queue_lock:
            if not self.music_queue:
                return None
            return self.music_queue.pop(0)

    async def add_song(self, player_info: Any, author: str) -> None:
        async with self.music_queue_lock:
            self.music_queue.append((player_info, author))

    async def clear_queue(self) -> None:
        async with self.music_queue_lock:
            self.music_queue.clear()
        self._cleanup_prefetched()

    async def get_queue_list(self) -> list[SongRequest]:
        async with self.music_queue_lock:
            return list(self.music_queue)

    async def rebuild_queue(self, queue_items: list[SongRequest]) -> None:
        async with self.music_queue_lock:
            self.music_queue = list(queue_items)

    def reset_playback(self) -> None:
        self.is_playing = False
        self.current_song_info = None
        self._cleanup_prefetched()

    def _cleanup_prefetched(self) -> None:
        if self.prefetched_song is not None:
            try:
                self.prefetched_song[0].cleanup()
            except Exception:
                pass
            self.prefetched_song = None

    def record_played(self, video_id: str, max_size: int = 50) -> None:
        if not video_id:
            return
        if video_id in self.recently_played:
            self.recently_played.remove(video_id)
        self.recently_played.append(video_id)
        if len(self.recently_played) > max_size:
            self.recently_played.pop(0)


_guild_states: dict[int, GuildState] = {}


def get_guild_state_sync(guild_id: int) -> Optional[GuildState]:
    return _guild_states.get(guild_id)


async def get_guild_state(guild_id: int) -> GuildState:
    state = _guild_states.get(guild_id)
    if state is None:
        state = GuildState()
        _guild_states[guild_id] = state
    return state
