from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from PIL import Image, ImageSequence

from services.api.app import accounts, sticker_integrations
from services.common.config import get_settings
from services.common.search_models import SavedAsset
from services.common.storage import atomic_write, sha256


def test_mobile_discord_sticker_action_and_retry(client, db_session, monkeypatch):
    buffer = BytesIO()
    Image.new("RGB", (24, 16), "red").save(
        buffer,
        "GIF",
        save_all=True,
        append_images=[Image.new("RGB", (24, 16), "blue")],
        duration=[4000, 4000],
        loop=0,
    )
    data = buffer.getvalue()
    digest = sha256(data)
    path = f"saved/{digest}.gif"
    atomic_write(get_settings().media_root, path, data)
    asset = SavedAsset(
        sha256=digest,
        title="Sticker",
        source_url="",
        image_url="",
        provider="test",
        gif_path=path,
        frame_count=2,
    )
    db_session.add(asset)
    db_session.commit()
    url = f"/sticker-integrations/saved-assets/{asset.id}"

    guild_id = "123456789012345678"
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("DISCORD_STICKER_GUILD_ID", guild_id)
    monkeypatch.setenv("DISCORD_STICKER_GUILD_NAME", 'Team "GIF" & Friends')
    monkeypatch.setenv("DISCORD_STICKER_ACCOUNTS", '["tester"]')
    monkeypatch.setenv("ACCOUNT_LOGIN_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        accounts,
        "identify",
        lambda token: SimpleNamespace(username=token, workspace="public") if token else None,
    )

    created = []
    encoded = sticker_integrations.encode_discord_sticker(data)
    with Image.open(BytesIO(encoded)) as sticker:
        assert sticker.size == (320, 320)
        assert sticker.n_frames == 2
        assert sum(frame.info["duration"] for frame in ImageSequence.Iterator(sticker)) == 5000
        assert sticker.convert("RGBA").getpixel((0, 0))[3] == 0
        assert sticker.convert("RGB").getpixel((160, 160)) == (0, 0, 255)

    def discord(request):
        assert request.url == f"https://discord.com/api/v10/guilds/{guild_id}/stickers"
        assert request.headers["Authorization"] == "Bot test-bot-token"
        if request.method == "GET":
            return httpx.Response(200, json=created)
        assert encoded in request.read()
        created.append(
            {
                "id": "1234",
                "name": f"MemeRetrieve {digest[:8]}",
                "format_type": 4,
                "description": f"MemeRetrieve GIF {digest}",
            }
        )
        raise httpx.ReadTimeout("Response lost after creation", request=request)

    http_client = httpx.Client
    monkeypatch.setattr(
        sticker_integrations.httpx,
        "Client",
        lambda **kwargs: http_client(transport=httpx.MockTransport(discord), **kwargs),
    )
    assert client.post(f"{url}/discord").status_code == 401
    client.cookies.set(accounts.COOKIE, "other")
    assert client.post(f"{url}/discord").status_code == 403
    assert 'data-discord-stickers="true"' not in client.get("/web/").text
    client.cookies.set(accounts.COOKIE, "tester")
    page = client.get("/web/")
    assert 'data-discord-stickers="true"' in page.text
    assert 'data-discord-guild-name="Team &quot;GIF&quot; &amp; Friends"' in page.text
    assert "test-bot-token" not in page.text
    assert client.post(f"{url}/discord").status_code == 502
    assert client.post(f"{url}/discord").json() == {
        "id": "1234",
        "name": f"MemeRetrieve {digest[:8]}",
        "guild_id": guild_id,
        "already_added": True,
    }
    assert len(created) == 1


def test_signal_creates_and_reuses_an_animated_pack(client, db_session, monkeypatch):
    output = BytesIO()
    first = Image.new("RGB", (48, 24), "yellow")
    first.save(
        output,
        "GIF",
        save_all=True,
        append_images=[Image.new("RGB", first.size, "purple")],
        duration=[2400, 2400],
        loop=0,
    )
    data = output.getvalue()
    digest = sha256(data)
    path = f"saved/{digest}.gif"
    atomic_write(get_settings().media_root, path, data)
    asset = SavedAsset(
        sha256=digest,
        title="New animation",
        source_url="",
        image_url="",
        provider="test",
        gif_path=path,
        frame_count=2,
    )
    db_session.add(asset)
    db_session.commit()
    url = f"/sticker-integrations/saved-assets/{asset.id}/signal"
    monkeypatch.setenv("SIGNAL_CLI_EXECUTABLE", "test-signal-cli")
    monkeypatch.setenv("SIGNAL_CLI_DATA_DIR", "test-linked-account")
    monkeypatch.setenv("SIGNAL_STICKER_ACCOUNTS", '["tester"]')
    monkeypatch.setenv("ACCOUNT_LOGIN_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        accounts,
        "identify",
        lambda token: SimpleNamespace(username=token, workspace="public") if token else None,
    )

    pack_url = f"https://signal.art/addstickers/#pack_id={'a' * 32}&pack_key={'b' * 64}"
    uploads = []

    def upload(args, **kwargs):
        assert args[:-1] == [
            "test-signal-cli",
            "--data-dir",
            "test-linked-account",
            "--output",
            "json",
            "uploadStickerPack",
        ]
        manifest = Path(args[-1])
        pack = json.loads(manifest.read_text(encoding="utf-8"))
        (item,) = pack["stickers"]
        sticker_path = manifest.parent / item["file"]
        assert pack["title"] == f"MemeRetrieve {digest[:8]}"
        assert sticker_path.stat().st_size <= 300_000
        with Image.open(sticker_path) as sticker:
            assert sticker.format == "PNG" and sticker.n_frames == 2
            assert sticker.size == (512, 512)
            assert sum(frame.info["duration"] for frame in ImageSequence.Iterator(sticker)) == 3000
            assert sticker.convert("RGB").getpixel((256, 256)) == (128, 0, 128)
        with Image.open(manifest.parent / pack["cover"]["file"]) as cover:
            assert cover.size == (512, 512) and not cover.is_animated
        uploads.append(manifest)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"url": pack_url}))

    monkeypatch.setattr(sticker_integrations.subprocess, "run", upload)
    assert client.post(url).status_code == 401
    client.cookies.set(accounts.COOKIE, "other")
    assert client.post(url).status_code == 403
    assert 'data-signal-stickers="true"' not in client.get("/web/").text
    client.cookies.set(accounts.COOKIE, "tester")
    assert 'data-signal-stickers="true"' in client.get("/web/").text
    assert client.post(url).json() == {"url": pack_url, "already_created": False}
    assert client.post(url).json() == {"url": pack_url, "already_created": True}
    assert len(uploads) == 1 and not uploads[0].exists()
