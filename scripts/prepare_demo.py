"""Download the attributed Noto reaction corpus and extract real screenshot examples."""

from __future__ import annotations

import argparse
import hashlib
import json
import ssl
from pathlib import Path
from urllib.request import urlopen
from uuid import NAMESPACE_URL, uuid5

import certifi
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/demo-corpus.json"


def prepare():
    catalog = json.loads(SOURCE.read_text())
    output = ROOT / "data/reference"
    output.mkdir(parents=True, exist_ok=True)
    examples = output / "examples"
    examples.mkdir(exist_ok=True)
    assets = []
    for entry in catalog["assets"]:
        name = entry["codepoint"]
        target = output / f"{name}.gif"
        if not target.exists():
            context = ssl.create_default_context(cafile=certifi.where())
            with urlopen(entry["source_url"], timeout=60, context=context) as response:
                data = response.read(25 * 1024 * 1024 + 1)
            if len(data) > 25 * 1024 * 1024:
                raise ValueError("GIF exceeds the download limit")
            target.write_bytes(data)
        checksum = hashlib.sha256(target.read_bytes()).hexdigest()
        expected = entry.get("sha256")
        if expected and checksum != expected:
            raise ValueError(f"Upstream GIF changed: {name}. Review before updating the checksum.")
        entry["sha256"] = checksum
        with Image.open(target) as gif:
            if gif.format != "GIF" or getattr(gif, "n_frames", 1) < 2:
                raise ValueError(f"Not an animated GIF: {name}")
            gif.seek(gif.n_frames // 3)
            rgba = gif.convert("RGBA")
            white = Image.new("RGBA", rgba.size, "white")
            Image.alpha_composite(white, rgba).convert("RGB").save(examples / f"{name}.png")
        assets.append(
            {
                "reference_asset_id": str(uuid5(NAMESPACE_URL, entry["source_url"])),
                "title": entry["title"],
                "source_reference": entry["source_url"],
                "permission_note": "Google Noto Animated Emoji, CC BY 4.0. Original GIF unchanged. "
                "https://creativecommons.org/licenses/by/4.0/",
                "gif_path": f"{name}.gif",
                "sha256": checksum,
            }
        )
        print(f"Prepared {entry['title']}", flush=True)
    manifest = {"corpus_version": catalog["corpus_version"], "assets": assets}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return catalog


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record-checksums",
        action="store_true",
        help="Record the first reviewed upstream file hashes in the source catalog",
    )
    args = parser.parse_args()
    result = prepare()
    if args.record_checksums:
        SOURCE.write_text(json.dumps(result, indent=2) + "\n")
