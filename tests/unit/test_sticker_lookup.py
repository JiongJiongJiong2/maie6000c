from io import BytesIO

from PIL import Image, ImageDraw

from services.search_agent.meme_types import (
    EntityHypothesis,
    MediaSource,
    PipelineError,
    VisualAnalysis,
)
from services.search_agent.sticker_lookup import find_public_sticker

LINE = "https://store.line.me/stickershop/product/999/en"
LINE_PREVIEW = "https://stickershop.line-scdn.net/stickershop/v1/sticker/5/android/sticker.png"
PUBLISHER = "https://brand.gov.hk/events/sticker-launch"
PICKUP = "https://whatsticker.online/p/PackID/HK/en"
PICKUP_PREVIEW = "https://whatsticker.online/stickers_asset/ws-pack-PackID/one.png"
REPOST = "https://fan.example.com/repost"
REPOST_PREVIEW = "https://fan.example.com/sticker.png"


def artwork(background, center):
    image = Image.new("RGB", (150, 158), background)
    draw = ImageDraw.Draw(image)
    draw.polygon([(15, 145), (68, 13), (128, 119)], fill=center)
    draw.ellipse((54, 52, 84, 86), fill="#aff1b4")
    with BytesIO() as output:
        image.save(output, "PNG")
        return output.getvalue()


class Search:
    def __init__(self, urls):
        self.urls = urls
        self.queries = []

    def search(self, query, limit):
        self.queries.append(query)
        return [
            MediaSource(source_url=url, provider="test", title=title)
            for item in self.urls
            for url, title in [item if isinstance(item, tuple) else (item, "")]
        ]


class Fetch:
    def __init__(self, files):
        self.files = files

    def get(self, url, kind, max_bytes):
        if url not in self.files:
            raise PipelineError("fetch_no_public_preview")
        return self.files[url], url


def recognize(*_):
    return VisualAnalysis(
        entity_hypotheses=[EntityHypothesis(name="Pattern Mascot", confidence=0.9)]
    ), []


def test_platform_pickup_requires_matching_published_art():
    screenshot = artwork("#f8f8f8", "#123261")
    different = artwork("#000000", "#fe5d00")
    web = Search([LINE, REPOST])
    fetcher = Fetch(
        {
            LINE: (
                "<title>Pattern Mascot - LINE STORE</title>"
                '<a class="mdCMN38Item01Author">Artist</a>'
                f'''<li data-preview='{{"staticUrl":"{LINE_PREVIEW}"}}'></li>'''
            ).encode(),
            LINE_PREVIEW: different,
            REPOST: f'<title>Official claim</title><img src="{REPOST_PREVIEW}">'.encode(),
            REPOST_PREVIEW: screenshot,
        }
    )
    result = find_public_sticker(screenshot, analyzer=recognize, web=web, fetcher=fetcher)
    assert result.state == "candidates"
    assert not result.links and str(result.leads[0].url) == REPOST
    assert any("site:store.line.me" in query for query in web.queries)
    assert any("微信 QQ" in query for query in web.queries)

    fetcher.files[LINE_PREVIEW] = screenshot
    result = find_public_sticker(screenshot, analyzer=recognize, web=web, fetcher=fetcher)
    assert result.state == "matched"
    assert [str(source.url) for source in result.links] == [LINE]
    assert result.links[0].publisher == "Artist"
    assert str(result.leads[0].url) == REPOST


def test_publisher_cross_link_confirms_third_party_pickup():
    screenshot = artwork("#f8f8f8", "#123261")
    web = Search([PUBLISHER])
    fetcher = Fetch(
        {
            PUBLISHER: (
                f'<title>Our mascot sticker launch</title><a href="{PICKUP}">Download sticker</a>'
            ).encode(),
            PICKUP: (
                f'<title>Pattern Mascot</title><img class="sticker" src="{PICKUP_PREVIEW}">'
            ).encode(),
            PICKUP_PREVIEW: screenshot,
        }
    )
    result = find_public_sticker(screenshot, analyzer=recognize, web=web, fetcher=fetcher)
    assert result.state == "matched"
    assert str(result.links[0].url) == PICKUP
    assert str(result.links[0].evidence_url) == PUBLISHER

    web.urls = [PICKUP]
    result = find_public_sticker(screenshot, analyzer=recognize, web=web, fetcher=fetcher)
    assert result.state == "candidates"
    assert not result.links and str(result.leads[0].url) == PICKUP


def test_unavailable_previews_leave_only_relevant_text_candidates():
    screenshot = artwork("#f8f8f8", "#123261")
    community = "https://www.sigstick.com/pack/ABC123XY"
    article = "https://publisher.example.com/wechat-launch"
    web = Search(
        [
            (LINE, "Different cartoon – LINE stickers"),
            (community, "Pattern Mascot Stickers"),
            (article, "Pattern Mascot 微信表情包下载"),
            (REPOST, "Pattern Mascot"),
        ]
    )
    result = find_public_sticker(screenshot, analyzer=recognize, web=web, fetcher=Fetch({}))
    assert result.state == "candidates"
    assert not result.links
    assert [(str(source.url), source.match_basis) for source in result.leads] == [
        (community, "text"),
        (article, "text"),
    ]


def test_mainland_publisher_instructions_with_matching_art_are_verified():
    screenshot = artwork("#f8f8f8", "#123261")
    publisher = "https://college.example.edu.cn/article/647"
    asset = "https://college.example.edu.cn/sticker.png"
    web = Search([publisher])
    fetcher = Fetch(
        {
            publisher: (
                f'<title>书院微信表情包正式上线</title><img src="{asset}">'
                "获取方式：在微信中搜索表情包"
            ).encode(),
            asset: screenshot,
        }
    )
    result = find_public_sticker(screenshot, analyzer=recognize, web=web, fetcher=fetcher)
    assert result.state == "matched"
    assert str(result.links[0].url) == publisher
    assert result.links[0].match_basis == "artwork"
