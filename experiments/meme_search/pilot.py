"""Small, read-only meme search pilot; no search-provider or product integration."""

from __future__ import annotations

import argparse
import hashlib
import io
import ipaddress
import json
import math
import os
from pathlib import Path
import socket
import stat
import statistics
import time
from urllib.parse import urljoin, urlsplit
import warnings

import httpx
from PIL import Image

ARMS = {"literal", "rewrite", "skill"}
MAX_BYTES = 5 * 1024 * 1024
MAX_ITEMS = 30
MAX_FRAMES = 500
MAX_FRAME_PIXELS = 25_000_000
MAX_TOTAL_PIXELS = 100_000_000
DEFAULT_CACHE = Path(".cache/meme-search-pilot")


def _ranks(value, allowed, field):
    if value is None:
        return None
    if not isinstance(value, list) or any(type(r) is not int or r not in allowed for r in value):
        raise ValueError(f"{field}: ranks must refer to existing result ranks")
    if len(set(value)) != len(value):
        raise ValueError(f"{field}: duplicate ranks")
    return value


def _percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def _aggregate(rows):
    metrics = {}
    for field, name in [
        ("relevant_ranks", "top5_page_discovery"),
        ("blank_ranks", "top5_blank_page_discovery"),
        ("gif_ranks", "top5_gif_page_discovery"),
    ]:
        known = [row[field] for row in rows if row[field] is not None]
        successes = sum(any(rank <= 5 for rank in ranks) for ranks in known)
        metrics[name] = {
            "successes": successes,
            "judged_cases": len(known),
            "unknown_cases": len(rows) - len(known),
            "rate": successes / len(known) if known else None,
        }
    relevant = [row["relevant_ranks"] for row in rows if row["relevant_ranks"] is not None]
    top5 = [[rank for rank in ranks if rank <= 5] for ranks in relevant]
    rr = [1 / min(ranks) if ranks else 0 for ranks in top5]
    latency = [row["elapsed_seconds"] for row in rows if row["elapsed_seconds"] is not None]
    return {
        "counted_cases": len(rows),
        "missing_judgments": sum(row["missing"] for row in rows),
        **metrics,
        "mean_reciprocal_rank": {
            "value": statistics.mean(rr) if rr else None,
            "judged_cases": len(rr),
            "cutoff": 5,
        },
        "latency_seconds": {
            "n": len(latency),
            "median": statistics.median(latency) if latency else None,
            "p95": _percentile(latency, 0.95),
        },
    }


def summarize(runs, judgments):
    if runs.get("protocol_version") != 1 or runs.get("provider") != "host_web_search":
        raise ValueError("unsupported runs protocol or provider")
    cases = runs.get("cases")
    if not isinstance(cases, list):
        raise ValueError("cases must be a list")
    seen, results = set(), {}
    for case in cases:
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError("invalid or duplicate case id")
        seen.add(case_id)
        if not isinstance(case["category"], str) or set(case["arms"]) != ARMS:
            raise ValueError("each case needs a category and exactly literal/rewrite/skill arms")
        for arm, run in case["arms"].items():
            ranks = [result["rank"] for result in run["results"]]
            if any(type(rank) is not int or rank < 1 for rank in ranks) or len(set(ranks)) != len(
                ranks
            ):
                raise ValueError("invalid or duplicate result ranks")
            latency = run.get("elapsed_seconds")
            if latency is not None and (
                type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0
            ):
                raise ValueError("invalid elapsed_seconds")
            results[(case_id, arm)] = {
                "category": case["category"],
                "allowed": set(ranks),
                "elapsed_seconds": latency,
                "missing": True,
                "relevant_ranks": None,
                "blank_ranks": None,
                "gif_ranks": None,
            }
    judged = set()
    for item in judgments.get("items", []):
        key = (item["case_id"], item["arm"])
        if key not in results or key in judged:
            raise ValueError("unknown or duplicate judgment")
        judged.add(key)
        row = results[key]
        for field in ("relevant_ranks", "blank_ranks", "gif_ranks"):
            row[field] = _ranks(item.get(field), row["allowed"], field)
        row["missing"] = False
    categories = sorted({case["category"] for case in cases})
    return {
        "protocol_version": 1,
        "provider": runs["provider"],
        "metric_scope": (
            "Assessor-labeled search-result PAGE discovery, not verified image/media retrieval. "
            "MRR@5 assigns zero when no relevant page occurs within the first five ranks."
        ),
        "latency_scope": "Descriptive only; p95 uses linear interpolation; no inferential claims.",
        "cost": {"measured": False, "value": None},
        "missing_judgment_items": [
            {"case_id": case_id, "arm": arm}
            for (case_id, arm), row in results.items()
            if row["missing"]
        ],
        "by_arm": {
            arm: _aggregate([r for (_, a), r in results.items() if a == arm])
            for arm in sorted(ARMS)
        },
        "by_category": {
            category: {
                arm: _aggregate(
                    [r for (_, a), r in results.items() if a == arm and r["category"] == category]
                )
                for arm in sorted(ARMS)
            }
            for category in categories
        },
        "limitations": judgments.get("limitations", []),
    }


class ProbeFailure(Exception):
    """Only fixed safe error codes are surfaced to the output."""


def cache_image(cache_dir, digest, data):
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / digest
    try:
        # Exclusive creation never follows or overwrites an existing link, including
        # one created between an existence check and open.
        with target.open("xb") as destination:
            destination.write(data)
    except FileExistsError:
        if target.is_symlink() or not target.is_file():
            raise ProbeFailure("unsafe_cache_entry") from None
        if target.resolve().parent != cache_dir.resolve():
            raise ProbeFailure("unsafe_cache_entry") from None
        with target.open("rb") as existing:
            if not stat.S_ISREG(os.fstat(existing.fileno()).st_mode):
                raise ProbeFailure("unsafe_cache_entry")
            stored = existing.read(MAX_BYTES + 1)
        if hashlib.sha256(stored).hexdigest() != digest:
            raise ProbeFailure("cache_checksum_mismatch") from None


def validate_public_url(url):
    try:
        if not isinstance(url, str):
            raise ProbeFailure("invalid_url")
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ProbeFailure("invalid_url")
        if parsed.port not in (None, 80, 443):
            raise ProbeFailure("unsupported_port")
        answers = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
        addresses = [ipaddress.ip_address(answer[4][0]) for answer in answers]
        if not addresses or any(
            not address.is_global or address.is_multicast for address in addresses
        ):
            raise ProbeFailure("non_public_address")
    except ProbeFailure:
        raise
    except (ValueError, OSError):
        raise ProbeFailure("invalid_or_unresolved_url") from None


def _signature(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG", "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "GIF", "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "WEBP", "image/webp"
    raise ProbeFailure("unsupported_image_signature")


def probe_one(item, cache_dir, client):
    # Never copy supplied URLs, redirect locations, or exception strings to output:
    # these may contain credentials/query tokens even in a public corpus.
    metadata = {"id": item["id"], "status": "failed"}
    try:
        url = item["url"]
        started = time.monotonic()
        for redirect in range(6):
            validate_public_url(url)
            remaining = 15 - (time.monotonic() - started)
            if remaining <= 0:
                raise ProbeFailure("time_limit")
            with client.stream("GET", url, follow_redirects=False, timeout=remaining) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    if redirect == 5 or not response.headers.get("location"):
                        raise ProbeFailure("redirect_limit_or_missing_location")
                    url = urljoin(url, response.headers["location"])
                    continue
                if response.status_code != 200:
                    raise ProbeFailure("http_status")
                content_type = (
                    response.headers.get("content-type", "").split(";")[0].strip().lower()
                )
                if content_type not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
                    raise ProbeFailure("unsupported_mime")
                chunks, size = [], 0
                for chunk in response.iter_bytes(chunk_size=65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ProbeFailure("size_limit")
                    if time.monotonic() - started > 15:
                        raise ProbeFailure("time_limit")
                    chunks.append(chunk)
                data = b"".join(chunks)
            break
        fmt, expected_mime = _signature(data)
        if content_type != expected_mime:
            raise ProbeFailure("mime_signature_mismatch")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
            with Image.open(io.BytesIO(data)) as img:
                width, height = img.size
                frames = getattr(img, "n_frames", 1)
                if (
                    width * height > MAX_FRAME_PIXELS
                    or frames > MAX_FRAMES
                    or width * height * frames > MAX_TOTAL_PIXELS
                ):
                    raise ProbeFailure("decoded_size_limit")
                for frame in range(frames):
                    if time.monotonic() - started > 15:
                        raise ProbeFailure("time_limit")
                    img.seek(frame)
                    img.load()
        digest = hashlib.sha256(data).hexdigest()
        cache_image(cache_dir, digest, data)
        metadata.update(
            status="verified_image",
            mime=content_type,
            format=fmt,
            byte_size=len(data),
            width=width,
            height=height,
            frame_count=frames,
            sha256=digest,
        )
    except ProbeFailure as exc:
        metadata["error"] = str(exc)
    except (httpx.HTTPError, httpx.InvalidURL):
        metadata["error"] = "network_or_tls_error"
    except (
        OSError,
        ValueError,
        EOFError,
        SyntaxError,
        OverflowError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        metadata["error"] = "invalid_image_or_io_error"
    return metadata


def probe(payload, cache_dir, client=None):
    cache_dir = Path(cache_dir).resolve()
    expected = DEFAULT_CACHE.resolve()
    if not cache_dir.is_relative_to(expected):
        raise ValueError("cache-dir must be within .cache/meme-search-pilot")
    items = payload.get("items", [])
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise ValueError("probe accepts at most 30 explicitly supplied URLs")
    ids = [item["id"] for item in items]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("invalid or duplicate probe ids")
    if client is None:
        with httpx.Client(timeout=15, verify=True, trust_env=False) as owned:
            return probe(payload, cache_dir, owned)
    return {
        "items": [probe_one(item, cache_dir, client) for item in items],
        "limitations": [
            "DNS is checked before every request and redirect. Standard HTTP transport "
            "resolves again; DNS rebinding is not eliminated. Use only an explicitly "
            "selected trusted public corpus.",
            "15 seconds is a cooperative wall-clock budget plus per-operation HTTP timeout, "
            "not a hard process deadline.",
            "Only PNG/JPEG/GIF/WebP accepted. Image validation does not assess relevance, "
            "license, or safety.",
            f"Decoded images are limited to {MAX_FRAMES} frames, {MAX_FRAME_PIXELS} "
            f"pixels per canvas, and {MAX_TOTAL_PIXELS} canvas pixels multiplied by frames; "
            "every accepted frame is decoded before caching.",
            "Output omits URLs to avoid leaking query tokens; join to the local input by id.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    summary = commands.add_parser("summarize")
    summary.add_argument("--runs", type=Path, required=True)
    summary.add_argument("--judgments", type=Path, required=True)
    summary.add_argument("--out", type=Path, required=True)
    fetch = commands.add_parser("probe")
    fetch.add_argument("--urls", type=Path, required=True)
    fetch.add_argument("--out", type=Path, required=True)
    fetch.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args()

    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        result = (
            summarize(read(args.runs), read(args.judgments))
            if args.command == "summarize"
            else probe(read(args.urls), args.cache_dir)
        )
    except (ValueError, KeyError, TypeError, OSError):
        parser.exit(2, "Invalid input or inaccessible file; no URLs or raw errors are printed.\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
