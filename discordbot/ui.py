from typing import Optional

import discord

from discordbot.configuration import (
    PANEL_COLOR,
    PANEL_FOOTER_DEFAULT,
    PANEL_FOOTER_PREFIX,
    PANEL_IDLE_DESCRIPTION,
    PANEL_IDLE_TITLE,
)


def build_music_panel_embed(
    *,
    title: Optional[str] = None,
    song_url: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    author: Optional[str] = None,
    uploader: Optional[str] = None,
) -> discord.Embed:
    if title:
        author_text = "🎵 현재 재생 중"
        if uploader:
            author_text += f"  •  {uploader}"
        embed = discord.Embed(title=title, url=song_url, color=PANEL_COLOR)
        embed.set_author(name=author_text)
    else:
        embed = discord.Embed(title=PANEL_IDLE_TITLE, description=PANEL_IDLE_DESCRIPTION, color=PANEL_COLOR)

    if thumbnail_url:
        embed.set_image(url=thumbnail_url)

    if author:
        embed.set_footer(text=f"{PANEL_FOOTER_PREFIX} | 신청자: {author}")
    else:
        embed.set_footer(text=PANEL_FOOTER_DEFAULT)

    return embed


def is_music_panel_message(msg: discord.Message, bot_user_id: int) -> bool:
    if not msg.embeds:
        return False
    footer = msg.embeds[0].footer
    if footer is None or footer.text is None:
        return False
    return msg.author.id == bot_user_id and PANEL_FOOTER_PREFIX in footer.text
