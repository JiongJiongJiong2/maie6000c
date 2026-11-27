"""Build three local demo stickers for the isolated Safari feasibility probe."""

import base64
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parents[2]
TITLES = ("Mind blown", "Laughing tears", "Party time")


def build():
    manifest = json.loads((ROOT / "data/reference/manifest.json").read_text("utf-8"))
    stickers, static_stickers, evidence = [], [], []
    tray = None
    for title in TITLES:
        asset = next(a for a in manifest["assets"] if a["title"] == title)
        original = (ROOT / "data/reference" / asset["gif_path"]).read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        if digest != asset["sha256"]:
            raise ValueError(f"Source changed: {title}")
        with Image.open(io.BytesIO(original)) as gif:
            frames, durations = [], []
            for frame in ImageSequence.Iterator(gif):
                frames.append(frame.convert("RGBA"))
                durations.append(frame.info["duration"])
        if frames[0].size != (512, 512) or len(frames) < 2:
            raise ValueError(f"Invalid animated source: {title}")
        if min(durations) < 8 or sum(durations) > 10000:
            raise ValueError(f"Unsupported timing: {title}")
        output = io.BytesIO()
        frames[0].save(
            output, "WEBP", quality=80, method=4)
        static_webp = output.getvalue()
        with Image.open(io.BytesIO(static_webp)) as decoded_static:
            decoded_static.load()
            if (decoded_static.size != (512, 512) or decoded_static.n_frames != 1
                    or len(static_webp) > 100 * 1024):
                raise ValueError(f"Invalid static control: {title}")
        static_stickers.append({"image_data": base64.b64encode(static_webp).decode("ascii"),
                                "emojis": [], "accessibility_text": title})
        for quality in (80, 65, 50):
            output = io.BytesIO()
            frames[0].save(output, "WEBP", save_all=True, append_images=frames[1:],
                           duration=durations, loop=0, quality=quality, method=4)
            webp = output.getvalue()
            if len(webp) <= 500 * 1024:
                break
        else:
            raise ValueError(f"Sticker is too large: {title}")
        with Image.open(io.BytesIO(webp)) as decoded:
            actual_durations = []
            for frame in ImageSequence.Iterator(decoded):
                frame.load()
                actual_durations.append(frame.info["duration"])
            if (decoded.size != (512, 512) or decoded.n_frames < 2
                    or min(actual_durations) < 8 or sum(actual_durations) != sum(durations)):
                raise ValueError(f"Animation did not survive conversion: {title}")
            frame_count = decoded.n_frames
        if tray is None:
            output = io.BytesIO()
            frames[0].resize((96, 96), Image.Resampling.LANCZOS).save(output, "PNG")
            tray = output.getvalue()
            if len(tray) > 50 * 1024:
                raise ValueError("Tray icon is too large")
        stickers.append({"image_data": base64.b64encode(webp).decode("ascii"),
                         "emojis": [], "accessibility_text": title})
        evidence.append({"title": title, "source_sha256": digest,
                         "webp_sha256": hashlib.sha256(webp).hexdigest(),
                         "bytes": len(webp), "frames": frame_count,
                         "duration_ms": sum(actual_durations), "quality": quality,
                         "static_webp_bytes": len(static_webp),
                         "static_webp_sha256": hashlib.sha256(static_webp).hexdigest()})
    pack = {"identifier": "maie6000c-web-probe-v1", "name": "MemeRetrieve web test",
            "publisher": "MAIE6000C / Google Noto", "animated_sticker_pack": True,
            "tray_image": base64.b64encode(tray).decode("ascii"), "stickers": stickers}
    target = ROOT / "web/whatsapp-demo-pack.json"
    static_pack = {**pack, "identifier": "maie6000c-web-static-control-v3",
                   "name": "MemeRetrieve static test", "animated_sticker_pack": False,
                   "stickers": static_stickers}
    bundle = {"experiment_version": 3, "packs": {"static": static_pack, "animated": pack}}
    target.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
    report = {"stickers": evidence, "tray_bytes": len(tray), "pack_bytes": target.stat().st_size,
              "static_pack_bytes": len(json.dumps(static_pack, separators=(",", ":")).encode()),
              "note": "Converted from Google Noto Emoji, CC BY 4.0. No phone import verified."}
    (ROOT / ".cache").mkdir(exist_ok=True)
    (ROOT / ".cache/whatsapp-pack-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    build()
