"""Build a source-attributed local evaluation corpus from the pinned meme-api ZIP."""

import argparse
import hashlib
import json
import tempfile
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from services.common.media import MediaError, inspect_media

REPO = "https://github.com/shumengya/meme-api"
REV = "d452126069915ee401a125227081cb7ba7ece4b3"
PREFIX = f"meme-api-{REV}/public/meme/"
ARCHIVE_SHA256 = "1c2419604bd67a7d532c5a49eef148834e4ba0c1e7c7a6d0515f4b3283564a24"
LICENSE = f"shumengya/meme-api · CC BY-NC-SA 4.0 · {REPO}/blob/{REV}/ASSET_LICENSE.md"
# Keep named sequel packs and obvious alternate names in the same split.
FAMILY_ALIASES = {"抹茶旦旦2": "抹茶旦旦", "白色小人2": "白色小人", "熊猫人": "金馆长熊猫"}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prepare(archive, output):
    with archive.open("rb") as src:
        digest = hashlib.file_digest(src, "sha256").hexdigest()
    if digest != ARCHIVE_SHA256:
        raise ValueError("Archive differs from the verified upstream snapshot")
    if output.exists():
        raise FileExistsError(f"Choose a new corpus directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        root = Path(temp) / "dataset"
        media = root / "media"
        media.mkdir(parents=True)
        gifs, stills, excluded, seen = [], [], [], set()
        categories = Counter()
        with zipfile.ZipFile(archive) as zf:
            for entry in sorted(zf.infolist(), key=lambda item: item.filename):
                if not entry.filename.startswith(PREFIX) or entry.is_dir():
                    continue
                relative = PurePosixPath(entry.filename.removeprefix(PREFIX))
                if len(relative.parts) != 2 or relative.suffix.lower() not in {".gif", ".webp"}:
                    continue
                pack, name = relative.parts
                categories[pack] += 1
                if entry.file_size > 12 * 1024**2:
                    excluded.append([str(relative), "over_media_limit"])
                    continue
                data = zf.read(entry)
                try:
                    info = inspect_media(data)
                except MediaError as exc:
                    excluded.append([str(relative), str(exc)])
                    continue
                if info.sha256 in seen:
                    excluded.append([str(relative), "duplicate_sha256"])
                    continue
                animated_gif = info.format == "GIF" and info.frame_count > 1
                if info.frame_count > 1 and not animated_gif:
                    excluded.append([str(relative), "animated_non_gif"])
                    continue
                seen.add(info.sha256)
                path = f"media/{info.sha256}.{info.suffix}"
                (root / path).write_bytes(data)
                row = dict(
                    id=info.sha256,
                    title=f"{pack}/{name}",
                    sha256=info.sha256,
                    family_id=FAMILY_ALIASES.get(pack, pack),
                    license=LICENSE,
                    frame_count=info.frame_count,
                    category=pack,
                    source=f"{REPO}/blob/{REV}/public/meme/{quote(str(relative))}",
                )
                if animated_gif:
                    gifs.append(dict(row, gif_path=path))
                else:
                    stills.append(dict(row, image=path))
        if not gifs or not stills:
            raise ValueError("Expected both decoded animated GIFs and static media")
        common = dict(upstream=REPO, revision=REV, archive_sha256=digest, license=LICENSE)
        write_json(root / "gifs.json", dict(common, assets=gifs))
        write_json(root / "stills.json", dict(common, assets=stills))
        summary = dict(
            common,
            input_files=sum(categories.values()),
            categories=dict(categories),
            unique_animated_gifs=len(gifs),
            unique_stills=len(stills),
            excluded=excluded,
        )
        write_json(root / "inventory.json", summary)
        (root / "ATTRIBUTION.txt").write_text(
            f"素材来源：{LICENSE}\n素材为上游已处理的发布版本。原文件按字节保留。\n"
            "测试截图为抽帧、裁切、压缩或覆盖文字后的衍生图，沿用 CC BY-NC-SA 4.0。\n",
            encoding="utf-8",
        )
        root.rename(output)
        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = prepare(args.archive, args.output)
    print(
        f"{report['input_files']} files, {report['unique_animated_gifs']} animated GIFs, "
        f"{report['unique_stills']} stills, {len(report['excluded'])} excluded"
    )
