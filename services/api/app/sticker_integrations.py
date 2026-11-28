"""Export verified GIFs to Discord stickers and Signal sticker packs."""

import json
import logging
import re
import subprocess
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Request
from PIL import Image, ImageOps, ImageSequence

from services.api.app.search import Database, authorize, fail, read_media, verify_saved_asset_media
from services.common.config import base_settings, get_settings
from services.common.search_models import Candidate, SavedAsset
from services.common.storage import atomic_write

router = APIRouter(prefix="/sticker-integrations", dependencies=[Depends(authorize)])
MediaKind = Literal["candidates", "saved-assets"]
STICKER_SIZE = 320
STICKER_BYTES = 512 * 1024
SIGNAL_STICKER_SIZE = 512
SIGNAL_STICKER_BYTES = 300_000
SIGNAL_PACK_URL = re.compile(
    r"https://signal\.art/addstickers/#pack_id=[a-f0-9]{32}&pack_key=[a-f0-9]{64}"
)
discord_lock = Lock()
signal_lock = Lock()
logger = logging.getLogger(__name__)


def can_add_discord_sticker(request: Request) -> bool:
    settings = get_settings()
    account = getattr(request.state, "account", None)
    return bool(
        settings.discord_sticker_guild_id
        and settings.discord_bot_token.get_secret_value()
        and account
        and account.username in settings.discord_sticker_accounts
    )


def can_create_signal_pack(request: Request) -> bool:
    settings = get_settings()
    account = getattr(request.state, "account", None)
    return bool(
        settings.signal_cli_executable
        and settings.signal_cli_data_dir
        and account
        and account.username in settings.signal_sticker_accounts
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


def clipped_delays(delays: list[int], remaining: int) -> list[int]:
    durations = []
    for index, delay in enumerate(delays):
        if remaining < 20:
            break
        # Keep room for a second frame even when the first is unusually long.
        limit = remaining - 20 if index == 0 else remaining
        duration = min(max(20, delay or 100), limit)
        durations.append(duration)
        remaining -= duration
    return durations


def center_frame(frame: Image.Image, max_side: int, canvas_side: int) -> Image.Image:
    image = ImageOps.contain(frame.convert("RGBA"), (max_side, max_side))
    canvas = Image.new("RGBA", (canvas_side, canvas_side))
    canvas.paste(image, ((canvas_side - image.width) // 2, (canvas_side - image.height) // 2))
    return canvas


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
        durations = clipped_delays(delays, 5000)
        for side, colors in ((STICKER_SIZE, 255), (256, 127), (192, 95), (144, 63), (112, 47)):
            frames = []
            for index in range(len(durations)):
                source.seek(index)
                canvas = center_frame(source, side, STICKER_SIZE)
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


def encode_signal_sticker(data: bytes) -> tuple[bytes, bytes]:
    """Return a 512×512 APNG and a still PNG cover within Signal's size limit."""
    with Image.open(BytesIO(data)) as source:
        delays = [frame.info.get("duration", 0) for frame in ImageSequence.Iterator(source)]
        durations = clipped_delays(delays, 3000)
        for side in (512, 320, 224, 160, 112, 80, 56):
            frames = []
            for index in range(len(durations)):
                source.seek(index)
                frames.append(center_frame(source, side, SIGNAL_STICKER_SIZE))
            output = BytesIO()
            frames[0].save(
                output,
                format="PNG",
                save_all=True,
                append_images=frames[1:],
                duration=durations,
                loop=0,
                disposal=1,
                blend=0,
            )
            if output.tell() > SIGNAL_STICKER_BYTES:
                continue
            with Image.open(output) as sticker:
                if not sticker.is_animated:
                    continue
            cover = BytesIO()
            frames[0].save(cover, format="PNG")
            if cover.tell() <= SIGNAL_STICKER_BYTES:
                return output.getvalue(), cover.getvalue()
    raise fail(422, "signal_sticker_too_large", "This GIF could not fit Signal’s sticker limits.")


def upload_signal_pack(manifest: Path) -> str:
    settings = get_settings()
    try:
        result = subprocess.run(
            [
                settings.signal_cli_executable,
                "--data-dir",
                str(settings.signal_cli_data_dir),
                "--output",
                "json",
                "uploadStickerPack",
                str(manifest),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise fail(
            504, "signal_upload_timeout", "Signal did not confirm the pack in time."
        ) from error
    except OSError as error:
        raise fail(503, "signal_unavailable", "The Signal publisher is unavailable.") from error
    if result.returncode:
        logger.warning("Signal pack upload failed with exit code %s", result.returncode)
        raise fail(502, "signal_upload_failed", "Signal could not create the sticker pack.")
    try:
        payload = json.loads(result.stdout)
        url = payload.get("url") if isinstance(payload, dict) else None
    except ValueError:
        url = None
    if not isinstance(url, str) or not SIGNAL_PACK_URL.fullmatch(url):
        raise fail(502, "signal_unconfirmed", "Signal did not return a valid sticker pack link.")
    return url


@router.post("/{kind}/{gif_id}/signal")
def create_signal_pack(kind: MediaKind, gif_id: UUID, request: Request, db: Database) -> dict:
    if not can_create_signal_pack(request):
        raise fail(403, "signal_packs_disabled", "Signal sticker export is unavailable.")
    data = gif_bytes(gif_record(kind, gif_id, db), db)
    digest = sha256(data).hexdigest()
    root = base_settings().media_root / "signal-packs"
    filename = f"{digest}.txt"
    try:
        with signal_lock:
            try:
                url = (root / filename).read_text(encoding="ascii")
            except FileNotFoundError:
                pass
            else:
                if not SIGNAL_PACK_URL.fullmatch(url):
                    raise OSError("Invalid stored Signal pack link")
                return {"url": url, "already_created": True}

            root.mkdir(parents=True, exist_ok=True)
            sticker, cover = encode_signal_sticker(data)
            with TemporaryDirectory(prefix="pack-", dir=root) as temporary:
                directory = Path(temporary)
                (directory / "sticker.apng").write_bytes(sticker)
                (directory / "cover.png").write_bytes(cover)
                manifest = directory / "manifest.json"
                manifest.write_text(
                    json.dumps(
                        {
                            "title": f"MemeRetrieve {digest[:8]}",
                            "author": "MemeRetrieve",
                            "cover": {"file": "cover.png", "contentType": "image/png"},
                            "stickers": [
                                {"file": "sticker.apng", "contentType": "image/apng", "emoji": "😄"}
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                url = upload_signal_pack(manifest)
                atomic_write(root, filename, url.encode("ascii"))
    except (OSError, UnicodeError) as error:
        logger.warning("Signal pack cache could not be accessed: %s", type(error).__name__)
        raise fail(
            503, "signal_storage_unavailable", "Signal sticker storage is unavailable."
        ) from error
    return {"url": url, "already_created": False}
