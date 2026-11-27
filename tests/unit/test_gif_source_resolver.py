import socket
import time
from pathlib import Path

import httpx
import pytest

from services.retrieval import download
from services.search_agent import resolvers
from services.search_agent.models import Source


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("208.80.154.224", 443))],
    )


def read(client, url="https://upload.wikimedia.org/test.gif", **kwargs):
    return download.fetch(
        url,
        hosts=download.MEDIA_HOSTS,
        max_bytes=kwargs.get("max_bytes", 100),
        deadline=time.monotonic() + 10,
        client=client,
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/x",
        "http://upload.wikimedia.org/x",
        "https://upload.wikimedia.org:444/x",
        "https://u:p@upload.wikimedia.org/x",
        "https://127.0.0.1/x",
    ],
)
def test_policy_rejects_before_get(url):
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("Network called"))) as c:
        with pytest.raises(download.DownloadError) as exc:
            read(c, url)
    assert not exc.value.attempted


def test_private_dns_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.9", 443))],
    )
    with pytest.raises(download.DownloadError, match="source_unavailable"):
        download.check_url("https://upload.wikimedia.org/x", download.MEDIA_HOSTS)


def test_redirect_policy_and_budget():
    for location in ["https://evil.example/x", "/loop"]:
        calls = []

        def response(r):
            calls.append(r)
            return httpx.Response(302, headers={"location": location})

        with httpx.Client(transport=httpx.MockTransport(response)) as c:
            with pytest.raises(download.DownloadError) as exc:
                read(c)
        assert exc.value.attempted
        assert len(calls) == (1 if "evil" in location else 4)


def test_byte_limit_counts_stream():
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 101))
    ) as c:
        with pytest.raises(download.DownloadError, match="invalid_media"):
            read(c)


def test_timeout_classification():
    def response(r):
        raise httpx.ReadTimeout("sensitive URL")

    with httpx.Client(transport=httpx.MockTransport(response)) as c:
        with pytest.raises(download.DownloadError) as exc:
            read(c)
    assert exc.value.code == "download_timeout" and exc.value.attempted


def test_success_and_fragment_normalization():
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"GIF"))
    ) as c:
        assert read(c)[0] == b"GIF"
    assert download.canonical_url("https://UPLOAD.wikimedia.org/x?a=1#z") == (
        "https://upload.wikimedia.org/x?a=1"
    )


def test_original_selector_uses_captured_real_markup(monkeypatch):
    html = (Path(__file__).parents[1] / "fixtures/commons_original.html").read_bytes()
    monkeypatch.setattr(resolvers, "fetch", lambda *a, **k: (html, a[0], 0))
    source = Source(
        source_url="https://commons.wikimedia.org/wiki/File:Rotating_earth_(large).gif",
        provider="fixture",
    )
    batch = resolvers.resolve_sources(
        [source], deadline=time.monotonic() + 10, remaining_pages=1, remaining_downloads=1
    )
    assert batch.page_requests == 1 and len(batch.sources) == 1
    assert "Rotating_earth_%28large%29.gif?" in batch.sources[0].image_url
    assert "&utm_campaign=" in batch.sources[0].image_url
    assert batch.sources[0].source_url == source.source_url


def test_page_budget_and_unknown_host(monkeypatch):
    calls = []

    def fetch(*a, **k):
        calls.append(a[0])
        raise download.DownloadError("download_failed", attempted=True)

    monkeypatch.setattr(resolvers, "fetch", fetch)
    sources = [
        Source(source_url=f"https://commons.wikimedia.org/wiki/File:{i}", provider="x")
        for i in range(3)
    ]
    sources.append(Source(source_url="https://unknown.example/x", provider="x"))
    batch = resolvers.resolve_sources(
        sources, deadline=time.monotonic() + 10, remaining_pages=1, remaining_downloads=6
    )
    assert batch.page_requests == 1 and len(calls) == 1
    assert batch.failures == ["source_unavailable", "unsupported_source"]


def test_deadline_stops_before_next_stream_read(monkeypatch):
    clock, reads = [0.0], []
    monkeypatch.setattr(download.time, "monotonic", lambda: clock[0])

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            reads.append(1)
            clock[0] = 20
            yield b"first"
            reads.append(2)
            yield b"never read"

    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Stream()))
    ) as client:
        with pytest.raises(download.DownloadError, match="download_timeout"):
            download.fetch(
                "https://upload.wikimedia.org/x",
                hosts=download.MEDIA_HOSTS,
                max_bytes=100,
                deadline=10,
                client=client,
            )
    assert reads == [1]


def test_deadline_rechecked_after_dns(monkeypatch):
    clock, calls = [0.0], []
    monkeypatch.setattr(download.time, "monotonic", lambda: clock[0])

    def dns(*a, **k):
        clock[0] = 20
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("208.80.154.224", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    with httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r))) as client:
        with pytest.raises(download.DownloadError, match="download_timeout") as exc:
            download.fetch(
                "https://upload.wikimedia.org/x",
                hosts=download.MEDIA_HOSTS,
                max_bytes=100,
                deadline=10,
                client=client,
            )
    assert not calls and not exc.value.attempted


@pytest.mark.parametrize(
    "path", ["File:Example.gif", "File%3AExample.gif", "file:Example.gif", "FILE%3aExample.gif"]
)
def test_encoded_file_namespace_uses_original_request_url(monkeypatch, path):
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return b'<a class="internal" href="//upload.wikimedia.org/Example.gif">Original</a>', url, 0

    monkeypatch.setattr(resolvers, "fetch", fetch)
    page = "https://commons.wikimedia.org/wiki/" + path
    result = resolvers.resolve_sources(
        [Source(source_url=page, provider="fixture")],
        deadline=time.monotonic() + 10,
        remaining_pages=1,
        remaining_downloads=1,
    )
    assert (
        calls == [page]
        and result.sources[0].image_url == "https://upload.wikimedia.org/Example.gif"
    )


def test_article_and_double_encoded_namespace_rejected(monkeypatch):
    monkeypatch.setattr(resolvers, "fetch", lambda *a, **k: pytest.fail("Not a file page"))
    for path in ["Earth", "File%253AExample.gif"]:
        result = resolvers.resolve_sources(
            [Source(source_url="https://commons.wikimedia.org/wiki/" + path, provider="fixture")],
            deadline=time.monotonic() + 10,
            remaining_pages=1,
            remaining_downloads=1,
        )
        assert result.failures == ["unsupported_source"] and result.page_requests == 0


def test_relative_link_cannot_escape_media_registry(monkeypatch):
    markup = b'<a class="internal" href="/wrong.gif">Wrong</a><a class="internal" href="https://evil.example/a.gif">Wrong</a>'
    monkeypatch.setattr(resolvers, "fetch", lambda url, **k: (markup, url, 0))
    result = resolvers.resolve_sources(
        [Source(source_url="https://commons.wikimedia.org/wiki/File:X.gif", provider="fixture")],
        deadline=time.monotonic() + 10,
        remaining_pages=1,
        remaining_downloads=1,
    )
    assert result.sources == [] and result.reasons == {"no_original_gif": 1}


def test_parrot_selects_only_permission_reviewed_original(monkeypatch):
    markup = (
        b'<img data-src="/parrots/hd/parrot.gif"><img data-src="/parrots/hd/originalparrot.gif">'
    )
    monkeypatch.setattr(resolvers, "fetch", lambda url, **k: (markup, url, 0))
    result = resolvers.resolve_sources(
        [Source(source_url="https://cultofthepartyparrot.com/", provider="fixture")],
        deadline=time.monotonic() + 10,
        remaining_pages=1,
        remaining_downloads=2,
    )
    assert [s.image_url for s in result.sources] == [
        "https://cultofthepartyparrot.com/parrots/hd/originalparrot.gif"
    ]


@pytest.mark.parametrize("status", [403, 404, 429])
def test_http_status_is_safe_diagnostic(status):
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, text="secret upstream"))
    ) as c:
        with pytest.raises(download.DownloadError) as exc:
            read(c)
    assert exc.value.code == "download_failed" and exc.value.reason == f"http_{status}"
    assert exc.value.http_status == status and exc.value.stage == "http"
    assert "secret" not in str(exc.value)


def test_other_parrot_variants_not_enabled_by_media_host_registration():
    with pytest.raises(download.DownloadError, match="unsupported_source"):
        download.check_url(
            "https://cultofthepartyparrot.com/parrots/hd/parrot.gif", download.MEDIA_HOSTS
        )
    assert download.check_url(
        "https://cultofthepartyparrot.com/parrots/hd/originalparrot.gif", download.MEDIA_HOSTS
    )


def test_tenor_only_viewed_post_and_animated_formats(monkeypatch):
    import json
    from services.search_agent.resolvers import TenorOriginal

    formats = {
        "gif": {"url": "https://media1.tenor.com/m/main.gif", "size": 1000},
        "mediumgif": {"url": "https://media1.tenor.com/m/medium.gif", "size": 500},
        "tinygif": {"url": "https://media.tenor.com/tiny.gif", "size": 100},
        "gifpreview": {"url": "https://media.tenor.com/static.gif"},
        "mp4": {"url": "https://media.tenor.com/main.mp4"},
    }
    payload = {
        "gifs": {
            "byId": {
                "123": {"results": [{"id": "123", "media_formats": formats}]},
                "456": {"results": [{"id": "456", "media_formats": formats}]},
            }
        }
    }
    markup = '<script id="store-cache" type="text/x-cache">' + json.dumps(payload) + "</script>"
    parser = TenorOriginal("https://tenor.com/view/target-gif-123")
    parser.feed(markup)
    assert parser.urls == [
        "https://media1.tenor.com/m/main.gif",
        "https://media1.tenor.com/m/medium.gif",
    ]
    monkeypatch.setattr(resolvers, "fetch", lambda url, **k: (markup.encode(), url, 0))
    batch = resolvers.resolve_sources(
        [Source(source_url="https://tenor.com/view/target-gif-123", provider="fixture")],
        deadline=time.monotonic() + 10,
        remaining_pages=1,
        remaining_downloads=2,
    )
    assert batch.page_requests == 1 and [s.image_url for s in batch.sources] == parser.urls


def test_tenor_does_not_derive_media_url_or_use_related_post():
    from services.search_agent.resolvers import TenorOriginal

    parser = TenorOriginal("https://tenor.com/view/missing-gif-123")
    parser.feed('<script id="store-cache">{"gifs":{"byId":{"456":{"results":[]}}}}</script>')
    assert parser.urls == []


def test_tenor_prefers_distinct_posts_before_extra_renditions(monkeypatch):
    import json

    def fetch(url, **kwargs):
        key = url.rsplit("-", 1)[1]
        payload = {
            "gifs": {
                "byId": {
                    key: {
                        "results": [
                            {
                                "id": key,
                                "media_formats": {
                                    "gif": {"url": f"https://media.tenor.com/{key}.gif"},
                                    "mediumgif": {
                                        "url": f"https://media.tenor.com/{key}-medium.gif"
                                    },
                                },
                            }
                        ]
                    }
                }
            }
        }
        return ('<script id="store-cache">' + json.dumps(payload) + "</script>").encode(), url, 0

    monkeypatch.setattr(resolvers, "fetch", fetch)
    sources = [
        Source(source_url=f"https://tenor.com/view/post-{i}", provider="fixture") for i in [1, 2]
    ]
    result = resolvers.resolve_sources(
        sources, deadline=time.monotonic() + 10, remaining_pages=2, remaining_downloads=2
    )
    assert [s.image_url for s in result.sources] == [
        "https://media.tenor.com/1.gif",
        "https://media.tenor.com/2.gif",
    ]


def test_tenor_localized_view_page_is_supported(monkeypatch):
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        return b"<html></html>", url, 0

    monkeypatch.setattr(resolvers, "fetch", fetch)
    source = Source(
        source_url="https://tenor.com/es-CL/view/bumble-bee-sus-gif-123", provider="fixture"
    )
    result = resolvers.resolve_sources(
        [source], deadline=time.monotonic() + 10, remaining_pages=1, remaining_downloads=1
    )
    assert calls == [source.source_url] and result.page_requests == 1
    assert result.reasons == {"no_original_gif": 1}
