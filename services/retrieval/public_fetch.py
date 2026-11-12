"""Isolated credential-free media egress. Actual TCP peers are pinned to public IPs.

httpx 0.28.1/httpcore 1.0.9 are pinned because the transport pool/backend API is
version-specific. httpcore retains the ORIGINAL URL host for Host, SNI and TLS
verification; only connect_tcp receives the already validated numeric address.
"""

import ipaddress
import json
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin, urlsplit

import certifi
import httpcore
import httpx
from httpcore._backends.sync import SyncBackend


class FetchError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def public_address(address):
    value = ipaddress.ip_address(address)
    if not value.is_global or (value.ipv4_mapped is not None if value.version == 6 else False):
        raise FetchError("non_public_address")
    return str(value)


def valid_url(url):
    try:
        p = urlsplit(url)
        if (
            p.scheme not in {"http", "https"}
            or not p.hostname
            or p.username
            or p.password
            or p.port not in (None, 443 if p.scheme == "https" else 80)
            or len(url) > 4096
        ):
            raise ValueError
        host = p.hostname.encode("idna").decode().lower()
        if host in {"localhost", "metadata.google.internal"} or host.endswith(
            (".local", ".internal", ".localhost")
        ):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if "." not in host:
                raise ValueError
        else:
            public_address(host)
        return host
    except ValueError:
        raise FetchError("url_policy") from None


class PublicBackend(SyncBackend):
    def __init__(self, dns_mode, deadline, stats):
        self.dns_mode, self.deadline, self.stats = dns_mode, deadline, stats
        self.context = ssl.create_default_context(cafile=certifi.where())

    def addresses(self, host):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return [public_address(host)]
        self.stats["dns_queries"] += 1
        if self.dns_mode == "doh":
            # Explicit DNS service, not a fabricated DNS result. Bootstrap is a
            # public numeric IP with verified IP certificate; no image is sent.
            remaining = self.deadline - time.monotonic()
            with httpx.Client(verify=self.context, trust_env=False, timeout=min(8, remaining)) as c:
                r = c.get(
                    "https://1.1.1.1/dns-query",
                    params={"name": host, "type": "A"},
                    headers={"Accept": "application/dns-json"},
                )
                r.raise_for_status()
                if len(r.content) > 65536:
                    raise FetchError("dns_response_limit")
                self.stats["bytes_used"] += len(r.content)
                values = [v["data"] for v in r.json().get("Answer", []) if v.get("type") == 1]
        else:
            values = [a[4][0] for a in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
        if not values:
            raise FetchError("dns_failed")
        # Mixed public/private answers are rejected as a whole.
        return sorted({public_address(v) for v in values}, key=lambda v: (":" in v, v))

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if port not in {80, 443}:
            raise FetchError("port_policy")
        last = None
        for address in self.addresses(host):
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise FetchError("deadline")
            self.stats["connections"] += 1
            try:
                stream = super().connect_tcp(
                    address,
                    port,
                    timeout=min(timeout or 8, remaining),
                    socket_options=socket_options,
                )
                peer = stream.get_extra_info("server_addr")
                try:
                    if not peer or public_address(peer[0]) != address:
                        raise FetchError("peer_mismatch")
                except ValueError:
                    stream.close()
                    raise FetchError("peer_mismatch") from None
                self.stats["peers"].append(address)
                return stream
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        raise FetchError("connection_failed") from last


class PublicTransport(httpx.HTTPTransport):
    def __init__(self, dns_mode, deadline, stats):
        super().__init__(trust_env=False, retries=0)
        self._pool.close()
        context = ssl.create_default_context(cafile=certifi.where())
        self._pool = httpcore.ConnectionPool(
            ssl_context=context,
            retries=0,
            max_connections=1,
            network_backend=PublicBackend(dns_mode, deadline, stats),
        )


def request_public(url, max_bytes, seconds, dns_mode="system", redirect_limit=3):
    if dns_mode not in {"system", "doh"} or not 0 < seconds <= 40:
        raise FetchError("invalid_fetch_request")
    if not 0 < max_bytes <= 12 * 1024 * 1024 or not 0 <= redirect_limit <= 3:
        raise FetchError("invalid_fetch_request")
    deadline = time.monotonic() + seconds
    stats = dict(bytes_used=0, redirects=0, dns_queries=0, connections=0, peers=[], http_gets=0)
    try:
        with httpx.Client(
            transport=PublicTransport(dns_mode, deadline, stats),
            trust_env=False,
            follow_redirects=False,
        ) as c:
            for hop in range(redirect_limit + 1):
                valid_url(url)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError("deadline")
                stats["http_gets"] += 1
                with c.stream(
                    "GET",
                    url,
                    timeout=min(12, remaining),
                    headers={
                        "User-Agent": "MemeRetrieve/2.0 (+https://github.com/JiongJiongJiong2/maie6000c)",
                        "Accept": "image/*,text/html;q=0.8",
                    },
                ) as r:
                    if r.status_code in {301, 302, 303, 307, 308}:
                        if hop >= redirect_limit or not r.headers.get("location"):
                            raise FetchError("redirect_limit")
                        url = urljoin(url, r.headers["location"])
                        stats["redirects"] += 1
                        continue
                    if r.status_code != 200:
                        raise FetchError(f"http_{r.status_code}")
                    parts, size = [], 0
                    iterator = iter(r.iter_bytes(chunk_size=8192))
                    while True:
                        if time.monotonic() >= deadline:
                            raise FetchError("deadline")
                        try:
                            chunk = next(iterator)
                        except StopIteration:
                            break
                        size += len(chunk)
                        stats["bytes_used"] += len(chunk)
                        if size > max_bytes:
                            raise FetchError("byte_limit")
                        parts.append(chunk)
                    stats["final_url"] = url
                    return b"".join(parts), stats
    except Exception as exc:
        code = (
            exc.code
            if isinstance(exc, FetchError)
            else (
                "timeout"
                if isinstance(exc, (httpx.TimeoutException, httpcore.TimeoutException))
                else "transport_failed"
            )
        )
        error = FetchError(code)
        error.stats = stats
        raise error from None


slots = threading.BoundedSemaphore(6)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(45)

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path != "/health/live":
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def do_POST(self):
        if self.path != "/fetch" or not slots.acquire(blocking=False):
            self.send_error(429)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                raise FetchError("request_limit")
            request = json.loads(self.rfile.read(length))
            data, stats = request_public(**request)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Fetch-Stats", json.dumps(stats, separators=(",", ":")))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            body = json.dumps(
                dict(
                    code=exc.code if isinstance(exc, FetchError) else "fetch_failed",
                    stats=getattr(exc, "stats", {}),
                )
            ).encode()
            self.send_response(422)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        finally:
            slots.release()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8120), Handler).serve_forever()
