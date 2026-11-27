"""Validated bounded image ingestion."""

import hashlib
import io
import ipaddress
import socket
import time
from urllib.parse import urlsplit
import httpx
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 24_000_000
MAX_FRAMES = 200
# Restrict remote ingestion to established image CDNs, preventing arbitrary DNS targets.
MEDIA_HOSTS = {"i.imgflip.com", "i.imgur.com"}


class MediaError(ValueError):
    pass


def validate_url(url):
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
        ):
            raise ValueError()
        host = (parsed.hostname or "").lower()
        if host not in MEDIA_HOSTS:
            raise ValueError()
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError()
        return url
    except (ValueError, OSError):
        raise MediaError("Image host is unsupported or not a public HTTPS address.") from None


def download_image(url: str) -> bytes:
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(12, connect=5), follow_redirects=False, trust_env=False
        ) as client:
            for _ in range(4):
                validate_url(url)
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers.get("location", "")))
                        continue
                    response.raise_for_status()
                    if not response.headers.get("content-type", "").lower().startswith("image/"):
                        raise MediaError("The source did not return an image.")
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() - started > 25:
                            raise MediaError("Image download timed out.")
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise MediaError("Image exceeds the download limit.")
                    result = bytes(data)
                    inspect_image(result)
                    return result
        raise MediaError("Too many image redirects.")
    except httpx.HTTPError:
        raise MediaError("Image download failed.") from None


def inspect_image(data: bytes) -> dict:
    if not data or len(data) > MAX_BYTES:
        raise MediaError("Image is empty or exceeds the size limit.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
            frames = getattr(im, "n_frames", 1)
            if (
                width * height > MAX_PIXELS
                or frames > MAX_FRAMES
                or width * height * frames > 100_000_000
            ):
                raise MediaError("Image exceeds pixel or animation limits.")
            fmt = im.format
            if fmt not in {"PNG", "JPEG", "GIF", "WEBP"}:
                raise MediaError("Unsupported image format.")
            for i in range(frames):
                im.seek(i)
                im.load()
            return dict(
                format=fmt,
                width=width,
                height=height,
                frames=frames,
                animated=frames > 1,
                sha256=hashlib.sha256(data).hexdigest(),
            )
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise MediaError("Invalid or unsafe image data.") from None
