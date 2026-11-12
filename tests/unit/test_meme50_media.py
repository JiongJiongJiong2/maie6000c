"""Deterministic media/egress boundaries; no paid API or live quality assertions."""

import io
import time

import numpy as np
import pytest
from PIL import Image

from services.common.media import inspect_media, representative_frames, safe_file
from services.common.storage import MediaError
from services.retrieval.dedup import ContentGroups
from services.retrieval.public_fetch import FetchError, PublicBackend, valid_url
from services.search_agent.meme_types import Ledger, MemeSettings, PipelineError


def image_bytes(fmt="PNG", colors=("red",), size=(48, 32), durations=None):
    frames = [Image.new("RGB", size, c) for c in colors]
    out = io.BytesIO()
    options = (
        dict(save_all=True, append_images=frames[1:], duration=durations or 100, loop=0)
        if len(frames) > 1
        else {}
    )
    frames[0].save(out, format=fmt, **options)
    return out.getvalue()


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "GIF"])
def test_all_static_formats_and_transparency(fmt):
    data = image_bytes(fmt)
    m = inspect_media(data)
    assert m.format == fmt and m.media_kind == "static" and m.frame_count == 1
    assert m.byte_size == len(data) and m.width == 48
    frames, records = representative_frames(data)
    assert len(frames) == 1 and records[0]["frame_index"] == 0
    assert frames[0].mode == "RGB"
    if fmt == "PNG":
        out = io.BytesIO()
        Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(out, "PNG")
        assert representative_frames(out.getvalue())[0][0].getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("fmt", ["GIF", "WEBP", "PNG"])
def test_animation_time_samples_do_not_only_use_empty_first_frame(fmt):
    data = image_bytes(fmt, ("white", "red", "blue"), durations=[10, 500, 500])
    m = inspect_media(data)
    assert m.frame_count == 3 and m.media_kind == "animated"
    frames, records = representative_frames(data, count=2)
    assert [r["frame_index"] for r in records] == [1, 2]
    assert len(frames) == 2


def test_exif_original_identity_and_corrupt_input(tmp_path):
    out = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (24, 12), "red").save(out, "JPEG", exif=exif)
    data = out.getvalue()
    assert inspect_media(data).width == 24
    assert representative_frames(data)[0][0].size == (12, 24)
    for broken in [b"", b"GIF89a", data[:100], b"x" * (12 * 1024 * 1024 + 1)]:
        with pytest.raises(MediaError):
            inspect_media(broken)
    outside = tmp_path.parent / "escape.png"
    outside.write_bytes(data)
    (tmp_path / "link").symlink_to(outside)
    with pytest.raises(MediaError):
        safe_file(tmp_path, "link")
    with pytest.raises(MediaError):
        safe_file(tmp_path, "../escape.png")


def test_content_versions_merge_but_actions_and_text_changes_survive():
    groups = ContentGroups()
    vector = np.array([0.2, 0.0])  # Normalization is part of the grouping boundary.
    a = image_bytes("GIF", ("red", "blue"))
    b = image_bytes("GIF", ("red", "blue"), size=(96, 64))
    c = image_bytes("GIF", ("red", "green"))
    ka, new = groups.add(inspect_media(a), a, vector, "https://example.org/one")
    assert new
    assert groups.add(inspect_media(b), b, vector, "https://example.org/two") == (ka, False)
    kc, new = groups.add(inspect_media(c), c, vector, "https://example.org/one")
    assert new and kc != ka  # Generic same page isn't a content identity.
    assert groups.add(inspect_media(a), a, vector, "https://example.org/other") == (None, False)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "https://[::1]/",
        "http://169.254.169.254/",
        "https://198.18.0.1/x",
        "file:///tmp/a",
        "https://localhost/a",
        "https://x.internal/",
        "https://u:p@example.com",
        "https://example.com:8443",
    ],
)
def test_egress_refuses_private_and_non_http(url):
    with pytest.raises(FetchError):
        valid_url(url)


def test_public_unregistered_host_numeric_connection_peer_check(monkeypatch):
    assert valid_url("https://cdn-never-listed.example.net/a.png") == "cdn-never-listed.example.net"
    stats = dict(dns_queries=0, connections=0, peers=[])
    backend = PublicBackend("system", time.monotonic() + 10, stats)
    monkeypatch.setattr(backend, "addresses", lambda host: ["8.8.8.8"])
    closed, connected = [], []

    class Stream:
        def get_extra_info(self, key):
            return ("8.8.8.8", 443)

        def close(self):
            closed.append(True)

    def connect(self, host, port, **kwargs):
        connected.append((host, port))
        return Stream()

    monkeypatch.setattr("httpcore._backends.sync.SyncBackend.connect_tcp", connect)
    assert backend.connect_tcp("unregistered.example.net", 443)
    assert connected == [("8.8.8.8", 443)] and stats["peers"] == ["8.8.8.8"]
    monkeypatch.setattr(Stream, "get_extra_info", lambda self, key: ("127.0.0.1", 443))
    with pytest.raises(FetchError, match="peer_mismatch"):
        backend.connect_tcp("unregistered.example.net", 443)
    assert closed


def test_mixed_dns_rejected_and_budget_shared(monkeypatch):
    stats = dict(dns_queries=0)
    backend = PublicBackend("system", time.monotonic() + 10, stats)
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("8.8.8.8", 443)), (0, 0, 0, "", ("10.1.0.1", 443))],
    )
    with pytest.raises(FetchError):
        backend.addresses("example.net")
    ledger = Ledger(MemeSettings(max_search_calls=2), clock=lambda: 100)
    ledger.take("search_calls", 2)
    with pytest.raises(PipelineError, match="search_calls_limit"):
        ledger.take("search_calls")
    ledger.reservations["response_bytes"] = ledger.settings.max_bytes
    with pytest.raises(PipelineError, match="response_bytes_limit"):
        ledger.take("response_bytes")
    ledger.deadline = 99
    with pytest.raises(PipelineError, match="deadline"):
        ledger.remaining()


def test_same_frame_palette_different_temporal_actions_are_not_collapsed():
    from services.retrieval.dedup import fingerprint, same_animation

    a = image_bytes("GIF", ("red", "blue", "red"), durations=[100, 100, 100])
    b = image_bytes("GIF", ("red", "blue"), durations=[100, 200])
    assert not same_animation(fingerprint(a), fingerprint(b))


def test_jpeg_size_variant_merges_despite_clip_resize_drift():
    import math
    from PIL import ImageDraw

    original = Image.new("RGB", (400, 600), "#94b1cc")
    ImageDraw.Draw(original).ellipse((60, 70, 330, 490), fill="#dda445")
    a = io.BytesIO()
    original.save(a, "PNG")
    b = io.BytesIO()
    original.resize((120, 180)).save(b, "JPEG", quality=88)
    groups = ContentGroups()
    first = groups.add(
        inspect_media(a.getvalue()), a.getvalue(), np.array([1.0, 0.0]), "https://example.org/a"
    )
    second = groups.add(
        inspect_media(b.getvalue()),
        b.getvalue(),
        np.array([0.968, math.sqrt(1 - 0.968**2)]),
        "https://example.net/b",
    )
    assert first[1] and second == (first[0], False)


def test_small_but_meaningful_caption_change_does_not_merge():
    from PIL import ImageDraw, ImageFont
    from services.retrieval.dedup import fingerprint, same_animation

    data = []
    for caption in ["YES", "NO"]:
        image = Image.new("RGB", (256, 256), "white")
        ImageDraw.Draw(image).text(
            (5, 220), caption, font=ImageFont.load_default(size=24), fill="black"
        )
        out = io.BytesIO()
        image.save(out, "PNG")
        data.append(out.getvalue())
    assert not same_animation(fingerprint(data[0]), fingerprint(data[1]))


def test_reaction_post_identity_groups_cutout_and_preview_but_not_gallery():
    from services.retrieval.dedup import source_identity

    page = "https://reactionstash.com/r/a-reaction-01895718-36fa-c6fa-faf8-d6d044679fd6"
    assert source_identity(page) == "reactionstash:01895718-36fa-c6fa-faf8-d6d044679fd6"
    assert source_identity("https://reactionstash.com/search/bee") is None
    assert (
        source_identity(
            "https://unregistered.example.org/r/a-reaction-01895718-36fa-c6fa-faf8-d6d044679fd6"
        )
        is None
    )


def test_rephased_motion_groups_without_merging_reverse_action_or_caption():
    from PIL import ImageDraw, ImageFont
    from services.retrieval.dedup import same_motion

    def clip(caption):
        frames = []
        for i in range(12):
            frame = Image.new("RGB", (64, 64), "white")
            draw = ImageDraw.Draw(frame)
            draw.rectangle((i * 3, 30, i * 3 + 12, 48), fill="red")
            draw.text((2, 1), caption, fill="black", font=ImageFont.load_default(size=18))
            frames.append(np.asarray(frame, dtype=np.float32) / 255)
        return np.stack(frames)

    original = clip("YES")
    assert same_motion(original, np.roll(original, 4, axis=0))
    assert same_motion(original, np.concatenate([original, original]))
    assert not same_motion(original, original[::-1])
    assert not same_motion(original, clip("NO"))


def test_rephased_codec_motion_merges_despite_embedding_drift():
    from PIL import ImageDraw

    frames = []
    for i in range(12):
        frame = Image.new("RGB", (64, 64), "white")
        ImageDraw.Draw(frame).rectangle((i * 3, 30, i * 3 + 12, 48), fill="red")
        frames.append(frame)

    def gif(items, duration):
        out = io.BytesIO()
        items[0].save(out, "GIF", save_all=True, append_images=items[1:], duration=duration, loop=0)
        return out.getvalue()

    original = gif(frames, 100)
    shifted = gif(frames[4:] + frames[:4], 50)
    groups = ContentGroups()
    key, _ = groups.add(
        inspect_media(original), original, np.array([1.0, 0.0]), "https://example.org/one"
    )
    assert groups.add(
        inspect_media(shifted),
        shifted,
        np.array([0.97, (1 - 0.97**2) ** 0.5]),
        "https://example.org/two",
    ) == (key, False)


def test_static_gif_delay_does_not_make_a_new_content_group():
    gif = io.BytesIO()
    png = io.BytesIO()
    image = Image.new("RGB", (128, 128), "orange")
    image.save(gif, "GIF", duration=100)
    image.save(png, "PNG")
    a, b = gif.getvalue(), png.getvalue()
    assert inspect_media(a).duration_ms > 0 and inspect_media(b).duration_ms == 0
    groups = ContentGroups()
    key, _ = groups.add(inspect_media(a), a, np.array([1.0, 0.0]), "https://example.org/a")
    assert groups.add(inspect_media(b), b, np.array([1.0, 0.0]), "https://example.org/b") == (
        key,
        False,
    )


def test_zero_duration_animation_versions_still_merge():
    a = image_bytes("PNG", ("red", "blue"), durations=[0, 0])
    b = image_bytes("PNG", ("red", "blue"), size=(96, 64), durations=[0, 0])
    ma, mb = inspect_media(a), inspect_media(b)
    assert ma.media_kind == mb.media_kind == "animated"
    assert ma.duration_ms == mb.duration_ms == 0
    groups = ContentGroups()
    key, _ = groups.add(ma, a, np.array([1.0, 0.0]), "https://example.org/a")
    assert groups.add(mb, b, np.array([1.0, 0.0]), "https://example.org/b") == (key, False)


def test_short_motion_resampling_keeps_order_and_caption_changes():
    from PIL import ImageDraw, ImageFont
    from services.retrieval.dedup import same_timeline

    def clip(caption="YES"):
        poses = []
        for offset in (0, 9, 18, 27):
            frame = Image.new("RGB", (64, 64), "white")
            draw = ImageDraw.Draw(frame)
            draw.rectangle((offset, 29, offset + 15, 49), fill="red")
            draw.text((2, 1), caption, fill="black", font=ImageFont.load_default(size=18))
            poses.append(np.asarray(frame, dtype=np.float32) / 255)
        return np.stack([poses[i] for i in (0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3)])

    original = clip()
    changed_rate = original[[0, 0, 4, 4, 4, 4, 4, 8, 8, 8, 12, 12, 12, 12, 12, 12]]
    assert same_timeline(original, np.roll(changed_rate, 3, axis=0))
    assert not same_timeline(original, original[::-1])
    assert not same_timeline(original, clip("NO"))
    low_information = np.stack([np.zeros((64, 64, 3)), np.ones((64, 64, 3))] * 8)
    assert not same_timeline(low_information, np.roll(low_information, 1, axis=0))

    def gif(frames, duration):
        images = [Image.fromarray((frame * 255).astype(np.uint8)) for frame in frames]
        out = io.BytesIO()
        images[0].save(
            out, "GIF", save_all=True, append_images=images[1:], duration=duration, loop=0
        )
        return out.getvalue()

    a = gif(original, 100)
    b = gif(np.roll(changed_rate, 3, axis=0), 75)
    changed_text = gif(clip("NO"), 100)
    groups = ContentGroups()
    key, _ = groups.add(inspect_media(a), a, np.array([1.0, 0]), "https://example.org/a")
    drifted = np.array([0.90, (1 - 0.90**2) ** 0.5])
    assert groups.add(inspect_media(b), b, drifted, "https://example.org/b") == (key, False)
    assert groups.add(inspect_media(changed_text), changed_text, drifted, "https://example.org/c")[
        1
    ]


def test_gallery_page_does_not_merge_different_artwork():
    from services.retrieval.dedup import source_identity

    assert source_identity("https://imgbin.com/png/uFXs9ngS/tom-cat-jerry-png") is None
    assert source_identity("https://imgbin.com/png/uFXs9ngS/another-slug") is None
    assert source_identity("https://imgbin.com/search/cat") is None
    assert source_identity("https://other.example/png/uFXs9ngS/tom-cat-jerry-png") is None
    a = image_bytes("PNG", size=(64, 64))
    b = image_bytes("PNG", colors=("blue",), size=(96, 64))
    groups = ContentGroups()
    groups.add(inspect_media(a), a, np.array([1, 0]), "https://imgbin.com/png/uFXs9ngS/a")
    assert groups.add(inspect_media(b), b, np.array([1, 0]), "https://imgbin.com/png/uFXs9ngS/a")[1]


def test_padding_removal_preserves_added_caption():
    from PIL import ImageDraw, ImageFont

    def png(text, padded=False):
        image = Image.new("RGB", (80, 80), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((20, 25, 60, 65), fill="orange", outline="black", width=2)
        draw.text((12, 2), text, font=ImageFont.load_default(size=17), fill="black")
        if padded:
            canvas = Image.new("RGB", (140, 110), "black")
            canvas.paste(image, (30, 15))
            image = canvas
        out = io.BytesIO()
        image.save(out, "PNG")
        return out.getvalue()

    a, padded, changed = png("YES"), png("YES", True), png("NO", True)
    groups = ContentGroups()
    key, _ = groups.add(inspect_media(a), a, np.array([1, 0]), "https://example.org/a")
    assert groups.add(inspect_media(padded), padded, np.array([1, 0]), "https://example.org/b") == (
        key,
        False,
    )
    assert groups.add(inspect_media(changed), changed, np.array([1, 0]), "https://example.org/c")[1]


def test_registered_crop_does_not_merge_reverse_motion_or_changed_text():
    from PIL import ImageDraw, ImageFont
    from services.retrieval.dedup import same_registered

    def clip(caption):
        frames = []
        for i in range(12):
            frame = Image.new("RGB", (64, 64), "white")
            draw = ImageDraw.Draw(frame)
            draw.rectangle((i * 3, 31, i * 3 + 14, 51), fill="red")
            draw.text((2, 2), caption, font=ImageFont.load_default(size=17), fill="black")
            frames.append(frame)
        return np.stack([np.asarray(frame, dtype=np.float32) / 255 for frame in frames])

    def crop(frames):
        return np.stack(
            [
                np.asarray(
                    Image.fromarray((frame * 255).astype(np.uint8))
                    .crop((2, 2, 62, 62))
                    .resize((64, 64)),
                    dtype=np.float32,
                )
                / 255
                for frame in frames
            ]
        )

    original = clip("YES")
    assert same_registered(original, np.roll(crop(original), 3, axis=0))
    assert not same_registered(original, crop(original[::-1]))
    assert not same_registered(original, crop(clip("NO")))


def test_known_single_asset_pages_and_explicit_meme_hero_relationship():
    from services.retrieval.dedup import source_identity

    page_gif = "https://gifdb.com/gif/title-7rt6x5cizxeawu1z.html"
    main_gif = "https://gifdb.com/images/branded/high/title-7rt6x5cizxeawu1z.gif"
    related_gif = "https://gifdb.com/images/thumbnail/other-dzz9oii7fe0ni0um.gif"
    assert source_identity(page_gif) is None
    assert source_identity(page_gif, main_gif) == "gifdb:7rt6x5cizxeawu1z"
    assert source_identity(page_gif, related_gif) == "gifdb:dzz9oii7fe0ni0um"
    assert source_identity("https://gifdb.com/search/pepe") is None
    vector_page = "https://vectorseek.com/vector_logo/example-logo/"
    primary = "https://vectorseek.com/wp-content/uploads/2023/08/logo.svg-.png"
    thumb = "https://vectorseek.com/wp-content/uploads/2023/08/logo.svg--300x233.png"
    assert source_identity(vector_page) is None
    assert source_identity(vector_page, primary) == source_identity(vector_page, thumb)
    page = "https://meme.com/memes/example-template"
    original = "https://cdn-v2.meme.com//memes/example-template/2026-05-16/1778922530239.webp"
    card = "https://cdn-v2.meme.com/memes/example-template/og-card/2026-10-03/1791002673122.webp"
    assert (
        source_identity(page, original)
        == source_identity(page, card)
        == "meme-hero:example-template"
    )
    assert source_identity(page) is None
    assert source_identity(page, original.replace("example-template", "different-template")) is None


def test_checkerboard_matte_keeps_artwork_and_caption_identity():
    from PIL import ImageDraw, ImageFont
    from services.retrieval.dedup import remove_checkerboard

    def image(size, caption="YES"):
        canvas = Image.new("RGB", size)
        draw = ImageDraw.Draw(canvas)
        for y in range(0, size[1], 8):
            for x in range(0, size[0], 8):
                value = 204 if (x // 8 + y // 8) % 2 else 255
                draw.rectangle((x, y, x + 7, y + 7), fill=(value,) * 3)
        x, y = (size[0] - 80) // 2, (size[1] - 80) // 2
        draw.ellipse((x + 10, y + 25, x + 70, y + 75), fill=(204,) * 3, outline="black", width=3)
        draw.ellipse((x + 30, y + 40, x + 40, y + 50), fill="yellow", outline="black")
        draw.text((x + 20, y + 2), caption, fill="black", font=ImageFont.load_default(size=17))
        out = io.BytesIO()
        canvas.save(out, "PNG")
        return out.getvalue(), canvas, (x + 50, y + 50)

    a, original, center = image((128, 128))
    b, _, _ = image((160, 120))
    changed, _, _ = image((160, 120), "NO")
    assert remove_checkerboard(original).getpixel(center) == (204, 204, 204)
    groups = ContentGroups()
    key, _ = groups.add(inspect_media(a), a, np.array([1, 0]), "https://example.org/a")
    assert groups.add(inspect_media(b), b, np.array([1, 0]), "https://example.org/b") == (
        key,
        False,
    )
    assert groups.add(inspect_media(changed), changed, np.array([1, 0]), "https://example.org/c")[1]


def test_gifdb_related_clip_is_not_the_primary_clip_identity():
    page = "https://gifdb.com/gif/title-7rt6x5cizxeawu1z.html"
    a = image_bytes("GIF", ("red", "blue"))
    b = image_bytes("GIF", ("red", "green"))
    groups = ContentGroups()
    key, _ = groups.add(
        inspect_media(a),
        a,
        np.array([1, 0]),
        page,
        "https://gifdb.com/images/thumbnail/title-7rt6x5cizxeawu1z.gif",
    )
    other, new = groups.add(
        inspect_media(b),
        b,
        np.array([1, 0]),
        page,
        "https://gifdb.com/images/thumbnail/other-dzz9oii7fe0ni0um.gif",
    )
    assert new and other != key
