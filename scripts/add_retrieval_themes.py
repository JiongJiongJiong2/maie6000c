"""Add individually pinned, privately evaluated topic GIFs to the frozen corpus."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from scripts.prepare_chinese_meme_corpus import write_json
from services.common.media import MAX_BYTES, inspect_media


def add_themes(corpus, sources, cache=None):
    """The source index records the exact reviewed file and its usage status."""
    dataset = json.loads((corpus / "gifs.json").read_bytes())
    rows = json.loads(sources.read_bytes())["assets"]
    seen = {row["sha256"] for row in dataset["assets"]}
    for row in rows:
        digest = row["sha256"]
        if digest in seen:
            raise ValueError("Duplicate source content in the frozen theme index")
        url = urlsplit(row["source"])
        if url.scheme != "https" or url.hostname != "raw.githubusercontent.com":
            raise ValueError("Expected a pinned public GitHub source URL")
        if cache is None:
            req = Request(row["source"], headers={"User-Agent": "MemeRetrieve course evaluation"})
            with urlopen(req, timeout=60) as resp:
                data = resp.read(MAX_BYTES + 1)
        else:
            local = (cache / row["gif_path"]).resolve()
            if not local.is_relative_to(cache.resolve()):
                raise ValueError("Source media path escapes the local cache")
            data = local.read_bytes()
        info = inspect_media(data)
        if info.sha256 != digest or info.format != "GIF" or info.frame_count < 2:
            raise ValueError("Theme GIF differs from reviewed content")
        relative = f"media/{digest}.gif"
        target = corpus / relative
        if not target.exists():
            target.write_bytes(data)
        elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("Existing media failed integrity check")
        dataset["assets"].append(dict(row, id=digest, gif_path=relative))
        seen.add(digest)
    dataset["supplement_sources_sha256"] = hashlib.sha256(sources.read_bytes()).hexdigest()
    output = corpus / "gifs-with-themes.json"
    write_json(output, dataset)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("sources", type=Path)
    parser.add_argument("--from-cache", type=Path, help="Read local copies instead of downloading")
    args = parser.parse_args()
    print(add_themes(args.corpus, args.sources, args.from_cache))
