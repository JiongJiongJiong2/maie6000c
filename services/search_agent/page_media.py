"""Bounded deterministic HTML clues; no URL guessing or whole-site crawling."""

import json
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .meme_types import MediaSource
from .resolvers import CommonsOriginal, LicensedParrot, TenorOriginal


class TenorRelated(HTMLParser):
    """Read bounded public recommendations with their own actual permalinks.

    These are independent candidates, never renditions of the viewed post.
    No embedded API configuration or credentials leave this parser.
    """

    def __init__(self, page_url):
        super().__init__(convert_charrefs=True)
        self.post_id = urlsplit(page_url).path.rstrip("/").rsplit("-", 1)[-1]
        self.collecting = False
        self.parts = []
        self.posts = []

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
            posts = (
                store.get("gifs", {}).get("related", {}).get(self.post_id, {}).get("results", [])
            )
            for post in posts[:20]:
                permalink = post.get("itemurl", "")
                parsed = urlsplit(permalink)
                if parsed.hostname != "tenor.com" or "/view/" not in parsed.path:
                    continue
                media = post.get("media_formats", {})
                for kind in ["webp", "gif", "mediumgif", "tinygif"]:
                    entry = media.get(kind, {})
                    url = entry.get("url")
                    if isinstance(url, str) and 0 < entry.get("size", 0) <= 12 * 1024 * 1024:
                        self.posts.append(
                            (
                                permalink,
                                url,
                                str(post.get("content_description") or post.get("title") or "")[
                                    :500
                                ],
                            )
                        )
                        break
        except (ValueError, TypeError, AttributeError, RecursionError):
            return
        finally:
            self.parts = []


class PageImages(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.clues = []
        self.json_parts = []
        self.in_json = False

    def handle_starttag(self, tag, attrs):
        # HTML boolean/empty attributes are represented by HTMLParser as None.
        a = {key: value or "" for key, value in attrs}
        if tag == "meta" and (a.get("property") or a.get("name", "")).lower() in {
            "og:image",
            "og:image:url",
            "og:image:secure_url",
            "twitter:image",
            "twitter:image:src",
        }:
            if a.get("content"):
                self.clues.append((0, a["content"]))
        if tag == "img":
            label = (a.get("alt", "") + " " + a.get("class", "")).lower()
            if any(x in label for x in ["favicon", "logo", "avatar", "icon", "tracking", "spacer"]):
                return
            for k in ["data-original", "data-src", "data-lazy-src", "src"]:
                if a.get(k):
                    self.clues.append((3, a[k]))
                    break
            if a.get("srcset"):
                options = []
                for candidate in a["srcset"].split(","):
                    parts = candidate.split()
                    if parts:
                        try:
                            size = float(parts[-1][:-1]) if len(parts) > 1 else 0
                        except ValueError:
                            size = 0
                        options.append((size, parts[0]))
                if options:
                    self.clues.append((2, max(options)[1]))
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self.in_json = True
            self.json_parts = []

    def handle_data(self, data):
        if self.in_json:
            self.json_parts.append(data)

    def handle_endtag(self, tag):
        if tag != "script" or not self.in_json:
            return
        self.in_json = False
        try:
            self.walk(json.loads("".join(self.json_parts)))
        except (ValueError, TypeError, RecursionError):
            pass

    def walk(self, value, depth=0):
        if depth > 12:
            return
        if isinstance(value, list):
            for item in value[:40]:
                self.walk(item, depth + 1)
        elif isinstance(value, dict):
            for key in ["image", "contentUrl", "thumbnailUrl"]:
                item = value.get(key)
                if isinstance(item, str):
                    self.clues.append((1, item))
                elif isinstance(item, (list, dict)):
                    self.walk(item, depth + 1)
            if value.get("@type") == "ImageObject" and isinstance(value.get("url"), str):
                self.clues.append((1, value["url"]))
            for key in ["@graph", "mainEntity", "associatedMedia"]:
                if key in value:
                    self.walk(value[key], depth + 1)


def page_sources(source, data, final_url):
    generic = PageImages()
    generic.feed(data.decode("utf-8", errors="replace"))
    host = urlsplit(final_url).hostname
    specific = None
    if host == "tenor.com" and "/view/" in urlsplit(final_url).path:
        # v2 supports actual animated WebP bytes. Prefer one public primary
        # rendition instead of spending originals/pages on GIF size variants.
        specific = TenorOriginal(final_url, prefer_webp=True)
    elif host == "commons.wikimedia.org":
        specific = CommonsOriginal()
    elif host == "cultofthepartyparrot.com":
        specific = LicensedParrot()
    if specific:
        specific.feed(data.decode("utf-8", errors="replace"))
    # Direct/structured/HTML clues first, specialized originals receive a better
    # identity/quality preference without allowing unrelated Tenor recommendations.
    clues = [(-1, u) for u in specific.urls] if specific and specific.urls else generic.clues
    output = []
    seen = set()
    for _, href in sorted(clues, key=lambda v: v[0]):
        url = urljoin(final_url, href)
        p = urlsplit(url)
        if (
            p.scheme not in {"http", "https"}
            or not p.hostname
            or p.username
            or p.password
            or p.path.lower().endswith((".svg", ".ico", ".mp4", ".webm"))
            or url in seen
        ):
            continue
        seen.add(url)
        try:
            output.append(
                MediaSource(
                    **{**source.model_dump(), "media_url": url, "source_type": "page-extracted"}
                ).checked()
            )
        except ValueError:
            continue
        if len(output) == 4:
            break
    if isinstance(specific, TenorOriginal):
        related = TenorRelated(final_url)
        related.feed(data.decode("utf-8", errors="replace"))
        for permalink, media, title in related.posts:
            if media in seen:
                continue
            try:
                candidate = MediaSource(
                    **{
                        **source.model_dump(),
                        "source_url": permalink,
                        "media_url": media,
                        "title": title,
                        "source_type": "page-extracted",
                    }
                ).checked()
            except ValueError:
                continue
            seen.add(media)
            output.append(candidate)
            if len(output) >= 14:
                break
    return output
