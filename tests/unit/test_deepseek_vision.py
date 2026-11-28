import base64
import io
import json
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from services.search_agent import meme_providers as providers
from services.search_agent.caption_review import review_scores
from services.search_agent.entity_verifier import verify_entities
from services.search_agent.meme_types import Ledger, MemeSettings, PipelineError
from services.search_agent.visual_analysis import analyze_image


def mock_transport(monkeypatch, respond):
    client = httpx.Client
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(providers.httpx, "Client", lambda **kw: client(transport=transport, **kw))


def test_deepseek_only_image_entity_and_caption_review_share_one_key(monkeypatch, tmp_path):
    key = "controlled-deepseek-only"
    settings = MemeSettings(_env_file=None, deepseek_api_key=key, max_pages=0)
    assert (settings.vision_provider, settings.provider_policy) == ("deepseek", "deepseek-only-v1")
    assert settings.effective_vision_model == "deepseek-flash"
    ledger = Ledger(settings)
    requests = []
    colors = ["red", "green", "blue", "orange"]
    frames = [Image.new("RGB", (32, 24), color) for color in colors]
    gif = io.BytesIO()
    frames[0].save(gif, format="GIF", save_all=True, append_images=frames[1:], duration=100)

    def respond(request):
        assert request.method == "POST" and request.url.host == "api.deepseek.com"
        assert request.headers["Authorization"] == "Bearer " + key
        body = json.loads(request.content)
        if request.url.path == "/v1/tools/search":
            requests.append("web")
            return httpx.Response(200, json={"results": [{"url": "https://example.org/asset"}]})
        assert request.url.path == "/chat/completions"
        assert body["model"] == "deepseek-flash" and body["stream"] is False
        assert body["thinking"] == {"type": "disabled"}
        assert body["response_format"] == {"type": "json_object"}
        (message,) = body["messages"]
        assert message["role"] == "user"
        first, *images = message["content"]
        prompt = json.loads(first["text"])
        assert first["type"] == "text" and "JSON" in first["text"]
        pixels = []
        for part in images:
            assert part["type"] == "image_url"
            header, encoded = part["image_url"]["url"].split(",", 1)
            assert header == "data:image/png;base64"
            with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as image:
                assert image.format == "PNG"
                pixels.append(image.convert("RGB").getpixel((0, 0)))
        if "candidate_count" in prompt:
            requests.append("review")
            assert len(images) == 2 and prompt["candidate_count"] == 1
            response = {"relations": ["same_joke"]}
        else:
            assert pixels == [frame.getpixel((0, 0)) for frame in frames]
            evidence = prompt["evidence_to_check"]
            requests.append("verify" if evidence else "vision")
            response = {
                "observations": ["卡通形象摇头"],
                "ocr_text": "今天放假",
                "entity_hypotheses": [{"name": "奶龙", "confidence": 0.5, "status": "uncertain"}],
                "queries": [
                    {"text": "黄色卡通摇头", "angle": "visual_description"},
                    {"text": "今天放假 表情", "angle": "caption"},
                ],
                "evidence_relations": [{"id": e["id"], "relation": "supports"} for e in evidence],
            }
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(response, ensure_ascii=False)},
                    }
                ]
            },
        )

    mock_transport(monkeypatch, respond)
    analysis, sampled = analyze_image(gif.getvalue(), "找这张动图", settings, ledger)
    assert analysis.ocr_provider == "deepseek-visible-text" and analysis.ocr_text == "今天放假"
    assert analysis.analysis_version.startswith("deepseek/deepseek-flash/")
    checked, warnings = verify_entities(analysis, sampled, settings, ledger)
    assert not warnings and checked.evidence[0]["relation"] == "supports"
    frames[0].save(tmp_path / "preview.png")
    item = SimpleNamespace(
        key="candidate", score=0.4, preview_relative_path="preview.png", signals={}
    )
    assert review_scores([item], sampled[0], checked, tmp_path, ledger) == {
        "candidate": pytest.approx(0.53)
    }
    assert requests[0] == "vision" and requests[-2:] == ["verify", "review"]
    assert set(requests[1:-2]) == {"web"}
    assert ledger.counts["model_calls"] == 3 and ledger.counts["rerank_model_calls"] == 1
    assert key not in repr(ledger.trace) + repr(settings.model_dump())


def test_deepseek_only_without_key_never_uses_school_or_google_keys(monkeypatch):
    mock_transport(monkeypatch, lambda _: pytest.fail("No credential should be sent"))
    settings = MemeSettings(
        _env_file=None,
        deepseek_api_key="",
        hkust_api_key="other-school-key",
        hkgai_api_key="other-hkgai-key",
        gemini_api_key="other-google-key",
    )
    ledger = Ledger(settings)
    with pytest.raises(PipelineError, match="visual_provider_unconfigured"):
        providers.vision_client(settings, ledger).analyze([], "")
    assert not ledger.counts["model_calls"]


@pytest.mark.parametrize(
    "name,value",
    [("MEME50_VISION_PROVIDER", "hkgai"), ("MEME50_PROVIDER_POLICY", "hkgai-deepseek-v1")],
)
def test_legacy_explicit_environment_selection_remains_consistent(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    settings = MemeSettings(_env_file=None)
    assert (settings.vision_provider, settings.provider_policy) == ("hkgai", "hkgai-deepseek-v1")


@pytest.mark.parametrize(
    "status,body,code",
    [
        (401, {"error": {"message": "vendor-echo"}}, "provider_http_401"),
        (200, {"error": {"message": "vendor-echo"}}, "visual_service_error"),
        (
            200,
            {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
            "visual_response_invalid",
        ),
        (
            200,
            {"choices": [{"finish_reason": "stop", "message": {"content": "  "}}]},
            "visual_response_invalid",
        ),
    ],
)
def test_deepseek_vision_errors_do_not_pass_or_expose_provider_text(
    monkeypatch, status, body, code
):
    mock_transport(monkeypatch, lambda _: httpx.Response(status, json=body))
    settings = MemeSettings(_env_file=None, deepseek_api_key="controlled-key")
    ledger = Ledger(settings)
    with pytest.raises(PipelineError, match=code) as caught:
        providers.vision_client(settings, ledger).analyze([Image.new("RGB", (8, 8))], "")
    if status == 401:
        assert caught.value.diagnostic["classification"] == "unauthorized"
    assert "vendor-echo" not in repr(caught.value.diagnostic) + repr(ledger.trace)
