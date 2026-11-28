"""Add verified project GIFs to Discord as animated server stickers."""

from hashlib import sha256
from io import BytesIO
from threading import Lock
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Request
from PIL import Image, ImageOps, ImageSequence

from services.api.app.search import Database, authorize, fail, read_media, verify_saved_asset_media
from services.common.config import get_settings
from services.common.search_models import Candidate, SavedAsset

router = APIRouter(prefix="/sticker-integrations", dependencies=[Depends(authorize)])
MediaKind = Literal["candidates", "saved-assets"]
STICKER_SIZE = 320
STICKER_BYTES = 512 * 1024
discord_lock = Lock()


def can_add_discord_sticker(request: Request) -> bool:
    settings = get_settings()
    account = getattr(request.state, "account", None)
    return bool(
        settings.discord_sticker_guild_id
        and settings.discord_bot_token.get_secret_value()
        and account
        and account.username in settings.discord_sticker_accounts
    )


def gif_record(kind: MediaKind, gif_id: UUID, db: Database) -> Candidate | SavedAsset:
    model = Candidate if kind == "candidates" else SavedAsset
    gif = db.get(model, str(gif_id))
    if gif is None:
        raise fail(404, "gif_not_found", "This GIF is no longer available.")
    if gif.frame_count < 2 or (isinstance(gif, Candidate) and gif.media_format != "GIF"):
        raise fail(422, "requires_animated_gif", "Choose an animated GIF.")
    return gif


def gif_bytes(gif: Candidate | SavedAsset, db: Database) -> bytes:
    if isinstance(gif, SavedAsset):
        return verify_saved_asset_media(gif)
    return read_media(UUID(gif.id), db).body


def encode_discord_sticker(data: bytes) -> bytes:
    """Fit up to the first five seconds of the animation to Discord's canvas."""
    with Image.open(BytesIO(data)) as source:
        delays = [frame.info.get("duration", 0) for frame in ImageSequence.Iterator(source)]
        if (
            source.size == (STICKER_SIZE, STICKER_SIZE)
            and len(data) <= STICKER_BYTES
            and len(delays) > 1
            and min(delays) >= 20
            and sum(delays) <= 5000
        ):
            return data
        durations = []
        remaining = 5000
        for index, delay in enumerate(delays):
            if remaining < 20:
                break
            # Keep room for a second frame even when the first is unusually long.
            limit = remaining - 20 if index == 0 else remaining
            duration = min(max(20, delay or 100), limit)
            durations.append(duration)
            remaining -= duration
        for side, colors in ((STICKER_SIZE, 255), (256, 127), (192, 95), (144, 63), (112, 47)):
            frames = []
            for index in range(len(durations)):
                source.seek(index)
                image = ImageOps.contain(source.convert("RGBA"), (side, side))
                canvas = Image.new("RGBA", (STICKER_SIZE, STICKER_SIZE))
                canvas.paste(
                    image, ((STICKER_SIZE - image.width) // 2, (STICKER_SIZE - image.height) // 2)
                )
                # Reserve a palette entry for transparency on every frame.
                indexed = canvas.convert("RGB").quantize(colors=colors)
                indexed.paste(255, mask=canvas.getchannel("A").point(lambda a: 255 * (a < 128)))
                frames.append(indexed)
            output = BytesIO()
            frames[0].save(
                output,
                format="GIF",
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=0,
                transparency=255,
                background=255,
                disposal=2,
                optimize=False,
            )
            if output.tell() <= STICKER_BYTES:
                with Image.open(output) as sticker:
                    if sticker.is_animated:
                        return output.getvalue()
    raise fail(422, "discord_sticker_too_large", "This GIF could not fit Discord's sticker limits.")


def discord_payload(response: httpx.Response):
    if response.status_code == 429:
        raise fail(429, "discord_rate_limited", "Discord is busy. Try again in a moment.")
    if response.status_code in (401, 403, 404):
        raise fail(502, "discord_access_denied", "MemeRetrieve cannot access the Discord server.")
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.is_success:
        return payload
    if isinstance(payload, dict) and payload.get("code") == 30039:
        raise fail(409, "discord_stickers_full", "The Discord server's sticker slots are full.")
    if response.status_code in (400, 413):
        raise fail(422, "discord_sticker_rejected", "Discord rejected this animated sticker.")
    raise fail(502, "discord_unavailable", "Discord could not save this sticker. Try again.")


@router.post("/{kind}/{gif_id}/discord")
def add_discord_sticker(kind: MediaKind, gif_id: UUID, request: Request, db: Database) -> dict:
    if not can_add_discord_sticker(request):
        raise fail(403, "discord_stickers_disabled", "Discord sticker export is unavailable.")
    settings = get_settings()
    data = gif_bytes(gif_record(kind, gif_id, db), db)
    digest = sha256(data).hexdigest()
    name = f"MemeRetrieve {digest[:8]}"
    description = f"MemeRetrieve GIF {digest}"
    endpoint = f"https://discord.com/api/v10/guilds/{settings.discord_sticker_guild_id}/stickers"
    headers = {"Authorization": f"Bot {settings.discord_bot_token.get_secret_value()}"}
    try:
        # Check Discord before every write so retries after a lost response reuse the sticker.
        with discord_lock, httpx.Client(headers=headers, timeout=10) as client:
            stickers = discord_payload(client.get(endpoint))
            if not isinstance(stickers, list):
                raise fail(
                    502, "discord_invalid_response", "Discord did not return its sticker list."
                )
            sticker = next(
                (
                    item
                    for item in stickers
                    if isinstance(item, dict)
                    and item.get("description") == description
                    and item.get("available", True)
                    and item.get("format_type") in (2, 4)
                ),
                None,
            )
            already_added = sticker is not None
            if not already_added:
                sticker = discord_payload(
                    client.post(
                        endpoint,
                        data={"name": name, "description": description, "tags": "😄"},
                        files={"file": ("meme.gif", encode_discord_sticker(data), "image/gif")},
                    )
                )
    except httpx.RequestError as exc:
        raise fail(502, "discord_unavailable", "Could not reach Discord. Try again.") from exc
    if (
        not isinstance(sticker, dict)
        or not sticker.get("id")
        or sticker.get("format_type") not in (2, 4)
        or not sticker.get("available", True)
    ):
        raise fail(502, "discord_unconfirmed", "Discord did not confirm an animated sticker.")
    return {
        "id": sticker["id"],
        "name": sticker.get("name") or name,
        "guild_id": settings.discord_sticker_guild_id,
        "already_added": already_added,
    }
