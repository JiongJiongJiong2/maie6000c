"""Bounded HTTPS reads for explicitly registered, trusted public sources.

DNS is checked on every hop; standard transport resolves again, so this is not
DNS-rebinding isolation. Do not extend this registry to arbitrary user hosts.
"""

import ipaddress
import socket
import time
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx

PAGE_HOSTS = frozenset({"commons.wikimedia.org", "cultofthepartyparrot.com", "tenor.com"})
MEDIA_HOSTS = frozenset(
    {"upload.wikimedia.org", "cultofthepartyparrot.com", "media.tenor.com", "media1.tenor.com"}
)
MEDIA_PATHS = {"cultofthepartyparrot.com": frozenset({"/parrots/hd/originalparrot.gif"})}
MAX_REDIRECTS = 3


def allowed_media_path(host, path):
    return host not in MEDIA_PATHS or unquote(path) in MEDIA_PATHS[host]


class DownloadError(ValueError):
    def __init__(self, code, *, attempted=False, reason=None, stage=None, http_status=None):
        super().__init__(code)
        self.code = code
        self.reason = reason or code
        self.stage = stage or "network"
        self.http_status = http_status
        self.attempted = attempted
        self.redirects = 0


def canonical_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, ""))


def check_url(url, hosts):
    try:
        p = urlsplit(url)
        if (
            p.scheme != "https"
            or p.hostname not in hosts
            or p.port not in (None, 443)
            or p.username
            or p.password
            or (hosts == MEDIA_HOSTS and not allowed_media_path(p.hostname, p.path))
        ):
            raise ValueError
    except ValueError:
        raise DownloadError("unsupported_source", reason="url_policy", stage="url") from None
    try:
        addresses = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise DownloadError("source_unavailable", reason="dns_failed", stage="dns") from None
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise DownloadError("source_unavailable", reason="dns_non_public", stage="dns")
    return canonical_url(url)


def fetch(url, *, hosts, max_bytes, deadline, client=None):
    """One logical GET attempt; redirects are limited and independently checked."""
    owned = client is None
    client = client or httpx.Client(trust_env=False, follow_redirects=False)
    attempted = False
    try:
        for hop in range(MAX_REDIRECTS + 1):
            if time.monotonic() >= deadline:
                raise DownloadError("download_timeout", attempted=attempted)
            url = check_url(url, hosts)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DownloadError("download_timeout", attempted=attempted)
            attempted = True
            with client.stream(
                "GET",
                url,
                timeout=min(12, remaining),
                headers={
                    "User-Agent": (
                        "MemeRetrieve/1.0 (https://github.com/JiongJiongJiong2/maie6000c; "
                        "academic source verification)"
                    )
                },
            ) as r:
                if r.status_code in {301, 302, 303, 307, 308}:
                    if hop == MAX_REDIRECTS or not r.headers.get("location"):
                        raise DownloadError("download_failed", attempted=True)
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code != 200:
                    raise DownloadError(
                        "download_failed",
                        attempted=True,
                        reason=f"http_{r.status_code}",
                        stage="http",
                        http_status=r.status_code,
                    )
                parts, size = [], 0
                chunks = iter(r.iter_bytes())
                while True:
                    if time.monotonic() >= deadline:
                        raise DownloadError("download_timeout", attempted=True)
                    try:
                        chunk = next(chunks)
                    except StopIteration:
                        break
                    if time.monotonic() >= deadline:
                        raise DownloadError("download_timeout", attempted=True)
                    size += len(chunk)
                    if size > max_bytes:
                        raise DownloadError("invalid_media", attempted=True)
                    parts.append(chunk)
                if time.monotonic() >= deadline:
                    raise DownloadError("download_timeout", attempted=True)
                return b"".join(parts), url, hop
    except DownloadError as exc:
        exc.attempted = exc.attempted or attempted
        exc.redirects = hop
        raise
    except httpx.TimeoutException:
        error = DownloadError("download_timeout", attempted=attempted, stage="transport")
        error.redirects = hop
        raise error from None
    except httpx.HTTPError as exc:
        tls = "SSL" in str(exc) or "CERTIFICATE" in str(exc)
        error = DownloadError(
            "download_failed",
            attempted=attempted,
            reason="tls_failed" if tls else "connection_failed",
            stage="tls" if tls else "transport",
        )
        error.redirects = hop
        raise error from None
    finally:
        if owned:
            client.close()
