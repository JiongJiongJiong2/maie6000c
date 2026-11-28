"""Find public sticker release pages and verify their artwork against the upload."""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from io import BytesIO
from itertools import islice, repeat, zip_longest
from threading import BoundedSemaphore
from unicodedata import normalize
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from PIL import Image, ImageStat

from services.common.sticker_catalog import frame_keys, image_distance
from services.common.sticker_web_models import LOOKUP_SECONDS, StickerSource, WebStickerSearch
from services.common.storage import MediaError
from services.retrieval.public_fetch import FetchError, valid_url

from .captions import caption_overlap, caption_phrases, generic_subject, words
from .meme_deepseek import DeepSeekWeb
from .meme_fetch import FetchClient
from .meme_types import Ledger, MediaSource, MemeSettings, PipelineError, VisualAnalysis
from .page_media import PageImages
from .visual_analysis import analyze_image

logger = logging.getLogger(__name__)
fetch_slots = BoundedSemaphore(4)

PAGE_LIMIT = 14
IMAGE_LIMIT = 144
VISUAL_DISTANCE = 0.13
MATCH_MARGIN = 0.025
LINE_PRODUCT = re.compile(r"/stickershop/product/(\d+)(?:/[a-zA-Z-]+)?/?")
LINE_SHARE = re.compile(r"/S/sticker/(\d+)/?", re.I)
TELEGRAM_SET = re.compile(r"/addstickers/([a-zA-Z0-9_]+)/?")
WHATSTICKER_PACK = re.compile(r"/p/([a-zA-Z0-9]+)(?:/[^/]+){0,2}/?")
WHATSAPP_PACK = re.compile(r"/stickerpack/([a-zA-Z0-9_-]+)/?")
SIGSTICK_PACK = re.compile(r"/pack/([a-zA-Z0-9]{8,32})(?:-[^/]+)?/?")
STICKERLY_PACK = re.compile(r"/s/[a-zA-Z0-9_-]{4,}/?")
GIPHY_STICKER = re.compile(r"/stickers/[^/]+-([a-zA-Z0-9]{8,})/?")
GIPHY_COLLECTION = re.compile(r"/(?:explore/[\w-]+-stickers|[\w.-]+/stickers)/?")
GIPHY_CDN = re.compile(r"media\d*\.giphy\.com")
KAKAO_PRODUCT = re.compile(r"/t/[\w-]+/?")
WEIBO_ANNOUNCEMENT = re.compile(r"/(?:news/)?detail/\d+(?:\.html)?/?")
ISSUER_DOMAINS = ("whatsapp.com", "signal.org", "telegram.org", "wechat.com", "line.me")
STICKER_WORDS = re.compile(r"sticker|貼圖|贴图|表情(?:包|专辑|專輯)|动图|スタンプ|스티커", re.I)
COLLECTION_WORDS = re.compile(
    r"(?:贴图|貼圖|表情包?|动图|gif).{0,12}(?:合集|大全|全集|套装)|stickers? (?:pack|collection)",
    re.I,
)
PICKUP_WORDS = re.compile(
    r"download|install|add to (?:whatsapp|wechat|signal|telegram)|get (?:the|these) stickers"
    r"|下載|下载|領取|领取|加入貼圖|获取方式|獲取方式|微信(?:内|中)?搜索|微信搜尋"
    r"|(?:正式)?上[架线線]|领取方式|(?:直接|长按)保存|ダウンロード|다운로드",
    re.I,
)
ART_STYLES = re.compile(
    r"\b(?:8[ -]bit|16[ -]bit|pixel(?:ated| art)|crochet|plush(?:ie)?|watercolou?r|"
    r"line art|stop[ -]motion|claymation|paper cutout|3d)\b",
    re.I,
)
VISUAL_CUES = (
    re.compile(r"\bwhite\b|白色|小白狗", re.I),
    re.compile(
        r"\b(?:doodle|line[ -]?(?:draw|art)|outline|sketch|hand[ -]?draw)|简笔画|线条|手绘", re.I
    ),
    re.compile(r"\b(?:dog|puppy|bear|animal|pet)\b|小狗|小熊|萌宠|马尔济斯", re.I),
    re.compile(r"\bdanc|跳舞|蹦迪|蹦跳", re.I),
    re.compile(r"\bmusi|音[符乐]", re.I),
)


def https_url(raw: str, base: str = "") -> str | None:
    try:
        url = urljoin(base, raw.strip())
        parsed = urlsplit(url)
        if parsed.scheme == "http" and parsed.port is None:
            parsed = parsed._replace(scheme="https")
            url = urlunsplit(parsed)
        if parsed.scheme != "https" or any(char in url for char in ("\r", "\n", "\t", "\\")):
            return None
        valid_url(url)
        return urlunsplit(parsed._replace(fragment=""))
    except (AttributeError, ValueError, FetchError):
        return None


def listing(url: str) -> str:
    parsed = urlsplit(url)
    host, path = parsed.hostname, parsed.path
    if host == "store.line.me" and LINE_PRODUCT.fullmatch(path):
        return "LINE STORE"
    if host == "t.me" and TELEGRAM_SET.fullmatch(path):
        return "Telegram sticker listing"
    if host in {"wa.me", "www.wa.me"} and WHATSAPP_PACK.fullmatch(path):
        return "WhatsApp sticker link"
    if host == "sticker.weixin.qq.com" and path.endswith("/emoticonview") and parsed.query:
        return "WeChat sticker listing"
    if host == "e.kakao.com" and KAKAO_PRODUCT.fullmatch(path):
        return "Kakao Emoticon Shop"
    if host in {"giphy.com", "www.giphy.com"} and GIPHY_STICKER.fullmatch(path):
        return "GIPHY sticker"
    return ""


def pickup_candidate(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.hostname == "line.me" and (match := LINE_SHARE.fullmatch(parsed.path)):
        return f"https://store.line.me/stickershop/product/{match[1]}/en"
    return url


def directory_id(url: str) -> str | None:
    parsed = urlsplit(url)
    match = WHATSTICKER_PACK.fullmatch(parsed.path)
    if match and parsed.hostname in {"whatsticker.online", "www.whatsticker.online"}:
        return match[1]
    return None


def community_listing(url: str) -> str:
    parsed = urlsplit(url)
    host, path = parsed.hostname, parsed.path
    if directory_id(url):
        return "WhatSticker"
    if host in {"sigstick.com", "www.sigstick.com"} and SIGSTICK_PACK.fullmatch(path):
        return "SigStick"
    if host in {"sticker.ly", "www.sticker.ly"} and STICKERLY_PACK.fullmatch(path):
        return "Sticker.ly"
    if host in {"giphy.com", "www.giphy.com"} and GIPHY_COLLECTION.fullmatch(path):
        return "GIPHY collection"
    if host == "mp.weixin.qq.com" and (path.startswith("/s/") or path == "/s"):
        return "WeChat article"
    if host in {"www.sina.cn", "m.weibo.cn"} and WEIBO_ANNOUNCEMENT.fullmatch(path):
        return "Weibo post"
    if (
        host in {"www.duitang.com", "m-2.duitang.com"}
        and path.rstrip("/") == "/album"
        and parsed.query
    ):
        return "Duitang sticker collection"
    if host == "memecub.com" and re.fullmatch(r"/(?:[a-z-]+/)?meme/[^/]+/?", path):
        return "MemeCub"
    return ""


def page_key(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if pack_id := directory_id(url):
        return ("whatsticker.online", pack_id)
    if parsed.hostname == "store.line.me" and (line_id := LINE_PRODUCT.fullmatch(parsed.path)):
        return ("store.line.me", line_id[1])
    if parsed.hostname in {"sigstick.com", "www.sigstick.com"} and (
        pack := SIGSTICK_PACK.fullmatch(parsed.path)
    ):
        return ("sigstick.com", pack[1])
    if parsed.hostname in {"giphy.com", "www.giphy.com"} and (
        item := GIPHY_STICKER.fullmatch(parsed.path)
    ):
        return ("giphy.com", item[1])
    if (
        parsed.hostname in {"www.duitang.com", "m-2.duitang.com"}
        and parsed.path.rstrip("/") == "/album"
    ):
        ids = parse_qs(parsed.query).get("id", [])
        return ("duitang.com", ids[0] if ids else parsed.query)
    if parsed.hostname in {"sticker.weixin.qq.com", "mp.weixin.qq.com"} and parsed.query:
        ids = parse_qs(parsed.query)
        key = "&".join(
            ids[name][0] for name in ("id", "md5", "__biz", "mid", "idx") if ids.get(name)
        )
        key = key or parsed.query
        return (parsed.hostname, parsed.path.rstrip("/") + "?" + key)
    return (parsed.hostname or "", parsed.path.rstrip("/"))


def issuer_host(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    public_issuer = (".gov", ".gov.cn", ".gov.hk", ".gov.uk", ".gov.sg", ".go.jp", ".edu.cn")
    return host.endswith(public_issuer) or any(
        host == domain or host.endswith("." + domain) for domain in ISSUER_DOMAINS
    )


def sticker_names(analysis: VisualAnalysis, minimum=0.72) -> list[str]:
    return [
        item.name
        for item in analysis.entity_hypotheses
        if item.confidence >= minimum
        and item.status not in {"unknown", "conflicting"}
        and not generic_subject(item.name)
    ]


def search_queries(analysis: VisualAnalysis) -> list[str]:
    entities = sticker_names(analysis)
    visual = next(
        (query.text for query in analysis.queries if query.angle == "visual_description"),
        " ".join(analysis.visual_keywords[:5]),
    )
    visible_text = re.sub(r"https?://\S+|site:\S+", "", " ".join(analysis.ocr_text.split()))[:48]
    name = entities[0][:65] if entities else ""
    identity = (name or visual[:65] or visible_text).strip()
    if not identity:
        return []
    normalized = re.sub(r"https?://\S+|site:\S+", "", identity, flags=re.I).strip()
    if not normalized:
        return []
    more = visible_text if visible_text.casefold() not in normalized.casefold() else ""
    style = ART_STYLES.search(visual + " " + " ".join(analysis.visual_keywords))
    detail = style[0] if style and style[0].casefold() not in normalized.casefold() else ""
    body = " ".join(part for part in (normalized, detail, more) if part)
    alternate = next((entity for entity in entities if re.search(r"[㐀-鿿]", entity)), "")
    chinese = (alternate or normalized).strip()[:65]
    local_visual = next(
        (
            q.text
            for q in analysis.queries
            if q.language.startswith("zh")
            and q.angle
            in {
                "appearance",
                "visual_description",
            }
        ),
        "",
    )
    if not entities:
        visual_text = " ".join((visual, *analysis.visual_keywords, *analysis.action_tags))
        if VISUAL_CUES[2].search(visual_text) and VISUAL_CUES[1].search(visual_text):
            white = "白色" if re.search(r"\bwhite\b", visual_text, re.I) else ""
            dance = "跳舞" if re.search(r"\bdanc", visual_text, re.I) else ""
            notes = "音符" if re.search(r"\bmusi", visual_text, re.I) else ""
            nearby = f"{white}线条小狗 {dance} {notes} 表情包 动图"
            local_collection = f"{white}线条小狗 表情包 动图 合集"
        else:
            nearby = f"{(local_visual or chinese)[:70]} {more[:20]} 微信表情包"
            local_collection = f"{(local_visual or chinese)[:75]} 表情包 微信"
        return clean_queries(
            [
                nearby,
                local_collection,
                f"{body[:84]} animated messaging sticker",
            ]
        )
    options = [
        f"{body[:82]} sticker pack download share",
        f"{body[:80]} stickers site:giphy.com/stickers",
        f"{chinese} {more[:22]} 微信表情包 上架 领取",
        f"{chinese} 微信表情包 上架 site:sina.cn",
        f"{normalized[:76]} WhatsApp Telegram stickers 貼圖",
        f"{body[:78]} stickers site:store.line.me",
    ]
    if re.search(r"[ぁ-ヿ]", visible_text) or re.search(r"[가-힣]", visible_text + chinese):
        options[4] = f"{body[:70]} 이모티콘 スタンプ site:e.kakao.com"
    return clean_queries(options)


def clean_queries(queries):
    return list(dict.fromkeys(" ".join(query.split())[:128] for query in queries if query.strip()))


def giphy_gallery_url(analysis):
    name = next(
        (
            name
            for name in sticker_names(analysis)
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9 .'-]{1,48}", name)
        ),
        "",
    )
    if not name:
        # A named object can have an indexed gallery even when the picture has no character.
        label = " ".join((*analysis.visual_keywords, *analysis.observations))
        object_name = re.search(
            r"\b(?:saturn|astronaut|space shuttle|space station|airplane|rocket)\b", label, re.I
        )
        name = object_name[0] if object_name else ""
    if name:
        slug = "-".join(words(name))
        return f"https://giphy.com/explore/{slug}-stickers"
    return None


class StickerPage(PageImages):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.author = ""
        self.previews = []
        self.sticker_images = []
        self.links = []
        self.text = []
        self.capture = ""
        self.in_code = False

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        values = {key: value or "" for key, value in attrs}
        classes = values.get("class", "").split()
        if tag in {"script", "style"}:
            self.in_code = True
        if tag == "title":
            self.capture = "title"
        elif tag == "a" and "mdCMN38Item01Author" in classes:
            self.capture = "author"
        if tag == "a" and values.get("href") and len(self.links) < 600:
            self.links.append(values["href"])
        if tag == "meta" and values.get("property") == "og:title":
            self.title = (values.get("content") or self.title)[:250]
        if tag == "img" and {"sticker", "tray-icon"}.intersection(classes):
            self.sticker_images.extend(
                values[key] for key in ("src", "data-webp") if values.get(key)
            )
        if values.get("data-preview") and len(self.previews) < 80:
            try:
                preview = json.loads(values["data-preview"])
                for key in ("staticUrl", "fallbackStaticUrl", "animationUrl"):
                    if isinstance(preview.get(key), str) and preview[key]:
                        self.previews.append(preview[key])
            except (ValueError, AttributeError):
                pass

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if tag in {"script", "style"}:
            self.in_code = False
        if (tag, self.capture) in {("title", "title"), ("a", "author")}:
            self.capture = ""

    def handle_data(self, data):
        super().handle_data(data)
        if self.capture == "title" and not self.title:
            self.title = data.strip()[:250]
        elif self.capture == "author":
            self.author = (self.author + data).strip()[:150]
        if not self.in_code and len(self.text) < 2500 and data.strip():
            self.text.append(data[:800])


@dataclass
class WebPage:
    url: str
    title: str
    channel: str
    author: str
    images: list[str]
    links: list[str] = field(default_factory=list)
    publisher_pickup: bool = False
    has_pickup: bool = False
    publisher_stickers: bool = False
    embedded: list[WebPage] = field(default_factory=list)


def fetch_public(fetcher, url, kind, max_bytes):
    # Share the egress service with the regular image search worker.
    with fetch_slots:
        return fetcher.get(url, kind, max_bytes)


def giphy_gallery_items(page, base):
    """Pair each indexed sticker link with its own thumbnail from the rendered gallery."""
    thumbnails = {}
    for _, raw in page.clues:
        if not (url := https_url(raw, base)) or not GIPHY_CDN.fullmatch(
            urlsplit(url).hostname or ""
        ):
            continue
        parts = urlsplit(url).path.split("/")
        if len(parts) >= 4 and parts[1] == "media":
            label = page.image_labels.get(raw, "")
            key = parts[-2]
            if key not in thumbnails or label and not thumbnails[key][1]:
                thumbnails[key] = (url, label)
    items = {}
    for raw in page.links:
        url = https_url(raw, base)
        if not url or listing(url) != "GIPHY sticker":
            continue
        key = page_key(url)[1]
        if key in thumbnails and key not in items:
            preview, title = thumbnails[key]
            items[key] = WebPage(url, title or "GIPHY sticker", "GIPHY sticker", "", [preview])
    return list(items.values())[:20]


def read_page(fetcher, url: str, title: str = "") -> WebPage | None:
    try:
        raw, landed = fetch_public(fetcher, url, "page_attempts", 1_800_000)
        final_url = https_url(landed)
        if not final_url or b"<" not in raw[:1000]:
            return None
        page = StickerPage()
        page.feed(raw.decode("utf-8", errors="replace"))
    except (PipelineError, ValueError, RecursionError):
        return None
    channel = listing(final_url)
    community = community_listing(final_url)
    pack_id = directory_id(final_url)
    if channel == "LINE STORE":
        image_refs = [
            url
            for href in page.previews
            if (url := https_url(href, final_url))
            and urlsplit(url).hostname == "stickershop.line-scdn.net"
        ]
    elif pack_id:
        prefix = f"/stickers_asset/ws-pack-{pack_id}/"
        image_refs = [
            url
            for href in page.sticker_images
            if (url := https_url(href, final_url)) and urlsplit(url).path.startswith(prefix)
        ]
    elif community == "SigStick":
        pack = SIGSTICK_PACK.fullmatch(urlsplit(final_url).path)
        image_refs = [href for _, href in page.clues if f"/{pack[1]}/" in href]
    elif channel == "GIPHY sticker":
        item = GIPHY_STICKER.fullmatch(urlsplit(final_url).path)
        image_refs = [
            href
            for _, href in page.clues
            if f"/{item[1]}/" in href and GIPHY_CDN.fullmatch(urlsplit(href).hostname or "")
        ]
    elif channel == "Kakao Emoticon Shop":
        image_refs = [
            href
            for rank, href in page.clues
            if rank == 1 and urlsplit(href).hostname == "item.kakaocdn.net"
        ]
    else:
        image_refs = [href for _, href in sorted(page.clues, key=lambda clue: clue[0])]
    images = list(dict.fromkeys(url for href in image_refs if (url := https_url(href, final_url))))
    text = " ".join(page.text)
    sticker_page = bool(STICKER_WORDS.search(page.title + " " + text))
    has_pickup = sticker_page and bool(PICKUP_WORDS.search(page.title + " " + text))
    verified_issuer = issuer_host(final_url) and sticker_page
    links = []
    if not channel and not pack_id and community != "GIPHY collection":
        links = list(
            dict.fromkeys(
                target
                for href in page.links
                if (url := https_url(href, final_url))
                and (target := pickup_candidate(url))
                and (listing(target) or (sticker_page and community_listing(target)))
                and page_key(target) != page_key(final_url)
            )
        )[:8]
    return WebPage(
        final_url,
        (page.title or title or urlsplit(final_url).hostname or final_url)[:250],
        channel,
        page.author,
        images[: 48 if channel or pack_id or community == "SigStick" else 12],
        links,
        verified_issuer and has_pickup,
        has_pickup,
        verified_issuer,
        giphy_gallery_items(page, final_url) if community == "GIPHY collection" else [],
    )


def text_leads(candidates, pages, analysis, excluded):
    names = [" ".join(words(normalize("NFKC", name))) for name in sticker_names(analysis)]
    names = [
        name
        for name in names
        if name
        and (
            len(name.split()) >= 2
            or re.search(r"[㐀-鿿ぁ-ヿ가-힣]{2,}", name)
            or len(name) >= 4
            and name
            not in {
                "duck",
                "bear",
                "bunny",
                "rabbit",
                "kitten",
                "puppy",
                "mascot",
                "penguin",
                "frog",
            }
        )
    ]
    captions = caption_phrases(analysis.ocr_text)
    description = " ".join(
        (*analysis.observations, *analysis.visual_keywords, *analysis.action_tags)
    )
    cues = [pattern for pattern in VISUAL_CUES if pattern.search(description)]
    observed = {page_key(page.url): page for page in pages}
    scored = []
    for key, (url, hit) in candidates.items():
        if key in excluded:
            continue
        page = observed.get(key)
        label = " ".join(
            words(normalize("NFKC", " ".join((hit.title, page.title if page else ""))))
        )
        snippet = " ".join(words(normalize("NFKC", hit.snippet)))
        channel = listing(url) or community_listing(url)
        search_text = hit.title + " " + hit.snippet
        release = bool(page and page.has_pickup) or bool(
            STICKER_WORDS.search(search_text) and PICKUP_WORDS.search(search_text)
        )
        collection = channel in {
            "GIPHY collection",
            "Duitang sticker collection",
            "Kakao Emoticon Shop",
        } or bool(COLLECTION_WORDS.search(hit.title))
        if (not channel or channel in {"WeChat article", "Weibo post"}) and not (
            release or collection
        ):
            continue

        def contains(text, phrase):
            if re.search(r"[㐀-鿿ぁ-ヿ가-힣]", phrase):
                return phrase in text
            return f" {phrase} " in f" {text} "

        score = max(
            (3 if contains(label, name) else int(contains(snippet, name)) for name in names),
            default=0,
        )
        visual_cues = sum(bool(cue.search(search_text[:650])) for cue in cues)
        visual_description = visual_cues >= 4 and bool(channel or collection)
        if visual_description:
            score = max(score, visual_cues - 1)
        score += 4 * int(caption_overlap(captions, label) == 1.0)
        score += 2 * int(caption_overlap(captions, snippet) == 1.0)
        if score and release and channel in {"Weibo post", "WeChat article"}:
            score += 2
        if score and collection:
            score += 2
        if score < 2 or not (hit.title.strip() or page):
            continue
        if channel:
            score += 1
        scored.append(
            (
                score,
                StickerSource(
                    title=(hit.title.strip() or page.title)[:250],
                    url=url,
                    channel=channel
                    or ("Sticker collection" if collection else "Pickup instructions"),
                    match_basis="series"
                    if visual_description
                    or collection
                    or channel in {"WhatSticker", "SigStick", "Sticker.ly"}
                    else "text",
                ),
            )
        )
    return [source for _, source in sorted(scored, key=lambda item: -item[0])[:5]]


def visual_distance(fetcher, image_url: str, features) -> float:
    try:
        raw, _ = fetch_public(fetcher, image_url, "preview_attempts", 1_500_000)
        with Image.open(BytesIO(raw), formats=("PNG", "WEBP", "JPEG", "GIF")) as image:
            if max(image.size) < 20 or image.width * image.height > 3_000_000:
                return 1.0
            count = getattr(image, "n_frames", 1)
            if count * image.width * image.height > 50_000_000:
                return 1.0
            indexes = {round(i * (count - 1) / 15) for i in range(16)}
            scores = []
            for index in sorted(indexes):
                image.seek(index)
                scores.extend(
                    image_distance(left, right) for left in features for right in frame_keys(image)
                )
            return min(scores, default=1.0)
    except (PipelineError, MediaError, OSError, ValueError, EOFError, Image.DecompressionBombError):
        return 1.0


def refinement_queries(analysis, shop_terms):
    names = sticker_names(analysis)
    if not names:
        return []
    primary = names[0][:64]
    chinese = next((name[:40] for name in names if re.search(r"[㐀-鿿]", name)), primary)
    english = next((name[:46] for name in names if re.match(r"[A-Za-z]", name)), primary)
    return clean_queries(
        [
            f"{chinese} {english} 微信表情包 上架 site:sina.cn",
            f"{chinese} {english} 表情包 动图 合集",
            f"{shop_terms or english} site:e.kakao.com",
        ]
    )


def find_public_sticker(data: bytes, settings=None, *, analyzer=None, web=None, fetcher=None):
    settings = (settings or MemeSettings()).model_copy(
        update={
            "timeout_seconds": LOOKUP_SECONDS,
            "call_timeout_seconds": 12,
            "max_queries": 6,
            "max_search_calls": 6,
            "max_pages": PAGE_LIMIT,
            "max_previews": IMAGE_LIMIT,
            "max_bytes": 50 * 1024 * 1024,
        }
    )
    ledger = Ledger(settings)
    web = web or DeepSeekWeb(settings, ledger)
    fetcher = fetcher or FetchClient(ledger)
    with Image.open(BytesIO(data)) as image:
        features = [key for key in frame_keys(image) if max(ImageStat.Stat(key).stddev) >= 8]
    if not features:
        return WebStickerSearch(state="no_match")
    for hint in (
        "Identify any recognizable messaging-sticker character and creator. Give separate common "
        "Chinese and English aliases when known. Include a short Simplified Chinese description "
        "among the visual_description queries. Read visible original-language text.",
        "Identify the character in this sticker.",
    ):
        try:
            analysis, _ = (analyzer or analyze_image)(data, hint, settings, ledger)
            break
        except PipelineError as exc:
            logger.info("sticker_vision_failed", extra={"code": exc.code})
            if exc.code in {
                "visual_provider_unconfigured",
                "provider_policy_violation",
                "deadline",
            }:
                return WebStickerSearch(state="unavailable")
    else:
        return WebStickerSearch(state="unavailable")

    queries = search_queries(analysis)
    if not queries:
        return WebStickerSearch(state="no_match")

    def search_query(query):
        try:
            return web.search(query, limit=14)
        except PipelineError as exc:
            logger.info("sticker_web_search_failed", extra={"code": exc.code})
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        found = list(pool.map(search_query, queries))
        if all(batch is None for batch in found):
            return WebStickerSearch(state="unavailable")
        if not sticker_names(analysis) and (refine := getattr(web, "sticker_identities", None)):
            examples = [hit for batch in found for hit in (batch or [])[:4]]
            try:
                aliases, shop_terms = refine(analysis, examples)
            except PipelineError as exc:
                logger.info("sticker_identity_refinement_failed", extra={"code": exc.code})
            else:
                analysis = analysis.model_copy(update={"entity_hypotheses": aliases})
                followups = [
                    q for q in refinement_queries(analysis, shop_terms) if q not in queries
                ]
                found.extend(pool.map(search_query, followups[: 6 - len(queries)]))
        candidates = {}
        for row in zip_longest(*(batch or [] for batch in found)):
            for hit in row:
                if hit and (url := https_url(hit.source_url)):
                    url = pickup_candidate(url)
                    if hit.source_type != "direct":
                        candidates.setdefault(page_key(url), (url, hit))
        groups = {}, {}, {}
        for url, hit in candidates.values():
            platform = listing(url) or community_listing(url)
            host = page_key(url)[0]
            group = groups[0 if platform else 1 if issuer_host(url) else 2]
            group.setdefault(host, []).append((url, hit.title))
        # Give the initial batch a mix of platform listings and publisher pages.
        queues = [
            [pair for row in zip_longest(*group.values()) for pair in row if pair]
            for group in groups
        ]
        initial = [pair for row in zip_longest(*queues) for pair in row if pair]
        priority = [
            (str(source.url), source.title)
            for source in text_leads(candidates, [], analysis, set())[:3]
        ]
        if gallery := giphy_gallery_url(analysis):
            priority.insert(0, (gallery, "GIPHY sticker collection"))
        ordered = {}
        for url, title in priority + initial:
            ordered.setdefault(page_key(url), (url, title))
        initial = list(ordered.values())[: PAGE_LIMIT - 4]
        pages = [page for page in pool.map(lambda pair: read_page(fetcher, *pair), initial) if page]
        discovered = {page_key(target): target for page in pages for target in page.links}
        proof = {
            page_key(target): page.url
            for page in pages
            if page.publisher_stickers
            for target in page.links
        }
        known = {page_key(page.url) for page in pages}
        follow = [(key, url) for key, url in discovered.items() if key not in known]
        follow.sort(key=lambda pair: pair[0] not in proof)
        followed = [
            page for page in pool.map(lambda pair: read_page(fetcher, pair[1]), follow[:4]) if page
        ]
        galleries = [page for page in pages if page.embedded]
        pages = followed + pages
        known = {page_key(page.url) for page in pages}
        for page in galleries:
            if page_key(page.url) not in candidates:
                candidates[page_key(page.url)] = (
                    page.url,
                    MediaSource(
                        source_url=page.url,
                        provider="giphy_web",
                        title=page.title,
                    ),
                )
            for item in page.embedded:
                if page_key(item.url) not in known:
                    pages.append(item)
                    known.add(page_key(item.url))
        pages.sort(
            key=lambda page: (
                0
                if page_key(page.url) in proof
                else 1
                if page.channel or page.publisher_pickup
                else 2
            )
        )
        confirmed, leads = match_pages(pool, fetcher, pages, proof, features, ledger)
        excluded = {page_key(str(source.url)) for source in (*confirmed, *leads)}
        leads.extend(text_leads(candidates, pages, analysis, excluded))
        excluded.update(page_key(str(source.url)) for source in leads)
        for page in galleries:
            if page.url == gallery and page_key(page.url) not in excluded:
                leads.append(
                    StickerSource(
                        title=page.title,
                        url=page.url,
                        channel="GIPHY collection",
                        match_basis="series",
                    )
                )
    if confirmed:
        state = "matched"
    elif leads:
        state = "candidates"
    else:
        state = "unavailable" if initial and not pages else "no_match"
    return WebStickerSearch(state=state, links=confirmed, leads=leads[: 5 - len(confirmed)])


def match_pages(pool, fetcher, pages, proof, features, ledger):
    confirmed, leads = {}, {}
    work = (
        pair
        for row in zip_longest(*(zip(repeat(page), page.images) for page in pages))
        for pair in row
        if pair is not None
    )
    # Check the first preview of each page before spending the budget on one large pack.
    for offset in range(0, IMAGE_LIMIT, 12):
        if ledger.clock() >= ledger.deadline:
            break
        group = list(islice(work, min(12, IMAGE_LIMIT - offset)))
        if not group:
            break
        distances = pool.map(lambda pair: visual_distance(fetcher, pair[1], features), group)
        for (page, _), distance in zip(group, distances, strict=True):
            cutoff = (
                0.105
                if page.channel in {"GIPHY sticker", "Kakao Emoticon Shop"}
                else VISUAL_DISTANCE
            )
            if distance > cutoff:
                continue
            key = page_key(page.url)
            publisher_evidence = proof.get(key)
            channel = page.channel or (
                "Publisher-linked claim page"
                if publisher_evidence
                else "Publisher download page"
                if page.publisher_pickup
                else ""
            )
            target = confirmed if channel else leads
            if key not in target or target[key][0] > distance:
                target[key] = (
                    distance,
                    StickerSource(
                        title=page.title,
                        url=page.url,
                        channel=channel
                        or community_listing(page.url)
                        or ("Pickup instructions" if page.has_pickup else ""),
                        publisher=page.author,
                        evidence_url=publisher_evidence,
                    ),
                )
        if confirmed and min(distance for distance, _ in confirmed.values()) <= 0.06:
            break
    ordered = sorted(leads.values(), key=lambda pair: pair[0])
    return strongest(confirmed), [source for _, source in ordered[:5]]


def strongest(results):
    ordered = sorted(results.values(), key=lambda pair: pair[0])
    if not ordered:
        return []
    cutoff = ordered[0][0] + MATCH_MARGIN
    return [source for distance, source in ordered[:3] if distance <= cutoff]
