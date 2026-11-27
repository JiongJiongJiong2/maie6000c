import io
import json

import numpy as np
import pytest
from PIL import Image

from services.search_agent import meme_deepseek as deepseek
from services.search_agent.meme_providers import vision_client
from services.search_agent.meme_types import (
    Ledger,
    MemeSettings,
    PipelineError,
    Query,
    VisualAnalysis,
)


def analysis():
    return VisualAnalysis(
        observations=["visible orange animal"],
        ocr_text="hello",
        user_text="",
        queries=[
            {"text": "orange animal meme", "angle": "appearance"},
            {"text": "happy reaction", "angle": "emotion"},
        ],
    )


def settings():
    return MemeSettings(
        _env_file=None,
        hkust_api_key="controlled-school-key",
        deepseek_api_key="controlled-deepseek-key",
    )


def test_flash_planning_uses_only_official_deepseek_endpoint_and_bounds(monkeypatch):
    def request(method, url, ledger, **kwargs):
        assert method == "POST" and url == "https://api.deepseek.com/chat/completions"
        assert kwargs["headers"] == {"Authorization": "Bearer controlled-deepseek-key"}
        payload = kwargs["json"]
        assert payload["model"] == "deepseek-flash"
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["response_format"] == {"type": "json_object"}
        assert "image_url" not in json.dumps(payload)
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {"queries": [q.model_dump() for q in analysis().queries]}
                        )
                    },
                }
            ]
        }

    monkeypatch.setattr(deepseek, "bounded_json", request)
    s = settings()
    ledger = Ledger(s)
    queries = deepseek.DeepSeekQueryPlanner(s, ledger).plan(analysis())
    assert len(queries) == 2 and ledger.counts["model_calls"] == 1
    assert "deepseek_api_key" not in s.model_dump()
    assert "controlled-deepseek-key" not in repr(s)


def test_search_returns_actual_pages_or_direct_urls_not_invented_images(monkeypatch):
    def request(method, url, ledger, **kwargs):
        assert method == "POST" and url == "https://api.deepseek.com/v1/tools/search"
        assert kwargs["json"] == {
            "query": "orange animal reaction",
            "count": 50,
            "need_content": False,
        }
        return {
            "results": [
                {"url": "https://example.org/post", "title": "actual page"},
                {"url": "https://cdn.example.org/original.gif?size=full", "title": "actual media"},
                {"url": "http://127.0.0.1/private"},
            ]
        }

    monkeypatch.setattr(deepseek, "bounded_json", request)
    s = settings()
    ledger = Ledger(s)
    items = deepseek.DeepSeekWeb(s, ledger).search("orange animal reaction", 200)
    assert len(items) == 2
    assert items[0].media_url is None and items[0].source_type == "page"
    assert items[1].media_url == "https://cdn.example.org/original.gif?size=full"
    assert ledger.counts["queries"] == ledger.counts["search_calls"] == 1


@pytest.mark.parametrize("namespace", ["File:", "File%3A", "file:"])
def test_search_treats_commons_file_namespace_as_page_and_preserves_direct_urls(
    monkeypatch, namespace
):
    page = f"https://commons.wikimedia.org/wiki/{namespace}Example.gif"
    original = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Example.gif?download=1"
    ordinary = "https://cdn.example.org/reaction/Gesture.GIF?size=full"
    monkeypatch.setattr(
        deepseek,
        "bounded_json",
        lambda *a, **k: {"results": [{"url": url} for url in (page, original, ordinary)]},
    )
    s = settings()
    items = deepseek.DeepSeekWeb(s, Ledger(s)).search("animated reaction GIF", 3)
    assert [(item.source_url, item.source_type, item.media_url) for item in items] == [
        (page, "page", None),
        (original, "direct", original),
        (ordinary, "direct", ordinary),
    ]


@pytest.mark.parametrize(
    ("user_text", "domain"),
    [
        ("I saw this GIF on Wikimedia Commons", "commons.wikimedia.org"),
        ("来源：Tenor", "tenor.com"),
        (
            "This is from https://commons.wikimedia.org/wiki/File:Private-name.gif",
            "commons.wikimedia.org",
        ),
    ],
)
def test_user_source_reserves_one_bounded_query_alongside_broad_search(user_text, domain):
    queries = [
        Query(text="green animal reaction", angle="identity_hypothesis"),
        Query(text="three foxes jumping in a loop " * 6, angle="action"),
        Query(text="funny cartoon expression", angle="emotion"),
    ]
    ledger = Ledger(settings())
    result = deepseek.prioritize_user_source(queries, user_text, 2, ledger)
    assert len(result) == 2 and result[1] == queries[0]
    assert result[0].text.startswith(f"site:{domain} three foxes jumping in a loop")
    assert len(result[0].text) <= 128 and "Private-name" not in result[0].text
    assert result[0].angle == "user_source_lookup"
    assert ledger.counts["queries"] == ledger.counts["search_calls"] == 0
    assert ledger.trace[0]["details"] == {
        "domain": domain,
        "origin": "user_explicit_source",
        "query": result[0].model_dump(),
        "reused": False,
    }


def test_user_source_reuses_existing_scope_and_preserves_other_scopes():
    broad = Query(text="jumping animal GIF", angle="appearance")
    first = Query(text="jumping animal site:tenor.com", angle="user_source_lookup")
    duplicate = Query(text="site:tenor.com animated fox", angle="action")
    other = Query(text="site:imgflip.com/memetemplate running fox", angle="template_catalog")
    queries = [broad, first, duplicate, other]
    ledger = Ledger(settings())
    assert deepseek.prioritize_user_source(queries, "Saw it on Tenor.", 3, ledger) == [
        first,
        broad,
        other,
    ]
    assert ledger.trace[0]["details"]["reused"] is True
    assert deepseek.prioritize_user_source([first, broad], "Saw it on Tenor.", 1, ledger) == [broad]


@pytest.mark.parametrize(
    ("user_text", "remaining"),
    [
        ("", 6),
        ("A tenor in a blue suit", 6),
        ("It was not from Tenor", 6),
        ("-site:tenor.com", 6),
        ("Saw it on https://tenor.com.example.org", 6),
        ("Saw it on Tenor", 1),
        ("Saw it on Tenor", 0),
    ],
)
def test_user_source_keeps_default_queries_without_explicit_source_or_spare_budget(
    user_text, remaining
):
    queries = [Query(text="Wikimedia Commons mentions Tenor", angle="appearance")]
    ledger = Ledger(settings())
    assert deepseek.prioritize_user_source(queries, user_text, remaining, ledger) == queries
    assert ledger.trace == []


def test_recall_spends_two_existing_search_slots_on_explicit_source_and_broad_search(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace

    from services.search_agent.meme_pipeline import search_memes

    queries = []

    def request(method, url, ledger, **kwargs):
        assert url == "https://api.deepseek.com/v1/tools/search"
        queries.append(kwargs["json"]["query"])
        return {"results": []}

    monkeypatch.setattr(deepseek, "bounded_json", request)
    input_path = tmp_path / "input.png"
    Image.new("RGB", (20, 20), "orange").save(input_path)
    user_text = "This animation is from Tenor"
    prior = VisualAnalysis(
        user_text=user_text,
        planner_version="prior-plan",
        queries=[
            Query(text="orange cartoon animal", angle="appearance"),
            Query(text="cartoon animal jumps back", angle="action"),
            Query(text="cartoon animal startled", angle="emotion"),
        ],
    )
    result = search_memes(
        input_path,
        user_text,
        tmp_path / "work",
        settings=settings().model_copy(update={"max_queries": 4, "max_search_calls": 2}),
        saved_analysis=prior,
        embeddings=SimpleNamespace(
            load_model=lambda: None,
            encode_images=lambda frames: np.ones((len(frames), 1)),
            encode_texts=lambda texts: np.ones((len(texts), 1)),
        ),
    )
    assert result["status"] == "completed"
    assert queries == ["site:tenor.com orange cartoon animal", "orange cartoon animal"]
    assert result["ledger"]["queries"] == result["ledger"]["search_calls"] == 2


def test_verification_binds_to_actual_search_url_and_query_limit(monkeypatch):
    def request(method, url, ledger, **kwargs):
        assert len(kwargs["json"]["query"]) == 128 and kwargs["json"]["count"] == 5
        return {"results": [{"url": "https://example.org/actual", "summary": "retrieved prose"}]}

    monkeypatch.setattr(deepseek, "bounded_json", request)
    s = settings()
    ledger = Ledger(s)
    evidence = deepseek.DeepSeekWeb(s, ledger).verify("x" * 200)
    assert evidence == [
        {
            "id": "ds-e1",
            "url": "https://example.org/actual",
            "title": "",
            "snippet": "retrieved prose",
            "relation": "unassessed",
        }
    ]


@pytest.mark.parametrize(
    "data",
    [
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": '{"queries":[]}'}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]},
    ],
)
def test_invalid_plan_cannot_silently_pass(monkeypatch, data):
    monkeypatch.setattr(deepseek, "bounded_json", lambda *a, **k: data)
    s = settings()
    with pytest.raises(PipelineError, match="deepseek_plan_invalid"):
        deepseek.DeepSeekQueryPlanner(s, Ledger(s)).plan(analysis())


def test_provider_policy_refuses_google_and_missing_deepseek_never_uses_other_keys():
    s = MemeSettings(
        _env_file=None,
        vision_provider="gemini",
        gemini_api_key="controlled-google-key",
        brave_api_key="controlled-brave-key",
        deepseek_api_key="",
    )
    with pytest.raises(PipelineError, match="provider_policy_violation"):
        vision_client(s, Ledger(s))
    with pytest.raises(PipelineError, match="deepseek_provider_unconfigured"):
        deepseek.DeepSeekWeb(s, Ledger(s)).search("meme")


def test_production_web_media_flow_never_constructs_brave_or_google(monkeypatch, tmp_path):
    from services.search_agent import meme_pipeline as pipeline

    def forbidden(*a, **k):
        pytest.fail("disallowed third-party provider")

    monkeypatch.setattr("services.search_agent.meme_providers.GoogleImageSearch", forbidden)
    monkeypatch.setattr("services.search_agent.meme_providers.BraveImages", forbidden)
    monkeypatch.setattr(
        pipeline, "analyze_image", lambda *a: (analysis(), [Image.new("RGB", (24, 24), "orange")])
    )

    def request(method, url, ledger, **kwargs):
        assert url.startswith("https://api.deepseek.com/")
        if url.endswith("chat/completions"):
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"queries": [q.model_dump() for q in analysis().queries]}
                            )
                        },
                    }
                ]
            }
        return {"results": [{"url": "https://example.org/post", "title": "original reaction"}]}

    monkeypatch.setattr(deepseek, "bounded_json", request)
    data = io.BytesIO()
    Image.new("RGB", (24, 24), "orange").save(data, "PNG")
    image = data.getvalue()
    source = tmp_path / "random.bin"
    source.write_bytes(image)

    class Fetch:
        def get(self, url, kind, maximum):
            return (
                b'<html><img src="https://cdn.example.org/original.png"></html>'
                if url.endswith("/post")
                else image
            ), url

    class Embeddings:
        def load_model(self):
            pass

        def encode_images(self, frames):
            return np.array([[1.0, 0.0] for f in frames])

        def encode_texts(self, texts):
            return np.array([[1.0, 0.0] for t in texts])

    result = pipeline.search_memes(
        source,
        "",
        tmp_path / "work",
        1,
        settings=settings(),
        fetcher=Fetch(),
        embeddings=Embeddings(),
    )
    assert result["status"] == "completed" and len(result["candidate_keys"]) == 1
    assert "reverse_image_unavailable" not in result["warnings"]
    assert any(t["step"] == "reverse_image_disabled" for t in result["trace"])
    assert any(t["step"] == "keyword_web" for t in result["trace"])


@pytest.mark.parametrize(
    "status,confidence,expected",
    [("supported", 0.9, True), ("uncertain", 0.9, False), ("supported", 0.84, False)],
)
def test_supported_visual_entity_is_retained_without_guessing_uncertain_names(
    monkeypatch, status, confidence, expected
):
    value = analysis().model_copy(deep=True)
    from services.search_agent.meme_types import EntityHypothesis

    value.entity_hypotheses = [
        EntityHypothesis(name="Blue Whisker", status=status, confidence=confidence)
    ]

    def request(*args, **kwargs):
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps({"queries": [q.model_dump() for q in value.queries]})
                    },
                }
            ]
        }

    monkeypatch.setattr(deepseek, "bounded_json", request)
    ledger = Ledger(settings())
    queries = deepseek.DeepSeekQueryPlanner(settings(), ledger).plan(value)
    assert any("Blue Whisker" in q.text for q in queries) is expected
    assert len(queries) <= 5 and ledger.counts["model_calls"] == 1
    assert any(t["step"] == "identity_anchor_query" for t in ledger.trace) is expected


def test_verification_query_keeps_hypothesis_before_long_observations(monkeypatch):
    from services.search_agent import entity_verifier
    from services.search_agent.meme_types import EntityHypothesis

    value = analysis().model_copy(deep=True)
    value.observations = ["visible details " * 60]
    value.entity_hypotheses = [
        EntityHypothesis(name="Blue Whisker", status="uncertain", confidence=0.7)
    ]
    captured = []

    class Search:
        def __init__(self, *a):
            pass

        def verify(self, query):
            captured.append(query)
            return []

    monkeypatch.setattr(entity_verifier, "DeepSeekWeb", Search)
    result, warnings = entity_verifier.verify_entities(value, [], settings(), Ledger(settings()))
    assert captured[0].startswith("Blue Whisker ") and len(captured[0]) <= 128
    assert result is value and warnings == []


def test_identity_query_preserves_five_query_budget_and_avoids_duplicate_name(monkeypatch):
    from services.search_agent.meme_types import EntityHypothesis, Query

    value = analysis().model_copy(deep=True)
    value.entity_hypotheses = [
        EntityHypothesis(name="Blue and Whisker", status="supported", confidence=0.95)
    ]
    original = [
        Query(text=f"visible reaction {i}", angle="emotion" if i % 2 else "appearance")
        for i in range(5)
    ]

    def request(*args, **kwargs):
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps({"queries": [q.model_dump() for q in original]})
                    },
                }
            ]
        }

    monkeypatch.setattr(deepseek, "bounded_json", request)
    result = deepseek.DeepSeekQueryPlanner(settings(), Ledger(settings())).plan(value)
    assert len(result) == 5 and result[0].angle == "identity"
    assert all(len(q.text) <= 128 for q in result)
    original[0] = Query(text="Blue Whisker happy GIF", angle="identity")
    result = deepseek.DeepSeekQueryPlanner(settings(), Ledger(settings())).plan(value)
    assert len(result) == 5 and sum(q.angle == "identity" for q in result) == 1


def test_broad_model_entity_query_precedes_over_specific_pose_queries(monkeypatch):
    from services.search_agent.meme_types import EntityHypothesis, Query

    value = analysis().model_copy(deep=True)
    value.entity_hypotheses = [
        EntityHypothesis(name="Blue Whisker", status="supported", confidence=0.9)
    ]
    raw = [
        Query(text="Blue Whisker holding a tiny cup", angle="action"),
        Query(text="Blue Whisker sad in chair", angle="emotion"),
        Query(text="Blue Whisker funny reaction GIF", angle="appearance"),
    ]
    monkeypatch.setattr(
        deepseek,
        "bounded_json",
        lambda *a, **k: {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"queries": [q.model_dump() for q in raw]})},
                }
            ]
        },
    )
    ledger = Ledger(settings())
    result = deepseek.DeepSeekQueryPlanner(settings(), ledger).plan(value)
    assert result[0].text == raw[-1].text and len(result) == len(raw)
    event = next(t for t in ledger.trace if t["step"] == "identity_anchor_query")
    assert event["details"]["origin"] == "deepseek_generated_query"
    assert event["details"]["prioritized"] is True and event["details"]["added"] is False


def test_existing_uncertain_name_query_can_be_broadened_without_confirming_identity(monkeypatch):
    from services.search_agent.meme_types import EntityHypothesis, Query

    value = analysis().model_copy(deep=True)
    value.entity_hypotheses = [
        EntityHypothesis(name="Blue Whisker", status="uncertain", confidence=0.9)
    ]
    raw = [
        Query(text="Blue Whisker holding a cup", angle="action"),
        Query(text="orange cartoon animal sad reaction", angle="emotion"),
    ]
    monkeypatch.setattr(
        deepseek,
        "bounded_json",
        lambda *a, **k: {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"queries": [q.model_dump() for q in raw]})},
                }
            ]
        },
    )
    ledger = Ledger(settings())
    result = deepseek.DeepSeekQueryPlanner(settings(), ledger).plan(value)
    assert (
        result[0].text == "Blue Whisker reaction GIF" and result[0].angle == "identity_hypothesis"
    )
    assert result[1].text == raw[1].text and len(result) == 2
    assert value.entity_hypotheses[0].status == "uncertain"
    event = next(t for t in ledger.trace if t["step"] == "identity_anchor_query")
    assert (
        event["details"]["origin"] == "existing_model_hypothesis"
        and event["details"]["hypothesis_only"] is True
    )


def test_composite_query_survives_single_entity_normalization(monkeypatch):
    from services.search_agent.meme_types import EntityHypothesis, Query

    value = analysis()
    value.queries[0] = Query(text="paper astronaut in a painted landscape", angle="composite")
    value.entity_hypotheses = [
        EntityHypothesis(name="astronaut", confidence=0.95, status="supported")
    ]
    generated = [
        {"text": "astronaut reaction", "angle": "identity"},
        {"text": "painted landscape", "angle": "appearance"},
    ]
    monkeypatch.setattr(
        deepseek,
        "bounded_json",
        lambda *a, **kw: {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({"queries": generated})},
                }
            ]
        },
    )
    planned = deepseek.DeepSeekQueryPlanner(settings(), Ledger(settings())).plan(value)
    assert planned[0] == value.queries[0]
    assert any(q.angle == "appearance" for q in planned)


def test_reference_matching_requires_pixels_and_reserves_recall_budget(monkeypatch):
    from types import SimpleNamespace
    from services.search_agent import entity_verifier as verify
    from services.search_agent.meme_types import Query

    value = analysis()
    value.queries[0] = Query(text="cutout astronaut over painted landscape", angle="composite")
    value.visual_keywords = ["paper astronaut", "painted landscape", "folded arms"]
    public = "https://catalog.example.org"

    def media(color):
        output = io.BytesIO()
        Image.new("RGB", (16, 16), color).save(output, format="PNG")
        return output.getvalue()

    pixels = [media("red"), media("blue")]

    class Search:
        def __init__(self, settings, ledger):
            self.ledger = ledger

        def verify(self, query):
            self.ledger.take("queries")
            return [{"id": f"e{i}", "title": "edit", "url": f"{public}/p{i}"} for i in range(2)]

    class Fetch:
        def get(self, url, kind, limit):
            if "/p" in url:
                return f'<meta property="og:image" content="/i{url[-1]}">'.encode(), url
            return pixels[int(url[-1])], url

    def encode(images):
        return np.array(
            [
                [float(im.getpixel((0, 0))[0] > 0), float(im.getpixel((0, 0))[2] > 0)]
                for im in images
            ]
        )

    def correct(frames, text, evidence):
        result = value.model_copy(deep=True)
        result.evidence = evidence
        return result

    monkeypatch.setattr(verify, "DeepSeekWeb", Search)
    monkeypatch.setattr(verify, "vision_client", lambda *a: SimpleNamespace(analyze=correct))
    config = settings().model_copy(update={"max_queries": 2})
    ledger = Ledger(config)
    output, warnings = verify.verify_entities(
        value,
        [Image.new("RGB", (16, 16), "red")],
        config,
        ledger,
        fetcher=Fetch(),
        embeddings=SimpleNamespace(encode_images=encode),
    )
    assert not warnings and ledger.counts["queries"] == 1
    assert output.evidence[0]["matching_media_url"] == public + "/i0"
    assert "matching_media_url" not in output.evidence[1]
    assert output.evidence[0]["id"] != output.evidence[1]["id"]
    assert "paper astronaut" in verify.verification_queries(value)[0]
