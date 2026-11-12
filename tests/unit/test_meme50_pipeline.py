import io

import numpy as np
import pytest
from PIL import Image

from services.search_agent.meme_pipeline import search_memes
from services.search_agent.meme_providers import BraveImages, GoogleImageSearch
from services.search_agent.meme_types import (
    Ledger,
    MediaSource,
    MemeSettings,
    Query,
    VisualAnalysis,
)
from services.search_agent.page_media import page_sources


def test_pipeline_fills_fifty_mixed_distinct_groups_and_streams(tmp_path):
    assets = {}
    for i in range(60):
        image = Image.new("RGB", (48, 32), ((i * 67) % 255, (i * 31) % 255, (i * 19) % 255))
        out = io.BytesIO()
        animated = i % 2 == 0
        image.save(
            out,
            "GIF" if animated else "PNG",
            **(
                dict(
                    save_all=True,
                    append_images=[Image.new("RGB", image.size, ((i * 67 + 80) % 255, 0, 255))],
                    duration=100,
                )
                if animated
                else {}
            ),
        )
        assets[f"https://new-cdn.example.net/{i}"] = out.getvalue()
    path = tmp_path / "random.bin"
    path.write_bytes(next(iter(assets.values())))
    sources = [
        MediaSource(
            source_url=f"https://new-source.example.net/{i}",
            media_url=url,
            provider="controlled-test",
            source_rank=i + 1,
        )
        for i, url in enumerate(assets)
    ]

    def analyze(data, text, settings, ledger):
        ledger.take("model_calls")
        return VisualAnalysis(
            observations=["controlled test"],
            queries=[
                Query(text="appearance", angle="appearance"),
                Query(text="action", angle="action"),
            ],
        ), [Image.new("RGB", (10, 10))]

    class Reverse:
        def search(self, frame):
            return [], "actual OCR", []

    class Keywords:
        def search(self, query, limit):
            return sources

    class Fetch:
        def get(self, url, kind, maximum):
            return assets[url], url

    class Embeddings:
        def load_model(self):
            pass

        def encode_images(self, frames):
            return np.array([[1.0, 0.0] for _ in frames])

        def encode_texts(self, texts):
            return np.array([[1.0, 0.0] for _ in texts])

    events = []
    result = search_memes(
        path,
        "",
        tmp_path / "work",
        analyze=analyze,
        reverse=Reverse(),
        keywords=Keywords(),
        fetcher=Fetch(),
        embeddings=Embeddings(),
        emit=lambda kind, payload: events.append((kind, payload)),
    )
    assert result["status"] == "completed" and len(result["candidate_keys"]) == 50
    assert result["stop_reason"] == "target_reached"
    candidates = {
        p["candidate"]["key"]: p["candidate"] for k, p in events if k == "candidate_ready"
    }
    final = [candidates[k] for k in result["candidate_keys"]]
    assert len({c["content_group_id"] for c in final}) == 50
    assert {c["metadata"]["media_kind"] for c in final} == {"static", "animated"}
    assert (
        next(p for k, p in events if k == "analysis_ready")["analysis"]["ocr_text"] == "actual OCR"
    )
    assert [k for k, p in events].count("final") == 1


def test_missing_vision_fails_without_filename_or_fixed_caption(tmp_path):
    out = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(out, "PNG")
    path = tmp_path / "the-answer-is-a-character.png"
    path.write_bytes(out.getvalue())
    result = search_memes(
        path,
        "",
        tmp_path / "work",
        settings=MemeSettings(_env_file=None, vision_provider="hkust", hkust_api_key=""),
    )
    assert result["status"] == "failed" and result["candidate_keys"] == []
    assert result["stop_reason"] == "visual_provider_unconfigured"
    assert result["ledger"]["model_calls"] == 0


def test_provider_shapes_separate_images_pages_and_no_fake_pagination(monkeypatch):
    calls = []

    def request(method, url, ledger, **kw):
        calls.append((url, kw))
        if "vision.googleapis" in url:
            assert kw["json"]["requests"][0]["image"]["content"]
            return {
                "responses": [
                    {
                        "webDetection": {
                            "fullMatchingImages": [{"url": "https://cdn.example.org/image"}],
                            "pagesWithMatchingImages": [
                                {"url": "https://example.org/page", "pageTitle": "a title"}
                            ],
                        },
                        "fullTextAnnotation": {"text": "caption"},
                    }
                ]
            }
        return {
            "results": [
                {
                    "url": "https://example.org/page",
                    "properties": {"url": "https://cdn.example.org/full.png"},
                    "thumbnail": {"src": "https://cdn.example.org/preview.png"},
                }
            ]
        }

    monkeypatch.setattr("services.search_agent.meme_providers.bounded_json", request)
    settings = MemeSettings(google_vision_api_key="test", brave_api_key="test")
    ledger = Ledger(settings)
    results, ocr, _ = GoogleImageSearch(settings, ledger).search(Image.new("RGB", (20, 20)))
    assert results[0].media_url and results[1].media_url is None and ocr == "caption"
    results = BraveImages(settings, ledger).search("visible action", limit=200)
    assert results[0].media_url != results[0].preview_url != results[0].source_url
    assert "offset" not in calls[-1][1]["params"]
    assert ledger.counts["search_calls"] == 2
    with pytest.raises(ValueError):
        BraveImages(settings, ledger).search("x", 201)


def test_generic_page_clues_relative_urls_and_limit():
    page = b"""<meta property="og:image" content="../original.webp">
<script type="application/ld+json">{"@type":"ImageObject","contentUrl":"/main.png"}</script>
<img class="logo" src="/logo.png"><img srcset="/small.jpg 100w, /large.jpg 900w">
<img data-src="/lazy.gif"><img src="/extra.png">"""
    source = MediaSource(source_url="https://unregistered.example.org/view/one", provider="test")
    result = page_sources(source, page, source.source_url)
    urls = [s.media_url for s in result]
    assert len(urls) == 4 and urls[0] == "https://unregistered.example.org/original.webp"
    assert "https://unregistered.example.org/large.jpg" in urls
    assert not any("logo" in u for u in urls)


def test_visual_evidence_cannot_fabricate_urls_and_uncertain_entity_remains(monkeypatch):
    import json
    from services.search_agent.meme_providers import GeminiVision

    response = {
        "observations": ["visible orange animal"],
        "entity_hypotheses": [{"name": "unknown", "confidence": 0.2, "status": "uncertain"}],
        "queries": [
            {"text": "orange animal reaction", "angle": "appearance"},
            {"text": "suspicious reaction", "angle": "emotion"},
        ],
        "evidence_relations": [
            {"id": "e1", "relation": "conflicts", "reason": "different visible animal"}
        ],
    }

    def request(method, url, ledger, **kwargs):
        assert "inlineData" in kwargs["json"]["contents"][0]["parts"][1]
        return {"candidates": [{"content": {"parts": [{"text": json.dumps(response)}]}}]}

    monkeypatch.setattr("services.search_agent.meme_providers.bounded_json", request)
    settings = MemeSettings(gemini_api_key="controlled-test")
    evidence = [{"id": "e1", "url": "https://example.org/actual-result", "title": "retrieved"}]
    result = GeminiVision(settings, Ledger(settings)).analyze(
        [Image.new("RGB", (10, 10))], "", evidence
    )
    assert result.evidence[0]["url"] == evidence[0]["url"]
    assert result.evidence[0]["relation"] == "conflicts"
    assert result.entity_hypotheses[0].status == "uncertain"


def test_actual_media_html_wrapper_uses_real_embedded_url_and_shared_budget(tmp_path):
    import io
    from services.search_agent.meme_types import PipelineError

    out = io.BytesIO()
    Image.new("RGB", (30, 30), "red").save(out, "PNG")
    image = out.getvalue()
    path = tmp_path / "random-input.png"
    path.write_bytes(image)
    state = {}

    def analyze(data, text, settings, ledger):
        state["ledger"] = ledger
        return VisualAnalysis(
            queries=[
                Query(text="appearance", angle="appearance"),
                Query(text="action", angle="action"),
            ]
        ), [Image.new("RGB", (10, 10))]

    class Reverse:
        def search(self, frame):
            return [], "", []

    class Keywords:
        def search(self, query, limit):
            return [
                MediaSource(
                    source_url="https://example.org/post",
                    media_url="https://media1.tenor.com/wrapper.gif",
                    provider="controlled",
                )
            ]

    class Fetch:
        def get(self, url, kind, maximum):
            state["ledger"].take(kind)
            if url == "https://media1.tenor.com/wrapper.gif":
                return b'<html><img src="https://c.tenor.com/actual.gif"></html>', url
            if url == "https://c.tenor.com/actual.gif":
                return image, url
            raise PipelineError("unexpected_url")

    class Embeddings:
        def load_model(self):
            pass

        def encode_images(self, frames):
            return np.array([[1.0, 0.0] for _ in frames])

        def encode_texts(self, texts):
            return np.array([[1.0, 0.0] for _ in texts])

    events = []
    result = search_memes(
        path,
        "",
        tmp_path / "work",
        target_count=1,
        analyze=analyze,
        reverse=Reverse(),
        keywords=Keywords(),
        fetcher=Fetch(),
        embeddings=Embeddings(),
        emit=lambda kind, payload: events.append((kind, payload)),
    )
    assert result["status"] == "completed" and len(result["candidate_keys"]) == 1
    assert result["ledger"]["media_attempts"] == 2 and result["ledger"]["page_attempts"] == 1
    item = next(p["candidate"] for k, p in events if k == "candidate_ready")
    assert item["media_url"] == "https://c.tenor.com/actual.gif"
    assert result["counts"]["channel_download_attempts"]["keyword"] == 2


def test_page_budget_is_shared_between_query_angles_and_media_is_not_last(tmp_path):
    path = tmp_path / "random.png"
    out = io.BytesIO()
    Image.new("RGB", (30, 30), "red").save(out, "PNG")
    data = out.getvalue()
    path.write_bytes(data)
    state = {"calls": [], "queries": []}

    def analyze(data, text, settings, ledger):
        state["ledger"] = ledger
        return VisualAnalysis(
            queries=[
                Query(text="appearance", angle="appearance"),
                Query(text="action", angle="action"),
            ]
        ), [Image.new("RGB", (10, 10))]

    class Reverse:
        def search(self, frame):
            return [], "", []

    class Keywords:
        def search(self, query, limit):
            state["queries"].append(query)
            prefix = "bad" if query == "appearance" else "good"
            return [
                MediaSource(
                    source_url=f"https://example.org/{prefix}/{i}",
                    provider="controlled",
                    source_rank=i + 1,
                )
                for i in range(8)
            ]

    class Fetch:
        def get(self, url, kind, maximum):
            state["ledger"].take(kind)
            state["calls"].append((kind, url))
            if kind == "page_attempts":
                return (
                    b"<html></html>"
                    if "/bad/" in url
                    else b'<html><meta property="og:image" content="https://cdn.example.net/image.png"></html>'
                ), url
            return data, url

    class Embeddings:
        def load_model(self):
            pass

        def encode_images(self, frames):
            return np.array([[1.0, 0.0] for _ in frames])

        def encode_texts(self, texts):
            return np.array([[1.0, 0.0] for _ in texts])

    result = search_memes(
        path,
        "",
        tmp_path / "work",
        target_count=1,
        settings=MemeSettings(max_pages=8),
        analyze=analyze,
        reverse=Reverse(),
        keywords=Keywords(),
        fetcher=Fetch(),
        embeddings=Embeddings(),
    )
    assert result["status"] == "completed" and len(result["candidate_keys"]) == 1
    assert state["queries"] == ["appearance", "action"]
    assert sum("/bad/" in url for kind, url in state["calls"] if kind == "page_attempts") == 4
    assert result["ledger"]["page_attempts"] == 8


def test_localized_tenor_pages_are_one_recall_item():
    from services.search_agent.meme_pipeline import fuse_sources

    sources = [
        MediaSource(source_url=u, provider="controlled")
        for u in [
            "https://tenor.com/view/bee-gif-12345",
            "https://tenor.com/en-XC/view/bee-gif-12345",
            "https://tenor.com/view/bee-gif-67890",
        ]
    ]
    assert len(fuse_sources(sources, 500)) == 2


def test_tenor_recommendations_keep_real_independent_sources_and_are_bounded():
    import json

    posts = [
        {
            "itemurl": f"https://tenor.com/view/related-gif-{i}",
            "content_description": f"visible action {i}",
            "media_formats": {
                "webp": {"url": f"https://media.tenor.com/{i}/image.webp", "size": 123}
            },
        }
        for i in range(30)
    ]
    posts.insert(0, {**posts[0], "itemurl": "https://other.example/view/wrong-999"})
    store = {
        "gifs": {
            "byId": {
                "123": {
                    "results": [
                        {
                            "id": "123",
                            "media_formats": {
                                "gif": {
                                    "url": "https://media.tenor.com/main/image.gif",
                                    "size": 456,
                                }
                            },
                        }
                    ]
                }
            },
            "related": {"123": {"results": posts}},
        },
        "appConfig": {"privateKey": "must-not-be-used"},
    }
    page = ('<script id="store-cache">' + json.dumps(store) + "</script>").encode()
    source = MediaSource(source_url="https://tenor.com/view/main-gif-123", provider="test")
    result = page_sources(source, page, source.source_url)
    assert len(result) == 14
    assert result[0].source_url == source.source_url
    assert all(s.source_url != source.source_url for s in result[1:])
    assert result[1].source_url == "https://tenor.com/view/related-gif-0"
    assert result[1].title == "visible action 0"
    assert all("other.example" not in s.source_url for s in result)
    assert "must-not-be-used" not in str(result)


def test_public_html_boolean_attributes_do_not_abort_the_job():
    source = MediaSource(source_url="https://public.example/page", provider="test")
    page = b'<meta property name><script type></script><img alt class src="/valid.gif">'
    result = page_sources(source, page, source.source_url)
    assert [s.media_url for s in result] == ["https://public.example/valid.gif"]
    commons = MediaSource(
        source_url="https://commons.wikimedia.org/wiki/File:test.gif", provider="test"
    )
    result = page_sources(
        commons, b'<a class href="/ignored"><img alt class src="/valid.gif">', commons.source_url
    )
    assert len(result) == 1


def test_meme50_tenor_prefers_real_webp_without_redundant_gif_variant():
    import json

    post = {
        "id": "123",
        "media_formats": {
            "webp": {"url": "https://media.tenor.com/a/actual.webp", "size": 120},
            "gif": {"url": "https://media.tenor.com/a/actual.gif", "size": 600},
        },
    }
    data = (
        '<script id="store-cache">'
        + json.dumps({"gifs": {"byId": {"123": {"results": [post]}}}})
        + "</script>"
    ).encode()
    source = MediaSource(source_url="https://tenor.com/view/post-gif-123", provider="test")
    result = page_sources(source, data, source.source_url)
    assert [s.media_url for s in result] == ["https://media.tenor.com/a/actual.webp"]
    from services.search_agent.resolvers import TenorOriginal

    legacy = TenorOriginal(source.source_url)
    legacy.feed(data.decode())
    assert legacy.urls == ["https://media.tenor.com/a/actual.gif"]
