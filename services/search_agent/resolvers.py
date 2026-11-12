"""Deterministic source resolution; page contents never enter the planner."""

import json
import re
from collections import Counter
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import unquote, urljoin, urlsplit

from pydantic import BaseModel, Field

from services.retrieval.download import (
    MEDIA_HOSTS,
    PAGE_HOSTS,
    DownloadError,
    canonical_url,
    allowed_media_path,
    fetch,
)
from .models import Source


class ResolvedBatch(BaseModel):
    sources: list[Source] = Field(default_factory=list)
    failures: list[Literal["unsupported_source", "source_unavailable"]] = Field(
        default_factory=list
    )
    page_requests: int = Field(default=0, ge=0)
    redirects: int = Field(default=0, ge=0)
    diagnostics: list[dict] = Field(default_factory=list)
    reasons: dict[str, int] = Field(default_factory=dict)


class CommonsOriginal(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = {key: value or "" for key, value in attrs}
        if tag == "a" and "internal" in attrs.get("class", "").split():
            href = attrs.get("href", "")
            self.urls.append(href)


class LicensedParrot(HTMLParser):
    """Only the original green gif has established upstream permission here.

    The gallery's colorful variants are not licensed by its code's MIT license.
    Do not widen this set based on a substring or inferred family resemblance.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        href = attrs.get("data-src", "")
        if tag == "img" and href == "/parrots/hd/originalparrot.gif":
            self.urls.append(href)


class TenorOriginal(HTMLParser):
    """Read only the viewed post's media_formats, never related GIF cards.

    Public page metadata is used without its embedded API key or a private API.
    Actual byte type, animation and size are independently checked downstream.
    """

    def __init__(self, page_url, *, prefer_webp=False):
        super().__init__(convert_charrefs=True)
        self.prefer_webp = prefer_webp
        match = re.search(r"-(\d+)$", urlsplit(page_url).path.rstrip("/"))
        self.post_id = match.group(1) if match else None
        self.collecting = False
        self.parts = []
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "store-cache":
            self.collecting = True
            self.parts = []

    def handle_data(self, data):
        if self.collecting:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag != "script" or not self.collecting:
            return
        self.collecting = False
        try:
            store = json.loads("".join(self.parts))
            posts = store.get("gifs", {}).get("byId", {}).get(self.post_id, {}).get("results", [])
            for post in posts:
                if str(post.get("id")) != self.post_id:
                    continue
                media = post.get("media_formats", {})
                kinds = (
                    ["webp", "gif", "mediumgif", "tinygif"]
                    if self.prefer_webp
                    else ["gif", "mediumgif", "tinygif"]
                )
                for kind in kinds:
                    entry = media.get(kind, {})
                    if entry.get("size", 0) > 12 * 1024 * 1024:
                        continue
                    url = entry.get("url")
                    if isinstance(url, str) and url not in self.urls:
                        self.urls.append(url)
                    if len(self.urls) == (1 if self.prefer_webp else 2):
                        break
        except (ValueError, TypeError, AttributeError):
            return


def resolve_sources(sources, *, deadline, remaining_pages, remaining_downloads):
    result = ResolvedBatch()
    reasons = Counter()
    deferred_renditions = []
    for source in sources:
        if len(result.sources) >= remaining_downloads:
            break
        if source.image_url:
            result.sources.append(source)
            continue
        p = urlsplit(source.source_url)
        if p.hostname in MEDIA_HOSTS and p.path.lower().endswith(".gif"):
            result.sources.append(source.model_copy(update={"image_url": source.source_url}))
            continue
        commons = p.hostname == "commons.wikimedia.org" and unquote(p.path).casefold().startswith(
            "/wiki/file:"
        )
        parrot = p.hostname == "cultofthepartyparrot.com" and p.path in {"", "/"}
        tenor = p.hostname == "tenor.com" and bool(
            re.fullmatch(r"/(?:[a-z]{2}(?:-[A-Za-z]{2})?/)?view/[^/]+-\d+/?", p.path)
        )
        if not (commons or parrot or tenor):
            result.failures.append("unsupported_source")
            reasons["unsupported_source"] += 1
            continue
        if result.page_requests >= remaining_pages:
            reasons["page_budget_exhausted"] += 1
            continue
        try:
            data, final, redirects = fetch(
                source.source_url, hosts=PAGE_HOSTS, max_bytes=2 * 1024 * 1024, deadline=deadline
            )
            result.page_requests += 1
            result.redirects += redirects
            parser = (
                TenorOriginal(final)
                if tenor
                else (CommonsOriginal() if commons else LicensedParrot())
            )
            parser.feed(data.decode("utf-8", errors="replace"))
            urls = []
            for href in parser.urls:
                url = canonical_url(urljoin(final, href))
                parsed = urlsplit(url)
                if (
                    parsed.scheme == "https"
                    and parsed.hostname in MEDIA_HOSTS
                    and parsed.port in (None, 443)
                    and not parsed.username
                    and not parsed.password
                    and parsed.path.lower().endswith(".gif")
                    and allowed_media_path(parsed.hostname, parsed.path)
                ):
                    urls.append(url)
            urls = list(dict.fromkeys(urls))
            if not urls:
                reasons["no_original_gif"] += 1
            selected = urls[: min(2, remaining_downloads - len(result.sources))]
            if tenor and len(selected) > 1:
                # Distinct posts precede extra resolutions of the same animation.
                deferred_renditions.append(
                    Source.model_validate({**source.model_dump(), "image_url": selected[1]})
                )
                selected = selected[:1]
            for url in selected:
                result.sources.append(
                    Source.model_validate({**source.model_dump(), "image_url": url})
                )
        except DownloadError as exc:
            result.page_requests += int(exc.attempted)
            result.redirects += exc.redirects
            result.failures.append("source_unavailable")
            reasons[exc.reason] += 1
            result.diagnostics.append(
                dict(code=exc.code, reason=exc.reason, stage=exc.stage, http_status=exc.http_status)
            )
    result.sources.extend(deferred_renditions[: remaining_downloads - len(result.sources)])
    result.reasons = dict(reasons)
    return result
