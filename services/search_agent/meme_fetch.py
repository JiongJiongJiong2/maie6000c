"""Client to the isolated, credential-free public egress service."""

import json
import os
from urllib.parse import urlsplit

import httpx

from .meme_types import PipelineError


class FetchClient:
    def __init__(self, ledger, endpoint=None):
        self.ledger = ledger
        self.endpoint = endpoint or os.environ.get("MEME50_FETCH_URL", "http://127.0.0.1:8120")
        p = urlsplit(self.endpoint)
        if p.username or p.password or p.query or p.fragment or p.scheme not in {"http", "https"}:
            raise PipelineError("fetch_service_config")

    def get(self, url, kind, max_bytes):
        self.ledger.take(kind)
        remaining = self.ledger.remaining()
        with self.ledger.lock:
            available = (
                self.ledger.settings.max_bytes
                - self.ledger.counts["response_bytes"]
                - self.ledger.reservations["response_bytes"]
            )
            # One small DNS response per redirect host is reserved as well.
            redirect_lease = min(
                3,
                self.ledger.settings.max_redirects
                - self.ledger.counts["redirects"]
                - self.ledger.reservations["redirects"],
            )
            dns_reserve = 65536 * (redirect_lease + 1) + 8192
            limit = min(max_bytes, available - dns_reserve)
            if limit <= 0:
                raise PipelineError("response_bytes_limit")
            lease = limit + dns_reserve
            self.ledger.reservations["response_bytes"] += lease
            self.ledger.reservations["redirects"] += redirect_lease
        # Unknown service-side consumption is conservatively charged, not refunded.
        consumed, stats = lease, {}
        try:
            with httpx.Client(trust_env=False, timeout=remaining + 1) as client:
                r = client.post(
                    self.endpoint + "/fetch",
                    json=dict(
                        url=url,
                        max_bytes=limit,
                        seconds=min(remaining, 40),
                        dns_mode=self.ledger.settings.dns_mode,
                        redirect_limit=redirect_lease,
                    ),
                )
                if r.status_code != 200:
                    error = r.json()
                    stats = error.get("stats", {})
                    consumed = stats.get("bytes_used", lease)
                    raise PipelineError("fetch_" + error.get("code", "failed"))
                stats = json.loads(r.headers.get("X-Fetch-Stats", "{}"))
                consumed = stats.get("bytes_used", lease)
                if len(r.content) > limit:
                    raise PipelineError("fetch_response_limit")
                return r.content, stats.get("final_url", url)
        except (httpx.HTTPError, ValueError):
            raise PipelineError("fetch_service_unavailable") from None
        finally:
            with self.ledger.lock:
                self.ledger.reservations["response_bytes"] -= lease
                self.ledger.reservations["redirects"] -= redirect_lease
                self.ledger.counts["response_bytes"] += consumed
                for field in ["dns_queries", "connections", "redirects"]:
                    self.ledger.counts[field] += stats.get(field, 0)
            self.ledger.note(
                "fetch",
                kind=kind,
                host=urlsplit(url).hostname,
                bytes_used=consumed,
                redirects=stats.get("redirects", 0),
                peers=stats.get("peers", []),
            )
