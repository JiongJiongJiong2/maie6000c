from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from services.api.app.main import app
from services.common.config import get_settings


def as_image_bytes(image, format="PNG"):
    with BytesIO() as output:
        image.save(output, format=format)
        return output.getvalue()


def test_public_screenshot_to_pack_download_with_account_login_enabled(monkeypatch):
    monkeypatch.setenv("ACCOUNT_LOGIN_ENABLED", "true")
    monkeypatch.setenv("STICKER_PACK_EXPERIMENT", "false")
    get_settings.cache_clear()
    with TestClient(app) as visitor:
        assert visitor.get("/search-jobs/1").status_code == 401
        assert 'href="/stickers/"' in visitor.get("/web/search").text
        page = visitor.get("/stickers/")
        assert page.status_code == 200
        assert 'data-variant="finder"' in page.text

        response = visitor.get("/stickers/catalog")
        assert response.status_code == 200
        directory = response.json()
        assert directory["demo"] is True
        assert len(directory["packs"]) == 2
        assert "permission_note" not in response.text
        example = visitor.get(directory["example"])
        assert example.status_code == 200
        result = visitor.post("/stickers/search", content=example.content)
        assert result.json() == {"matches": [{"packId": "pond-post", "stickerId": "hello"}]}
        assert result.headers["cache-control"] == "no-store"
        pack = next(pack for pack in directory["packs"] if pack["id"] == "pond-post")
        assert pack["creator"] == "MemeRetrieve Studio"
        assert pack["publisher"] == "MemeRetrieve"
        assert [item["id"] for item in pack["stickers"]] == ["hello", "tea-break"]

        item = pack["stickers"][1]
        poster = visitor.get(item["poster"])
        assert poster.headers["content-type"] == "image/png"
        original = visitor.get(item["animation"])
        assert original.headers["content-type"] == "image/webp"
        with Image.open(BytesIO(original.content)) as animation:
            animation.seek(4)
            frame = animation.convert("RGBA").resize((173, 173))
        screenshot = Image.new("RGBA", (246, 231), "#242629")
        screenshot.alpha_composite(frame, (34, 24))
        dark_crop = as_image_bytes(screenshot.convert("RGB"), "JPEG")
        match = visitor.post("/stickers/search", content=dark_crop)
        assert match.json() == {"matches": [{"packId": "pond-post", "stickerId": "tea-break"}]}

        download = visitor.post("/stickers/packs/pond-post/claim/archive?view=finder")
        assert download.headers["content-disposition"] == 'attachment; filename="pond-post.zip"'
        with ZipFile(BytesIO(download.content)) as archive:
            assert archive.namelist() == ["hello.webp", "tea-break.webp"]
            assert archive.read("tea-break.webp") == original.content
        metrics = visitor.get("/metrics").text
        assert 'sticker_pack_events_total{event="one_match",variant="finder"}' in metrics
        assert (
            'sticker_pack_claims_total{channel="archive",pack="pond-post",variant="finder"}'
            in metrics
        )


def test_unknown_and_invalid_screenshots_have_no_false_success(client):
    image = Image.new("RGB", (160, 200), "#ed6f6f")
    ImageDraw.Draw(image).rectangle((24, 25, 74, 185), fill="#171525")
    unknown = client.post("/stickers/search", content=as_image_bytes(image))
    assert unknown.json() == {
        "matches": [],
        "web": {"state": "unavailable", "links": [], "leads": []},
    }
    assert client.post("/stickers/search", content=b"not an image").status_code == 422
    assert client.post("/stickers/search", content=b"0" * (5 * 1024 * 1024 + 1)).status_code == 413
    assert client.post("/stickers/packs/pond-post/claim/unknown").status_code == 404
    assert client.get("/stickers/packs/pond-post/items/unknown/original").status_code == 404


def test_partner_catalog_claim_and_sticky_directory_variant(monkeypatch, tmp_path):
    import json

    from services.api.app.sticker_packs import VARIANT_COOKIE

    locator = "https://example.com/stickers/launch"
    (tmp_path / "sticker.png").write_bytes(as_image_bytes(Image.new("RGB", (20, 20), "blue")))
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "packs": [
                    {
                        "id": "partner",
                        "name": "Partner collection",
                        "publisher": "Partner",
                        "creator": "Illustrator",
                        "description": "Campaign stickers",
                        "permission_note": "Authorized test asset",
                        "stickers": [{"id": "hello", "name": "Hello", "file": "sticker.png"}],
                        "channels": [{"id": "campaign", "label": "Get the pack", "url": locator}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STICKER_PACK_ROOT", str(tmp_path))
    monkeypatch.setenv("STICKER_PACK_EXPERIMENT", "true")
    monkeypatch.setattr("services.api.app.sticker_packs.secrets.choice", lambda _: "directory")
    get_settings.cache_clear()
    with TestClient(app) as visitor:
        first = visitor.get("/stickers/")
        assert "HttpOnly" in first.headers["set-cookie"]
        assert visitor.cookies.get(VARIANT_COOKIE) == "directory"
        assert 'data-variant="directory"' in first.text
        assert "set-cookie" not in visitor.get("/stickers/").headers
        assert [pack["id"] for pack in visitor.get("/stickers/catalog").json()["packs"]] == [
            "partner"
        ]
        claimed = visitor.post(
            "/stickers/packs/partner/claim/campaign?view=directory", follow_redirects=False
        )
        assert claimed.status_code == 303
        assert claimed.headers["location"] == locator
        assert claimed.headers["referrer-policy"] == "no-referrer"
        assert visitor.get("/stickers/example").status_code == 404
        assert visitor.get("/stickers/manifest.json").status_code == 404


def test_catalog_miss_submits_the_same_screenshot_to_public_lookup(client, monkeypatch):
    from services.api.app import sticker_packs
    from services.common.sticker_web_models import StickerSource, WebStickerSearch

    screenshot = as_image_bytes(Image.new("RGB", (100, 110), "#e44e4e"))
    lookup_url = "https://store.line.me/stickershop/product/999"

    async def lookup(data):
        assert data == screenshot
        return WebStickerSearch(
            state="matched",
            links=[StickerSource(title="Public result", url=lookup_url, channel="LINE STORE")],
        )

    monkeypatch.setattr(sticker_packs, "web_sticker_matches", lookup)
    response = client.post("/stickers/search?view=workspace", content=screenshot)
    assert response.status_code == 200
    assert response.json()["matches"] == []
    assert response.json()["web"]["links"][0]["url"] == lookup_url
